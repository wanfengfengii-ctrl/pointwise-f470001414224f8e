"""Fixed withdrawal sheets and standalone withdrawal notices.

A sheet is issued from an already published, exact frozen revision.  It keeps
the station-internal material (record numbers, private nodes, graphs with
private endpoints and individual routes) on the station side and publishes
only anonymous aliases plus the witness families needed to re-judge the
original public relations after *any* cumulative withdrawal.

Chosen ``response`` format (``kind == "withdrawal-witnesses"``)::

    {"kind": "withdrawal-witnesses",
     "singles": [{"relation": [start, end],
                  "witnesses": [[alias, ...], ...]}, ...]}

For every distinct public single relation of the original V1 evidence the
sheet lists every record set that witnesses the relation, with each original
record replaced by the alias assigned to it in this sheet.  Under a withdrawn
alias set ``W``:

* a single relation is eligible exactly when some witness is disjoint from ``W``;
* a pair of relations is eligible exactly when two witnesses (one per
  relation, necessarily distinct when the two relations are equal) are
  pairwise disjoint and each is disjoint from ``W``.

V1 eligibility is defined by precisely those two existential constraints over
station walks, so this family is *complete* for every cumulative withdrawal.
Taking ``W`` empty reproduces the original V1 eligibility, which is also what
the night shift re-checks at acceptance.

Aliases are deterministic per (pack, record) and only meaningful inside the
fixed sheet of one revision; the same record number in another revision is a
different scope.  Record numbers, private nodes and individual routes never
leave the station.
"""

import hashlib
import json
from itertools import combinations_with_replacement

from freeze.history import read_revision
from intake.days import require_identity

from .catalog import read_publication
from .evidence import EligibilityEvidence, _pair_key
from .package import decode_package
from .routes import collect_route_witnesses


SHEET_KIND = 'withdrawal-sheet'
NOTICE_KIND = 'withdrawal-notice'
RESPONSE_KIND = 'withdrawal-witnesses'

_HEX_DIGITS = frozenset('0123456789abcdef')


def canonical(obj):
    return json.dumps(
        obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False,
    )


def _digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _require_digest(value, error):
    if not isinstance(value, str) or len(value) != 64 or not set(value) <= _HEX_DIGITS:
        raise ValueError(error)
    return value


def _record_aliases(frozen, pack_id):
    """Return one deterministic, anonymous, distinct alias per revision record."""
    aliases = {}
    used = set()
    for record_id in sorted(transfer.record_id for transfer in frozen.transfers):
        stem = 'WA-' + hashlib.sha256(
            ('withdrawal-alias\0' + pack_id + '\0' + record_id).encode('utf-8')
        ).hexdigest()
        alias = stem
        suffix = 1
        while alias in used:
            alias = f'{stem}-{suffix}'
            suffix += 1
        used.add(alias)
        aliases[record_id] = alias
    return aliases


def _minimal_witnesses(entries):
    """Keep only inclusion-minimal and distinct record sets.

    A superset witness is redundant for every cumulative withdrawal: a
    withdrawn set disjoint from a superset is also disjoint from any subset,
    and any two disjoint witnesses have disjoint minimal subsets.  Keeping the
    minimal family therefore preserves single *and* pair eligibility exactly
    while publishing strictly less.
    """
    unique = sorted({frozenset(entry) for entry in entries}, key=lambda item: (len(item), sorted(item)))
    kept = []
    for candidate in unique:
        if not any(other < candidate for other in kept):
            kept.append(candidate)
    return [sorted(item) for item in kept]


def _witness_families(frozen, alias_by_record):
    witnesses = collect_route_witnesses(frozen)
    families = {}
    for relation in sorted(witnesses):
        entries = [
            [alias_by_record[record_id] for record_id in records]
            for records in witnesses[relation]
            if records
        ]
        minimal = _minimal_witnesses(entries)
        if minimal:
            families[relation] = minimal
    return families


def _response(frozen, alias_by_record):
    return {
        'kind': RESPONSE_KIND,
        'singles': [
            {'relation': [start, end], 'witnesses': entries}
            for (start, end), entries in _witness_families(frozen, alias_by_record).items()
        ],
    }


