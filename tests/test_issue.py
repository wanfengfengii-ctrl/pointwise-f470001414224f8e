import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from freeze import close_day, open_successor, read_revision
from intake import add_node, create_draft, initialize_source, open_source, read_draft_snapshot, record, withdraw_record
from publish import publish_pack
from results import export_excerpt, fetch, initialize_night, issue, open_night
from review import ReviewRequest, import_pack
from samples import BATCH, FRONT, FRONT_BOUNDARIES, REAR, SAMPLES, foreign_pack, stage_front, stage_rear


class TestIssue(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.night_path = self.root / 'night.db'

    def foreign_request(self, db):
        front_id = import_pack(db, foreign_pack(FRONT, 'fixed-front', 'aligned'))
        rear_id = import_pack(db, foreign_pack(REAR, 'fixed-rear', 'aligned'))
        return ReviewRequest(front_id, rear_id, SAMPLES)

    def assert_rows(self, db, signed):
        result_rows = db.execute('SELECT result_id FROM issued_results ORDER BY result_id').fetchall()
        receipt_rows = db.execute('SELECT result_id, receipt_id FROM receipts ORDER BY result_id').fetchall()
        self.assertEqual(result_rows, [(result.result_id,) for result in signed])
        self.assertEqual(receipt_rows, [(result.result_id, result.receipt.receipt_id) for result in signed])

    def test_commit_failure(self):
        with closing(open_night(self.night_path)) as db:
            request = self.foreign_request(db)
            old = issue(db, request)
            db.execute('''
                CREATE TEMP TRIGGER fail_receipt BEFORE INSERT ON receipts
                BEGIN SELECT RAISE(ABORT, 'fixture receipt write failed'); END
            ''')
            with self.assertRaisesRegex(sqlite3.IntegrityError, '^fixture receipt write failed$'):
                issue(db, request)
            self.assertFalse(db.in_transaction)
        with closing(open_night(self.night_path)) as db:
            self.assert_rows(db, [old])
            self.assertEqual(fetch(db, old.result_id), old)
            with self.assertRaisesRegex(LookupError, '^RESULT_NOT_FOUND$'):
                fetch(db, old.result_id + 1)
            retry = issue(db, request)
            self.assertEqual(retry.interfaces, ('p', 'q'))
            self.assertNotEqual(retry.receipt, old.receipt)
            self.assert_rows(db, [old, retry])
            self.assertEqual(fetch(db, retry.result_id), retry)

    def test_deferred_commit_failure(self):
        with closing(open_night(self.night_path)) as db:
            request = self.foreign_request(db)
            old = issue(db, request)
            db.execute('CREATE TEMP TABLE fixture_parent (id INTEGER PRIMARY KEY)')
            db.execute('''
                CREATE TEMP TABLE fixture_block (
                    parent_id INTEGER REFERENCES fixture_parent (id) DEFERRABLE INITIALLY DEFERRED
                )
            ''')
            db.execute('''
                CREATE TEMP TRIGGER defer_failure AFTER INSERT ON receipts
                BEGIN INSERT INTO fixture_block VALUES (17); END
            ''')
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
                issue(db, request)
            self.assertFalse(db.in_transaction)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM fixture_block').fetchone(), (0,))
        with closing(open_night(self.night_path)) as db:
            self.assert_rows(db, [old])
            self.assertEqual(fetch(db, old.result_id), old)

    def test_historical_reprint(self):
        prep_path, lab_path = self.root / 'prep.db', self.root / 'lab.db'
        with closing(open_source(prep_path)) as prep, closing(open_source(lab_path)) as lab:
            old_pack = stage_front(prep, 'D1', 'R1', parallel=True)
            rear_pack = stage_rear(lab, revision='LAB-7')
            with closing(open_night(self.night_path)) as night:
                front_id = import_pack(night, old_pack)
                rear_id = import_pack(night, rear_pack)
                old = issue(night, ReviewRequest(front_id, rear_id, SAMPLES))
                original_excerpt = export_excerpt(night, old.result_id)
            correction = open_successor(prep, (FRONT, BATCH, 'R1'), 'D2')
            withdraw_record(prep, correction.key, 'r2')
            revised = close_day(prep, correction.key, 'R2', FRONT_BOUNDARIES)
            revised_payload = publish_pack(prep, revised.key)
            self.assertEqual(publish_pack(prep, (FRONT, BATCH, 'R1')), old_pack)
        prep_path.unlink()
        lab_path.unlink()
        with closing(open_night(self.night_path)) as night:
            revised_id = import_pack(night, revised_payload)
            self.assertNotEqual(revised_id, front_id)
            with self.assertRaisesRegex(ValueError, '^NO_COMMON_EVIDENCE$'):
                issue(night, ReviewRequest(revised_id, rear_id, SAMPLES))
            reopened = fetch(night, old.result_id)
            self.assertEqual(reopened, old)
            self.assertEqual(export_excerpt(night, old.result_id), original_excerpt)
            excerpt = json.loads(original_excerpt)
            self.assertEqual(excerpt, {
                'result_id': old.result_id,
                'parents': [
                    {'pack_id': front_id, 'station': FRONT, 'batch': BATCH, 'revision': 'R1'},
                    {'pack_id': rear_id, 'station': REAR, 'batch': BATCH, 'revision': 'LAB-7'},
                ],
                'samples': [
                    {'sample_id': 'sample-A', 'start': 'a1', 'end': 'b1', 'interface': 'p'},
                    {'sample_id': 'sample-B', 'start': 'a2', 'end': 'b2', 'interface': 'q'},
                ],
                'receipt': {'receipt_id': old.receipt.receipt_id, 'result_id': old.result_id},
            })
            self.assert_rows(night, [old])

    def test_missing_result(self):
        with closing(open_night(self.night_path)) as db:
            for result_id in (13, 0, True, '13', 2**63):
                with self.subTest(result_id=result_id), self.assertRaisesRegex(LookupError, '^RESULT_NOT_FOUND$'):
                    fetch(db, result_id)
            with self.assertRaisesRegex(LookupError, '^RESULT_NOT_FOUND$'):
                export_excerpt(db, 13)
            self.assert_rows(db, [])

    def test_repeat_init(self):
        source_path = self.root / 'user-prep.db'
        rear_path = self.root / 'user-lab.db'
        with closing(open_source(source_path)) as prep, closing(open_source(rear_path)) as lab:
            front_pack = stage_front(prep, 'D1', 'R1', parallel=True)
            rear_pack = stage_rear(lab)
            user = create_draft(prep, FRONT, BATCH, 'user-draft')
            add_node(prep, user.key, 'user-from')
            add_node(prep, user.key, 'user-to')
            saved = record(prep, user.key, 'user-record', 'user-from', 'user-to')
            initialize_source(prep)
        with closing(open_source(source_path)) as prep:
            self.assertEqual(read_draft_snapshot(prep, user.key).transfers, (saved,))
            self.assertEqual(read_revision(prep, (FRONT, BATCH, 'R1')).draft, 'D1')
            self.assertEqual(publish_pack(prep, (FRONT, BATCH, 'R1')), front_pack)
        with closing(open_night(self.night_path)) as db:
            request = ReviewRequest(import_pack(db, front_pack), import_pack(db, rear_pack), SAMPLES)
            old = issue(db, request)
            initialize_night(db)
            self.assert_rows(db, [old])
        source_path.unlink()
        rear_path.unlink()
        with closing(open_night(self.night_path)) as db:
            self.assertEqual(fetch(db, old.result_id), old)
            self.assertEqual(self.db_import_count(db), 2)
            retry = issue(db, request)
            self.assertEqual(retry.parents, old.parents)
            self.assertEqual(retry.interfaces, old.interfaces)
            self.assert_rows(db, [old, retry])

    def db_import_count(self, db):
        return db.execute('SELECT COUNT(*) FROM imported_packages').fetchone()[0]
