from dataclasses import dataclass

from .days import DraftDay, load_draft, require_open_draft
from .nodes import insert_nodes, list_nodes, require_endpoints
from .source_store import source_transaction
from .transfers import Transfer, accept_transfer, delete_transfer, list_transfers


@dataclass(frozen=True)
class DraftSnapshot:
    day: DraftDay
    nodes: tuple[str, ...]
    transfers: tuple[Transfer, ...]


def record(db, key, record_id, start, end):
    with source_transaction(db):
        require_open_draft(db, key)
        require_endpoints(db, key, start, end)
        return accept_transfer(db, key, Transfer(record_id, start, end))


def withdraw_record(db, key, record_id):
    with source_transaction(db):
        require_open_draft(db, key)
        delete_transfer(db, key, record_id)


def _load_snapshot(db, key):
    return DraftSnapshot(load_draft(db, key), list_nodes(db, key), list_transfers(db, key))


def read_draft_snapshot(db, key):
    if db.in_transaction:
        return _load_snapshot(db, key)
    db.execute('BEGIN')
    with db:
        return _load_snapshot(db, key)


def populate_draft(db, key, nodes, transfers):
    require_open_draft(db, key)
    insert_nodes(db, key, nodes)
    for transfer in transfers:
        require_endpoints(db, key, transfer.start, transfer.end)
        accept_transfer(db, key, transfer)
