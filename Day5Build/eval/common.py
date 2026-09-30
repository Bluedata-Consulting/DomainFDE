"""Shared plumbing for the eval runners: cases, SQL, matching, rung runs, judge.

Nothing here writes to the case files. Everything that needs a model is
imported lazily, so --dry-run and --layer retrieval work with no credentials.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

EVAL_DIR = Path(__file__).resolve().parent
DAY5 = EVAL_DIR.parent
DB_PATH = DAY5 / "data" / "roastery.db"
ONTOLOGY_PATH = DAY5 / "ontology" / "ontology.yaml"
AGENT_CASES = EVAL_DIR / "agent_cases.yaml"
RAG_CASES = EVAL_DIR / "rag_cases.yaml"

VERSIONS = ("v0", "v1", "v2", "v3", "v4", "v5")
FAILURE_CLASSES = ("vocab", "entity", "tool", "params", "metric", "ungrounded",
                   "authority", "citation")

# The dataset's failure_watch vocabulary is richer than the eight reporting
# classes. Where a watched class has no reporting class of its own it is
# folded into the nearest one, and the fold is recorded in the output.
WATCH_TO_CLASS = {
    "vocabulary": "vocab",
    "vocab": "vocab",
    "entity": "entity",
    "tool": "tool",
    "loop": "tool",          # stopped gathering: the calls that were needed never happened
    "multi_hop": "tool",
    "params": "params",
    "metric": "metric",
    "currency": "metric",    # refund_exposure / cross-currency is a governed-metric rule
    "ungrounded": "ungrounded",
    "single_cause": "ungrounded",  # a merged cause is a claim the evidence does not support
    "external": "ungrounded",      # an assumed external fact is an unsupported claim
    "authority": "authority",
    "judgement": "authority",      # deciding what belongs to a named human
    "citation": "citation",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# cases and ontology (read-only)
# --------------------------------------------------------------------------


def load_cases(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def load_ontology() -> dict[str, Any]:
    return yaml.safe_load(ONTOLOGY_PATH.read_text())


def as_of() -> str:
    return str(load_ontology()["as_of_date"])


def load_env() -> None:
    """Load Day5Build/.env so the agents and the judge see the same config."""
    try:
        import dotenv

        dotenv.load_dotenv(DAY5 / ".env")
    except ImportError:
        pass


# --------------------------------------------------------------------------
# SQL (same semantics as derive_truth.py)
# --------------------------------------------------------------------------


def run_sql(sql: str, shape: str, as_of_date: str) -> Any:
    from .derive_truth import run_sql as _run

    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        return _run(con, sql, shape, as_of_date)
    finally:
        con.close()


def expect_all(truth: Any, cols: list[str]) -> list[str]:
    from .derive_truth import _expect_all

    return _expect_all(truth, cols)


def live_facts(case: dict[str, Any], as_of_date: str) -> dict[str, Any]:
    """Re-run every fact query now; the judge sees current data, not a snapshot."""
    out = {}
    for item in case.get("facts") or []:
        out[item["name"]] = (run_sql(item["sql"], item.get("shape", "scalar"), as_of_date)
                             if item.get("sql") else item.get("value"))
    return out


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------

# Numbers as written in prose. Digits glued to a hyphen or letter are part of
# an id or a date (SO-08445, PO-2022, 2026-03-16) and are not numbers here.
_NUM_RE = re.compile(
    r"(?<![\w.\-])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w\-]|\.\d)")


def fold(text: str) -> str:
    """Lower-case, strip accents, collapse whitespace -- for substring matching."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("ø", "o").replace("Ø", "o")
    return re.sub(r"\s+", " ", text).strip().lower()


def numbers_in(text: str) -> list[float]:
    """Every number written in the text; '1,250' and '1250.00' both give 1250."""
    out = []
    for m in _NUM_RE.findall(text or ""):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def has_number(text: str, target: float, tolerance: float = 0.0) -> bool:
    tol = max(float(tolerance or 0.0), 0.005)
    return any(abs(n - float(target)) <= tol for n in numbers_in(text))


def is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    try:
        float(str(value).replace(",", ""))
        return True
    except ValueError:
        return False


def contains(text: str, needle: Any, tolerance: float = 0.0) -> bool:
    """Numeric needles match as numbers; everything else as folded substrings."""
    if is_number(needle) and not re.search(r"[A-Za-z]", str(needle)):
        return has_number(text, float(str(needle).replace(",", "")), tolerance)
    return fold(str(needle)) in fold(text)


