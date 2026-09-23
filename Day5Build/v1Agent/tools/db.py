"""Shared read-only SQLite access for every tool in this package.

Nothing in the tool layer opens its own connection: all reads go through
`connect_ro()` / `rows()` so the database can never be written by the agent.
"""

import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "roastery.db"

# The case database is generated against this date; the agent must not use
# the real clock.
TODAY = "2026-03-16"


def connect_ro() -> sqlite3.Connection:
    """Open the roastery database read-only, with dict-like rows."""
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found at {DB_PATH}. Run `python data/generate.py` first."
        )
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def rows(sql: str, params: Any = (), limit: int | None = None) -> list[dict]:
    """Run a read-only query and return the rows as a list of dicts.

    Args:
        sql: SQL text with `?` placeholders.
        params: Values bound to the placeholders.
        limit: Optional cap on the number of rows returned.

    Returns:
        A list of dicts, one per row (empty if nothing matched).
    """
    conn = connect_ro()
    try:
        cursor = conn.execute(sql, params)
        fetched = cursor.fetchall() if limit is None else cursor.fetchmany(limit)
    finally:
        conn.close()
    return [dict(r) for r in fetched]


def one(sql: str, params: Any = ()) -> dict | None:
    """Run a read-only query and return the first row, or None."""
    result = rows(sql, params, limit=1)
    return result[0] if result else None


def like(value: str) -> str:
    """Wrap a value for a case-insensitive LIKE '%value%' match."""
    return f"%{value}%"
