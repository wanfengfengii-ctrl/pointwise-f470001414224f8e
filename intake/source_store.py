import sqlite3
from contextlib import contextmanager


@contextmanager
def source_transaction(db):
    if db.in_transaction:
        raise ValueError('SOURCE_TRANSACTION_ALREADY_OPEN')
    db.execute('BEGIN IMMEDIATE')
    with db:
        yield


def initialize_source(db):
    from freeze.history import initialize_revisions
    from publish.catalog import initialize_catalog

    if db.in_transaction:
        raise ValueError('SOURCE_TRANSACTION_ALREADY_OPEN')
    db.execute('PRAGMA foreign_keys = ON')
    with source_transaction(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS drafts (
                station TEXT NOT NULL, batch TEXT NOT NULL, draft TEXT NOT NULL,
                base_revision TEXT, sealed INTEGER NOT NULL DEFAULT 0 CHECK (sealed IN (0, 1)),
                PRIMARY KEY (station, batch, draft)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS nodes (
                station TEXT NOT NULL, batch TEXT NOT NULL, draft TEXT NOT NULL, node TEXT NOT NULL,
                PRIMARY KEY (station, batch, draft, node),
                FOREIGN KEY (station, batch, draft) REFERENCES drafts (station, batch, draft)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS transfers (
                station TEXT NOT NULL, batch TEXT NOT NULL, draft TEXT NOT NULL,
                record_id TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
                PRIMARY KEY (station, batch, draft, record_id),
                FOREIGN KEY (station, batch, draft, start) REFERENCES nodes (station, batch, draft, node),
                FOREIGN KEY (station, batch, draft, end) REFERENCES nodes (station, batch, draft, node)
            )
        ''')
        initialize_revisions(db)
        initialize_catalog(db)


def open_source(path):
    db = sqlite3.connect(path, isolation_level=None)
    try:
        initialize_source(db)
    except BaseException:
        db.close()
        raise
    return db