def _sheet_object(frozen, pack_id, published_payload):
    alias_by_record = _record_aliases(frozen, pack_id)
    return {
        'kind': SHEET_KIND,
        'version': 1,
        'pack_id': pack_id,
        'pack_sha256': _digest(published_payload),
        'aliases': sorted(alias_by_record.values()),
        'response': _response(frozen, alias_by_record),
    }


# --------------------------------------------------------------------------
# Station-side issuance


def withdrawal_sheet(db, revision_key):
    """Return the fixed review sheet of an already published exact revision.

    The sheet is a pure function of the frozen revision and its published
    payload, so repeated calls, reopening the source database and closing
    later revisions all keep returning the same text.
    """
    payload = read_publication(db, revision_key)
    frozen = read_revision(db, revision_key)
    return canonical(_sheet_object(frozen, decode_package(payload).pack_id, payload))


def _record_id_set(record_ids):
    if not isinstance(record_ids, (list, tuple, set, frozenset)):
        raise ValueError('INVALID_NOTICE')
    values = [require_identity(record_id, 'INVALID_NOTICE') for record_id in record_ids]
    if not values:
        raise ValueError('INVALID_NOTICE')
    return set(values)


def withdrawal_notice(db, revision_key, notice_id, record_ids):
    """Return a standalone notice withdrawing a non-empty set of records.

    ``record_ids`` is interpreted as a set and may mention records that are
    not connected to any public endpoint.  The notice references the fixed
    sheet of ``revision_key`` by its canonical SHA-256; it can be obtained
    before the sheet itself is fetched.
    """
    require_identity(notice_id, 'INVALID_NOTICE')
    wanted = _record_id_set(record_ids)
    payload = read_publication(db, revision_key)
    frozen = read_revision(db, revision_key)
    pack_id = decode_package(payload).pack_id
    alias_by_record = _record_aliases(frozen, pack_id)
    known = {transfer.record_id for transfer in frozen.transfers}
    if not wanted <= known:
        raise ValueError('RECORD_NOT_IN_REVISION')
    notice = {
        'kind': NOTICE_KIND,
        'version': 1,
        'pack_id': pack_id,
        'sheet_sha256': _digest(canonical(_sheet_object(frozen, pack_id, payload))),
        'notice_id': notice_id,
        'aliases': sorted({alias_by_record[record_id] for record_id in wanted}),
    }
    return canonical(notice)


# --------------------------------------------------------------------------
# Decoding helpers shared by issuance and acceptance


def _unique_object(error):
    def hook(entries):
        body = {}
        for key, value in entries:
            if key in body:
                raise ValueError(error)
            body[key] = value
        return body
    return hook


def _parse_json(payload, error):
    try:
        if isinstance(payload, bytes):
            payload = payload.decode('utf-8')
        if not isinstance(payload, str):
            raise ValueError(error)
        return json.loads(payload, object_pairs_hook=_unique_object(error))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(error) from exc


def _read_aliases(value, error):
    if not isinstance(value, list):
        raise ValueError(error)
    aliases = [require_identity(alias, error) for alias in value]
    if len(set(aliases)) != len(aliases):
        raise ValueError(error)
    return sorted(aliases)


def _read_families(response, boundaries, aliases, error='INVALID_SHEET'):
    if not isinstance(response, dict) or set(response) != {'kind', 'singles'}:
        raise ValueError(error)
    if response['kind'] != RESPONSE_KIND:
        raise ValueError(error)
    singles = response['singles']
    if not isinstance(singles, list):
        raise ValueError(error)
    families = {}
    normalized = []
    for entry in singles:
        if not isinstance(entry, dict) or set(entry) != {'relation', 'witnesses'}:
            raise ValueError(error)
        relation = entry['relation']
        if not isinstance(relation, list) or len(relation) != 2:
            raise ValueError(error)
        start = require_identity(relation[0], error)
        end = require_identity(relation[1], error)
        if start == end or start not in boundaries or end not in boundaries:
            raise ValueError(error)
        if (start, end) in families:
            raise ValueError(error)
        witnesses = entry['witnesses']
        if not isinstance(witnesses, list) or not witnesses:
            raise ValueError(error)
        kept = set()
        for witness in witnesses:
            if not isinstance(witness, list) or not witness:
                raise ValueError(error)
            values = [require_identity(alias, error) for alias in witness]
            if len(set(values)) != len(values) or not set(values) <= aliases:
                raise ValueError(error)
            kept.add(frozenset(values))
        families[(start, end)] = [frozenset(item) for item in kept]
        normalized.append({
            'relation': [start, end],
            'witnesses': sorted(sorted(item) for item in kept),
        })
    normalized.sort(key=lambda item: item['relation'])
    return families, {'kind': RESPONSE_KIND, 'singles': normalized}


