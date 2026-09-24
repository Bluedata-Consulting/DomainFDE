"""Load ontology/ontology.yaml and make it usable by the agent.

Four public functions:

    load()                  parse and cache the YAML
    typed_tools(raw_tools)  re-signature the derived tools from the ontology,
                            so vocabulary-backed parameters become Literals
    resolve(question)       a plain-text note on who/what a question may mean
    prompt_core()           ambiguity notes + metric definitions + policy,
                            as markdown for the system instruction

Plus validate_ontology(), which checks every table, column, key and
vocabulary reference against roastery.db. It runs on import, so a drifted
ontology fails at startup rather than three turns into an agent trace.

Run directly to see the validation report (no ADK install needed):

    python v2Agent/ontology_loader.py
"""

import re
import sqlite3
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Literal

import yaml

try:
    from .tools.db import connect_ro
except ImportError:  # run as a script, so validation needs no ADK install
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from tools.db import connect_ro

ONTOLOGY_PATH = Path(__file__).resolve().parent.parent / "ontology" / "ontology.yaml"


class OntologyError(RuntimeError):
    """Raised when the ontology does not match the database it describes."""


# ---------------------------------------------------------------- 1. load


@lru_cache(maxsize=1)
def load() -> dict:
    """Parse ontology.yaml once and cache it.

    Returns:
        The ontology as a dict with keys: version, database, as_of_date,
        vocabularies, entities, metrics, policy, tools.
    """
    if not ONTOLOGY_PATH.exists():
        raise OntologyError(f"Ontology not found at {ONTOLOGY_PATH}")
    with ONTOLOGY_PATH.open() as handle:
        ontology = yaml.safe_load(handle)

    for block in ("vocabularies", "entities", "metrics", "policy", "tools"):
        if block not in ontology:
            raise OntologyError(f"ontology.yaml is missing the '{block}' block")
    return ontology


def _entities() -> dict:
    return load()["entities"]


def _vocabularies() -> dict:
    return load()["vocabularies"]


def _person_sources() -> list[dict]:
    person = _entities().get("Person", {})
    return person.get("resolution", {}).get("sources", [])


# --------------------------------------------------------- 2. typed_tools


_PY_TYPES = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "date": "str",
}


def _annotation(spec: dict) -> str:
    """Python annotation source for one parameter spec."""
    source = spec.get("from")
    if source and source.startswith("vocabularies."):
        vocab = source.split(".", 1)[1]
        values = _vocabularies()[vocab]["values"]
        literal = ", ".join(repr(v) for v in values)
        return f"Literal[{literal}]"
    if source:  # Entity.key reference -- ids are opaque strings
        return "str"
    return _PY_TYPES.get(spec.get("type", "string"), "str")


def _param_doc(name: str, spec: dict) -> str:
    """One extra docstring line when a parameter is constrained by the ontology."""
    source = spec.get("from", "")
    if source.startswith("vocabularies."):
        vocab = source.split(".", 1)[1]
        values = "|".join(_vocabularies()[vocab]["values"])
        return f"        {name}: one of {values}"
    if source:
        entity, key = source.split(".", 1)
        return f"        {name}: {key} of a {entity}"
    if spec.get("type") == "date":
        return f"        {name}: date 'YYYY-MM-DD'"
    return ""


