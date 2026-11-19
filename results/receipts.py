from dataclasses import dataclass


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    result_id: int


def write_receipt(db, result_id):
    receipt = Receipt(f'RC-{result_id}', result_id)
    db.execute('INSERT INTO receipts (result_id, receipt_id) VALUES (?, ?)', (result_id, receipt.receipt_id))
    return receipt


def read_receipt(db, result_id):
    row = db.execute('SELECT receipt_id FROM receipts WHERE result_id = ?', (result_id,)).fetchone()
    if row is None:
        raise LookupError('RECEIPT_NOT_FOUND')
    return Receipt(row[0], result_id)
