import json
from dataclasses import asdict, dataclass

from review.decisions import ParentRef
from review.requests import SampleRequest

from .receipts import Receipt, read_receipt


@dataclass(frozen=True)
class IssuedResult:
    result_id: int
    parents: tuple[ParentRef, ParentRef]
    samples: tuple[SampleRequest, ...]
    interfaces: tuple[str, ...]
    receipt: Receipt


def write_result(db, decision):
    snapshot = json.dumps({
        'parents': [asdict(parent) for parent in decision.parents],
        'samples': [asdict(sample) for sample in decision.request.samples],
        'interfaces': decision.interfaces,
    }, sort_keys=True, separators=(',', ':'))
    cursor = db.execute('INSERT INTO issued_results (snapshot) VALUES (?)', (snapshot,))
    return cursor.lastrowid


def fetch(db, result_id):
    if type(result_id) is not int or not 1 <= result_id <= 2**63 - 1:
        raise LookupError('RESULT_NOT_FOUND')
    row = db.execute('SELECT snapshot FROM issued_results WHERE result_id = ?', (result_id,)).fetchone()
    if row is None:
        raise LookupError('RESULT_NOT_FOUND')
    snapshot = json.loads(row[0])
    return IssuedResult(
        result_id,
        tuple(ParentRef(**parent) for parent in snapshot['parents']),
        tuple(SampleRequest(**sample) for sample in snapshot['samples']),
        tuple(snapshot['interfaces']),
        read_receipt(db, result_id),
    )
