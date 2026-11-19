import sqlite3
from contextlib import contextmanager

from review.intake import initialize_imports
from review.withdrawals import initialize_withdrawals


@contextmanager
def issue_transaction(db):
    if db.in_transaction:
        raise ValueError('NIGHT_TRANSACTION_ALREADY_OPEN')
    db.execute('BEGIN IMMEDIATE')
    with db:
        yield


def initialize_results(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS issued_results (
            result_id INTEGER PRIMARY KEY,
            snapshot TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS receipts (
            result_id INTEGER PRIMARY KEY REFERENCES issued_results (result_id),
            receipt_id TEXT NOT NULL UNIQUE
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS withdrawal_reviews (
            review_id INTEGER PRIMARY KEY,
            snapshot TEXT NOT NULL
        )
    ''')


def initialize_night(db):
    if db.in_transaction:
        raise ValueError('NIGHT_TRANSACTION_ALREADY_OPEN')
    db.execute('PRAGMA foreign_keys = ON')
    with issue_transaction(db):
        initialize_imports(db)
        initialize_withdrawals(db)
        initialize_results(db)


def open_night(path):
    db = sqlite3.connect(path, isolation_level=None)
    try:
        initialize_night(db)
    except BaseException:
        db.close()
        raise
    return db