def typed_tools(raw_tools: list[Callable]) -> list[Callable]:
    """Give each derived tool a signature generated from the ontology.

    A parameter backed by a vocabulary becomes Literal['a', 'b', ...], so the
    model can only send a legal value and never has to guess the house
    spelling. Ids and dates stay strings. Required parameters are emitted
    before defaulted ones.

    The wrapper source is built as text and exec'd, so the annotations are
    real objects that ADK's function-schema builder can read.

    Args:
        raw_tools: The plain tool functions, e.g. tools.DOMAIN_TOOLS.

    Returns:
        A new list: ontology-typed wrappers for the tools the ontology
        describes, and the original function for any it does not.
    """
    spec_by_tool = load()["tools"]
    wrapped: list[Callable] = []

    for func in raw_tools:
        spec = spec_by_tool.get(func.__name__)
        if spec is None:  # not in the ontology -- pass through untouched
            wrapped.append(func)
            continue

        params: dict = spec.get("params", {})
        required = [(n, s) for n, s in params.items() if s.get("required")]
        optional = [(n, s) for n, s in params.items() if not s.get("required")]

        signature, body, doc_lines = [], [], ["    _kw = {}"]
        doc_lines = []
        for name, pspec in required:
            signature.append(f"{name}: {_annotation(pspec)}")
            body.append(f"    _kw[{name!r}] = {name}")
            line = _param_doc(name, pspec)
            if line:
                doc_lines.append(line)
        for name, pspec in optional:
            signature.append(f"{name}: {_annotation(pspec)} | None = None")
            # Only forward what the caller actually supplied, so the raw
            # function keeps its own defaults (e.g. limit=25).
            body.append(f"    if {name} is not None: _kw[{name!r}] = {name}")
            line = _param_doc(name, pspec)
            if line:
                doc_lines.append(line)

        doc = (func.__doc__ or "").rstrip()
        header = f"Serves entity: {spec['entity']}."
        if spec.get("metric"):
            header += f" Metric: {spec['metric']}."
        doc = f"{doc}\n\n    {header}"
        if doc_lines:
            doc += "\n\n    Ontology-constrained values:\n" + "\n".join(doc_lines)

        source = (
            f"def {func.__name__}({', '.join(signature)}):\n"
            f"    {doc!r}\n"
            "    _kw = {}\n"
            + "\n".join(body)
            + "\n    return _raw(**_kw)\n"
        )
        namespace: dict[str, Any] = {"_raw": func, "Literal": Literal}
        # dont_inherit=True so no __future__ flag from this module (now or
        # later) can turn the generated annotations into strings, which ADK
        # could not build a schema from.
        exec(compile(source, f"<ontology:{func.__name__}>", "exec", dont_inherit=True),
             namespace)
        typed = namespace[func.__name__]
        typed.__module__ = func.__module__
        wrapped.append(typed)

    return wrapped


# ------------------------------------------------------------- 3. resolve


_STOPWORDS = {
    "what", "which", "who", "why", "how", "when", "where", "the", "and",
    "for", "with", "did", "does", "was", "were", "has", "have", "can",
    "our", "we", "is", "are", "in", "on", "of", "to", "a", "an", "it",
    "me", "my", "show", "tell", "give", "find", "about", "all", "any",
    "february", "january", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
}


def _name_candidates(token: str) -> list[str]:
    """Look one capitalised token up in every Person resolution source."""
    found: list[str] = []
    conn = connect_ro()
    try:
        for source in _person_sources():
            table = source["table"]
            id_column = source["id_column"]
            match_columns = source["match_columns"]
            extra = source.get("disambiguate_with", [])
            where = " OR ".join(f"{c} LIKE ?" for c in match_columns)
            columns = ", ".join([id_column] + match_columns + extra)
            rows = conn.execute(
                f"SELECT {columns} FROM {table} WHERE {where} LIMIT 10",
                [f"%{token}%"] * len(match_columns),
            ).fetchall()
            for row in rows:
                data = dict(row)
                label = " ".join(
                    str(data[c]) for c in match_columns if data.get(c)
                )
                details = ", ".join(
                    f"{c}={data[c]}" for c in extra if data.get(c) is not None
                )
                found.append(
                    f"  - {source['entity']} {data[id_column]}: {label}"
                    f"{' (' + details + ')' if details else ''}"
                    f"  [{source['describes']}]"
                )
    finally:
        conn.close()
    return found


