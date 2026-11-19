import json
from dataclasses import dataclass

from freeze.boundaries import validate_boundary_role
from intake.days import require_identity

from .evidence import EligibilityEvidence, validate_evidence


@dataclass(frozen=True)
class PublicBoundary:
    public_id: str
    direction: str
    neighbor: str | None


@dataclass(frozen=True)
class StationPackage:
    pack_id: str
    station: str
    batch: str
    revision: str
    boundaries: tuple[PublicBoundary, ...]
    evidence: EligibilityEvidence


def _unique_object(entries):
    body = {}
    for key, value in entries:
        if key in body:
            raise ValueError('INVALID_PACKAGE')
        body[key] = value
    return body


def _read_boundaries(entries, station):
    if not isinstance(entries, list):
        raise ValueError('INVALID_PACKAGE')
    by_id = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'id', 'direction', 'neighbor'}:
            raise ValueError('INVALID_PACKAGE')
        public_id = require_identity(entry['id'], 'INVALID_PACKAGE')
        direction, neighbor = entry['direction'], entry['neighbor']
        validate_boundary_role(direction, neighbor, station, 'INVALID_PACKAGE')
        if public_id in by_id:
            raise ValueError('INVALID_PACKAGE')
        by_id[public_id] = PublicBoundary(public_id, direction, neighbor)
    return by_id


def decode_package(payload):
    try:
        if isinstance(payload, bytes):
            payload = payload.decode('utf-8')
        if not isinstance(payload, str):
            raise ValueError('INVALID_PACKAGE')
        body = json.loads(payload, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('INVALID_PACKAGE') from exc
    fields = {'version', 'id', 'station', 'batch', 'revision', 'boundaries', 'eligibility'}
    if not isinstance(body, dict) or set(body) != fields:
        raise ValueError('INVALID_PACKAGE')
    if type(body['version']) is not int or body['version'] != 1:
        raise ValueError('INVALID_PACKAGE')
    pack_id, station, batch, revision = (
        require_identity(body[field], 'INVALID_PACKAGE')
        for field in ('id', 'station', 'batch', 'revision')
    )
    by_id = _read_boundaries(body['boundaries'], station)
    return StationPackage(
        pack_id, station, batch, revision, tuple(by_id[key] for key in sorted(by_id)),
        validate_evidence(body['eligibility'], by_id.keys()),
    )


def encode_package(package):
    body = {
        'version': 1,
        'id': package.pack_id,
        'station': package.station,
        'batch': package.batch,
        'revision': package.revision,
        'boundaries': [
            {'id': point.public_id, 'direction': point.direction, 'neighbor': point.neighbor}
            for point in sorted(package.boundaries, key=lambda item: item.public_id)
        ],
        'eligibility': {
            'singles': sorted(package.evidence.singles),
            'pairs': sorted(package.evidence.pairs),
        },
    }
    return json.dumps(body, sort_keys=True, separators=(',', ':'))
