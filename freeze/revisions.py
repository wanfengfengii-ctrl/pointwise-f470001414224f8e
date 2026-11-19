from intake.days import insert_draft, require_identity, seal_draft
from intake.ledger import populate_draft, read_draft_snapshot
from intake.source_store import source_transaction

from .boundaries import validate_boundaries
from .history import FrozenRevision, read_revision, save_revision
from .validation import validate_acyclic


def close_day(db, key, revision, boundaries):
    require_identity(revision)
    with source_transaction(db):
        draft = read_draft_snapshot(db, key)
        if draft.day.sealed:
            raise ValueError('DRAFT_CLOSED')
        directory = validate_boundaries(boundaries, draft.nodes, draft.day.station)
        validate_acyclic(draft.nodes, draft.transfers)
        frozen = FrozenRevision(
            draft.day.station, draft.day.batch, revision, draft.day.draft,
            draft.day.base_revision, draft.nodes, draft.transfers, directory,
        )
        save_revision(db, frozen)
        seal_draft(db, key)
    return frozen


def open_successor(db, revision_key, draft):
    require_identity(draft)
    with source_transaction(db):
        baseline = read_revision(db, revision_key)
        day = insert_draft(db, (baseline.station, baseline.batch, draft), baseline.revision)
        populate_draft(db, day.key, baseline.nodes, baseline.transfers)
    return day
