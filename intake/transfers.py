from dataclasses import dataclass

from .days import require_identity, validate_key


@dataclass(frozen=True)
class Transfer:
    record_id: str
    start: str
    end: str


def accept_transfer(db, key, transfer):
    require_identity(transfer.record_id)
    row = db.execute('''
        SELECT start, end FROM transfers
        WHERE station = ? AND batch = ? AND draft = ? AND record_id = ?
    ''', (*validate_key(key), transfer.record_id)).fetchone()
    if row is not None:
        if row != (transfer.start, transfer.end):
            raise ValueError('RECORD_CONFLICT')
        return Transfer(transfer.record_id, *row)
    db.execute('''
        INSERT INTO transfers (station, batch, draft, record_id, start, end)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (*key, transfer.record_id, transfer.start, transfer.end))
    return transfer


def list_transfers(db, key):
    rows = db.execute('''
        SELECT record_id, start, end FROM transfers
        WHERE station = ? AND batch = ? AND draft = ? ORDER BY record_id
    ''', validate_key(key))
    return tuple(Transfer(*row) for row in rows)


def delete_transfer(db, key, record_id):
    cursor = db.execute('''
        DELETE FROM transfers WHERE station = ? AND batch = ? AND draft = ? AND record_id = ?
    ''', (*validate_key(key), require_identity(record_id)))
    if cursor.rowcount != 1:
        raise LookupError('RECORD_NOT_FOUND')
