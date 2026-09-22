"""The Northwind database, in two shapes (Day 6: Ground).

The same records as data/northwind.json, stored the way a real back-office system
often stores them: short, cryptic table and column names, codes instead of words,
and one fact (vulnerability) recorded in two places that disagree.

On top of the raw tables sit four VIEWS, the semantic layer. They use the Day 4
ontology's names, do the joins for you, turn codes back into words, and read
vulnerability from the customer, where the ontology says it belongs.

    RAW TABLES                               SEMANTIC VIEWS
    cust_tbl  acc_tbl  ord_tbl  cmp_tbl      complaints_v   returns_v
    rfnd_tbl  rtn_tbl  cons_tbl              refunds_v      consents_v

Grounding on the raw tables and then on the views, with the same questions, is the
Day 6 experiment.

    python3 -m northwind.database            build data/northwind.db (run from the kit)
"""
import json
import sqlite3
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
DB_PATH = KIT / "data" / "northwind.db"
DATA = json.loads((KIT / "data" / "northwind.json").read_text(encoding="utf-8"))

GRADE_CODE = {"A": 1, "B": 2, "C": 3}

RAW_TABLES = {
    "cust_tbl": "cref TEXT, nm TEXT, vf INTEGER, circ TEXT",
    "acc_tbl": "aref TEXT, eml TEXT, cref TEXT, vuln INTEGER",
    "ord_tbl": "oref TEXT, aref TEXT, val REAL",
    "cmp_tbl": "cid TEXT, aref TEXT, oref TEXT, chn TEXT, txt TEXT, pcnt INTEGER",
    "rfnd_tbl": "fid TEXT, cid TEXT, amt REAL",
    "rtn_tbl": "rid TEXT, oref TEXT, cid TEXT, itm TEXT, val REAL, grd INTEGER, rcl TEXT, rcl_note TEXT, vnd TEXT, dl INTEGER",
    "cons_tbl": "cref TEXT, ch TEXT, purp TEXT, ok INTEGER",
}


def view_sql(t=lambda name: name):
    """The semantic layer. t() qualifies a table name, so the same SQL works in BigQuery."""
    return {
        "complaints_v": f"""
            SELECT c.cid AS complaint_id,
                   cu.cref AS customer_id,
                   cu.nm AS customer_name,
                   CASE WHEN cu.vf = 1 THEN 'yes' ELSE 'no' END AS customer_is_vulnerable,
                   c.oref AS order_id,
                   o.val AS order_value_gbp,
                   c.chn AS arrived_via,
                   c.txt AS complaint_text,
                   COALESCE((SELECT SUM(r.amt) FROM {t('rfnd_tbl')} r WHERE r.cid = c.cid), 0) AS refunds_so_far_gbp
            FROM {t('cmp_tbl')} c
            JOIN {t('acc_tbl')} a ON a.aref = c.aref
            JOIN {t('cust_tbl')} cu ON cu.cref = a.cref
            JOIN {t('ord_tbl')} o ON o.oref = c.oref""",
        "returns_v": f"""
            SELECT r.rid AS return_id,
                   r.cid AS complaint_id,
                   r.itm AS item,
                   r.val AS value_gbp,
                   CASE r.grd WHEN 1 THEN 'A' WHEN 2 THEN 'B' WHEN 3 THEN 'C' END AS condition_grade,
                   CASE WHEN r.rcl = 'Y' THEN 'yes' ELSE 'no' END AS on_recall_list,
                   r.rcl_note AS recall_notice,
                   r.vnd AS vendor,
                   r.dl AS days_to_vendor_deadline,
                   CASE WHEN r.dl >= 0 THEN 'yes' ELSE 'no' END AS vendor_claim_open
            FROM {t('rtn_tbl')} r""",
        "refunds_v": f"""
            SELECT f.fid AS refund_id, f.cid AS complaint_id, f.amt AS amount_gbp
            FROM {t('rfnd_tbl')} f""",
        "consents_v": f"""
            SELECT s.cref AS customer_id, cu.nm AS customer_name, s.ch AS channel,
                   s.purp AS purpose, CASE WHEN s.ok = 1 THEN 'yes' ELSE 'no' END AS allowed
            FROM {t('cons_tbl')} s JOIN {t('cust_tbl')} cu ON cu.cref = s.cref""",
    }


def rows():
    """The records, reshaped into the raw tables."""
    d = DATA
    return {
        "cust_tbl": [(c["customer_id"], c["name"], int(c["vulnerable"]), c["circumstance"]) for c in d["customers"]],
        # The legacy per-account flag: only set where an old system recorded it, and wrong for ACC-003B
        "acc_tbl": [(a["account_id"], a["email"], a["customer_id"],
                     int(a["vulnerable"]) if "vulnerable" in a else None) for a in d["accounts"]],
        "ord_tbl": [(o["order_id"], o["account_id"], o["value_gbp"]) for o in d["orders"]],
        "cmp_tbl": [(c["complaint_id"], c["account_id"], c["order_id"], c["arrived_via"], c["text"],
                     c["reported_previous_contacts"]) for c in d["complaints"]],
        "rfnd_tbl": [(r["refund_id"], r["complaint_id"], r["amount_gbp"]) for r in d["refunds"]],
        "rtn_tbl": [(r["return_id"], r["order_id"], r["complaint_id"], r["item"], r["value_gbp"],
                     GRADE_CODE[r["condition_grade"]], "Y" if r["on_recall_list"] else "N",
                     r["recall_notice"], r["vendor"], r["days_to_vendor_deadline"]) for r in d["returns"]],
        "cons_tbl": [(c["customer_id"], c["channel"], c.get("purpose"), int(c["allowed"])) for c in d["consents"]],
    }


def build(path=DB_PATH):
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    for table, columns in RAW_TABLES.items():
        con.execute(f"CREATE TABLE {table} ({columns})")
        data = rows()[table]
        if data:
            con.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(data[0]))})", data)
    for view, sql in view_sql().items():
        con.execute(f"CREATE VIEW {view} AS {sql}")
    con.commit()
    con.close()
    return path


if __name__ == "__main__":
    p = build()
    con = sqlite3.connect(p)
    for name in list(RAW_TABLES) + list(view_sql()):
        n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name:<14} {n} rows")
    print(f"\nBuilt {p.relative_to(KIT)}")
