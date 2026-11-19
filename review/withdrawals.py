"""Night-shift acceptance of fixed withdrawal sheets and notices.

Sheets are keyed by the original V1 pack they describe.  A sheet is accepted
only when the corresponding V1 package has already been accepted and the
sheet's ``pack_sha256`` matches that package's canonical text.  Notices are
keyed by the parent sheet plus the notice id; re-delivering the same alias
set returns the original identity, while a different set under the same
identity is rejected.
"""

import json

from intake.days import require_identity
from publish.package import encode_package
from publish.withdrawal import (
    _parse_json, canonical, parse_notice, parse_sheet, sheet_digest,
)

from .intake import load_imported_package
from .txn import night_write


def initialize_withdrawals(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS withdrawal_sheets (
            pack_id TEXT PRIMARY KEY NOT NULL,
            sheet_sha256 TEXT NOT NULL,
            payload TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS withdrawal_notices (
            pack_id TEXT NOT NULL,
            notice_id TEXT NOT NULL,
            aliases TEXT NOT NULL,
            PRIMARY KEY (pack_id, notice_id)
        )
    ''')


def _decode_aliases(text):
    return frozenset(json.loads(text))


def _sheet_row(db, pack_id):
    return db.execute(
        'SELECT sheet_sha256, payload FROM withdrawal_sheets WHERE pack_id = ?',
        (pack_id,),
    ).fetchone()


def load_sheet(db, pack_id):
    """Return ``(canonical_text, families, aliases)`` of an accepted sheet."""
    row = _sheet_row(db, require_identity(pack_id, 'INVALID_REQUEST'))
    if row is None:
        raise LookupError('SHEET_NOT_FOUND')
    package = load_imported_package(db, pack_id)
    text, families = parse_sheet(row[1], package, encode_package(package))
    aliases = frozenset(json.loads(text)['aliases'])
    return text, families, aliases


def import_withdrawal_sheet(db, payload):
    """Accept a fixed sheet for an already accepted V1 package.

    The V1 package must be present and the sheet digest must match its
    canonical text.  Re-delivering the same sheet is idempotent; only one
    fixed sheet can be accepted per parent package.
    """
    body = _parse_json(payload, 'INVALID_SHEET')
    if not isinstance(body, dict) or 'pack_id' not in body:
        raise ValueError('INVALID_SHEET')
    pack_id = require_identity(body['pack_id'], 'INVALID_SHEET')
    package = load_imported_package(db, pack_id)
    text, _families = parse_sheet(body, package, encode_package(package))
    digest = sheet_digest(text)
    with night_write(db):
        row = _sheet_row(db, pack_id)
        if row is not None:
            if row[0] == digest and row[1] == text:
                return pack_id
            raise ValueError('SHEET_CONFLICT')
        db.execute(
            'INSERT INTO withdrawal_sheets (pack_id, sheet_sha256, payload) VALUES (?, ?, ?)',
            (pack_id, digest, text),
        )
    return pack_id


def import_withdrawal_notice(db, payload):
    """Accept a standalone notice in the parent sheet's alias scope.

    Returns ``(pack_id, notice_id)``.  Unknown parents raise ``LookupError``;
    unknown aliases, digest mismatches and identity conflicts raise
    ``ValueError`` without changing the stored set.
    """
    pack_id, claimed_digest, notice_id, aliases = parse_notice(payload)
    row = _sheet_row(db, pack_id)
    if row is None:
        if db.execute(
            'SELECT 1 FROM imported_packages WHERE pack_id = ?', (pack_id,)
        ).fetchone() is None:
            raise LookupError('PACKAGE_NOT_FOUND')
        raise LookupError('SHEET_NOT_FOUND')
    if row[0] != claimed_digest:
        raise ValueError('SHEET_DIGEST_MISMATCH')
    _text, families, sheet_aliases = load_sheet(db, pack_id)
    if not aliases <= sheet_aliases:
        raise ValueError('UNKNOWN_ALIAS')
    stored = canonical(sorted(aliases))
    with night_write(db):
        current = db.execute(
            'SELECT aliases FROM withdrawal_notices WHERE pack_id = ? AND notice_id = ?',
            (pack_id, notice_id),
        ).fetchone()
        if current is not None:
            if _decode_aliases(current[0]) == aliases:
                return pack_id, notice_id
            raise ValueError('NOTICE_CONFLICT')
        db.execute(
            'INSERT INTO withdrawal_notices (pack_id, notice_id, aliases) VALUES (?, ?, ?)',
            (pack_id, notice_id, stored),
        )
    return pack_id, notice_id


def notices_for_pack(db, pack_id):
    """Return ``[(notice_id, aliases)]`` in text order of the notice id."""
    rows = db.execute(
        'SELECT notice_id, aliases FROM withdrawal_notices '
        'WHERE pack_id = ? ORDER BY notice_id',
        (pack_id,),
    )
    return [(row[0], _decode_aliases(row[1])) for row in rows]


def withdrawn_aliases(db, pack_id):
    aliases = set()
    for _notice_id, values in notices_for_pack(db, pack_id):
        aliases |= values
    return frozenset(aliases)
