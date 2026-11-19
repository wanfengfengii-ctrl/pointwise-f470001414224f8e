from contextlib import contextmanager


@contextmanager
def night_write(db):
    """Write an acceptance unit atomically, refusing an outer transaction."""
    if db.in_transaction:
        raise ValueError('NIGHT_TRANSACTION_ALREADY_OPEN')
    db.execute('BEGIN IMMEDIATE')
    with db:
        yield