def resolve(question: str) -> str:
    """Check a question for ambiguous names and business terms before answering it.

    Call this FIRST on any question that names a person, or that uses a word
    which could mean two different things (order, shipment, contact, lead
    time, lot, batch, at risk). It reads the ontology and the database and
    reports what the question could mean.

    Args:
        question: The user's question, verbatim.

    Returns:
        A plain-text note listing every person who matches a name in the
        question (all candidates, never just one), the entities and metrics
        whose vocabulary the question touches, and any synonym that maps to a
        house term. Returns a "nothing ambiguous" note when it finds nothing.
    """
    ontology = load()
    lowered = question.lower()
    words = set(re.findall(r"[a-z][a-z_'-]+", lowered)) - _STOPWORDS
    sections: list[str] = []

    # -- people ------------------------------------------------------------
    tokens = [
        t for t in re.findall(r"\b[A-Z][a-zA-Z'-]{2,}", question)
        if t.lower() not in _STOPWORDS
    ]
    person_lines: list[str] = []
    for token in dict.fromkeys(tokens):
        hits = _name_candidates(token)
        if hits:
            person_lines.append(f"'{token}' matches {len(hits)} person record(s):")
            person_lines += hits
    if person_lines:
        note = _entities()["Person"].get("disambiguation_note", "").strip()
        sections.append("PEOPLE\n" + "\n".join(person_lines) + f"\n  NOTE: {note}")

    # -- entities ----------------------------------------------------------
    entity_lines: list[str] = []
    for name, entity in _entities().items():
        terms = {t.lower() for t in entity.get("canonical_terms", [])}
        hit = {t for t in terms if t in words or (" " in t and t in lowered)}
        if hit and entity.get("disambiguation_note"):
            entity_lines.append(
                f"  - '{sorted(hit)[0]}' -> {name}"
                f" ({'abstract' if entity.get('abstract') else entity['table']}):"
                f" {entity['disambiguation_note'].strip()}"
            )
    if entity_lines:
        sections.append("TERMS THAT COMPETE\n" + "\n".join(entity_lines))

    # -- metrics -----------------------------------------------------------
    metric_lines = [
        f"  - '{term}' -> metric {name} (owner: {metric['owner']})"
        for name, metric in ontology["metrics"].items()
        for term in metric.get("terms", [])
        if term in lowered
    ]
    if metric_lines:
        sections.append(
            "METRICS INVOKED (use the house definition, see system prompt)\n"
            + "\n".join(dict.fromkeys(metric_lines))
        )

    # -- vocabulary synonyms ----------------------------------------------
    synonym_lines = [
        f"  - '{synonym}' means {canonical} ({vocab})"
        for vocab, block in _vocabularies().items()
        for synonym, canonical in (block.get("synonyms") or {}).items()
        if synonym.replace("_", " ") in lowered or synonym in words
    ]
    if synonym_lines:
        sections.append("HOUSE SPELLING\n" + "\n".join(synonym_lines))

    if not sections:
        return (
            "Nothing ambiguous found in this question: no known person name, "
            "competing term, metric or synonym matched. Proceed, but still "
            "name the tools and date range you used."
        )
    return "\n\n".join(sections)


# --------------------------------------------------------- 4. prompt_core


