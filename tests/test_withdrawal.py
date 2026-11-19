import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from freeze import close_day, open_successor
from intake import open_source, record, withdraw_record
from publish import (
    decode_package, publish_pack, withdrawal_notice, withdrawal_sheet,
)
from results import (
    export_excerpt, fetch, fetch_withdrawal_review, issue, open_night,
    review_withdrawals,
)
from review import (
    ReviewRequest, SampleRequest, import_pack, import_withdrawal_notice,
    import_withdrawal_sheet,
)
from samples import BATCH, FRONT, FRONT_BOUNDARIES, REAR, SAMPLES, stage_front, stage_rear
from withdrawal_cases import stage_fallback_rear, stage_withdrawal_front


FRONT_KEY = FRONT, BATCH, 'R1'
REAR_KEY = REAR, BATCH, 'R1'


def reduced_evidence(payload_reduction):
    return payload_reduction


class TestWithdrawalSheet(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.path = self.root / 'prep.db'
        self.db = open_source(self.path)
        self.addCleanup(self.db.close)
        self.payload = stage_withdrawal_front(self.db, spare=False)
        self.sheet = withdrawal_sheet(self.db, FRONT_KEY)

    def assert_sheet_shape(self, text):
        body = json.loads(text)
        self.assertEqual(
            set(body),
            {'kind', 'version', 'pack_id', 'pack_sha256', 'aliases', 'response'},
        )
        self.assertEqual(body['kind'], 'withdrawal-sheet')
        self.assertIs(type(body['version']), int)
        self.assertEqual(body['pack_id'], decode_package(self.payload).pack_id)
        self.assertEqual(len(body['pack_sha256']), 64)
        self.assertEqual(int(body['pack_sha256'], 16) >= 0, True)
        self.assertEqual(body['aliases'], sorted(body['aliases']))
        self.assertEqual(len(set(body['aliases'])), len(body['aliases']))
        for alias in body['aliases']:
            self.assertIsInstance(alias, str)
            self.assertTrue(alias.strip())

    def test_fixed_sheet(self):
        self.assert_sheet_shape(self.sheet)
        self.assertEqual(withdrawal_sheet(self.db, FRONT_KEY), self.sheet)

    def test_reopen_and_later_revision(self):
        successor = open_successor(self.db, FRONT_KEY, 'D2')
        withdraw_record(self.db, successor.key, 'private-r')
        publish_pack(self.db, close_day(self.db, successor.key, 'R2', FRONT_BOUNDARIES).key)
        self.assertEqual(withdrawal_sheet(self.db, FRONT_KEY), self.sheet)
        self.db.close()
        self.db = open_source(self.path)
        self.assertEqual(withdrawal_sheet(self.db, FRONT_KEY), self.sheet)

    def test_source_material_stays_home(self):
        frozen = self.db.execute(
            'SELECT snapshot FROM revisions WHERE station=? AND batch=? AND revision=?',
            FRONT_KEY,
        ).fetchone()[0]
        self.assertIn('private-r', frozen)
        for private in ('private-r', 'private-s', 'private-t', 'private-alternate',
                        'private-other-sample', 'hidden-in', 'hidden-out'):
            self.assertNotIn(private, self.sheet)
        # Every record, including the detached private-t and hidden nodes,
        # contributes exactly one alias.
        body = json.loads(self.sheet)
        self.assertEqual(len(body['aliases']), 5)

    def test_sheet_missing_publication(self):
        with self.assertRaisesRegex(LookupError, '^PUBLICATION_NOT_FOUND$'):
            withdrawal_sheet(self.db, (FRONT, BATCH, 'R9'))

    def test_notice_before_sheet(self):
        notice = withdrawal_notice(self.db, FRONT_KEY, 'n1', ['private-r'])
        body = json.loads(notice)
        self.assertEqual(
            set(body),
            {'kind', 'version', 'pack_id', 'sheet_sha256', 'notice_id', 'aliases'},
        )
        self.assertEqual(body['kind'], 'withdrawal-notice')
        self.assertEqual(body['notice_id'], 'n1')
        sheet = json.loads(self.sheet)
        import hashlib
        expected = hashlib.sha256(
            json.dumps(sheet, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=True, allow_nan=False).encode('utf-8')
        ).hexdigest()
        self.assertEqual(body['sheet_sha256'], expected)
        self.assertEqual(len(body['aliases']), 1)
        self.assertIn(body['aliases'][0], sheet['aliases'])

    def test_notice_argument_forms(self):
        as_list = withdrawal_notice(self.db, FRONT_KEY, 'n1', ['private-r', 'private-s'])
        as_tuple = withdrawal_notice(self.db, FRONT_KEY, 'n1', ('private-s', 'private-r'))
        as_set = withdrawal_notice(self.db, FRONT_KEY, 'n1', {'private-r', 'private-s'})
        self.assertEqual(as_list, as_tuple)
        self.assertEqual(as_list, as_set)
        repeated = withdrawal_notice(self.db, FRONT_KEY, 'n1',
                                     ['private-r', 'private-s', 'private-r'])
        self.assertEqual(as_list, repeated)

    def test_notice_detached_record(self):
        notice = withdrawal_notice(self.db, FRONT_KEY, 'detached', ['private-t'])
        self.assertTrue(json.loads(notice)['aliases'])

    def test_notice_rejections(self):
        for bad in ([], (), set(), [''], [None], 'private-r'):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, '^INVALID_NOTICE$'):
                withdrawal_notice(self.db, FRONT_KEY, 'n1', bad)
        with self.assertRaisesRegex(ValueError, '^RECORD_NOT_IN_REVISION$'):
            withdrawal_notice(self.db, FRONT_KEY, 'n1', ['no-such-record'])
        with self.assertRaisesRegex(ValueError, '^INVALID_NOTICE$'):
            withdrawal_notice(self.db, FRONT_KEY, '', ['private-r'])
        with self.assertRaisesRegex(LookupError, '^PUBLICATION_NOT_FOUND$'):
            withdrawal_notice(self.db, (FRONT, BATCH, 'R9'), 'n1', ['private-r'])
        with self.assertRaisesRegex(ValueError, '^RECORD_NOT_IN_REVISION$'):
            withdrawal_notice(self.db, FRONT_KEY, 'n1', ['private-r', 'ghost'])


class NightFixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.night_path = self.root / 'night.db'
        self.night = open_night(self.night_path)
        self.addCleanup(self.night.close)

    def sources(self, *, spare, rear_kind='fallback'):
        with closing(open_source(':memory:')) as prep, closing(open_source(':memory:')) as lab:
            front = stage_withdrawal_front(prep, spare=spare)
            rear = (stage_fallback_rear(lab) if rear_kind == 'fallback'
                    else stage_rear(lab))
            sheets = {
                FRONT: withdrawal_sheet(prep, FRONT_KEY),
                REAR: withdrawal_sheet(lab, REAR_KEY),
            }
            return front, rear, sheets

    def seed(self, *, spare, samples=SAMPLES):
        front, rear, sheets = self.sources(spare=spare)
        front_id = import_pack(self.night, front)
        rear_id = import_pack(self.night, rear)
        result = issue(self.night, ReviewRequest(front_id, rear_id, samples))
        import_withdrawal_sheet(self.night, sheets[FRONT])
        import_withdrawal_sheet(self.night, sheets[REAR])
        return result, sheets

    def notice(self, sheets, pack_id, notice_id, records):
        # Regenerate the same notice via the issuing source helpers.
        return _notice_for(sheets, pack_id, notice_id, records)


def _notice_for(sheets, pack_id, notice_id, records):
    raise AssertionError('overridden per test')


class TestSheetAcceptance(NightFixture):
    def test_requires_accepted_package(self):
        with closing(open_source(':memory:')) as prep:
            stage_withdrawal_front(prep, spare=False)
            sheet = withdrawal_sheet(prep, FRONT_KEY)
        with self.assertRaisesRegex(LookupError, '^PACKAGE_NOT_FOUND$'):
            import_withdrawal_sheet(self.night, sheet)

    def test_redelivery_and_structure(self):
        front, rear, sheets = self.sources(spare=False)
        front_id = import_pack(self.night, front)
        self.assertEqual(import_withdrawal_sheet(self.night, sheets[FRONT].encode()), front_id)
        self.assertEqual(import_withdrawal_sheet(self.night, sheets[FRONT]), front_id)
        body = json.loads(sheets[FRONT])
        body['response']['singles'] = list(reversed(body['response']['singles']))
        rearranged = json.dumps(body)
        self.assertEqual(import_withdrawal_sheet(self.night, rearranged), front_id)
        self.assertEqual(
            self.night.execute('SELECT COUNT(*) FROM withdrawal_sheets').fetchone(), (1,)
        )

    def test_digest_and_structure_rejections(self):
        front, rear, sheets = self.sources(spare=False)
        front_id = import_pack(self.night, front)
        base = json.loads(sheets[FRONT])

        tampered_digest = {**base, 'pack_sha256': '0' * 64}
        for body, message in (
            (tampered_digest, '^SHEET_DIGEST_MISMATCH$'),
            ({**base, 'version': True}, '^INVALID_SHEET$'),
            ({**base, 'kind': 'withdrawal-witnesses'}, '^INVALID_SHEET$'),
            ({**base, 'aliases': []}, '^INVALID_SHEET$'),
            ({**base, 'aliases': ['a', 'a']}, '^INVALID_SHEET$'),
            ({**base, 'response': {'kind': 'other', 'singles': []}}, '^INVALID_SHEET$'),
        ):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, message):
                import_withdrawal_sheet(self.night, json.dumps(body))
        with self.assertRaisesRegex(LookupError, '^PACKAGE_NOT_FOUND$'):
            import_withdrawal_sheet(self.night, json.dumps({**base, 'pack_id': 'other'}))
        with self.assertRaisesRegex(ValueError, '^INVALID_SHEET$'):
            import_withdrawal_sheet(self.night, '{"kind":"withdrawal-sheet","kind":"x"}')
        self.assertEqual(
            self.night.execute('SELECT COUNT(*) FROM withdrawal_sheets').fetchone(), (0,)
        )
        self.assertEqual(import_withdrawal_sheet(self.night, sheets[FRONT]), front_id)

    def test_one_sheet_per_parent(self):
        front, rear, sheets = self.sources(spare=False)
        import_pack(self.night, front)
        import_withdrawal_sheet(self.night, sheets[FRONT])
        body = json.loads(sheets[FRONT])
        # A different sheet that still reproduces V1 on an empty withdrawal:
        # drop the unused alias of a record that no public route mentions.
        referenced = {
            alias
            for entry in body['response']['singles']
            for witness in entry['witnesses']
            for alias in witness
        }
        unused = [alias for alias in body['aliases'] if alias not in referenced]
        self.assertTrue(unused)
        body['aliases'].remove(unused[0])
        with self.assertRaisesRegex(ValueError, '^SHEET_CONFLICT$'):
            import_withdrawal_sheet(self.night, json.dumps(body))
        stored = self.night.execute('SELECT payload FROM withdrawal_sheets').fetchone()[0]
        self.assertEqual(json.loads(stored), json.loads(sheets[FRONT]))

    def test_empty_withdrawal_must_match_v1(self):
        front, rear, sheets = self.sources(spare=False)
        import_pack(self.night, front)
        body = json.loads(sheets[FRONT])
        dropped = body['response']['singles'][0]
        body['response']['singles'] = body['response']['singles'][1:]
        with self.assertRaisesRegex(ValueError, '^INVALID_SHEET$'):
            import_withdrawal_sheet(self.night, json.dumps(body))
        body['response']['singles'].append(dropped)
        import_withdrawal_sheet(self.night, json.dumps(body))


