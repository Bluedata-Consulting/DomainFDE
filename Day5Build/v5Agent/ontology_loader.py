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

import inspect
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


def _scalar_annotation(spec: dict) -> str:
    """Python annotation source for one parameter, ignoring `many`."""
    source = spec.get("from")
    if source and source.startswith("vocabularies."):
        vocab = source.split(".", 1)[1]
        values = _vocabularies()[vocab]["values"]
        literal = ", ".join(repr(v) for v in values)
        return f"Literal[{literal}]"
    if source:  # Entity.key reference -- ids are opaque strings
        return "str"
    return _PY_TYPES.get(spec.get("type", "string"), "str")


def _annotation(spec: dict) -> str:
    """Python annotation source for one parameter spec.

    A `many: true` parameter becomes `list[...]`, so the schema the model reads
    advertises a batch call. The tools still accept a bare scalar defensively,
    but the declaration asks for a list -- that is what stops a model issuing
    one call per id.
    """
    scalar = _scalar_annotation(spec)
    return f"list[{scalar}]" if spec.get("many") else scalar


def _param_doc(name: str, spec: dict) -> str:
    """One extra docstring line when a parameter needs more than its annotation.

    Deliberately silent about vocabulary values: the `Literal[...]` annotation
    already puts the enum in the function schema, and the tool's own `Args:`
    block lists it too, so spelling it out a third time only inflated the
    declaration.
    """
    source = spec.get("from", "")
    if source.startswith("vocabularies."):
        return ""
    if source:
        entity, key = source.split(".", 1)
        if spec.get("many"):
            return (
                f"        {name}: list of {key}s, one or many. Pass EVERY id you"
                f" need in a single call -- do not call this once per {entity}."
            )
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

        # The ontology is only allowed to describe parameters the function
        # actually has. A rename used to produce a wrapper that raised
        # TypeError on the first call instead of failing here.
        raw_sig = inspect.signature(func)
        unknown = [n for n, _ in params.items() if n not in raw_sig.parameters]
        if unknown:
            raise OntologyError(
                f"tools.{func.__name__}.params names parameter(s) "
                f"{unknown} that {func.__name__}() does not accept"
            )

        signature, body, doc_lines = [], [], []
        for name, pspec in required:
            signature.append(f"{name}: {_annotation(pspec)}")
            body.append(f"    _kw[{name!r}] = {name}")
            line = _param_doc(name, pspec)
            if line:
                doc_lines.append(line)
        for name, pspec in optional:
            raw_default = raw_sig.parameters[name].default
            if raw_default is inspect.Parameter.empty or raw_default is None:
                # A genuine filter: absent means "do not filter on this".
                signature.append(f"{name}: {_annotation(pspec)} | None = None")
                body.append(f"    if {name} is not None: _kw[{name!r}] = {name}")
            else:
                # A real default (limit=50, min_slip_days=1, months=6). Emit it
                # so it reaches the schema the model reads. Hiding it was why a
                # model that got exactly 50 rows re-called with limit=1000: it
                # could not see that 50 was the cap doing the cutting.
                signature.append(f"{name}: {_annotation(pspec)} = {raw_default!r}")
                body.append(f"    _kw[{name!r}] = {name}")
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


def _documents() -> dict:
    """The document registry, or an empty dict for an ontology without one."""
    return load().get("documents", {}) or {}


@lru_cache(maxsize=1)
def document_terms() -> tuple[tuple[str, str], ...]:
    """(term, doc_id) for every phrase a document declares it governs.

    Longest first, so 'goodwill cap' is recognised before 'goodwill'.
    """
    pairs: list[tuple[str, str]] = []
    for doc_id, spec in _documents().items():
        for key in ("governs", "terms"):
            for term in spec.get(key) or []:
                pairs.append((str(term).lower().strip(), doc_id))
    # De-duplicate, keeping the first document that claims a term.
    seen: dict[str, str] = {}
    for term, doc_id in pairs:
        seen.setdefault(term, doc_id)
    return tuple(sorted(seen.items(), key=lambda kv: -len(kv[0])))


