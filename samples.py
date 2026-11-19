import json

from freeze import BoundaryPoint, close_day
from intake import add_node, create_draft, record
from publish import publish_pack
from review import SampleRequest


BATCH = 'day-01'
FRONT = 'prep'
REAR = 'lab'
SAMPLES = (SampleRequest('sample-A', 'a1', 'b1'), SampleRequest('sample-B', 'a2', 'b2'))
FRONT_BOUNDARIES = (
    BoundaryPoint('a1', 'a1'), BoundaryPoint('a2', 'a2'),
    BoundaryPoint('p', 'p', 'out', REAR), BoundaryPoint('q', 'q', 'out', REAR),
)
REAR_BOUNDARIES = (
    BoundaryPoint('p', 'p', 'in', FRONT), BoundaryPoint('q', 'q', 'in', FRONT),
    BoundaryPoint('b1', 'b1'), BoundaryPoint('b2', 'b2'),
)


def stage_front(db, draft, revision, *, parallel=False, alternative=False):
    day = create_draft(db, FRONT, BATCH, draft)
    for node in ('a1', 'a2', 'u-private', 'v-private', 'p', 'q'):
        add_node(db, day.key, node)
    for record_id, start, end in (
        ('01-feed-a', 'a1', 'u-private'), ('02-feed-b', 'a2', 'u-private'),
        ('03-exit-p', 'v-private', 'p'), ('04-exit-q', 'v-private', 'q'),
    ):
        record(db, day.key, record_id, start, end)
    for record_id in ('r1', 'r2') if parallel else ('r',):
        record(db, day.key, record_id, 'u-private', 'v-private')
    if alternative:
        add_node(db, day.key, 'w-private')
        record(db, day.key, '91-alternative-start', 'a1', 'w-private')
        record(db, day.key, '92-alternative-end', 'w-private', 'p')
    frozen = close_day(db, day.key, revision, FRONT_BOUNDARIES)
    return publish_pack(db, frozen.key)


def stage_rear(db, draft='D1', revision='R1'):
    day = create_draft(db, REAR, BATCH, draft)
    for node in ('p', 'q', 'b1', 'b2'):
        add_node(db, day.key, node)
    record(db, day.key, 'lab-from-p', 'p', 'b1')
    record(db, day.key, 'lab-from-q', 'q', 'b2')
    return publish_pack(db, close_day(db, day.key, revision, REAR_BOUNDARIES).key)


def foreign_pack(side, pack_id, kind='both', *, batch=BATCH, permute=False):
    # Handwritten facts for a private four-relation graph. A and D use the
    # aligned ports, B and C the crossed ports. A and C share port p, B and D
    # share port q. Except in the 'same' fixture each port uses one terminal edge.
    # In 'aligned', B and C share an internal edge, with A and D each having
    # a direct bypass. In 'swapped', the direct bypasses are B and C instead.
    compatible = {
        'shared': (),
        'aligned': ((0, 1), (0, 3), (2, 3)),
        'swapped': ((0, 1), (1, 2), (2, 3)),
        'both': ((1, 2), (2, 3), (0, 3), (0, 1)),
        'same': ((0, 2),),
        'empty': (),
    }
    if side == FRONT:
        directory = FRONT_BOUNDARIES
        relations = [('a1', 'p'), ('a1', 'q'), ('a2', 'p'), ('a2', 'q')]
    elif side == REAR:
        directory = REAR_BOUNDARIES
        relations = [('p', 'b1'), ('q', 'b1'), ('p', 'b2'), ('q', 'b2')]
    else:
        raise ValueError('UNKNOWN_SAMPLE_STATION')
    boundaries = [
        {'id': point.public_id, 'direction': point.direction, 'neighbor': point.neighbor}
        for point in directory
    ]
    pairs = [[relations[i], relations[j]] for i, j in compatible[kind]]
    singles = {'empty': [], 'same': [relations[0], relations[2]]}.get(kind, relations)
    if permute:
        boundaries.reverse()
        singles = list(reversed(singles))
        pairs = [pair[::-1] for pair in reversed(pairs)]
    return json.dumps({
        'version': 1, 'id': pack_id, 'station': side, 'batch': batch,
        'revision': 'external-r1', 'boundaries': boundaries,
        'eligibility': {'singles': singles, 'pairs': pairs},
    })
