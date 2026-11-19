import json
from dataclasses import asdict, dataclass

from intake.days import validate_key
from intake.transfers import Transfer

from .boundaries import BoundaryPoint


@dataclass(frozen=True)
class FrozenRevision:
    station: str
    batch: str
    revision: str
    draft: str
    base_revision: str | None
    nodes: tuple[str, ...]
    transfers: tuple[Transfer, ...]
    boundaries: tuple[BoundaryPoint, ...]

    @property
    def key(self):
        return self.station, self.batch, self.revision


def initialize_revisions(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS revisions (
            station TEXT NOT NULL, batch TEXT NOT NULL, revision TEXT NOT NULL,
            draft TEXT NOT NULL, base_revision TEXT, snapshot TEXT NOT NULL,
            PRIMARY KEY (station, batch, revision), UNIQUE (station, batch, draft),
            FOREIGN KEY (station, batch, draft) REFERENCES drafts (station, batch, draft),
            FOREIGN KEY (station, batch, base_revision) REFERENCES revisions (station, batch, revision)
        )
    ''')


def save_revision(db, frozen):
    snapshot = json.dumps({
        'nodes': frozen.nodes,
        'transfers': [asdict(item) for item in frozen.transfers],
        'boundaries': [asdict(item) for item in frozen.boundaries],
    }, sort_keys=True, separators=(',', ':'))
    cursor = db.execute('''
        INSERT INTO revisions (station, batch, revision, draft, base_revision, snapshot)
        VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (station, batch, revision) DO NOTHING
    ''', (*frozen.key, frozen.draft, frozen.base_revision, snapshot))
    if cursor.rowcount != 1:
        raise ValueError('REVISION_EXISTS')


def read_revision(db, key):
    row = db.execute('''
        SELECT draft, base_revision, snapshot FROM revisions
        WHERE station = ? AND batch = ? AND revision = ?
    ''', validate_key(key)).fetchone()
    if row is None:
        raise LookupError('REVISION_NOT_FOUND')
    body = json.loads(row[2])
    return FrozenRevision(
        *key, row[0], row[1], tuple(body['nodes']),
        tuple(Transfer(**entry) for entry in body['transfers']),
        tuple(BoundaryPoint(**entry) for entry in body['boundaries']),
    )
