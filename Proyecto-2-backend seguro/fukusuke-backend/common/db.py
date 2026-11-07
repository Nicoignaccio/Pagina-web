"""SQLite por servicio (cada servicio es dueño exclusivo de su archivo)."""
import os
import sqlite3
from contextlib import contextmanager


def _connect(name: str) -> sqlite3.Connection:
    d = os.getenv("DATA_DIR", "./data")
    os.makedirs(d, exist_ok=True)
    c = sqlite3.connect(os.path.join(d, f"{name}.db"), isolation_level=None, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init(name: str, ddl: str) -> None:
    c = _connect(name)
    c.executescript(ddl)
    c.close()


@contextmanager
def read(name: str):
    c = _connect(name)
    try:
        yield c
    finally:
        c.close()


@contextmanager
def tx(name: str):
    """Transacción atómica; cualquier excepción hace rollback completo."""
    c = _connect(name)
    try:
        c.execute("BEGIN IMMEDIATE")
        yield c
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()