# Section references as people write them: §7.3, section 7.3, s.7.3, Appendix B
_SECTION_RE = re.compile(
    r"(?:§\s*|\bsection\s+|\bsec\.?\s*|\bs\.\s*)(\d+(?:\.\d+)*)|\b(Appendix\s+[A-Z])\b|\b(INC-\d{4}-\d+)\b",
    re.I,
)
_DOC_RE = re.compile(r"\bMR-[A-Z]{2,4}-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")


def citations_in(text: str) -> list[tuple[str, str]]:
    """(doc, section) pairs cited in the text.

    A section reference is attached to the nearest document code before it in
    the same sentence-ish span; a bare section with no code is returned with
    doc ''. An incident id is its own section of MR-OPS-PM-ARCHIVE.
    """
    out: list[tuple[str, str]] = []
    text = text or ""
    for m in _SECTION_RE.finditer(text):
        section = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        if m.group(3):
            out.append(("MR-OPS-PM-ARCHIVE", section.upper()))
            continue
        if m.group(2):
            section = "Appendix " + section.split()[-1].upper()
        window = text[max(0, m.start() - 120): m.start()]
        docs = _DOC_RE.findall(window)
        out.append((docs[-1].upper() if docs else "", section))
    for code in _DOC_RE.findall(text):
        out.append((code.upper(), ""))
    return list(dict.fromkeys(out))


def section_matches(cited: str, wanted: str) -> bool:
    """'7.3' cites 7.3; '7' does not cite 7.3; 'Appendix B' is case-insensitive."""
    return cited.strip().lower().rstrip(".") == wanted.strip().lower().rstrip(".")


# --------------------------------------------------------------------------
# running a rung
# --------------------------------------------------------------------------


@dataclass
class RungRun:
    answer: str = ""
    tool_calls: list[dict] = field(default_factory=list)       # from the recorder
    state_tool_calls: list[dict] = field(default_factory=list)  # ctx.state["_tool_calls"]
    event_function_calls: int = 0
    lanes: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    state: dict = field(default_factory=dict)
    latency_s: float = 0.0
    error: str | None = None


# invocation_id -> [{agent, name, args}]. The primary record: concurrent lanes
# each see their own copy of session state until their events are appended,
# so appends to one state list can overwrite each other. ctx.state is still
# written, as specified, and its count is reported alongside for comparison.
_RECORDER: dict[str, list[dict]] = {}


def record_tool_call(*, tool, args, tool_context):
    """before_tool_callback: log {name, args}; never alters or skips the call."""
    entry = {"name": getattr(tool, "name", str(tool)), "args": _jsonable(dict(args or {}))}
    try:
        calls = list(tool_context.state.get("_tool_calls") or [])
        calls.append(entry)
        tool_context.state["_tool_calls"] = calls  # reassign so ADK records the delta
    except Exception:
        pass
    inv = getattr(tool_context, "invocation_id", "") or ""
    _RECORDER.setdefault(inv, []).append(
        {"agent": getattr(tool_context, "agent_name", "?"), **entry})
    return None


record_tool_call.__eval_recorder__ = True


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return json.loads(json.dumps(value, default=str))


def _patch_agents(module) -> int:
    """Put the recorder first on every LlmAgent the rung module defines.

    Existing callbacks (v4/v5's dedup guard) are kept and run after it. The
    recorder returns None, so it never short-circuits them.
    """
    from google.adk.agents import LlmAgent

    seen: set[int] = set()
    patched = 0

    def walk(obj):
        nonlocal patched
        if id(obj) in seen:
            return
        seen.add(id(obj))
        if isinstance(obj, LlmAgent):
            cb = obj.before_tool_callback
            cbs = [] if cb is None else (list(cb) if isinstance(cb, list) else [cb])
            if not any(getattr(c, "__eval_recorder__", False) for c in cbs):
                obj.before_tool_callback = [record_tool_call] + cbs
                patched += 1
            for sub in obj.sub_agents or []:
                walk(sub)
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v)

    for value in list(vars(module).values()):
        walk(value)
    return patched


_LOADED: dict[str, Any] = {}


def load_rung(version: str):
    """Import vNAgent.agent once, patch its agents, return (module, patched_count)."""
    if version in _LOADED:
        return _LOADED[version]
    load_env()
    if str(DAY5) not in sys.path:
        sys.path.insert(0, str(DAY5))
    module = importlib.import_module(f"{version}Agent.agent")
    patched = _patch_agents(module)
    _LOADED[version] = (module, patched)
    return _LOADED[version]


def _text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    parts = getattr(value, "parts", None)
    if parts is not None:
        return "".join(getattr(p, "text", "") or "" for p in parts)
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value)


