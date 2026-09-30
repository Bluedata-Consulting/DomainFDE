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


# ------------------------------------------------- lane-scoped SQL access

# SQLite authorizer action codes we care about. Anything that reads a table or
# a column arrives as one of these with the table name in arg1.
_SQLITE_OK = 0
_SQLITE_DENY = 1
_SQLITE_READ = 20
_SQLITE_SELECT = 21
_SQLITE_FUNCTION = 31


def compact_schema(tables: tuple[str, ...] | list[str]) -> str:
    """Render `table(col, col, ...)` lines for the given tables.

    Cheap enough to paste into a system instruction -- the whole 19-table
    database is ~520 tokens this way against ~1,900 as CREATE TABLE DDL. Giving
    an agent the schema up front is what stops it spending turns on
    `list_tables` and `get_table_schemas` before it can write a query.
    """
    lines = []
    for schema in get_table_schemas(list(tables)):
        if schema.get("error"):
            continue
        cols = ", ".join(c["name"] for c in schema["columns"])
        lines.append(f"{schema['table']}({cols})")
    return "\n".join(lines)


def make_scoped_execute_sql(allowed_tables: tuple[str, ...], lane: str):
    """Build an `execute_sql` that can only read `allowed_tables`.

    The allowlist is enforced by SQLite's own authorizer, not by inspecting the
    query text, so a subquery, CTE or view cannot smuggle a read past it. This
    is what lets a lane have real SQL without dissolving the lane partition:
    the delivery lane can join shipments to sales_orders freely and still
    cannot read `tickets`.

    Args:
        allowed_tables: Tables this lane may read.
        lane: Lane name, used in the error message and the tool name.

    Returns:
        A function suitable for registering as an ADK tool.
    """
    allowed = set(allowed_tables)
    allowed_list = ", ".join(sorted(allowed))

    def _authorizer(action, arg1, arg2, db_name, trigger):
        if action in (_SQLITE_READ, _SQLITE_SELECT):
            # arg1 is the table name for READ; SELECT carries no table.
            if action == _SQLITE_READ and arg1 not in allowed:
                return _SQLITE_DENY
            return _SQLITE_OK
        if action == _SQLITE_FUNCTION:
            return _SQLITE_OK
        # Everything else (writes, attach, pragma on other schemas) is refused.
        return _SQLITE_DENY

    def execute_sql(query: str, max_rows: int = 200) -> dict:
        try:
            conn = connect_ro()
            try:
                conn.set_authorizer(_authorizer)
                cursor = conn.execute(query.strip().rstrip(";").strip())
                fetched = cursor.fetchmany(max_rows + 1)
                columns = [d[0] for d in cursor.description] if cursor.description else []
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            message = str(exc)
            # SQLite words an authorizer refusal several ways depending on
            # where it tripped: "access to X.Y is prohibited", "not authorized".
            lowered = message.lower()
            if "prohibited" in lowered or "not authorized" in lowered:
                return {
                    "error": (
                        f"This lane may only read: {allowed_list}. The query touched "
                        "something else, which is deliberate -- another lane owns that "
                        "data. Report it as an open question instead of querying around it."
                    ),
                    "allowed_tables": sorted(allowed),
                }
            return {"error": f"{type(exc).__name__}: {message}"}

        truncated = len(fetched) > max_rows
        rows_out = [dict(r) for r in fetched[:max_rows]]
        result = {
            "columns": columns,
            "rows": rows_out,
            "row_count": len(rows_out),
            "truncated": truncated,
        }
        if truncated:
            result["next_step"] = (
                f"More than {max_rows} rows matched. Aggregate in SQL (COUNT, SUM, "
                "GROUP BY) rather than re-running this with a bigger max_rows."
            )
        return result

    execute_sql.__name__ = "execute_sql"
    execute_sql.__doc__ = f"""Run one read-only SQL query against the roastery database.

    For a join across your tables, an aggregate no business tool exposes, or
    anything that would otherwise take three or more separate calls. Your
    instruction lists the tables you may read and their columns, so do not look
    the schema up. Reads outside that list are refused by the database.

    Args:
        query: A single SELECT / WITH / EXPLAIN statement.
        max_rows: Maximum rows to return (default 200). Aggregate in SQL rather
            than raising this.

    Returns:
        {{columns, rows, row_count, truncated}}, or {{error}}.
    """
    return execute_sql


def tables_in_source(func) -> set[str]:
    """Tables a tool's own SQL reads, scraped from its source.

    Used to derive a lane's SQL allowlist from what its tools already query, so
    `execute_sql` can reach exactly the data the lane's tools already return and
    nothing more. Deriving it beats hand-listing it: a tool that grows a JOIN
    cannot drift out of step with the allowlist.
    """
    import inspect
    import re as _re

    try:
        source = inspect.getsource(func)
    except (OSError, TypeError):
        return set()
    names = set(_re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", source))
    # `FROM (` subqueries and the odd SQL keyword are not tables.
    return {n for n in names if not n.isupper()} - {"SELECT"}