def prompt_core() -> str:
    """Render the ambiguity notes, metric definitions and policy as markdown."""
    ontology = load()
    out: list[str] = ["## Business ontology (authoritative)"]

    out.append(
        "\n### Words that mean two things\n"
        "Decide which one the asker means before you answer. If it could "
        "genuinely be either, say which you took, or ask."
    )
    for name, entity in ontology["entities"].items():
        note = (entity.get("disambiguation_note") or "").strip()
        if not note:
            continue
        table = "abstract" if entity.get("abstract") else entity["table"]
        terms = ", ".join(entity.get("canonical_terms", [])[:5])
        out.append(f"- **{name}** ({table}) -- said as: {terms}. {note}")

    out.append(
        "\n### Metric definitions\n"
        "These are the house definitions. Do not invent a variant, and do not "
        "silently change the population a metric is measured over."
    )
    for name, metric in ontology["metrics"].items():
        out.append(
            f"- **{name}** (owner: {metric['owner']}): "
            f"{' '.join(metric['definition'].split())}"
        )

    policy = ontology["policy"]
    caps = policy["goodwill_caps"]
    out.append("\n### Goodwill policy")
    out.append(
        "- D2C caps per incident (USD): "
        + ", ".join(f"{tier} {amount}" for tier, amount in caps["d2c"].items())
    )
    out.append(
        "- Wholesale caps per incident (USD): "
        + ", ".join(f"{tier} {amount}" for tier, amount in caps["wholesale"].items())
    )
    out.append(
        f"- Anything above {policy['human_approval_required_above']} "
        f"{policy['currency']} requires named human approval before it is offered."
    )
    for note in policy.get("notes", []):
        out.append(f"- {note}")

    return "\n".join(out)


# ------------------------------------------------------------- validation


def _db_shape(conn: sqlite3.Connection) -> dict[str, set[str]]:
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {
        t: {row["name"] for row in conn.execute(f'PRAGMA table_info("{t}")')}
        for t in tables
    }


def validate_ontology() -> list[str]:
    """Check every reference in the ontology against the live database.

    Verifies that each entity table exists, that keys, label columns,
    Person-resolution columns, vocabulary columns and metric tables/columns
    all exist, and that every tool parameter's `from:` resolves to a real
    vocabulary or a real entity key.

    Returns:
        A list of problem strings. Empty means the ontology matches the
        database.
    """
    ontology = load()
    conn = connect_ro()
    try:
        shape = _db_shape(conn)
    finally:
        conn.close()
    problems: list[str] = []

    def check_columns(table: str, columns, where: str) -> None:
        missing = [c for c in columns if c not in shape.get(table, set())]
        if missing:
            problems.append(f"{where}: {table} has no column(s) {missing}")

    # entities
    for name, entity in ontology["entities"].items():
        if entity.get("abstract"):
            continue
        table = entity.get("table")
        if table not in shape:
            problems.append(f"entities.{name}: no such table '{table}'")
            continue
        check_columns(table, [entity["key"]], f"entities.{name}.key")
        check_columns(table, entity.get("label_columns", []),
                      f"entities.{name}.label_columns")

    # Person resolution sources
    for index, source in enumerate(_person_sources()):
        where = f"entities.Person.resolution.sources[{index}]"
        table = source.get("table")
        if table not in shape:
            problems.append(f"{where}: no such table '{table}'")
            continue
        if source.get("entity") not in ontology["entities"]:
            problems.append(f"{where}: unknown entity '{source.get('entity')}'")
        check_columns(table, [source["id_column"]], f"{where}.id_column")
        check_columns(table, source.get("match_columns", []), f"{where}.match_columns")
        check_columns(table, source.get("disambiguate_with", []),
                      f"{where}.disambiguate_with")

    # vocabularies -- the column must exist; unseen values are reported as info
    for name, vocab in ontology["vocabularies"].items():
        ref = vocab.get("column", "")
        if "." not in ref:
            problems.append(f"vocabularies.{name}.column: expected 'table.column'")
            continue
        table, column = ref.split(".", 1)
        if table not in shape:
            problems.append(f"vocabularies.{name}: no such table '{table}'")
            continue
        check_columns(table, [column], f"vocabularies.{name}.column")
        if not vocab.get("values"):
            problems.append(f"vocabularies.{name}: no values listed")
        for synonym, canonical in (vocab.get("synonyms") or {}).items():
            if canonical not in vocab.get("values", []):
                problems.append(
                    f"vocabularies.{name}.synonyms['{synonym}'] maps to "
                    f"'{canonical}', which is not one of its values"
                )

    # metrics
    for name, metric in ontology["metrics"].items():
        for table in metric.get("tables", []):
            if table not in shape:
                problems.append(f"metrics.{name}.tables: no such table '{table}'")
        for ref in metric.get("columns", []):
            if "." not in ref:
                problems.append(f"metrics.{name}.columns: expected 'table.column', got '{ref}'")
                continue
            table, column = ref.split(".", 1)
            if table not in shape:
                problems.append(f"metrics.{name}.columns: no such table '{table}'")
            elif column not in shape[table]:
                problems.append(f"metrics.{name}.columns: {table} has no column '{column}'")
        if not metric.get("definition"):
            problems.append(f"metrics.{name}: no definition")
        if not metric.get("owner"):
            problems.append(f"metrics.{name}: no owner")

    # tools
    for tool, spec in ontology["tools"].items():
        entity = spec.get("entity")
        if entity not in ontology["entities"]:
            problems.append(f"tools.{tool}.entity: unknown entity '{entity}'")
        if spec.get("metric") and spec["metric"] not in ontology["metrics"]:
            problems.append(f"tools.{tool}.metric: unknown metric '{spec['metric']}'")
        for param, pspec in (spec.get("params") or {}).items():
            source = pspec.get("from")
            if source is None:
                if pspec.get("type") not in _PY_TYPES:
                    problems.append(
                        f"tools.{tool}.params.{param}: unknown type "
                        f"'{pspec.get('type')}'"
                    )
                continue
            if source.startswith("vocabularies."):
                vocab = source.split(".", 1)[1]
                if vocab not in ontology["vocabularies"]:
                    problems.append(
                        f"tools.{tool}.params.{param}: unknown vocabulary '{vocab}'"
                    )
                continue
            if "." not in source:
                problems.append(
                    f"tools.{tool}.params.{param}: 'from' must be "
                    f"vocabularies.X or Entity.key, got '{source}'"
                )
                continue
            entity_name, key = source.split(".", 1)
            target = ontology["entities"].get(entity_name)
            if target is None:
                problems.append(
                    f"tools.{tool}.params.{param}: unknown entity '{entity_name}'"
                )
            elif target.get("key") != key:
                problems.append(
                    f"tools.{tool}.params.{param}: {entity_name}'s key is "
                    f"'{target.get('key')}', not '{key}'"
                )

    return problems