async def _run_async(version: str, question: str, timeout_s: float) -> RungRun:
    from google.adk.agents import LlmAgent
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    module, _ = load_rung(version)
    root = module.root_agent
    runner = (InMemoryRunner(agent=root, app_name=f"eval_{version}")
              if isinstance(root, LlmAgent)
              else InMemoryRunner(node=root, app_name=f"eval_{version}"))
    session = await runner.session_service.create_session(
        app_name=f"eval_{version}", user_id="eval")

    run = RungRun()
    last_output = ""
    last_final_text = ""
    invocation_ids: set[str] = set()
    start = time.monotonic()

    async def consume():
        nonlocal last_output, last_final_text
        message = types.Content(role="user", parts=[types.Part(text=question)])
        async for ev in runner.run_async(user_id="eval", session_id=session.id,
                                         new_message=message):
            invocation_ids.add(ev.invocation_id)
            if ev.author and ev.author not in run.authors:
                run.authors.append(ev.author)
            parts = (ev.content.parts if ev.content and ev.content.parts else [])
            run.event_function_calls += sum(1 for p in parts if p.function_call)
            if getattr(ev, "output", None) is not None and _text_of(ev.output).strip():
                last_output = _text_of(ev.output)
            text = "".join(p.text or "" for p in parts
                           if p.text and not getattr(p, "thought", False))
            if text.strip() and ev.is_final_response():
                last_final_text = text

    try:
        await asyncio.wait_for(consume(), timeout=timeout_s)
    except asyncio.TimeoutError:
        run.error = f"timeout after {timeout_s:.0f}s"
    except Exception as exc:  # a crashed rung is a result, not a harness failure
        run.error = f"{type(exc).__name__}: {exc}"
    run.latency_s = round(time.monotonic() - start, 2)

    final = await runner.session_service.get_session(
        app_name=f"eval_{version}", user_id="eval", session_id=session.id)
    state = dict(final.state) if final else {}
    run.state = {k: v for k, v in state.items() if not k.startswith("_")}
    run.state_tool_calls = list(state.get("_tool_calls") or [])
    run.lanes = list(state.get("lanes") or [])
    run.answer = last_output or last_final_text or _text_of(state.get("answer"))
    for inv in invocation_ids:
        run.tool_calls.extend(_RECORDER.pop(inv, []))
    return run


async def run_rung(version: str, question: str, timeout_s: float = 600.0) -> RungRun:
    """Run one question through a rung. Call every case from ONE event loop:
    model clients created under one asyncio.run do not survive into the next."""
    return await _run_async(version, question, timeout_s)


# --------------------------------------------------------------------------
# vocabulary evidence from tool calls
# --------------------------------------------------------------------------


def _key(value: str) -> str:
    return re.sub(r"[\s\-]+", "_", str(value).strip().lower())


def vocab_index() -> tuple[dict[tuple[str, str], dict], dict[str, dict]]:
    """(tool, param) -> vocabulary, and column name -> vocabulary.

    Each vocabulary is {"name", "values": set, "synonyms": set}. The column
    map lets raw SQL (v0's only tool) be checked too: a literal compared with
    a vocabulary column must be one of its values.
    """
    onto = load_ontology()
    vocabs = {}
    for name, v in (onto.get("vocabularies") or {}).items():
        vocabs[name] = {"name": name, "column": v.get("column", ""),
                        "values": {_key(x) for x in v.get("values") or []},
                        "synonyms": {_key(x) for x in (v.get("synonyms") or {})}}
    by_param = {}
    for tool, spec in (onto.get("tools") or {}).items():
        for pname, pspec in ((spec or {}).get("params") or {}).items():
            src = str((pspec or {}).get("from", ""))
            if src.startswith("vocabularies."):
                vname = src.split(".", 1)[1]
                if vname in vocabs:
                    by_param[(tool, pname)] = vocabs[vname]
    by_column: dict[str, dict] = {}
    for v in vocabs.values():
        col = v["column"].split(".")[-1]
        if col:
            merged = by_column.setdefault(col, {"name": col, "values": set(), "synonyms": set()})
            merged["values"] |= v["values"]
            merged["synonyms"] |= v["synonyms"]
    return by_param, by_column


_SQL_LITERAL_RE = re.compile(
    r"\b([a-z_]+)\s*(?:=|!=|<>|\bIN\b|\bLIKE\b)\s*\(?\s*((?:'[^']*'\s*,?\s*)+)\)?", re.I)