def derive_evidence(families, withdrawn):
    """Derive public eligibility from witness families minus withdrawn aliases."""
    active = {}
    for relation, witnesses in families.items():
        kept = [witness for witness in witnesses if witness.isdisjoint(withdrawn)]
        if kept:
            active[relation] = kept
    singles = frozenset(active)
    pairs = set()
    for first, second in combinations_with_replacement(sorted(active), 2):
        if any(
            left.isdisjoint(right)
            for left in active[first]
            for right in active[second]
        ):
            pairs.add(_pair_key(first, second))
    return EligibilityEvidence(singles, frozenset(pairs))


def parse_sheet(payload, package, canonical_payload):
    """Validate a withdrawal-sheet envelope against an accepted V1 package.

    Returns ``(canonical_text, families)``.  ``canonical_text`` normalizes
    ordering so that re-deliveries with rearranged entries compare equal.
    """
    body = payload if isinstance(payload, dict) else _parse_json(payload, 'INVALID_SHEET')
    fields = {'kind', 'version', 'pack_id', 'pack_sha256', 'aliases', 'response'}
    if not isinstance(body, dict) or set(body) != fields:
        raise ValueError('INVALID_SHEET')
    if body['kind'] != SHEET_KIND:
        raise ValueError('INVALID_SHEET')
    if type(body['version']) is not int or body['version'] != 1:
        raise ValueError('INVALID_SHEET')
    pack_id = require_identity(body['pack_id'], 'INVALID_SHEET')
    if pack_id != package.pack_id:
        raise ValueError('INVALID_SHEET')
    digest = _require_digest(body['pack_sha256'], 'INVALID_SHEET')
    if digest != _digest(canonical_payload):
        raise ValueError('SHEET_DIGEST_MISMATCH')
    aliases = _read_aliases(body['aliases'], 'INVALID_SHEET')
    boundaries = {point.public_id for point in package.boundaries}
    families, normalized_response = _read_families(body['response'], boundaries, frozenset(aliases))
    # The sheet must reproduce the original V1 eligibility on an empty
    # withdrawal; otherwise its witness families are not a faithful view.
    if derive_evidence(families, frozenset()) != package.evidence:
        raise ValueError('INVALID_SHEET')
    normalized = {
        'kind': SHEET_KIND,
        'version': 1,
        'pack_id': pack_id,
        'pack_sha256': digest,
        'aliases': aliases,
        'response': normalized_response,
    }
    return canonical(normalized), families


def parse_notice(payload):
    """Validate a withdrawal-notice envelope; return its claimed fields."""
    body = _parse_json(payload, 'INVALID_NOTICE')
    fields = {'kind', 'version', 'pack_id', 'sheet_sha256', 'notice_id', 'aliases'}
    if not isinstance(body, dict) or set(body) != fields:
        raise ValueError('INVALID_NOTICE')
    if body['kind'] != NOTICE_KIND:
        raise ValueError('INVALID_NOTICE')
    if type(body['version']) is not int or body['version'] != 1:
        raise ValueError('INVALID_NOTICE')
    pack_id = require_identity(body['pack_id'], 'INVALID_NOTICE')
    sheet_sha256 = _require_digest(body['sheet_sha256'], 'INVALID_NOTICE')
    notice_id = require_identity(body['notice_id'], 'INVALID_NOTICE')
    if not isinstance(body['aliases'], list) or not body['aliases']:
        raise ValueError('INVALID_NOTICE')
    aliases = frozenset(
        require_identity(alias, 'INVALID_NOTICE') for alias in body['aliases']
    )
    return pack_id, sheet_sha256, notice_id, aliases


def sheet_digest(text):
    return _digest(text)