class TestNoticeAcceptance(NightFixture):
    def setUp(self):
        super().setUp()
        self.front, self.rear, self.sheets = self.sources(spare=False)
        with closing(open_source(':memory:')) as prep, closing(open_source(':memory:')) as lab:
            stage_withdrawal_front(prep, spare=False)
            stage_fallback_rear(lab)
            self.prep = prep
        self.front_id = import_pack(self.night, self.front)
        self.rear_id = import_pack(self.night, self.rear)

    def publish_source_notices(self):
        with closing(open_source(':memory:')) as prep, closing(open_source(':memory:')) as lab:
            stage_withdrawal_front(prep, spare=False)
            stage_fallback_rear(lab)
            return {
                'r': withdrawal_notice(prep, FRONT_KEY, 'r', ['private-r']),
                's': withdrawal_notice(prep, FRONT_KEY, 's', ['private-s']),
                't': withdrawal_notice(prep, FRONT_KEY, 't', ['private-t']),
                'rs': withdrawal_notice(prep, FRONT_KEY, 'rs', ['private-r', 'private-s']),
            }

    def test_failed_notice_import_leaves_set_unchanged(self):
        notices = self.publish_source_notices()
        import_withdrawal_sheet(self.night, self.sheets[FRONT])
        import_withdrawal_notice(self.night, notices['r'])
        self.night.execute('''
            CREATE TEMP TRIGGER fail_notice BEFORE INSERT ON withdrawal_notices
            BEGIN SELECT RAISE(ABORT, 'fixture notice write failed'); END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, '^fixture notice write failed$'):
            import_withdrawal_notice(self.night, notices['s'])
        self.assertFalse(self.night.in_transaction)
        rows = self.night.execute(
            'SELECT notice_id FROM withdrawal_notices ORDER BY notice_id'
        ).fetchall()
        self.assertEqual(rows, [('r',)])
        self.night.execute('DROP TRIGGER fail_notice')
        self.assertEqual(import_withdrawal_notice(self.night, notices['s']),
                         (self.front_id, 's'))
        self.assertEqual(
            self.night.execute('SELECT COUNT(*) FROM withdrawal_notices').fetchone(), (2,)
        )

    def test_notice_requires_sheet(self):
        notices = self.publish_source_notices()
        with self.assertRaisesRegex(LookupError, '^SHEET_NOT_FOUND$'):
            import_withdrawal_notice(self.night, notices['r'])
        with self.assertRaisesRegex(LookupError, '^PACKAGE_NOT_FOUND$'):
            import_withdrawal_notice(
                self.night, notices['r'].replace(self.front_id, 'unknown-pack')
            )

    def test_identity_and_redelivery(self):
        notices = self.publish_source_notices()
        import_withdrawal_sheet(self.night, self.sheets[FRONT])
        first = import_withdrawal_notice(self.night, notices['r'])
        self.assertEqual(first, (self.front_id, 'r'))
        self.assertEqual(import_withdrawal_notice(self.night, notices['r'].encode()), first)
        body = json.loads(notices['r'])
        body['aliases'] = list(reversed(body['aliases']))
        self.assertEqual(import_withdrawal_notice(self.night, json.dumps(body)), first)
        self.assertEqual(import_withdrawal_notice(self.night, notices['s']),
                         (self.front_id, 's'))
        # Different notice ids may withdraw the same alias.
        self.assertEqual(import_withdrawal_notice(self.night, notices['t']),
                         (self.front_id, 't'))
        other = json.loads(notices['r'])
        other['aliases'] = sorted(other['aliases'] + json.loads(notices['s'])['aliases'])
        with self.assertRaisesRegex(ValueError, '^NOTICE_CONFLICT$'):
            import_withdrawal_notice(self.night, json.dumps(other))
        rows = self.night.execute(
            'SELECT notice_id, aliases FROM withdrawal_notices ORDER BY notice_id'
        ).fetchall()
        self.assertEqual([row[0] for row in rows], ['r', 's', 't'])
        self.assertEqual(json.loads(rows[0][1]), json.loads(notices['r'])['aliases'])

    def test_unknown_alias_and_wrong_sheet(self):
        notices = self.publish_source_notices()
        import_withdrawal_sheet(self.night, self.sheets[FRONT])
        body = json.loads(notices['r'])
        body['aliases'] = ['not-an-alias']
        with self.assertRaisesRegex(ValueError, '^UNKNOWN_ALIAS$'):
            import_withdrawal_notice(self.night, json.dumps(body))
        wrong = json.loads(notices['r'])
        wrong['sheet_sha256'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, '^SHEET_DIGEST_MISMATCH$'):
            import_withdrawal_notice(self.night, json.dumps(wrong))
        malformed = json.loads(notices['r'])
        malformed['aliases'] = []
        with self.assertRaisesRegex(ValueError, '^INVALID_NOTICE$'):
            import_withdrawal_notice(self.night, json.dumps(malformed))
        self.assertEqual(
            self.night.execute('SELECT COUNT(*) FROM withdrawal_notices').fetchone(), (0,)
        )


class TestWithdrawalReview(NightFixture):
    def setUp(self):
        super().setUp()
        self.prep_path = self.root / 'prep.db'
        self.lab_path = self.root / 'lab.db'
        with closing(open_source(self.prep_path)) as prep, closing(open_source(self.lab_path)) as lab:
            self.front_shared = stage_withdrawal_front(prep, spare=True)
            self.front_isolated = stage_withdrawal_front(prep, spare=False, revision='R9')
            self.rear = stage_fallback_rear(lab)
            self.sheet_shared = withdrawal_sheet(prep, (FRONT, BATCH, 'R1'))
            self.sheet_isolated = withdrawal_sheet(prep, (FRONT, BATCH, 'R9'))
            self.notices_shared = {
                from_records: withdrawal_notice(prep, FRONT_KEY, from_records, records)
                for from_records, records in {
                    'r': ['private-r'], 's': ['private-s'], 't': ['private-t'],
                    'rs': ['private-r', 'private-s'],
                }.items()
            }
            self.notices_isolated = {
                'r': withdrawal_notice(prep, (FRONT, BATCH, 'R9'), 'r', ['private-r']),
                's': withdrawal_notice(prep, (FRONT, BATCH, 'R9'), 's', ['private-s']),
            }
            self.rear_sheet = withdrawal_sheet(lab, REAR_KEY)

    def open_result(self, front_payload, sheet, notices):
        front_id = import_pack(self.night, front_payload)
        rear_id = import_pack(self.night, self.rear)
        result = issue(self.night, ReviewRequest(front_id, rear_id, SAMPLES))
        import_withdrawal_sheet(self.night, sheet)
        import_withdrawal_sheet(self.night, self.rear_sheet)
        for notice in notices:
            import_withdrawal_notice(self.night, notice)
        return result

    def test_cumulative_conclusions(self):
        shared = self.open_result(self.front_shared, self.sheet_shared,
                                  [self.notices_shared['r']])
        first = review_withdrawals(self.night, shared.result_id)
        self.assertEqual(first['status'], 'valid')
        self.assertEqual(first['interfaces'], ['p', 'q'])
        import_withdrawal_notice(self.night, self.notices_shared['s'])
        second = review_withdrawals(self.night, shared.result_id)
        self.assertEqual(second['status'], 'valid')
        self.assertEqual([row['notice_id'] for row in second['notices']], ['r', 's'])
        self.assertNotEqual(first['review_id'], second['review_id'])
        self.assertEqual(fetch_withdrawal_review(self.night, first['review_id']), first)
        self.assertEqual(fetch_withdrawal_review(self.night, second['review_id']), second)

        isolated = self.open_result(
            self.front_isolated, self.sheet_isolated,
            [self.notices_isolated['r'], self.notices_isolated['s']],
        )
        verdict = review_withdrawals(self.night, isolated.result_id)
        self.assertEqual(verdict['status'], 'invalid')
        self.assertEqual(verdict['interfaces'], ['p', 'q'])

    def test_notice_order_and_duplicate_delivery(self):
        shared = self.open_result(self.front_shared, self.sheet_shared,
                                  [self.notices_shared['r'], self.notices_shared['s']])
        first = review_withdrawals(self.night, shared.result_id)
        import_withdrawal_notice(self.night, self.notices_shared['s'])
        import_withdrawal_notice(self.night, self.notices_shared['r'])
        second = review_withdrawals(self.night, shared.result_id)
        self.assertEqual(first['status'], second['status'])
        self.assertEqual(first['notices'], second['notices'])
        self.assertEqual([row['notice_id'] for row in first['notices']], ['r', 's'])

    def test_fallback_parent_without_notice(self):
        shared = self.open_result(self.front_shared, self.sheet_shared, [])
        with self.assertRaisesRegex(LookupError, '^NO_WITHDRAWAL_NOTICE$'):
            review_withdrawals(self.night, shared.result_id)
        import_withdrawal_notice(self.night, self.notices_shared['r'])
        # Only the front parent has a notice; the rear falls back to V1.
        verdict = review_withdrawals(self.night, shared.result_id)
        self.assertEqual(verdict['status'], 'valid')
        self.assertEqual(verdict['notices'], [{'pack_id': verdict['parents'][0]['pack_id'],
                                               'notice_id': 'r'}])

    def test_other_revision_notice_does_not_participate(self):
        shared = self.open_result(self.front_shared, self.sheet_shared,
                                  [self.notices_shared['r']])
        # A notice for a different revision of the same station and batch.
        with closing(open_source(':memory:')) as prep:
            stranger_pack = stage_withdrawal_front(prep, spare=False, revision='R2')
            stranger_id = decode_package(stranger_pack).pack_id
            stranger_sheet = withdrawal_sheet(prep, (FRONT, BATCH, 'R2'))
            stranger = withdrawal_notice(prep, (FRONT, BATCH, 'R2'), 'zz', ['private-r'])
        import_pack(self.night, stranger_pack)
        import_withdrawal_sheet(self.night, stranger_sheet)
        import_withdrawal_notice(self.night, stranger)
        verdict = review_withdrawals(self.night, shared.result_id)
        self.assertEqual([row['notice_id'] for row in verdict['notices']], ['r'])
        self.assertNotEqual(verdict['parents'][0]['pack_id'], stranger_id)

    def test_missing_result(self):
        for result_id in (1, 0, True, '1', 2**63):
            with self.subTest(result_id=result_id), self.assertRaisesRegex(
                    LookupError, '^RESULT_NOT_FOUND$'):
                review_withdrawals(self.night, result_id)
        for review_id in (1, 0, True, '1', 2**63):
            with self.subTest(review_id=review_id), self.assertRaisesRegex(
                    LookupError, '^REVIEW_NOT_FOUND$'):
                fetch_withdrawal_review(self.night, review_id)

    def test_commit_failure_and_reopen(self):
        shared = self.open_result(self.front_shared, self.sheet_shared,
                                  [self.notices_shared['r']])
        self.night.execute('''
            CREATE TEMP TRIGGER fail_review BEFORE INSERT ON withdrawal_reviews
            BEGIN SELECT RAISE(ABORT, 'fixture review write failed'); END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, '^fixture review write failed$'):
            review_withdrawals(self.night, shared.result_id)
        self.assertFalse(self.night.in_transaction)
        self.assertEqual(
            self.night.execute('SELECT COUNT(*) FROM withdrawal_reviews').fetchone(), (0,)
        )
        self.night.execute('DROP TRIGGER fail_review')
        verdict = review_withdrawals(self.night, shared.result_id)
        self.assertEqual(verdict['status'], 'valid')
        self.night.close()
        self.night = open_night(self.night_path)
        self.assertEqual(fetch_withdrawal_review(self.night, verdict['review_id']), verdict)
        self.assertEqual(fetch(self.night, shared.result_id), shared)
        self.assertEqual(json.loads(export_excerpt(self.night, shared.result_id))['result_id'],
                         shared.result_id)

    def test_late_notice_does_not_change_old_review(self):
        shared = self.open_result(self.front_shared, self.sheet_shared,
                                  [self.notices_shared['r']])
        old = review_withdrawals(self.night, shared.result_id)
        import_withdrawal_notice(self.night, self.notices_shared['s'])
        self.assertEqual(fetch_withdrawal_review(self.night, old['review_id']), old)
        fresh = review_withdrawals(self.night, shared.result_id)
        self.assertEqual(len(fresh['notices']), 2)
        self.assertEqual([row['notice_id'] for row in old['notices']], ['r'])

    def test_detached_record_withdrawal_is_noop(self):
        shared = self.open_result(self.front_shared, self.sheet_shared,
                                  [self.notices_shared['r']])
        before = review_withdrawals(self.night, shared.result_id)
        import_withdrawal_notice(self.night, self.notices_shared['t'])
        after = review_withdrawals(self.night, shared.result_id)
        self.assertEqual(before['status'], after['status'])
        self.assertEqual(before['interfaces'], after['interfaces'])

    def test_original_binding_decides_even_if_alternative_exists(self):
        shared = self.open_result(self.front_shared, self.sheet_shared,
                                  [self.notices_shared['rs']])
        verdict = review_withdrawals(self.night, shared.result_id)
        # The original binding is (p, q); spare=True keeps it valid.
        self.assertEqual(verdict['status'], 'valid')
        isolated = self.open_result(
            self.front_isolated, self.sheet_isolated,
            [self.notices_isolated['r'], self.notices_isolated['s']],
        )
        verdict = review_withdrawals(self.night, isolated.result_id)
        self.assertEqual(verdict['status'], 'invalid')
        self.assertEqual(verdict['interfaces'], ['p', 'q'])

    def test_two_samples_sharing_relation(self):
        front = self.front_shared
        rear = self.rear
        front_id = import_pack(self.night, front)
        rear_id = import_pack(self.night, rear)
        samples = (SampleRequest('x', 'a1', 'b1'), SampleRequest('y', 'a1', 'b1'))
        # Two public relations are equal, but disjoint station records exist
        # on both sides, so this still counts as two samples.
        signed = issue(self.night, ReviewRequest(front_id, rear_id, samples))
        self.assertEqual(signed.interfaces, ('p', 'q'))
        self.assertEqual(signed.samples, samples)