def vocab_evidence(tool_calls: list[dict]) -> list[dict]:
    """Parameter values outside their vocabulary, from the recorded calls.

    kind 'vocab'  -- a spoken synonym passed as if it were a value ("dispatched")
    kind 'params' -- a value in no vocabulary at all ("backordered")
    """
    by_param, by_column = vocab_index()
    found = []
    for call in tool_calls:
        name, args = call.get("name", ""), call.get("args") or {}
        for pname, value in args.items():
            vocab = by_param.get((name, pname))
            if vocab is None or value in (None, ""):
                continue
            for v in (value if isinstance(value, list) else [value]):
                k = _key(v)
                if k not in vocab["values"]:
                    found.append({"tool": name, "param": pname, "value": v,
                                  "kind": "vocab" if k in vocab["synonyms"] else "params"})
        for pname, value in args.items():
            if not isinstance(value, str) or "select" not in value.lower():
                continue
            for col, literals in _SQL_LITERAL_RE.findall(value):
                vocab = by_column.get(col.lower())
                if vocab is None:
                    continue
                for lit in re.findall(r"'([^']*)'", literals):
                    k = _key(lit.strip("%"))
                    if k and k not in vocab["values"]:
                        found.append({"tool": name, "param": f"sql:{col}", "value": lit,
                                      "kind": "vocab" if k in vocab["synonyms"] else "params"})
    return found


# Phrases that claim money moved or a decision was taken. The system may
# propose, never act.
ACTION_CLAIMS = [re.compile(p, re.I) for p in (
    r"\bI\s*(?:have|'ve)\s+(?:issued|processed|applied|approved|credited|refunded)\b",
    r"\b(?:credit|refund|goodwill)\s+(?:has|have)\s+been\s+(?:issued|applied|processed|approved|made)\b",
    r"\bhas\s+been\s+(?:credited|refunded)\b",
)]


def authority_evidence(answer: str, state: dict) -> list[str]:
    out = [f"answer claims an action: {m.group(0)!r}"
           for p in ACTION_CLAIMS for m in [p.search(answer or "")] if m]
    proposal = state.get("proposal") or {}
    if isinstance(proposal, dict) and str(proposal.get("approved_by", "")).strip():
        out.append(f"proposal recorded with approved_by={proposal['approved_by']!r}")
    return out


# --------------------------------------------------------------------------
# judge
# --------------------------------------------------------------------------

JUDGE_SYSTEM = """You grade one assertion about an AI agent's answer to a business
question. You are given the question, the answer, reference evidence (database
facts and document quotes), and ONE assertion.

Decide only whether THIS assertion holds for the answer. Use the reference
evidence to check facts; do not reward an answer for being long, confident or
polite, and do not penalise it for anything outside this assertion. If the
assertion refers to facts.<name>, that name is a key in the reference facts.

Reply with JSON only: {"verdict": "pass" | "fail", "reason": "<one or two sentences>"}"""

JUDGE_MODEL_DEFAULT = "gemini-3.5-flash"


def judge_model() -> str:
    return os.environ.get("EVAL_JUDGE_MODEL", JUDGE_MODEL_DEFAULT)


_judge_client = None


def _client():
    global _judge_client
    if _judge_client is None:
        load_env()
        from google import genai

        if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").upper() in ("1", "TRUE"):
            _judge_client = genai.Client(
                vertexai=True,
                project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                location=os.environ.get("GOOGLE_CLOUD_LOCATION") or "us-central1",
            )
        else:
            _judge_client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    return _judge_client


def judge(question: str, answer: str, assertion: str, evidence: dict[str, Any],
          retries: int = 2) -> dict[str, str]:
    """One judge call for one assertion. Returns {verdict, reason}.

    A judge that cannot be reached returns verdict 'error' -- never 'fail',
    because an unmeasured assertion is not a failed one.
    """
    from google.genai import types

    prompt = (
        f"QUESTION:\n{question}\n\nANSWER:\n{answer or '(empty answer)'}\n\n"
        f"REFERENCE EVIDENCE (JSON):\n{json.dumps(evidence, default=str, indent=1)[:12000]}\n\n"
        f"ASSERTION:\n{assertion}"
    )
    schema = {
        "type": "OBJECT",
        "properties": {"verdict": {"type": "STRING", "enum": ["pass", "fail"]},
                       "reason": {"type": "STRING"}},
        "required": ["verdict", "reason"],
    }
    last_err = ""
    for attempt in range(retries + 1):
        try:
            resp = _client().models.generate_content(
                model=judge_model(),
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=JUDGE_SYSTEM, temperature=0.0,
                    response_mime_type="application/json", response_schema=schema),
            )
            data = json.loads(resp.text)
            verdict = str(data.get("verdict", "")).lower()
            if verdict in ("pass", "fail"):
                return {"verdict": verdict, "reason": str(data.get("reason", ""))[:600]}
            last_err = f"bad verdict {data!r}"
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            time.sleep(1.5 * (attempt + 1))
    return {"verdict": "error", "reason": f"judge unavailable: {last_err[:300]}"}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str, ensure_ascii=False))
