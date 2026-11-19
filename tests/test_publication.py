import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from freeze import BoundaryPoint, close_day, open_successor, read_revision
from intake import add_node, create_draft, open_source, read_draft_snapshot, record, withdraw_record
from publish import decode_package, publish_pack, read_publication
from samples import BATCH, FRONT, FRONT_BOUNDARIES, stage_front


class TestPublication(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.db = open_source(directory / 'source.db')
        self.addCleanup(self.db.close)

    def draft(self, name='D1', nodes=('A', 'B', 'C')):
        day = create_draft(self.db, FRONT, BATCH, name)
        for node in nodes:
            add_node(self.db, day.key, node)
        return day.key

    def test_frozen_source(self):
        payload = stage_front(self.db, 'D1', 'R1', parallel=True)
        key = FRONT, BATCH, 'R1'
        frozen = read_revision(self.db, key)
        package = decode_package(payload)
        self.assertEqual((package.station, package.batch, package.revision), key)
        self.assertEqual(frozen.draft, 'D1')
        self.assertEqual(frozen.boundaries, FRONT_BOUNDARIES)
        middle = [(item.record_id, item.start, item.end) for item in frozen.transfers if item.record_id.startswith('r')]
        self.assertEqual(middle, [('r1', 'u-private', 'v-private'), ('r2', 'u-private', 'v-private')])
        self.assertTrue(package.evidence.allows_single('a1', 'p'))
        self.assertTrue(package.evidence.allows_pair(('a1', 'p'), ('a2', 'q')))
        self.assertTrue(package.evidence.allows_pair(('a2', 'q'), ('a1', 'p')))
        for private in ('u-private', 'v-private', '01-feed-a', '"r1"', '"r2"'):
            self.assertNotIn(private, payload)
        self.assertEqual(read_publication(self.db, key), payload)
        self.assertEqual(publish_pack(self.db, key), payload)

    def test_conflicting_record(self):
        key = self.draft()
        first = record(self.db, key, 'r', 'A', 'B')
        with self.assertRaisesRegex(ValueError, '^RECORD_CONFLICT$'):
            record(self.db, key, 'r', 'A', 'C')
        saved, = read_draft_snapshot(self.db, key).transfers
        self.assertEqual(saved, first)
        self.assertEqual((saved.start, saved.end), ('A', 'B'))

    def test_exact_replay(self):
        key = self.draft()
        first = record(self.db, key, 'r', 'A', 'B')
        self.assertEqual(record(self.db, key, 'r', 'A', 'B'), first)
        second = record(self.db, key, 's', 'A', 'B')
        self.assertEqual(read_draft_snapshot(self.db, key).transfers, (first, second))

    def test_endpoint_membership(self):
        key = self.draft(nodes=('A', 'B'))
        self.draft('D2', nodes=('C',))
        other_station = create_draft(self.db, 'other', BATCH, 'D1')
        add_node(self.db, other_station.key, 'X')
        for end in ('C', 'X', 'missing'):
            with self.subTest(end=end), self.assertRaisesRegex(ValueError, '^ENDPOINT_NOT_IN_DRAFT$'):
                record(self.db, key, 'r', 'A', end)
        with self.assertRaisesRegex(ValueError, '^INVALID_ENDPOINT$'):
            record(self.db, key, 'r', 'A', '')
        self.assertEqual(read_draft_snapshot(self.db, key).transfers, ())

    def test_cyclic_day(self):
        key = self.draft()
        record(self.db, key, 'forward', 'A', 'B')
        record(self.db, key, 'backward', 'B', 'A')
        bounds = (BoundaryPoint('A', 'A'), BoundaryPoint('B', 'B'))
        with self.assertRaisesRegex(ValueError, '^CYCLIC_DAY$'):
            close_day(self.db, key, 'R1', bounds)
        self.assertFalse(read_draft_snapshot(self.db, key).day.sealed)
        with self.assertRaisesRegex(LookupError, '^REVISION_NOT_FOUND$'):
            publish_pack(self.db, (FRONT, BATCH, 'R1'))
        with self.assertRaisesRegex(LookupError, '^PUBLICATION_NOT_FOUND$'):
            read_publication(self.db, (FRONT, BATCH, 'R1'))
        withdraw_record(self.db, key, 'backward')
        self.assertEqual(close_day(self.db, key, 'R1', bounds).draft, 'D1')

    def test_detached_cycle(self):
        key = self.draft(nodes=('A', 'B', 'X', 'Y'))
        for record_id, start, end in (('valid', 'A', 'B'), ('xy', 'X', 'Y'), ('yx', 'Y', 'X')):
            record(self.db, key, record_id, start, end)
        with self.assertRaisesRegex(ValueError, '^CYCLIC_DAY$'):
            close_day(self.db, key, 'R1', (BoundaryPoint('A', 'A'), BoundaryPoint('B', 'B')))
        self.assertFalse(read_draft_snapshot(self.db, key).day.sealed)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM revisions').fetchone(), (0,))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM publications').fetchone(), (0,))

    def test_boundary_reference(self):
        key = self.draft(nodes=('A', 'B'))
        invalid = (
            (BoundaryPoint('p', 'absent'),),
            (BoundaryPoint('p', 'A'), BoundaryPoint('p', 'B')),
            (BoundaryPoint('p', 'A', 'out', FRONT),),
            (BoundaryPoint('p', 'A', 'out'),),
            (BoundaryPoint('p', 'A', 'local', 'lab'),),
        )
        for bounds in invalid:
            with self.subTest(bounds=bounds), self.assertRaisesRegex(ValueError, '^INVALID_BOUNDARY$'):
                close_day(self.db, key, 'R1', bounds)
        self.assertFalse(read_draft_snapshot(self.db, key).day.sealed)
        with self.assertRaisesRegex(LookupError, '^REVISION_NOT_FOUND$'):
            read_revision(self.db, (FRONT, BATCH, 'R1'))
        record(self.db, key, 'after-refusal', 'A', 'B')
        self.assertEqual(len(close_day(self.db, key, 'R1', (BoundaryPoint('p', 'B'),)).transfers), 1)

    def test_shared_parallel_projection(self):
        shared = decode_package(stage_front(self.db, 'D1', 'R1'))
        parallel = decode_package(stage_front(self.db, 'D2', 'R2', parallel=True))
        self.assertEqual(shared.evidence.singles, frozenset({('a1', 'p'), ('a1', 'q'), ('a2', 'p'), ('a2', 'q')}))
        self.assertEqual(shared.evidence.singles, parallel.evidence.singles)
        self.assertFalse(shared.evidence.allows_pair(('a1', 'p'), ('a2', 'q')), 'JOINT_PROJECTION_SHARED_RECORD')
        self.assertTrue(parallel.evidence.allows_pair(('a1', 'p'), ('a2', 'q')), 'JOINT_PROJECTION_PARALLEL_RECORDS')
        self.assertFalse(parallel.evidence.allows_pair(('a1', 'p'), ('a1', 'p')))

    def test_alternative_chain(self):
        shared = decode_package(stage_front(self.db, 'D1', 'R1'))
        alternate = decode_package(stage_front(self.db, 'D2', 'R2', alternative=True))
        self.assertEqual(shared.evidence.singles, alternate.evidence.singles)
        self.assertFalse(shared.evidence.allows_pair(('a1', 'p'), ('a2', 'q')))
        self.assertTrue(alternate.evidence.allows_pair(('a1', 'p'), ('a2', 'q')))
        self.assertFalse(alternate.evidence.allows_pair(('a1', 'q'), ('a2', 'p')))

    def test_pair_of_identical_endpoint_relations(self):
        key = self.draft(nodes=('A', 'B'))
        record(self.db, key, 'first', 'A', 'B')
        record(self.db, key, 'second', 'A', 'B')
        bounds = (BoundaryPoint('a', 'A'), BoundaryPoint('p', 'B'))
        frozen = close_day(self.db, key, 'R1', bounds)
        evidence = decode_package(publish_pack(self.db, frozen.key)).evidence
        self.assertEqual(evidence.singles, frozenset({('a', 'p')}))
        self.assertTrue(evidence.allows_pair(('a', 'p'), ('a', 'p')))

    def test_closed_draft(self):
        payload = stage_front(self.db, 'D1', 'R1', parallel=True)
        key = FRONT, BATCH, 'D1'
        for operation in (
            lambda: add_node(self.db, key, 'late'),
            lambda: record(self.db, key, 'late', 'a1', 'p'),
            lambda: withdraw_record(self.db, key, 'r1'),
            lambda: close_day(self.db, key, 'R2', FRONT_BOUNDARIES),
        ):
            with self.assertRaisesRegex(ValueError, '^DRAFT_CLOSED$'):
                operation()
        self.assertEqual(publish_pack(self.db, (FRONT, BATCH, 'R1')), payload)

    def test_explicit_revision(self):
        old = stage_front(self.db, 'D1', 'R1', parallel=True)
        old_key = FRONT, BATCH, 'R1'
        successor = open_successor(self.db, old_key, 'D2')
        with self.assertRaisesRegex(ValueError, '^DRAFT_EXISTS$'):
            open_successor(self.db, old_key, 'D2')
        withdraw_record(self.db, successor.key, 'r2')
        new_revision = close_day(self.db, successor.key, 'R2', FRONT_BOUNDARIES)
        new = publish_pack(self.db, new_revision.key)
        self.assertEqual(new_revision.base_revision, 'R1')
        self.assertEqual(publish_pack(self.db, old_key), old)
        self.assertNotEqual(decode_package(old).pack_id, decode_package(new).pack_id)
        self.assertTrue(decode_package(old).evidence.allows_pair(('a1', 'p'), ('a2', 'q')))
        self.assertFalse(decode_package(new).evidence.allows_pair(('a1', 'p'), ('a2', 'q')))