# ------------------------------------------------------------- 3. resolve


_STOPWORDS = {
    "what", "which", "who", "why", "how", "when", "where", "the", "and",
    "for", "with", "did", "does", "was", "were", "has", "have", "can",
    "our", "we", "is", "are", "in", "on", "of", "to", "a", "an", "it",
    "me", "my", "show", "tell", "give", "find", "about", "all", "any",
    "february", "january", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
}


_MAX_CANDIDATES_PER_SOURCE = 5
_MAX_NOTE_CHARS = 2500


def _name_candidates(conn: sqlite3.Connection, token: str) -> list[str]:
    """Look one capitalised token up in every Person resolution source.

    Takes an open connection: this used to open (and close) one per token, so a
    question naming seven capitalised words paid for seven connections and
    twenty-one table scans.
    """
    found: list[str] = []
    for source in _person_sources():
        table = source["table"]
        id_column = source["id_column"]
        match_columns = source["match_columns"]
        extra = source.get("disambiguate_with", [])
        where = " OR ".join(f"{c} LIKE ?" for c in match_columns)
        columns = ", ".join([id_column] + match_columns + extra)
        rows = conn.execute(
            f"SELECT {columns} FROM {table} WHERE {where} LIMIT ?",
            [f"%{token}%"] * len(match_columns) + [_MAX_CANDIDATES_PER_SOURCE + 1],
        ).fetchall()
        overflow = len(rows) > _MAX_CANDIDATES_PER_SOURCE
        rows = rows[:_MAX_CANDIDATES_PER_SOURCE]
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
        if overflow:
            # The ambiguity signal is "more than one", not the full list --
            # so say there are more rather than pasting all of them.
            found.append(
                f"  - ...and more {source['entity']} rows match '{token}';"
                " too many to list, ask which was meant."
            )
    return found


@lru_cache(maxsize=64)
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

    def _mentions(term: str) -> bool:
        """Whole-word match. Substring matching claimed 'delivery' contained 'live'."""
        term = term.lower()
        if " " in term or "_" in term:
            return re.search(rf"\b{re.escape(term.replace('_', ' '))}\b", lowered) is not None
        return term in words

    # -- people ------------------------------------------------------------
    tokens = [
        t for t in re.findall(r"\b[A-Z][a-zA-Z'-]{2,}", question)
        if t.lower() not in _STOPWORDS
    ]
    person_lines: list[str] = []
    if tokens:
        conn = connect_ro()
        try:
            for token in dict.fromkeys(tokens):
                hits = _name_candidates(conn, token)
                if hits:
                    person_lines.append(
                        f"'{token}' matches {len(hits)} person record(s):"
                    )
                    person_lines += hits
        finally:
            conn.close()
    if person_lines:
        note = _entities()["Person"].get("disambiguation_note", "").strip()
        sections.append("PEOPLE\n" + "\n".join(person_lines) + f"\n  NOTE: {note}")

    # -- entities ----------------------------------------------------------
    entity_lines: list[str] = []
    for name, entity in _entities().items():
        terms = {t.lower() for t in entity.get("canonical_terms", [])}
        hit = {t for t in terms if _mentions(t)}
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
        if _mentions(term)
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
        if _mentions(synonym)
    ]
    if synonym_lines:
        sections.append("HOUSE SPELLING\n" + "\n".join(synonym_lines))

    # -- document-governed terms ------------------------------------------
    # This is what tells the router a question needs the policy lane: the
    # ontology's own policy block is a summary of MR-CC-POL-004 and omits the
    # conditions and uplifts, so a question touching these terms must be
    # answered from the document, not from this file.
    policy_lines: list[str] = []
    claimed: set[str] = set()
    for term, doc_id in document_terms():
        if doc_id in claimed or not _mentions(term):
            continue
        claimed.add(doc_id)
        if doc_id == "MR-CC-POL-004":
            policy_lines.append(
                f"  - '{term}' is governed by {doc_id}. The ontology's policy "
                "block is a summary only -- retrieve the document before deciding."
            )
        else:
            title = _documents()[doc_id].get("title", doc_id)
            policy_lines.append(
                f"  - '{term}' is governed by {doc_id} ({title}). Retrieve the "
                "document rather than reasoning from the database alone."
            )
    if policy_lines:
        sections.append("POLICY TERM\n" + "\n".join(policy_lines))

    if not sections:
        return (
            "Nothing ambiguous found in this question: no known person name, "
            "competing term, metric or synonym matched. Proceed, but still "
            "name the tools and date range you used."
        )
    note = "\n\n".join(sections)
    if len(note) > _MAX_NOTE_CHARS:
        # This note is pasted into every lane's instruction and resent on every
        # turn, so an unbounded one is charged many times over.
        note = note[:_MAX_NOTE_CHARS].rsplit("\n", 1)[0] + "\n  ...note truncated."
    return note