class TestAcceptanceIntegrity(NightFixture):
    def test_duplicate_witness_alias_rejected(self):
        with closing(open_source(':memory:')) as prep:
            front = stage_withdrawal_front(prep, spare=False)
            sheet = json.loads(withdrawal_sheet(prep, FRONT_KEY))
        import_pack(self.night, front)
        entry = sheet['response']['singles'][0]
        entry['witnesses'].append(list(entry['witnesses'][0]) * 2)
        with self.assertRaisesRegex(ValueError, '^INVALID_SHEET$'):
            import_withdrawal_sheet(self.night, json.dumps(sheet))
        entry['witnesses'] = entry['witnesses'][:-1] + [['not-in-scope']]
        with self.assertRaisesRegex(ValueError, '^INVALID_SHEET$'):
            import_withdrawal_sheet(self.night, json.dumps(sheet))

    def test_notice_alias_must_be_in_sheet(self):
        with closing(open_source(':memory:')) as prep, closing(open_source(':memory:')) as lab:
            front = stage_withdrawal_front(prep, spare=False)
            rear = stage_fallback_rear(lab)
            sheet = withdrawal_sheet(prep, FRONT_KEY)
            notice = json.loads(withdrawal_notice(prep, FRONT_KEY, 'n', ['private-r']))
            other_notice = json.loads(withdrawal_notice(
                lab, REAR_KEY, 'n', ['private-lab-p']))
        front_id = import_pack(self.night, front)
        import_pack(self.night, rear)
        import_withdrawal_sheet(self.night, sheet)
        # Correct parent and digest, but an alias that is not in this sheet.
        notice['aliases'] = ['WA-' + '0' * 64]
        with self.assertRaisesRegex(ValueError, '^UNKNOWN_ALIAS$'):
            import_withdrawal_notice(self.night, json.dumps(notice))
        # The same alias in another parent's scope stays meaningless.
        crossed = {**other_notice, 'pack_id': front_id}
        with self.assertRaisesRegex(ValueError, '^SHEET_DIGEST_MISMATCH$'):
            import_withdrawal_notice(self.night, json.dumps(crossed))


