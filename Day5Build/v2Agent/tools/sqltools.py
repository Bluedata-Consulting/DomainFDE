"""SQLite tools for the agent: list tables, describe schemas, run queries.

All tools operate on data/roastery.db (resolved relative to the project root,
so they work regardless of the current working directory).
"""

import sqlite3

from .db import DB_PATH, connect_ro

_connect = connect_ro


def list_tables() -> list[str]:
    """Return the names of all user tables in the roastery database.

    Returns:
        A list of table names, in the order they were created.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY rowid"
        ).fetchall()
    return [row["name"] for row in rows]


def get_table_schemas(tables: list[str]) -> list[dict]:
    """Return the schema for each requested table.

    Args:
        tables: Names of the tables to describe.

    Returns:
        One dict per requested table with keys:
            - ``table``: the table name
            - ``create_sql``: the original CREATE TABLE statement (None if the
              table does not exist)
            - ``columns``: list of {name, type, notnull, default, primary_key}
            - ``error``: present only if the table does not exist
    """
    schemas = []
    with _connect() as conn:
        for table in tables:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if row is None:
                schemas.append(
                    {
                        "table": table,
                        "create_sql": None,
                        "columns": [],
                        "error": f"Table '{table}' does not exist.",
                    }
                )
                continue

            # PRAGMA does not accept bound parameters; the name is validated
            # above against sqlite_master, so quoting it here is safe.
            cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            schemas.append(
                {
                    "table": table,
                    "create_sql": row["sql"],
                    "columns": [
                        {
                            "name": c["name"],
                            "type": c["type"],
                            "notnull": bool(c["notnull"]),
                            "default": c["dflt_value"],
                            "primary_key": bool(c["pk"]),
                        }
                        for c in cols
                    ],
                }
            )
    return schemas


def execute_sql(query: str, max_rows: int = 200) -> dict:
    """Execute a SQL query against the roastery database and return the results.

    Only read-only (SELECT / WITH / EXPLAIN / PRAGMA) statements are allowed;
    the database is opened in read-only mode so writes are rejected by SQLite.

    Args:
        query: The SQL statement to execute.
        max_rows: Maximum number of rows to return (default 200).

    Returns:
        A dict with keys:
            - ``columns``: list of column names
            - ``rows``: list of rows, each a dict of column -> value
            - ``row_count``: number of rows returned
            - ``truncated``: True if more rows existed than ``max_rows``
        On failure, a dict with a single ``error`` key describing the problem.
    """
    stripped = query.strip().rstrip(";").strip()
    first_word = stripped.split(None, 1)[0].upper() if stripped else ""
    if first_word not in {"SELECT", "WITH", "EXPLAIN", "PRAGMA"}:
        return {
            "error": "Only read-only queries (SELECT / WITH / EXPLAIN / PRAGMA) are allowed."
        }

    try:
        conn = connect_ro()
        try:
            cursor = conn.execute(stripped)
            rows = cursor.fetchmany(max_rows + 1)
            columns = [d[0] for d in cursor.description] if cursor.description else []
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    truncated = len(rows) > max_rows
    rows = rows[:max_rows]
    return {
        "columns": columns,
        "rows": [dict(r) for r in rows],
        "row_count": len(rows),
        "truncated": truncated,
    }
