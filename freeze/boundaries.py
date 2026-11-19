from dataclasses import dataclass

from intake.days import require_identity


@dataclass(frozen=True)
class BoundaryPoint:
    public_id: str
    node: str
    direction: str = 'local'
    neighbor: str | None = None


def validate_boundary_role(direction, neighbor, station, error):
    if direction == 'local' and neighbor is None:
        return
    if direction in ('in', 'out') and require_identity(neighbor, error) != station:
        return
    raise ValueError(error)


def validate_boundaries(boundaries, nodes, station):
    if not isinstance(boundaries, (list, tuple)):
        raise ValueError('INVALID_BOUNDARY')
    available = set(nodes)
    by_id = {}
    for point in boundaries:
        if not isinstance(point, BoundaryPoint):
            raise ValueError('INVALID_BOUNDARY')
        public_id = require_identity(point.public_id, 'INVALID_BOUNDARY')
        node = require_identity(point.node, 'INVALID_BOUNDARY')
        if public_id in by_id or node not in available:
            raise ValueError('INVALID_BOUNDARY')
        validate_boundary_role(point.direction, point.neighbor, station, 'INVALID_BOUNDARY')
        by_id[public_id] = point
    return tuple(by_id[public_id] for public_id in sorted(by_id))