class TestReviewSnapshotShape(NightFixture):
    def test_snapshot_fields(self):
        with closing(open_source(':memory:')) as prep, closing(open_source(':memory:')) as lab:
            front = stage_withdrawal_front(prep, spare=False)
            rear = stage_fallback_rear(lab)
            front_sheet = withdrawal_sheet(prep, FRONT_KEY)
            rear_sheet = withdrawal_sheet(lab, REAR_KEY)
            notice = withdrawal_notice(prep, FRONT_KEY, 'n', ['private-r'])
        front_id = import_pack(self.night, front)
        rear_id = import_pack(self.night, rear)
        result = issue(self.night, ReviewRequest(front_id, rear_id, SAMPLES))
        import_withdrawal_sheet(self.night, front_sheet)
        import_withdrawal_sheet(self.night, rear_sheet)
        import_withdrawal_notice(self.night, notice)
        verdict = review_withdrawals(self.night, result.result_id)
        self.assertEqual(
            set(verdict),
            {'review_id', 'result_id', 'parents', 'samples', 'interfaces',
             'notices', 'status'},
        )
        self.assertIs(type(verdict['review_id']), int)
        self.assertEqual(verdict['result_id'], result.result_id)
        self.assertEqual(
            verdict['parents'],
            [
                {'pack_id': front_id, 'station': FRONT, 'batch': BATCH, 'revision': 'R1'},
                {'pack_id': rear_id, 'station': REAR, 'batch': BATCH, 'revision': 'R1'},
            ],
        )
        self.assertEqual(
            verdict['samples'],
            [
                {'sample_id': 'sample-A', 'start': 'a1', 'end': 'b1'},
                {'sample_id': 'sample-B', 'start': 'a2', 'end': 'b2'},
            ],
        )
        self.assertEqual(verdict['interfaces'], ['p', 'q'])
        self.assertEqual(verdict['notices'],
                         [{'pack_id': front_id, 'notice_id': 'n'}])
        self.assertEqual(verdict['status'], 'valid')
        self.assertEqual(verdict, fetch_withdrawal_review(
            self.night, verdict['review_id']))
        self.assertEqual(fetch(self.night, result.result_id), result)



