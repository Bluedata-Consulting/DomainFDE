"""Re-derive every computed answer in the Meridian eval dataset.

    python eval/derive_truth.py            # re-run all SQL, verify quotes, rewrite both files
    python eval/derive_truth.py --check    # same, but write nothing; exit 1 on any drift
    python eval/derive_truth.py --summary  # coverage summary only

Ground truth comes from the data and the documents, never from an agent's
implementation. This script is the only thing allowed to write a `truth`,
`value` or `expect_all` field: a hand-typed answer does not survive a data
regeneration, and a stale answer is worse than none.

What it does, per case:

  truth_sql + truth_shape      -> truth         (Tier A; the answer itself)
  expect_all_from: [cols]      -> expect_all    (strings the answer must contain)
  naive: [{sql, shape}]        -> naive[].value (the wrong-but-plausible answers)
  alt:   [{sql, shape}]        -> alt[].value   (defensible alternative readings)
  facts: [{name, sql, shape}]  -> facts[].value (evidence the Tier C judge is given)
  source/sources: {quote}      -> verified against the PDF page text (Tier B)

Shapes: scalar (first column of first row), row (first row as a mapping),
rows (every row as a mapping), column (first column as a list).

Every query may use :as_of, the case clock from ontology.yaml (2026-03-16).
The real date is never used.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

EVAL_DIR = Path(__file__).resolve().parent
DAY5 = EVAL_DIR.parent
DB_PATH = DAY5 / "data" / "roastery.db"
PDF_DIR = DAY5 / "data" / "EnterpriseKnoweledge"
OCR_DIR = PDF_DIR / ".ocr"
ONTOLOGY = DAY5 / "ontology" / "ontology.yaml"
CASE_FILES = [EVAL_DIR / "agent_cases.yaml", EVAL_DIR / "rag_cases.yaml"]

# Document code -> the leading number of its file in PDF_DIR.
DOC_FILES = {
    "MR-CC-POL-004": "01",
    "MR-QA-STD-002": "02",
    "MR-PROC-HB-003": "03",
    "MR-OPS-PM-ARCHIVE": "04",
}

HEADER = """\
# GENERATED FIELDS: truth, expect_all, naive[].value, alt[].value, facts[].value
# are written by eval/derive_truth.py from the SQL stored beside them. Do not
# edit them by hand -- edit the SQL and re-run the script. Everything else in
# this file is hand-authored. See meta.* for the vocabulary used below.
"""


# --------------------------------------------------------------------------
# SQL
# --------------------------------------------------------------------------


def _clean(value: Any) -> Any:
    """Round floats so a re-run is byte-stable."""
    if isinstance(value, float):
        value = round(value, 2)
        return int(value) if value.is_integer() else value
    return value


def run_sql(con: sqlite3.Connection, sql: str, shape: str, as_of: str) -> Any:
    params = {"as_of": as_of} if ":as_of" in sql else {}
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    rows = [[_clean(v) for v in r] for r in cur.fetchall()]
    if shape == "scalar":
        return rows[0][0] if rows else None
    if shape == "row":
        return dict(zip(cols, rows[0])) if rows else None
    if shape == "rows":
        return [dict(zip(cols, r)) for r in rows]
    if shape == "column":
        return [r[0] for r in rows]
    raise ValueError(f"unknown shape {shape!r}")


def _expect_all(truth: Any, cols: list[str]) -> list[str]:
    rows = truth if isinstance(truth, list) else [truth]
    out: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            out.extend(str(row[c]) for c in cols if row.get(c) is not None)
        elif row is not None:
            out.append(str(row))
    return list(dict.fromkeys(out))


# --------------------------------------------------------------------------
# document quotes
# --------------------------------------------------------------------------


def _norm(text: str) -> str:
    text = re.sub(r"[|*`#]|:?-{3,}:?", " ", text)
    text = text.replace("—", "-").replace("–", "-").replace("§", "")
    return re.sub(r"\s+", " ", text).strip().lower()


_page_cache: dict[tuple[str, int], str | None] = {}


def page_text(doc: str, page: int) -> str | None:
    """The text of one PDF page: the text layer if it has one, else the OCR cache.

    These PDFs were printed with every glyph drawn as a vector outline, so
    they usually have no text layer; build_index.py transcribes them into
    .ocr/<name>.pNN.md, which is what gets read here.
    """
    key = (doc, page)
    if key in _page_cache:
        return _page_cache[key]
    text = None
    prefix = DOC_FILES.get(doc)
    pdfs = sorted(PDF_DIR.glob(f"{prefix} *.pdf")) if prefix else []
    if pdfs:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(pdfs[0]))
            if 0 < page <= len(reader.pages):
                text = (reader.pages[page - 1].extract_text() or "").strip() or None
        except Exception:
            text = None
        if text is None:
            ocr = OCR_DIR / f"{pdfs[0].stem}.p{page:02d}.md"
            if ocr.exists():
                text = ocr.read_text()
    _page_cache[key] = text
    return text


def verify_source(src: dict[str, Any]) -> str | None:
    """None if the quote is on the cited page, else a reason."""
    quote = src.get("quote")
    if not quote:
        return None
    text = page_text(src["doc"], int(src["page"]))
    if text is None:
        return f"{src['doc']} p{src['page']}: no text available to verify against"
    if _norm(quote) not in _norm(text):
        return f"{src['doc']} p{src['page']} §{src.get('section')}: quote not found: {quote!r}"
    return None


# --------------------------------------------------------------------------
# derivation
# --------------------------------------------------------------------------


def derive_case(con, case: dict[str, Any], as_of: str, log: list[str],
                problems: list[str]) -> None:
    cid = case["id"]

    def update(holder: dict[str, Any], key: str, new: Any, label: str) -> None:
        old = holder.get(key)
        if old != new:
            log.append(f"  {cid:<5} {label}: {_short(old)} -> {_short(new)}")
        holder[key] = new

    try:
        if case.get("truth_sql"):
            truth = run_sql(con, case["truth_sql"], case.get("truth_shape", "scalar"), as_of)
            update(case, "truth", truth, "truth")
            if case.get("expect_all_from"):
                update(case, "expect_all", _expect_all(truth, case["expect_all_from"]),
                       "expect_all")
        for group in ("naive", "alt", "facts"):
            for item in case.get(group) or []:
                if item.get("sql"):
                    value = run_sql(con, item["sql"], item.get("shape", "scalar"), as_of)
                    update(item, "value", value, f"{group}.{item.get('name') or item.get('label')}")
    except sqlite3.Error as exc:
        problems.append(f"{cid}: SQL error: {exc}")

    for src in _sources(case):
        reason = verify_source(src)
        if reason:
            problems.append(f"{cid}: {reason}")


def _sources(case: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    if isinstance(case.get("source"), dict):
        out.append(case["source"])
    out.extend(case.get("sources") or [])
    return out


def _short(value: Any, n: int = 70) -> str:
    s = repr(value)
    return s if len(s) <= n else s[: n - 3] + "..."


# --------------------------------------------------------------------------
# YAML round trip
# --------------------------------------------------------------------------


class _Dumper(yaml.SafeDumper):
    pass


def _str_repr(dumper: yaml.SafeDumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_repr)


def dump(doc: dict[str, Any]) -> str:
    body = yaml.dump(doc, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                     width=88, default_flow_style=False)
    return HEADER + "\n" + body


# --------------------------------------------------------------------------
# coverage summary
# --------------------------------------------------------------------------


def summary(docs: dict[Path, dict[str, Any]]) -> str:
    lines: list[str] = []
    for path, doc in docs.items():
        cases = doc["cases"]
        lines.append(f"\n{path.name}: {len(cases)} cases")
        tiers = Counter(c["tier"] for c in cases)
        lines.append("  per tier:          " + _fmt(tiers))
        lines.append("  per category:      " + _fmt(Counter(c["category"] for c in cases)))
        watch = Counter(f for c in cases for f in c.get("failure_watch", []))
        lines.append("  per failure class: " + _fmt(watch))
        rungs = Counter(
            "never" if c.get("expected_fail") else c.get("expected_pass_from", "?")
            for c in cases
        )
        lines.append("  per rung (first expected pass): " + _fmt(rungs, order=RUNG_ORDER))
        if any("requires_docs" in c for c in cases):
            cross = sum(1 for c in cases if len(c.get("requires_docs", [])) > 1)
            db = sum(1 for c in cases if c.get("requires_db"))
            pf = sum(1 for c in cases if c.get("scoring") == "pass_fail")
            lines.append(f"  cross-document: {cross}   needs database: {db}   "
                         f"pass/fail (adversarial): {pf}")
    return "\n".join(lines)


RUNG_ORDER = ["V0", "V1", "V2", "V3", "V4", "V5", "never", "?"]


def _fmt(counter: Counter, order: list[str] | None = None) -> str:
    keys = sorted(counter, key=lambda k: (order.index(k) if order and k in order else 99, k))
    return "  ".join(f"{k}={counter[k]}" for k in keys)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 on drift")
    ap.add_argument("--summary", action="store_true", help="print coverage only")
    args = ap.parse_args()

    docs = {p: yaml.safe_load(p.read_text()) for p in CASE_FILES}
    if args.summary:
        print(summary(docs))
        return 0

    as_of = str(yaml.safe_load(ONTOLOGY.read_text())["as_of_date"])
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)

    log: list[str] = []
    problems: list[str] = []
    ids: Counter = Counter()
    for doc in docs.values():
        for case in doc["cases"]:
            ids[case["id"]] += 1
            derive_case(con, case, as_of, log, problems)
    problems += [f"duplicate case id {i}" for i, n in ids.items() if n > 1]

    print(f"database {DB_PATH.relative_to(DAY5)}  as_of {as_of}")
    print(f"{len(log)} derived value(s) changed" + (":" if log else ""))
    print("\n".join(log))
    if problems:
        print(f"\n{len(problems)} problem(s):")
        print("\n".join("  " + p for p in problems))

    if not args.check:
        for path, doc in docs.items():
            path.write_text(dump(doc))
        print(f"\nwrote {', '.join(p.name for p in docs)}")
    print(summary(docs))

    if problems or (args.check and log):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