def _unseen_vocabulary_values() -> list[str]:
    """Values the ontology declares that the current data never uses (info only)."""
    conn = connect_ro()
    notes: list[str] = []
    try:
        for name, vocab in load()["vocabularies"].items():
            table, column = vocab["column"].split(".", 1)
            seen = {
                r[0] for r in conn.execute(
                    f'SELECT DISTINCT "{column}" FROM "{table}"'
                ) if r[0] is not None
            }
            unseen = [v for v in vocab["values"] if v not in seen]
            if unseen:
                notes.append(f"  {name}: declared but unused in data -> {unseen}")
    finally:
        conn.close()
    return notes


# Fail loudly at import time, not three turns into an agent trace.
_PROBLEMS = validate_ontology()
if _PROBLEMS:
    raise OntologyError(
        "ontology.yaml does not match roastery.db:\n  - "
        + "\n  - ".join(_PROBLEMS)
    )


if __name__ == "__main__":
    ontology = load()
    print(f"ontology.yaml  v{ontology['version']}  as of {ontology['as_of_date']}")
    print(
        f"  {len(ontology['vocabularies'])} vocabularies, "
        f"{len(ontology['entities'])} entities, "
        f"{len(ontology['metrics'])} metrics, "
        f"{len(ontology['tools'])} tools"
    )
    problems = validate_ontology()
    if problems:
        print(f"\nFAIL -- {len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        raise SystemExit(1)
    print("\nOK -- every table, column, key and reference exists in roastery.db")
    unseen = _unseen_vocabulary_values()
    if unseen:
        print("\nInfo (not errors -- schema allows these, the data has none yet):")
        print("\n".join(unseen))
