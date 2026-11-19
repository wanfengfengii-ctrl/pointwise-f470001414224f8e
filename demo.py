import json
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from freeze import close_day, open_successor
from intake import open_source, record, withdraw_record
from publish import publish_pack, withdrawal_notice, withdrawal_sheet
from results import (
    export_excerpt, fetch, fetch_withdrawal_review, issue, open_night,
    review_withdrawals,
)
from review import (
    ReviewRequest, import_pack, import_withdrawal_notice, import_withdrawal_sheet,
)
from samples import BATCH, FRONT, FRONT_BOUNDARIES, REAR, SAMPLES, stage_front, stage_rear
from withdrawal_cases import stage_fallback_rear, stage_withdrawal_front


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


def _report_withdrawal(case_id, inputs, expected, actual, downstream_expected, downstream_actual):
    if actual != expected or downstream_actual != downstream_expected:
        raise RuntimeError(f'{case_id} did not match the withdrawal contract')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id, 'input': inputs, 'expected': expected, 'actual': actual,
        'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
        'code_paths': ['publish/withdrawal.py', 'review/withdrawals.py',
                       'results/withdrawal_review.py'],
        'oracle': '按撤回并集去掉站内记录后重算单件与双件资格，再对照原接口与复核号',
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

        withdrawal_demo(root, root / 'night-withdrawals.db')


def withdrawal_demo(root, night_path):
    front_path, rear_path = root / 'wd-prep.db', root / 'wd-lab.db'
    with closing(open_source(front_path)) as prep, closing(open_source(rear_path)) as lab:
        # spare=True keeps a second path a1->p after private-r and private-s
        # are both withdrawn, while spare=False loses the binding entirely.
        shared_front = stage_withdrawal_front(prep, spare=True)
        isolated_front = stage_withdrawal_front(prep, spare=False, revision='R9')
        downstream = stage_fallback_rear(lab)
        shared_sheet = withdrawal_sheet(prep, (FRONT, BATCH, 'R1'))
        isolated_sheet = withdrawal_sheet(prep, (FRONT, BATCH, 'R9'))
        rear_sheet = withdrawal_sheet(lab, (REAR, BATCH, 'R1'))
        notice_r = withdrawal_notice(prep, (FRONT, BATCH, 'R1'), 'N-r', ['private-r'])
        notice_s = withdrawal_notice(prep, (FRONT, BATCH, 'R1'), 'N-s', ['private-s'])
        iso_r = withdrawal_notice(prep, (FRONT, BATCH, 'R9'), 'N-r', ['private-r'])
        iso_s = withdrawal_notice(prep, (FRONT, BATCH, 'R9'), 'N-s', ['private-s'])
    front_path.unlink()
    rear_path.unlink()

    with closing(open_night(night_path)) as night:
        shared_id = import_pack(night, shared_front)
        isolated_id = import_pack(night, isolated_front)
        rear_id = import_pack(night, downstream)
        shared = issue(night, ReviewRequest(shared_id, rear_id, SAMPLES))
        isolated = issue(night, ReviewRequest(isolated_id, rear_id, SAMPLES))
        import_withdrawal_sheet(night, shared_sheet)
        import_withdrawal_sheet(night, isolated_sheet)
        import_withdrawal_sheet(night, rear_sheet)
        # Only the first notice has arrived; repeated delivery is idempotent.
        import_withdrawal_notice(night, notice_s)
        import_withdrawal_notice(night, notice_s)
        first = review_withdrawals(night, shared.result_id)
        _report_withdrawal(
            'w6.partial', {'withdrawn': ['private-s'], 'spare_to_p': True},
            'valid', first['status'],
            {'interfaces': ['p', 'q'], 'notice_ids': ['N-s']},
            {'interfaces': first['interfaces'],
             'notice_ids': [row['notice_id'] for row in first['notices']]},
        )
        # The second notice arrives later, in a separate delivery.
        import_withdrawal_notice(night, notice_r)
        import_withdrawal_notice(night, iso_r)
        import_withdrawal_notice(night, iso_s)
        second = review_withdrawals(night, shared.result_id)
        broken = review_withdrawals(night, isolated.result_id)
        _report_withdrawal(
            'w6.cumulative', {'withdrawn': ['private-r', 'private-s']},
            'valid', second['status'],
            {'interfaces': ['p', 'q'], 'notice_ids': ['N-r', 'N-s'],
             'isolated_status': 'invalid', 'isolated_interfaces': ['p', 'q']},
            {'interfaces': second['interfaces'],
             'notice_ids': [row['notice_id'] for row in second['notices']],
             'isolated_status': broken['status'],
             'isolated_interfaces': broken['interfaces']},
        )
        old_review_id, new_review_id = first['review_id'], second['review_id']

    # Reopen the night database after both sources are gone: both reviews and
    # the original result come back as fixed snapshots.
    with closing(open_night(night_path)) as night:
        reopened_first = fetch_withdrawal_review(night, old_review_id)
        reopened_second = fetch_withdrawal_review(night, new_review_id)
        original = fetch(night, reopened_first['result_id'])
        _report_withdrawal(
            'w6.reopen', {'source_dbs_removed': True},
            (first['status'], second['status'], second['interfaces']),
            (reopened_first['status'], reopened_second['status'], reopened_second['interfaces']),
            {'snapshots_stable': True, 'original_receipt': 'RC-1',
             'notice_ids_first': ['N-s'], 'notice_ids_second': ['N-r', 'N-s']},
            {'snapshots_stable': reopened_first == first and reopened_second == second,
             'original_receipt': original.receipt.receipt_id,
             'notice_ids_first': [row['notice_id'] for row in reopened_first['notices']],
             'notice_ids_second': [row['notice_id'] for row in reopened_second['notices']]},
        )
        print(json.dumps({
            'first_review': reopened_first, 'second_review': reopened_second,
            'original_excerpt': json.loads(export_excerpt(night, original.result_id)),
        }, ensure_ascii=True, sort_keys=True))


if __name__ == '__main__':
    main()