class TestDerivedEvidence(unittest.TestCase):
    def test_identical_relations_still_two_samples(self):
        from intake import add_node, create_draft, record
        from freeze import BoundaryPoint, close_day
        from publish import decode_package, publish_pack, withdrawal_sheet
        from publish.withdrawal import derive_evidence, parse_sheet
        from publish.package import encode_package

        with closing(open_source(':memory:')) as db:
            day = create_draft(db, 'one', 'day-01', 'D1')
            for node in ('A', 'B'):
                add_node(db, day.key, node)
            record(db, day.key, 'first', 'A', 'B')
            record(db, day.key, 'second', 'A', 'B')
            payload = publish_pack(db, close_day(
                db, day.key, 'R1',
                (BoundaryPoint('a', 'A'), BoundaryPoint('p', 'B')),
            ).key)
            package = decode_package(payload)
            self.assertTrue(package.evidence.allows_pair(('a', 'p'), ('a', 'p')))
            text = withdrawal_sheet(db, ('one', 'day-01', 'R1'))
            body = json.loads(text)
            entry = next(e for e in body['response']['singles']
                         if e['relation'] == ['a', 'p'])
            self.assertEqual(len(entry['witnesses']), 2)
            _text, families = parse_sheet(text, package, encode_package(package))
        # Withdraw one witness: the pair needs two disjoint witnesses, so it
        # must fail while the single relation stays eligible.
        withdrawn = frozenset(entry['witnesses'][0])
        reduced = derive_evidence(families, withdrawn)
        self.assertTrue(reduced.allows_single('a', 'p'))
        self.assertFalse(reduced.allows_pair(('a', 'p'), ('a', 'p')))
        # Withdraw everything: nothing is eligible.
        empty = derive_evidence(families, frozenset(body['aliases']))
        self.assertEqual(empty.singles, frozenset())
        self.assertEqual(empty.pairs, frozenset())


