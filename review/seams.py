from dataclasses import dataclass


@dataclass(frozen=True)
class Seam:
    front_station: str
    rear_station: str
    interfaces: tuple[str, ...]


def match_seam(front, rear):
    if front.batch != rear.batch:
        raise ValueError('MIXED_BATCH')
    if front.station == rear.station:
        raise ValueError('NON_ADJACENT')
    outgoing = {
        point.public_id for point in front.boundaries
        if point.direction == 'out' and point.neighbor == rear.station
    }
    incoming = {
        point.public_id for point in rear.boundaries
        if point.direction == 'in' and point.neighbor == front.station
    }
    shared = tuple(sorted(outgoing & incoming))
    if not shared:
        raise ValueError('NON_ADJACENT')
    return Seam(front.station, rear.station, shared)
