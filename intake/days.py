from dataclasses import dataclass


@dataclass(frozen=True)
class DraftDay:
    station: str
    batch: str
    draft: str
    base_revision: str | None
    sealed: bool

    @property
    def key(self):
        return self.station, self.batch, self.draft


def require_identity(value, error='INVALID_IDENTITY'):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(error)
    try:
        value.encode('utf-8')
    except UnicodeError as exc:
        raise ValueError(error) from exc
    return value


def validate_key(key):
    if not isinstance(key, tuple) or len(key) != 3:
        raise ValueError('INVALID_SOURCE_KEY')
    for value in key:
        require_identity(value, 'INVALID_SOURCE_KEY')
    return key


def insert_draft(db, key, base_revision):
    validate_key(key)
    cursor = db.execute('''
        INSERT INTO drafts (station, batch, draft, base_revision) VALUES (?, ?, ?, ?)
        ON CONFLICT (station, batch, draft) DO NOTHING
    ''', (*key, base_revision))
    if cursor.rowcount != 1:
        raise ValueError('DRAFT_EXISTS')
    return DraftDay(*key, base_revision, False)


def create_draft(db, station, batch, draft):
    return insert_draft(db, (station, batch, draft), None)


def load_draft(db, key):
    row = db.execute('''
        SELECT base_revision, sealed FROM drafts WHERE station = ? AND batch = ? AND draft = ?
    ''', validate_key(key)).fetchone()
    if row is None:
        raise LookupError('DRAFT_NOT_FOUND')
    return DraftDay(*key, row[0], bool(row[1]))


def require_open_draft(db, key):
    day = load_draft(db, key)
    if day.sealed:
        raise ValueError('DRAFT_CLOSED')
    return day


def seal_draft(db, key):
    require_open_draft(db, key)
    db.execute('UPDATE drafts SET sealed = 1 WHERE station = ? AND batch = ? AND draft = ?', key)
