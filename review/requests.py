from dataclasses import dataclass

from intake.days import require_identity


@dataclass(frozen=True)
class SampleRequest:
    sample_id: str
    start: str
    end: str


@dataclass(frozen=True)
class ReviewRequest:
    front_id: str
    rear_id: str
    samples: tuple[SampleRequest, ...]


def validate_request(request, front=None, rear=None):
    error = 'INVALID_REQUEST'
    if not isinstance(request, ReviewRequest):
        raise ValueError(error)
    require_identity(request.front_id, error)
    require_identity(request.rear_id, error)
    if not isinstance(request.samples, tuple) or len(request.samples) not in (1, 2):
        raise ValueError(error)
    seen = set()
    for sample in request.samples:
        if not isinstance(sample, SampleRequest):
            raise ValueError(error)
        sample_id = require_identity(sample.sample_id, error)
        require_identity(sample.start, error)
        require_identity(sample.end, error)
        if sample_id in seen:
            raise ValueError(error)
        seen.add(sample_id)
    if front is not None and rear is not None:
        starts = {point.public_id for point in front.boundaries}
        ends = {point.public_id for point in rear.boundaries}
        if any(sample.start not in starts or sample.end not in ends for sample in request.samples):
            raise ValueError(error)
    return request