# --------------------------------------------------------- 4. prompt_core


def _scope_for(tool_names: tuple[str, ...]) -> tuple[set[str], set[str], set[str]]:
    """Which entities, metrics and tables a set of tools actually touches.

    Derived from the ontology's own `tools:` block -- `entity:`, `metric:` and
    any `params.*.from: Entity.key` reference -- so there is no second map to
    keep in step with the lane definitions.

    Returns:
        (entity names, metric names, table names).
    """
    spec_by_tool = load()["tools"]
    entities: set[str] = set()
    metrics: set[str] = set()
    for name in tool_names:
        spec = spec_by_tool.get(name)
        if not spec:
            continue
        entities.add(spec["entity"])
        if spec.get("metric"):
            metrics.add(spec["metric"])
        for pspec in (spec.get("params") or {}).values():
            source = pspec.get("from", "")
            if source and not source.startswith("vocabularies."):
                entities.add(source.split(".", 1)[0])

    # A metric's own tables count too: a lane that may compute on_time_delivery
    # needs the tables the house definition is measured over.
    all_entities = _entities()
    tables = {
        all_entities[e]["table"]
        for e in entities
        if e in all_entities and not all_entities[e].get("abstract")
    }
    for metric_name in metrics:
        tables |= set(load()["metrics"][metric_name].get("tables", []))
    return entities, metrics, tables


def lane_tables(tool_names: tuple[str, ...], extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Tables a lane holding `tool_names` is allowed to read, sorted.

    This is the allowlist behind the lane-scoped SQL tool: it keeps the
    partition that makes the lanes worth having -- a lane that cannot see
    `tickets` cannot blame a ticket -- while still letting it join freely
    inside its own territory.
    """
    _, _, tables = _scope_for(tuple(tool_names))
    return tuple(sorted(tables | set(extra)))


@lru_cache(maxsize=32)
def prompt_core(
    tool_names: tuple[str, ...] = (),
    *,
    include_policy: bool = True,
) -> str:
    """Render the ambiguity notes, metric definitions and policy as markdown.

    Args:
        tool_names: Narrow the output to the entities and metrics these tools
            touch. The default -- an empty tuple -- renders everything, which
            is what the merger gets.
        include_policy: Whether to append the goodwill policy. Lanes are
            forbidden to offer anything, so for them this is dead weight.

    Returns:
        Markdown for a system instruction. Cached per argument pair, because
        this used to rebuild the same ~8 KB string on every call.
    """
    ontology = load()
    if tool_names:
        keep_entities, keep_metrics, _ = _scope_for(tool_names)
    else:
        keep_entities = set(ontology["entities"])
        keep_metrics = set(ontology["metrics"])
    out: list[str] = ["## Business ontology (authoritative)"]

    out.append(
        "\n### Words that mean two things\n"
        "Decide which one the asker means before you answer. If it could "
        "genuinely be either, say which you took, or ask."
    )
    for name, entity in ontology["entities"].items():
        note = (entity.get("disambiguation_note") or "").strip()
        if not note or name not in keep_entities:
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
        if name not in keep_metrics:
            continue
        out.append(
            f"- **{name}** (owner: {metric['owner']}): "
            f"{' '.join(metric['definition'].split())}"
        )

    if not include_policy:
        return "\n".join(out)

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
