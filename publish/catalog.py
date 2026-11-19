import hashlib
import json

from freeze.history import read_revision
from intake.days import validate_key
from intake.source_store import source_transaction

from .eligibility import build_eligibility
from .package import PublicBoundary, StationPackage, encode_package


def initialize_catalog(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS publications (
            station TEXT NOT NULL, batch TEXT NOT NULL, revision TEXT NOT NULL,
            pack_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
            PRIMARY KEY (station, batch, revision),
            FOREIGN KEY (station, batch, revision) REFERENCES revisions (station, batch, revision)
        )
    ''')


def _publication_row(db, key):
    return db.execute('''
        SELECT payload FROM publications WHERE station = ? AND batch = ? AND revision = ?
    ''', validate_key(key)).fetchone()


def read_publication(db, key):
    row = _publication_row(db, key)
    if row is None:
        raise LookupError('PUBLICATION_NOT_FOUND')
    return row[0]


def publish_pack(db, key):
    with source_transaction(db):
        prior = _publication_row(db, key)
        if prior is not None:
            return prior[0]
        frozen = read_revision(db, key)
        key_bytes = json.dumps(key, separators=(',', ':')).encode('ascii')
        pack_id = 'SP-' + hashlib.sha256(key_bytes).hexdigest()
        directory = tuple(
            PublicBoundary(point.public_id, point.direction, point.neighbor)
            for point in frozen.boundaries
        )
        payload = encode_package(StationPackage(
            pack_id, *key, directory, build_eligibility(frozen),
        ))
        db.execute('''
            INSERT INTO publications (station, batch, revision, pack_id, payload)
            VALUES (?, ?, ?, ?, ?)
        ''', (*key, pack_id, payload))
    return payload
