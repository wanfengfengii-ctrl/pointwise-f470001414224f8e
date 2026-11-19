"""Withdrawal review of an already issued result.

The review keeps the original parents, sample order and interfaces.  Only
notices accepted for those two parents take part; a parent without notices
falls back to its original V1 eligibility and may even lack a sheet.  The
conclusion is recomputed against station-internal witness families after the
cumulative alias withdrawal, never against a re-signed alternate interface.
"""

import json

from review.intake import load_imported_package
from review.withdrawals import (
    load_sheet, notices_for_pack, withdrawn_aliases,
)
from publish.withdrawal import derive_evidence

from .archive import fetch
from .store import issue_transaction


def _parent_evidence(db, pack_id, has_notice):
    package = load_imported_package(db, pack_id)
    if has_notice:
        _text, families, aliases = load_sheet(db, pack_id)
        return derive_evidence(families, withdrawn_aliases(db, pack_id))
    return package.evidence


def _allows(evidence, relations):
    if len(relations) == 1:
        return evidence.allows_single(*relations[0])
    return evidence.allows_pair(*relations)


def _status(db, result, notices_by_pack):
    front_id, rear_id = (parent.pack_id for parent in result.parents)
    front = _parent_evidence(db, front_id, bool(notices_by_pack[front_id]))
    rear = _parent_evidence(db, rear_id, bool(notices_by_pack[rear_id]))
    upstream = tuple(
        (sample.start, port) for sample, port in zip(result.samples, result.interfaces)
    )
    downstream = tuple(
        (port, sample.end) for sample, port in zip(result.samples, result.interfaces)
    )
    if _allows(front, upstream) and _allows(rear, downstream):
        return 'valid'
    return 'invalid'

def _snapshot(db, result_id):
    result = fetch(db, result_id)
    notices_by_pack = {
        parent.pack_id: notices_for_pack(db, parent.pack_id) for parent in result.parents
    }
    if not any(notices_by_pack.values()):
        raise LookupError('NO_WITHDRAWAL_NOTICE')
    notices = sorted(
        (
            {'pack_id': pack_id, 'notice_id': notice_id}
            for pack_id, entries in notices_by_pack.items()
            for notice_id, _aliases in entries
        ),
        key=lambda item: (item['pack_id'], item['notice_id']),
    )
    return {
        'result_id': result_id,
        'parents': [
            {
                'pack_id': parent.pack_id,
                'station': parent.station,
                'batch': parent.batch,
                'revision': parent.revision,
            }
            for parent in result.parents
        ],
        'samples': [
            {'sample_id': sample.sample_id, 'start': sample.start, 'end': sample.end}
            for sample in result.samples
        ],
        'interfaces': list(result.interfaces),
        'notices': notices,
        'status': _status(db, result, notices_by_pack),
    }


def review_withdrawals(db, result_id):
    """Re-judge an issued result against accepted cumulative withdrawals."""
    snapshot = _snapshot(db, result_id)
    with issue_transaction(db):
        cursor = db.execute(
            'INSERT INTO withdrawal_reviews (snapshot) VALUES (?)',
            (json.dumps(snapshot, sort_keys=True, separators=(',', ':')),),
        )
        review_id = cursor.lastrowid
    return {'review_id': review_id, **snapshot}


def fetch_withdrawal_review(db, review_id):
    if type(review_id) is not int or not 1 <= review_id <= 2**63 - 1:
        raise LookupError('REVIEW_NOT_FOUND')
    row = db.execute(
        'SELECT snapshot FROM withdrawal_reviews WHERE review_id = ?', (review_id,)
    ).fetchone()
    if row is None:
        raise LookupError('REVIEW_NOT_FOUND')
    return {'review_id': review_id, **json.loads(row[0])}
