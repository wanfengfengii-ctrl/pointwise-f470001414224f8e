import json
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from intake import open_source
from results import fetch, issue, open_night
from review import ReviewRequest, SampleRequest, import_pack, load_imported_package
from samples import FRONT, REAR, SAMPLES, foreign_pack, stage_front, stage_rear


class TestReview(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.db = open_night(self.root / 'night.db')
        self.addCleanup(self.db.close)

    def counts(self):
        return (self.db.execute('SELECT COUNT(*) FROM issued_results').fetchone()[0],
                self.db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0])

    def external_request(self, front_kind='both', rear_kind='both', prefix='external', *, permute=False):
        front_id = import_pack(self.db, foreign_pack(FRONT, prefix + '-front', front_kind, permute=permute))
        rear_id = import_pack(self.db, foreign_pack(REAR, prefix + '-rear', rear_kind, permute=permute))
        return ReviewRequest(front_id, rear_id, SAMPLES)

    def test_independent_package_order(self):
        request = self.external_request()
        result = issue(self.db, request)
        self.assertEqual(result.interfaces, ('p', 'q'))
        self.assertEqual(result.samples, SAMPLES)
        self.assertEqual(tuple(parent.pack_id for parent in result.parents), (request.front_id, request.rear_id))
        self.assertEqual(result.receipt.result_id, result.result_id)
        self.assertEqual(fetch(self.db, result.result_id), result)
        self.assertEqual(self.counts(), (1, 1))

    def test_permuted_candidates(self):
        first = issue(self.db, self.external_request(prefix='first'))
        rearranged = self.external_request(prefix='rearranged', permute=True)
        second = issue(self.db, rearranged)
        reversed_request = ReviewRequest(rearranged.front_id, rearranged.rear_id, SAMPLES[::-1])
        third = issue(self.db, reversed_request)
        self.assertEqual(first.interfaces, ('p', 'q'))
        self.assertEqual(second.interfaces, first.interfaces)
        self.assertEqual(third.interfaces, ('p', 'q'))
        self.assertEqual(third.samples, SAMPLES[::-1])
        self.assertEqual(self.counts(), (3, 3))

    def test_text_order(self):
        ids = []
        for side in (FRONT, REAR):
            body = json.loads(foreign_pack(side, side + '-text', permute=True))
            changes = {'p': 'p10', 'q': 'p2'}
            for point in body['boundaries']:
                point['id'] = changes.get(point['id'], point['id'])
            for relation in body['eligibility']['singles']:
                relation[:] = [changes.get(value, value) for value in relation]
            for pair in body['eligibility']['pairs']:
                for relation in pair:
                    relation[:] = [changes.get(value, value) for value in relation]
            ids.append(import_pack(self.db, json.dumps(body)))
        self.assertEqual(issue(self.db, ReviewRequest(*ids, SAMPLES)).interfaces, ('p10', 'p2'))

    def test_same_interface(self):
        request = self.external_request('same', 'same')
        self.assertEqual(issue(self.db, request).interfaces, ('p', 'p'))
        blocked = self.external_request('same', 'empty', prefix='empty')
        with self.assertRaisesRegex(ValueError, '^NO_COMMON_EVIDENCE$'):
            issue(self.db, blocked)
        self.assertEqual(self.counts(), (1, 1))

    def test_shared_transfer(self):
        front_path = self.root / 'prep.db'
        rear_path = self.root / 'lab.db'
        with closing(open_source(front_path)) as prep, closing(open_source(rear_path)) as lab:
            shared = stage_front(prep, 'D1', 'R1')
            parallel = stage_front(prep, 'D2', 'R2', parallel=True)
            downstream = stage_rear(lab)
        front_path.unlink()
        rear_path.unlink()
        front_id = import_pack(self.db, shared)
        rear_id = import_pack(self.db, downstream)
        for sample, expected in zip(SAMPLES, ('p', 'q')):
            signed = issue(self.db, ReviewRequest(front_id, rear_id, (sample,)))
            self.assertEqual(signed.interfaces, (expected,))
            self.assertEqual(fetch(self.db, signed.result_id), signed)
        self.assertEqual(self.counts(), (2, 2))
        with self.assertRaisesRegex(ValueError, '^NO_COMMON_EVIDENCE$', msg='SHARED_TRANSFER_DOUBLE_SIGNED'):
            issue(self.db, ReviewRequest(front_id, rear_id, SAMPLES))
        self.assertEqual(self.counts(), (2, 2))
        valid_id = import_pack(self.db, parallel)
        result = issue(self.db, ReviewRequest(valid_id, rear_id, SAMPLES))
        self.assertEqual(result.interfaces, ('p', 'q'))
        self.assertEqual(self.counts(), (3, 3))

    def test_independent_shared_transfer(self):
        request = self.external_request('shared', 'aligned')
        for sample, expected in zip(SAMPLES, ('p', 'p')):
            signed = issue(self.db, ReviewRequest(request.front_id, request.rear_id, (sample,)))
            self.assertEqual(signed.interfaces, (expected,))
        with self.assertRaisesRegex(ValueError, '^NO_COMMON_EVIDENCE$', msg='INDEPENDENT_SHARED_TRANSFER_DOUBLE_SIGNED'):
            issue(self.db, request)
        self.assertEqual(self.counts(), (2, 2))
        aligned = import_pack(self.db, foreign_pack(FRONT, 'independent-aligned', 'aligned'))
        self.assertEqual(issue(self.db, ReviewRequest(aligned, request.rear_id, SAMPLES)).interfaces, ('p', 'q'))
        self.assertEqual(self.counts(), (3, 3))

    def test_swapped_seam(self):
        aligned = self.external_request('aligned', 'aligned', prefix='aligned')
        old = issue(self.db, aligned)
        wrong_id = import_pack(self.db, foreign_pack(REAR, 'crossed-rear', 'swapped'))
        with self.assertRaisesRegex(ValueError, '^NO_COMMON_EVIDENCE$', msg='SWAPPED_SEAM_DOUBLE_SIGNED'):
            issue(self.db, ReviewRequest(aligned.front_id, wrong_id, SAMPLES))
        self.assertEqual(self.counts(), (1, 1))
        self.assertEqual(fetch(self.db, old.result_id), old)
        self.assertEqual(issue(self.db, aligned).interfaces, ('p', 'q'))
        self.assertEqual(self.counts(), (2, 2))

    def test_mixed_batch(self):
        request = self.external_request()
        other = import_pack(self.db, foreign_pack(REAR, 'other-batch', batch='day-02'))
        with self.assertRaisesRegex(ValueError, '^MIXED_BATCH$'):
            issue(self.db, ReviewRequest(request.front_id, other, SAMPLES))
        self.assertEqual(self.counts(), (0, 0))

    def test_non_adjacent(self):
        request = self.external_request()
        body = json.loads(foreign_pack(REAR, 'different-neighbor'))
        for point in body['boundaries']:
            if point['direction'] == 'in':
                point['neighbor'] = 'another-station'
        other = import_pack(self.db, json.dumps(body))
        with self.assertRaisesRegex(ValueError, '^NON_ADJACENT$'):
            issue(self.db, ReviewRequest(request.front_id, other, SAMPLES))
        with self.assertRaisesRegex(ValueError, '^NON_ADJACENT$'):
            issue(self.db, ReviewRequest(request.rear_id, request.front_id, SAMPLES))
        self.assertEqual(self.counts(), (0, 0))

    def test_invalid_request(self):
        req = self.external_request()
        for invalid in ((), (*SAMPLES, SAMPLES[0]), (SAMPLES[0], SAMPLES[0]),
                        (SampleRequest('other', 'private', 'b1'),),
                        (SampleRequest('other', 'a1', ''),),
                        (SampleRequest('', 'a1', 'b1'),)):
            with self.subTest(samples=invalid), self.assertRaisesRegex(ValueError, '^INVALID_REQUEST$'):
                issue(self.db, ReviewRequest(req.front_id, req.rear_id, invalid))
        with self.assertRaisesRegex(LookupError, '^PACKAGE_NOT_FOUND$'):
            issue(self.db, ReviewRequest(req.front_id, 'not-imported', SAMPLES))
        self.assertEqual(self.counts(), (0, 0))

    def test_invalid_evidence(self):
        base = json.loads(foreign_pack(FRONT, 'malformed'))
        invalid = (
            {'singles': []},
            {'singles': [['a1', 'private']], 'pairs': []},
            {'singles': [['a1', 'a1']], 'pairs': []},
            {'singles': [['a1', 'p']], 'pairs': [[['a1', 'p'], ['a2', 'q']]]},
            {'singles': [['a1', 'p']], 'pairs': [[['a1', 'p']]]},
            {'singles': [['a1', ['p']]], 'pairs': []},
        )
        for evidence in invalid:
            with self.subTest(evidence=evidence), self.assertRaisesRegex(ValueError, '^INVALID_EVIDENCE$'):
                import_pack(self.db, json.dumps({**base, 'eligibility': evidence}))
        for payload in (json.dumps({**base, 'version': True}), json.dumps({**base, 'revision': ''}),
                        json.dumps({**base, 'boundaries': [base['boundaries'][0]] * 2}),
                        '{"version":1,"version":1}', b'\xff'):
            with self.assertRaisesRegex(ValueError, '^INVALID_PACKAGE$'):
                import_pack(self.db, payload)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM imported_packages').fetchone(), (0,))
        self.assertEqual(import_pack(self.db, foreign_pack(FRONT, 'empty', 'empty')), 'empty')

    def test_import_conflict(self):
        key = import_pack(self.db, foreign_pack(FRONT, 'fixed', 'aligned').encode('utf-8'))
        old = load_imported_package(self.db, key)
        self.assertEqual(import_pack(self.db, foreign_pack(FRONT, 'fixed', 'aligned', permute=True)), key)
        with self.assertRaisesRegex(ValueError, '^PACKAGE_ID_CONFLICT$'):
            import_pack(self.db, foreign_pack(FRONT, 'fixed', 'swapped'))
        self.assertEqual(load_imported_package(self.db, key), old)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM imported_packages').fetchone(), (1,))
