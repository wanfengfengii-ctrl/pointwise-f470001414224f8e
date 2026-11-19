import json
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from freeze import close_day, open_successor
from intake import open_source, record, withdraw_record
from publish import publish_pack
from results import export_excerpt, fetch, issue, open_night
from review import ReviewRequest, import_pack
from samples import BATCH, FRONT, FRONT_BOUNDARIES, SAMPLES, stage_front, stage_rear


def _counts(db):
    results = db.execute('SELECT COUNT(*) FROM issued_results').fetchone()[0]
    receipts = db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0]
    return results, receipts


def _report(case_id, inputs, expected, actual, downstream_expected, downstream_actual):
    if actual != expected or downstream_actual != downstream_expected:
        raise RuntimeError(f'{case_id} did not match the sample contract')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id, 'input': inputs, 'expected': expected, 'actual': actual,
        'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
        'code_paths': ['publish/eligibility.py', 'review/bindings.py', 'results/issue.py', 'results/archive.py'],
        'oracle': '手算上下游连线及原记录占用，再按成果号对照持久记录',
    }, ensure_ascii=True, sort_keys=True))


def main():
    with TemporaryDirectory(prefix='sample-handoff-') as work:
        root = Path(work)
        front_path, rear_path, night_path = (root / name for name in ('prep.db', 'lab.db', 'night.db'))
        with closing(open_source(front_path)) as front, closing(open_source(rear_path)) as rear:
            shared = stage_front(front, 'D1', 'R1')
            successor = open_successor(front, (FRONT, BATCH, 'R1'), 'D2')
            withdraw_record(front, successor.key, 'r')
            for record_id in ('r1', 'r2'):
                record(front, successor.key, record_id, 'u-private', 'v-private')
            revised = close_day(front, successor.key, 'R2', FRONT_BOUNDARIES)
            parallel = publish_pack(front, revised.key)
            downstream = stage_rear(rear)
        front_path.unlink()
        rear_path.unlink()

        with closing(open_night(night_path)) as night:
            shared_id = import_pack(night, shared)
            parallel_id = import_pack(night, parallel)
            rear_id = import_pack(night, downstream)
            singles = [issue(night, ReviewRequest(shared_id, rear_id, (sample,))) for sample in SAMPLES]
            before = _counts(night)
            try:
                issue(night, ReviewRequest(shared_id, rear_id, SAMPLES))
            except ValueError as exc:
                refusal = str(exc)
            else:
                raise RuntimeError('v5 signed a request that uses the sole shared transfer')
            _report('v5', {'middle_records': ['r'], 'source_dbs_removed': True},
                    'NO_COMMON_EVIDENCE', refusal,
                    {'single_interfaces': [('p',), ('q',)], 'counts_before': (2, 2), 'counts_after': (2, 2)},
                    {'single_interfaces': [item.interfaces for item in singles],
                     'counts_before': before, 'counts_after': _counts(night)})
            signed = issue(night, ReviewRequest(parallel_id, rear_id, SAMPLES))

        with closing(open_night(night_path)) as night:
            old = fetch(night, signed.result_id)
            excerpt = json.loads(export_excerpt(night, old.result_id))
            _report('v5.parallel_recovery', {'middle_records': ['r1', 'r2'], 'source_dbs_removed': True},
                    ('p', 'q'), signed.interfaces,
                    {'interfaces': ['p', 'q'], 'revisions': ['R2', 'R1'], 'counts': (3, 3), 'reopened_equal': True},
                    {'interfaces': [row['interface'] for row in excerpt['samples']],
                     'revisions': [row['revision'] for row in excerpt['parents']],
                     'counts': _counts(night), 'reopened_equal': old == signed})
            print(json.dumps(excerpt, ensure_ascii=True, sort_keys=True))


if __name__ == '__main__':
    main()
