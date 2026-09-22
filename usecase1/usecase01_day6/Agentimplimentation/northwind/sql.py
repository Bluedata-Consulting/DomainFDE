"""Read-only SQL for the agent, in two modes (Day 6: Ground).

    mode "raw"       the agent may query only the raw tables, and sees bare column names
    mode "semantic"  the agent may query only the ontology-aligned views, with descriptions

The guardrail is in code, as on Day 2: one statement, SELECT only, only the tables
the mode allows, and at most 50 rows back. The model can write any SQL it likes;
only safe SQL runs.

Backend: SQLite by default (data/northwind.db). Set SQL_BACKEND=bigquery and
BQ_DATASET=project.dataset to run the same queries on BigQuery instead.
"""
import os
import re
import sqlite3
from pathlib import Path

import yaml

from .database import DB_PATH, RAW_TABLES, build, view_sql

SEMANTIC = yaml.safe_load((Path(__file__).parent / "semantic_layer.yaml").read_text(encoding="utf-8"))
ALLOWED = {"raw": set(RAW_TABLES), "semantic": set(SEMANTIC)}
MAX_ROWS = 50
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|replace|attach|pragma|grant|merge|truncate)\b", re.I)


def describe(mode):
    """What the agent may know about the data in this mode."""
    if mode == "semantic":
        return {"mode": mode, "views": {
            name: {"description": spec["description"], "columns": spec["columns"]}
            for name, spec in SEMANTIC.items()}}
    con = sqlite3.connect(_db())
    tables = {}
    for name in RAW_TABLES:
        tables[name] = [row[1] for row in con.execute(f"PRAGMA table_info({name})")]
    con.close()
    return {"mode": mode, "tables": tables}


def check(query, mode):
    """Returns None if the query may run, or the reason it may not."""
    q = query.strip().rstrip(";")
    if ";" in q:
        return "Only one statement at a time."
    if not re.match(r"^\s*(select|with)\b", q, re.I):
        return "Only SELECT queries are allowed."
    if FORBIDDEN.search(q):
        return "The query tries to change data. Only reading is allowed."
    named = {t.lower() for t in re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)", q, re.I)}
    ctes = {c.lower() for c in re.findall(r"\b([a-z_][a-z0-9_]*)\s+as\s*\(", q, re.I)}
    outside = named - ctes - ALLOWED[mode]
    if outside:
        return f"Not allowed in {mode} mode: {', '.join(sorted(outside))}. Allowed: {', '.join(sorted(ALLOWED[mode]))}."
    return None


def run(query, mode):
    reason = check(query, mode)
    if reason:
        return {"status": "blocked", "reason": reason}
    try:
        if os.getenv("SQL_BACKEND", "sqlite") == "bigquery":
            columns, rows = _bigquery(query)
        else:
            con = sqlite3.connect(f"file:{_db()}?mode=ro", uri=True)
            cursor = con.execute(query)
            columns = [c[0] for c in cursor.description]
            rows = cursor.fetchmany(MAX_ROWS + 1)
            con.close()
    except Exception as error:  # the model sees its mistake and can try again
        return {"status": "error", "error": str(error)[:300]}
    return {"status": "ok", "columns": columns, "rows": [list(r) for r in rows[:MAX_ROWS]],
            "truncated": len(rows) > MAX_ROWS}


def _db():
    return DB_PATH if DB_PATH.exists() else build()


def _bigquery(query):
    from google.cloud import bigquery  # only needed for the BigQuery option
    dataset = os.environ["BQ_DATASET"]
    client = bigquery.Client(project=dataset.split(".")[0])
    config = bigquery.QueryJobConfig(default_dataset=dataset, maximum_bytes_billed=10**8)
    result = client.query(query, job_config=config).result(max_results=MAX_ROWS + 1)
    rows = [tuple(r.values()) for r in result]
    return [f.name for f in result.schema], rows


def bigquery_setup():
    """Copy the raw tables into BigQuery and create the views there. Run once."""
    from google.cloud import bigquery
    from .database import rows
    dataset = os.environ["BQ_DATASET"]
    client = bigquery.Client(project=dataset.split(".")[0])
    client.create_dataset(dataset, exists_ok=True)
    for table, columns in RAW_TABLES.items():
        schema = [bigquery.SchemaField(c.split()[0], {"TEXT": "STRING", "INTEGER": "INT64", "REAL": "FLOAT64"}[c.split()[1]])
                  for c in columns.split(", ")]
        names = [f.name for f in schema]
        client.delete_table(f"{dataset}.{table}", not_found_ok=True)
        client.create_table(bigquery.Table(f"{dataset}.{table}", schema=schema))
        data = [dict(zip(names, r)) for r in rows()[table]]
        if data:
            errors = client.insert_rows_json(f"{dataset}.{table}", data)
            if errors:
                raise RuntimeError(errors)
        print(f"  table {table}: {len(data)} rows")
    for view, sql in view_sql(lambda name: f"`{dataset}.{name}`").items():
        client.query(f"CREATE OR REPLACE VIEW `{dataset}.{view}` AS {sql}").result()
        print(f"  view  {view}")
