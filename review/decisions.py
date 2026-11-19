from dataclasses import dataclass

from .bindings import find_binding
from .intake import load_imported_package
from .requests import ReviewRequest, validate_request
from .seams import match_seam


@dataclass(frozen=True)
class ParentRef:
    pack_id: str
    station: str
    batch: str
    revision: str

    @classmethod
    def from_package(cls, package):
        return cls(package.pack_id, package.station, package.batch, package.revision)


@dataclass(frozen=True)
class ReviewDecision:
    parents: tuple[ParentRef, ParentRef]
    request: ReviewRequest
    interfaces: tuple[str, ...]


def decide(db, request):
    validate_request(request)
    front = load_imported_package(db, request.front_id)
    rear = load_imported_package(db, request.rear_id)
    seam = match_seam(front, rear)
    validate_request(request, front, rear)
    binding = find_binding(front, rear, request, seam)
    if binding is None:
        raise ValueError('NO_COMMON_EVIDENCE')
    return ReviewDecision(
        (ParentRef.from_package(front), ParentRef.from_package(rear)), request, binding,
    )
