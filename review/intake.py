from intake.days import require_identity
from publish.package import decode_package, encode_package


def initialize_imports(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS imported_packages (
            pack_id TEXT PRIMARY KEY NOT NULL,
            payload TEXT NOT NULL
        )
    ''')


def import_pack(db, payload):
    package = decode_package(payload)
    canonical = encode_package(package)
    db.execute('''
        INSERT INTO imported_packages (pack_id, payload) VALUES (?, ?)
        ON CONFLICT (pack_id) DO NOTHING
    ''', (package.pack_id, canonical))
    if _read_payload(db, package.pack_id) != canonical:
        raise ValueError('PACKAGE_ID_CONFLICT')
    return package.pack_id


def _read_payload(db, pack_id):
    row = db.execute('SELECT payload FROM imported_packages WHERE pack_id = ?', (pack_id,)).fetchone()
    if row is None:
        raise LookupError('PACKAGE_NOT_FOUND')
    return row[0]


def load_imported_package(db, pack_id):
    return decode_package(_read_payload(db, require_identity(pack_id, 'INVALID_REQUEST')))