class TestParallelRecordWithdrawal(NightFixture):
    def test_shared_remaining_record(self):
        with closing(open_source(':memory:')) as prep, closing(open_source(':memory:')) as lab:
            front = stage_front(prep, 'D1', 'R1', parallel=True)
            rear = stage_rear(lab)
            front_sheet = withdrawal_sheet(prep, FRONT_KEY)
            rear_sheet = withdrawal_sheet(lab, REAR_KEY)
            notice = withdrawal_notice(prep, FRONT_KEY, 'drop-r1', ['r1'])
        front_id = import_pack(self.night, front)
        rear_id = import_pack(self.night, rear)
        result = issue(self.night, ReviewRequest(front_id, rear_id, SAMPLES))
        import_withdrawal_sheet(self.night, front_sheet)
        import_withdrawal_sheet(self.night, rear_sheet)
        import_withdrawal_notice(self.night, notice)
        joint = review_withdrawals(self.night, result.result_id)
        self.assertEqual(joint['status'], 'invalid')
        self.assertEqual(joint['interfaces'], ['p', 'q'])
        for sample in SAMPLES:
            signed = issue(self.night, ReviewRequest(front_id, rear_id, (sample,)))
            single = review_withdrawals(self.night, signed.result_id)
            self.assertEqual(single['status'], 'valid')
        self.assertEqual(self.night.execute(
            'SELECT COUNT(*) FROM issued_results').fetchone(), (3,))


