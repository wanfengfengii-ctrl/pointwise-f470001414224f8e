from .days import require_identity, require_open_draft, validate_key
from .source_store import source_transaction


def insert_nodes(db, key, nodes):
    db.executemany('''
        INSERT INTO nodes (station, batch, draft, node) VALUES (?, ?, ?, ?)
        ON CONFLICT (station, batch, draft, node) DO NOTHING
    ''', ((*key, require_identity(node)) for node in nodes))


def add_node(db, key, node):
    with source_transaction(db):
        require_open_draft(db, key)
        insert_nodes(db, key, (node,))
    return node


def list_nodes(db, key):
    rows = db.execute('''
        SELECT node FROM nodes WHERE station = ? AND batch = ? AND draft = ? ORDER BY node
    ''', validate_key(key))
    return tuple(row[0] for row in rows)


def require_endpoints(db, key, start, end):
    require_identity(start, 'INVALID_ENDPOINT')
    require_identity(end, 'INVALID_ENDPOINT')
    rows = db.execute('''
        SELECT node FROM nodes
        WHERE station = ? AND batch = ? AND draft = ? AND node IN (?, ?)
    ''', (*validate_key(key), start, end))
    if {row[0] for row in rows} != {start, end}:
        raise ValueError('ENDPOINT_NOT_IN_DRAFT')