class TestParentScope(NightFixture):
    def sources_for(self):
        with closing(open_source(':memory:')) as prep, closing(open_source(':memory:')) as lab:
            front = stage_withdrawal_front(prep, spare=True)
            rear = stage_fallback_rear(lab)
            sheets = {
                FRONT: withdrawal_sheet(prep, FRONT_KEY),
                REAR: withdrawal_sheet(lab, REAR_KEY),
            }
            front_notice = withdrawal_notice(prep, FRONT_KEY, 'same-id', ['private-r'])
            rear_notice = withdrawal_notice(lab, REAR_KEY, 'same-id', ['private-lab-p'])
        return front, rear, sheets, front_notice, rear_notice

    def test_same_notice_id_on_both_parents(self):
        front, rear, sheets, front_notice, rear_notice = self.sources_for()
        front_id = import_pack(self.night, front)
        rear_id = import_pack(self.night, rear)
        result = issue(self.night, ReviewRequest(front_id, rear_id, SAMPLES))
        import_withdrawal_sheet(self.night, sheets[FRONT])
        import_withdrawal_sheet(self.night, sheets[REAR])
        self.assertEqual(import_withdrawal_notice(self.night, front_notice),
                         (front_id, 'same-id'))
        self.assertEqual(import_withdrawal_notice(self.night, rear_notice),
                         (rear_id, 'same-id'))
        verdict = review_withdrawals(self.night, result.result_id)
        expected = sorted(
            ({'pack_id': front_id, 'notice_id': 'same-id'},
             {'pack_id': rear_id, 'notice_id': 'same-id'}),
            key=lambda row: (row['pack_id'], row['notice_id']),
        )
        self.assertEqual(verdict['notices'], expected)
        # Withdrawing the rear p->b1 record invalidates the original binding.
        self.assertEqual(verdict['status'], 'invalid')

    def test_single_sample_review(self):
        front, rear, sheets, front_notice, _rear_notice = self.sources_for()
        front_id = import_pack(self.night, front)
        rear_id = import_pack(self.night, rear)
        for sample in SAMPLES:
            result = issue(self.night, ReviewRequest(front_id, rear_id, (sample,)))
            import_withdrawal_sheet(self.night, sheets[FRONT])
            import_withdrawal_sheet(self.night, sheets[REAR])
            import_withdrawal_notice(self.night, front_notice)
            verdict = review_withdrawals(self.night, result.result_id)
            self.assertEqual(verdict['samples'], [
                {'sample_id': sample.sample_id, 'start': sample.start, 'end': sample.end},
            ])
            self.assertEqual(verdict['interfaces'], list(result.interfaces))
            self.assertEqual(verdict['status'], 'valid')


class TestReviewCommitFailure(NightFixture):
    def test_deferred_commit_failure_leaves_no_review(self):
        with closing(open_source(':memory:')) as prep, closing(open_source(':memory:')) as lab:
            front = stage_withdrawal_front(prep, spare=False)
            rear = stage_fallback_rear(lab)
            front_sheet = withdrawal_sheet(prep, FRONT_KEY)
            rear_sheet = withdrawal_sheet(lab, REAR_KEY)
            notice = withdrawal_notice(prep, FRONT_KEY, 'n', ['private-r'])
        front_id = import_pack(self.night, front)
        rear_id = import_pack(self.night, rear)
        result = issue(self.night, ReviewRequest(front_id, rear_id, SAMPLES))
        import_withdrawal_sheet(self.night, front_sheet)
        import_withdrawal_sheet(self.night, rear_sheet)
        import_withdrawal_notice(self.night, notice)
        self.night.execute('CREATE TEMP TABLE fixture_review_parent (id INTEGER PRIMARY KEY)')
        self.night.execute('''
            CREATE TEMP TABLE fixture_review_block (
                parent_id INTEGER REFERENCES fixture_review_parent (id)
                    DEFERRABLE INITIALLY DEFERRED
            )
        ''')
        self.night.execute('''
            CREATE TEMP TRIGGER defer_review_failure AFTER INSERT ON withdrawal_reviews
            BEGIN INSERT INTO fixture_review_block VALUES (23); END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
            review_withdrawals(self.night, result.result_id)
        self.assertFalse(self.night.in_transaction)
        self.assertEqual(self.night.execute(
            'SELECT COUNT(*) FROM fixture_review_block').fetchone(), (0,))
        self.assertEqual(self.night.execute(
            'SELECT COUNT(*) FROM withdrawal_reviews').fetchone(), (0,))
        self.night.close()
        self.night = open_night(self.night_path)
        self.assertEqual(self.night.execute(
            'SELECT COUNT(*) FROM withdrawal_reviews').fetchone(), (0,))
        verdict = review_withdrawals(self.night, result.result_id)
        self.assertEqual(verdict['status'], 'valid')
        self.assertEqual(fetch_withdrawal_review(self.night, verdict['review_id']), verdict)


class TestSameAliasTwoNotices(NightFixture):
    def test_two_notice_ids_withdrawing_same_alias(self):
        with closing(open_source(':memory:')) as prep, closing(open_source(':memory:')) as lab:
            front = stage_withdrawal_front(prep, spare=False)
            rear = stage_fallback_rear(lab)
            front_sheet = withdrawal_sheet(prep, FRONT_KEY)
            rear_sheet = withdrawal_sheet(lab, REAR_KEY)
            first_notice = withdrawal_notice(prep, FRONT_KEY, 'a-first', ['private-r'])
            second_notice = withdrawal_notice(prep, FRONT_KEY, 'b-second', ['private-r'])
        front_id = import_pack(self.night, front)
        rear_id = import_pack(self.night, rear)
        result = issue(self.night, ReviewRequest(front_id, rear_id, SAMPLES))
        import_withdrawal_sheet(self.night, front_sheet)
        import_withdrawal_sheet(self.night, rear_sheet)
        import_withdrawal_notice(self.night, first_notice)
        import_withdrawal_notice(self.night, second_notice)
        verdict = review_withdrawals(self.night, result.result_id)
        self.assertEqual([row['notice_id'] for row in verdict['notices']],
                         ['a-first', 'b-second'])
        self.assertEqual(verdict['status'], 'valid')
        self.assertEqual(self.night.execute(
            'SELECT COUNT(*) FROM withdrawal_notices').fetchone(), (2,))
