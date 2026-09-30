"""Score V5's document layer against eval/rag_cases.yaml, in three layers.

    python -m eval.run_rag_eval                        # all three, reported separately
    python -m eval.run_rag_eval --layer retrieval      # NO LLM; seconds; run it live
    python -m eval.run_rag_eval --layer generation     # passages supplied, retriever bypassed
    python -m eval.run_rag_eval --layer e2e            # the full V5 workflow

Retrieval and generation fail differently and are fixed differently, so the
layers are never blended into one score. Each layer writes its own section of
eval/results_rag.json; running one layer leaves the others' last results in
place, stamped with when they ran.

  retrieval   recall@k, precision@k, MRR, and superseded_leakage: any
              must_not_retrieve passage (or any passage flagged superseded)
              in the results is a HARD FAIL for that case, not a deduction.
  generation  the must_retrieve passages (and, where requires_db, the database
              facts) are handed to the model directly. Scores: value correct,
              citation present, citation accurate, conditions complete,
              faithfulness.
  e2e         V5 end to end. Adds routing_correct (did the policy lane fire
              when requires_docs is non-empty) and, where requires_db,
              synthesis (was the rule APPLIED to the fact, or were both merely
              reported side by side -- which fails).

Adversarial cases (scoring: pass_fail) get one PASS/FAIL per layer and are
kept out of every average.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import re
import sys
import time
from typing import Any

from .common import (
    DAY5, EVAL_DIR, RAG_CASES, as_of, citations_in, contains, has_number,
    is_number, judge, judge_model, live_facts, load_cases, load_env, now_iso,
    run_rung, run_sql, section_matches, write_json,
)

RESULTS = EVAL_DIR / "results_rag.json"
KNOWLEDGE_PY = DAY5 / "v5Agent" / "tools" / "knowledge.py"
PROMPTS_PY = DAY5 / "v5Agent" / "prompts.py"
AGENT_PY = DAY5 / "v5Agent" / "agent.py"
LAYERS = ("retrieval", "generation", "e2e")


# --------------------------------------------------------------------------
# loading V5 pieces without importing the V5 package
# --------------------------------------------------------------------------
# v5Agent/__init__.py imports the whole agent (and its telemetry). The
# retrieval layer must run with no credentials, so the two plain modules it
# needs are loaded from their files instead.


def _load_file(name: str, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_knowledge = None


def knowledge():
    global _knowledge
    if _knowledge is None:
        _knowledge = _load_file("_eval_v5_knowledge", KNOWLEDGE_PY)
    return _knowledge


def v5_model() -> str:
    m = re.search(r'^MODEL\s*=\s*"([^"]+)"', AGENT_PY.read_text(), re.M)
    return m.group(1) if m else "gemini-3.5-flash"


def retrieval_mode(force_keyword: bool) -> str:
    """'hybrid' if query embedding works here, else 'keyword_only'.

    Keyword-only is what the tool itself falls back to without credentials,
    so the numbers are real -- but they are not the numbers V5 gets live.
    """
    k = knowledge()
    if force_keyword or not k._index().get("embed_model"):
        k._embed_query = lambda query: []
        return "keyword_only"
    load_env()
    if k._embed_query("probe"):
        return "hybrid"
    k._embed_query = lambda query: []  # skip a failing call per query
    return "keyword_only"


def _key(doc: str, section: str) -> tuple[str, str]:
    return (doc.strip().upper(), section.strip().lstrip("§").rstrip(".").lower())


def _show(key: tuple[str, str]) -> str:
    """A comparison key back in the documents' own spelling."""
    doc, sec = key
    if sec.startswith("inc-"):
        sec = sec.upper()
    elif sec.startswith("appendix"):
        sec = "Appendix " + sec.split()[-1].upper()
    return f"{doc} §{sec}"


def _refs(items: list[dict]) -> set[tuple[str, str]]:
    return {_key(r["doc"], str(r["section"])) for r in items or []}


def _sources(case: dict) -> list[dict]:
    out = [case["source"]] if isinstance(case.get("source"), dict) else []
    return out + list(case.get("sources") or [])


# --------------------------------------------------------------------------
# layer 1: retrieval (no LLM)
# --------------------------------------------------------------------------


def layer_retrieval(cases: list[dict], k: int, force_keyword: bool) -> dict[str, Any]:
    mode = retrieval_mode(force_keyword)
    kn = knowledge()
    rows = []
    for case in cases:
        t0 = time.monotonic()
        hits = kn.search_policy_documents(case["q"], top_k=k)
        latency = round(time.monotonic() - t0, 3)
        if hits and "error" in hits[0]:
            rows.append({"id": case["id"], "error": hits[0]["error"]})
            print(f"  {case['id']}  ERROR {hits[0]['error'][:80]}")
            continue
        ranked = [(_key(h["doc_id"], h["section"]), bool(h.get("superseded"))) for h in hits]
        relevant = _refs(case.get("must_retrieve"))
        forbidden = _refs(case.get("must_not_retrieve"))

        found = {key for key, _ in ranked} & relevant
        first = next((i + 1 for i, (key, _) in enumerate(ranked) if key in relevant), None)
        leaked = sorted({_show((d, s)) for (d, s), sup in ranked if (d, s) in forbidden or sup})
        scorable = bool(relevant)
        row = {
            "id": case["id"], "category": case["category"], "k": k,
            "retrieved": [_show((d, s)) + (" [superseded]" if sup else "") for (d, s), sup in ranked],
            "must_retrieve": sorted(_show((d, s)) for d, s in relevant),
            "missed": sorted(_show((d, s)) for d, s in relevant - found),
            "recall_at_k": round(len(found) / len(relevant), 3) if scorable else None,
            "precision_at_k": round(sum(1 for key, _ in ranked if key in relevant) / k, 3) if scorable else None,
            "mrr": round(1 / first, 3) if (scorable and first) else (0.0 if scorable else None),
            "superseded_leakage": leaked,
            "hard_fail": bool(leaked),
            "latency_s": latency,
        }
        rows.append(row)
        status = "HARD FAIL (leak)" if row["hard_fail"] else "ok"
        metrics = (f"R@{k}={row['recall_at_k']:.2f} P@{k}={row['precision_at_k']:.2f} "
                   f"MRR={row['mrr']:.2f}") if scorable else "no must_retrieve (not scored)"
        print(f"  {case['id']}  {metrics:<34} {status}"
              + (f"  leaked: {', '.join(leaked)}" if leaked else "")
              + (f"  missed: {', '.join(row['missed'])}" if row["missed"] else ""))

    scored = [r for r in rows if r.get("recall_at_k") is not None]
    mean = lambda key: round(sum(r[key] for r in scored) / len(scored), 3) if scored else None
    return {
        "ran_at": now_iso(), "mode": mode, "k": k, "llm_calls": 0,
        "mode_note": ("keyword_only: query embedding unavailable here; V5 live uses hybrid "
                      "scoring, so these numbers can differ from production") if mode == "keyword_only" else "",
        "summary": {
            f"recall_at_{k}": mean("recall_at_k"), f"precision_at_{k}": mean("precision_at_k"),
            "mrr": mean("mrr"), "scored_cases": len(scored),
            "hard_fails": [r["id"] for r in rows if r.get("hard_fail")],
            "errors": [r["id"] for r in rows if r.get("error")],
        },
        "cases": rows,
    }


# --------------------------------------------------------------------------
# shared answer scoring for generation and e2e
# --------------------------------------------------------------------------


def _truth(case: dict, when: str) -> Any:
    if case.get("truth_sql"):
        return run_sql(case["truth_sql"], case.get("truth_shape", "scalar"), when)
    return case.get("truth")


def _numeric_targets(truth: Any) -> list[float] | None:
    """Numbers that ARE the answer, when the truth is numeric; else None."""
    if is_number(truth) and not isinstance(truth, str):
        return [float(truth)]
    if isinstance(truth, dict) and truth and all(is_number(v) and not isinstance(v, str) for v in truth.values()):
        return [float(v) for v in truth.values()]
    return None


def value_check(case: dict, answer: str, truth: Any, evidence: dict) -> dict:
    """Deterministic when the truth is a number; judged when it is prose."""
    targets = _numeric_targets(truth)
    if targets is not None:
        ok = all(has_number(answer, t) for t in targets)
        naive_hit = [n.get("value") for n in case.get("naive") or []
                     if is_number(n.get("value")) and not isinstance(n.get("value"), str)
                     and float(n["value"]) not in targets and has_number(answer, float(n["value"]))]
        return {"basis": "deterministic", "passed": ok,
                "detail": f"want {targets}" + (f"; naive values present {naive_hit}" if naive_hit else "")}
    v = judge(case["q"], answer,
              "The answer's conclusion agrees with the reference answer in substance "
              "(same outcome and same key figures); wording may differ.",
              {**evidence, "reference_answer": truth})
    return {"basis": "judged", "passed": v["verdict"] == "pass" if v["verdict"] != "error" else None,
            "verdict": v["verdict"], "reason": v["reason"]}


def citation_checks(case: dict, answer: str, corpus: set[tuple[str, str]],
                    allowed: set[tuple[str, str]]) -> dict:
    """citation_present / citation_accurate, both by rule.

    present   -- at least one document code with a section is cited.
    accurate  -- every cited (doc, section) exists in the corpus, none is a
                 must_not_retrieve passage, none falls outside `allowed` (the
                 passages the answer could legitimately rest on), and at least
                 one is a source or must_retrieve passage of the case.
    """
    cited = [(d, s) for d, s in citations_in(answer) if d and s]
    keys = {_key(d, s) for d, s in cited}
    targets = _refs(_sources(case)) | _refs(case.get("must_retrieve"))
    forbidden = _refs(case.get("must_not_retrieve"))
    present = bool(keys)
    if not present:
        return {"citation_present": False, "citation_accurate": None, "cited": []}
    bad = sorted(_show((d, s)) for d, s in keys if (d, s) not in corpus)
    banned = sorted(_show((d, s)) for d, s in keys & forbidden)
    outside = sorted(_show((d, s)) for d, s in keys - allowed - forbidden if (d, s) in corpus)
    hit = bool(keys & targets) or not targets
    accurate = not bad and not banned and not outside and hit
    return {"citation_present": True, "citation_accurate": accurate,
            "cited": sorted(_show((d, s)) for d, s in keys),
            "nonexistent": bad, "forbidden_cited": banned, "outside_allowed": outside,
            "cites_a_case_source": bool(keys & targets)}


def judged_assertions(case: dict, answer: str, evidence: dict) -> dict | None:
    items = list(case.get("assertions") or [])
    if not items:
        return None
    rows = [{"assertion": a, **judge(case["q"], answer, a, evidence)} for a in items]
    fails = sum(r["verdict"] == "fail" for r in rows)
    errors = sum(r["verdict"] == "error" for r in rows)
    return {"judged": True, "assertions": rows, "passed": sum(r["verdict"] == "pass" for r in rows),
            "total": len(rows), "verdict": "fail" if fails else ("unscored" if errors else "pass")}


def adversarial_verdict(case: dict, answer: str, evidence: dict, value: dict | None) -> dict:
    """Single PASS/FAIL. A deterministic naive hit fails outright; otherwise judged."""
    if value and value.get("basis") == "deterministic" and value["passed"] is False:
        return {"verdict": "fail", "basis": "deterministic", "reason": value["detail"]}
    v = judge(case["q"], answer,
              f"PASS when: {case.get('pass_when', '').strip()}  FAIL when: {case.get('fail_when', '').strip()}  "
              "Answer 'pass' only if the PASS condition holds and no FAIL condition does.",
              evidence)
    return {"verdict": v["verdict"] if v["verdict"] != "error" else "unscored",
            "basis": "judged", "reason": v["reason"]}


def corpus_sections() -> set[tuple[str, str]]:
    return {_key(c["doc_id"], c["section"]) for c in knowledge()._chunks() if c["section"]}


# --------------------------------------------------------------------------
# layer 2: generation (retriever bypassed)
# --------------------------------------------------------------------------

GENERATION_NOTE = """

## Retrieval has already been done for you
The passages below are the complete result of retrieval for this question.
You cannot call any tool. Answer from these passages (and the database facts,
if any are given) only, following every rule above, including citation.
"""


def _passages(case: dict) -> list[dict]:
    kn = knowledge()
    out = []
    for ref in case.get("must_retrieve") or []:
        sec = kn.get_document_section(ref["doc"], str(ref["section"]))
        if "error" not in sec:
            out.append(sec)
    return out


def _cite(sec: dict) -> str:
    version = f" v{sec['doc_version']}" if sec.get("doc_version") else ""
    return f"{sec['doc_id']}{version} §{sec['section']}, p.{sec['page']}"


def _generate(system: str, user: str, model: str) -> tuple[str, str | None]:
    from google.genai import types

    from .common import _client
    try:
        resp = _client().models.generate_content(
            model=model, contents=user,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0.0))
        return resp.text or "", None
    except Exception as exc:
        return "", f"{type(exc).__name__}: {exc}"


def layer_generation(cases: list[dict], when: str) -> dict[str, Any]:
    load_env()
    prompts = _load_file("_eval_v5_prompts", PROMPTS_PY)
    system = prompts.POLICY_INSTRUCTION + GENERATION_NOTE
    model = v5_model()
    corpus = corpus_sections()
    rows = []
    for case in cases:
        passages = _passages(case)
        facts = live_facts(case, when) if case.get("requires_db") else {}
        block = "\n\n".join(f"[{_cite(p)}] {p['section_title']}\n{p['text']}" for p in passages) \
            or "(no passages were retrieved)"
        user = f"QUESTION:\n{case['q']}\n\nPASSAGES:\n{block}"
        if facts:
            user += "\n\nDATABASE FACTS (from the operational database):\n" + json.dumps(facts, default=str, indent=1)
        t0 = time.monotonic()
        answer, err = _generate(system, user, model)
        latency = round(time.monotonic() - t0, 2)
        evidence = {"supplied_passages": [{"cite": _cite(p), "text": p["text"]} for p in passages],
                    "database_facts": facts}
        truth = _truth(case, when)
        allowed = {_key(p["doc_id"], p["section"]) for p in passages}
        row: dict[str, Any] = {"id": case["id"], "category": case["category"],
                               "scoring": case.get("scoring"), "answer": answer, "error": err,
                               "latency_s": latency, "supplied": [_cite(p) for p in passages]}
        if err:
            rows.append(row)
            print(f"  {case['id']}  ERROR {err[:90]}")
            continue
        value = value_check(case, answer, truth, evidence)
        cites = citation_checks(case, answer, corpus, allowed)
        faith = judge(case["q"], answer,
                      "Faithfulness: every factual claim in the answer is supported by the supplied "
                      "passages or database facts. Fail if the answer asserts anything absent from them.",
                      evidence)
        row.update({"value": value, **{k: cites[k] for k in ("citation_present", "citation_accurate")},
                    "citation_detail": cites,
                    "faithfulness": {"judged": True, **faith}})
        if case.get("scoring") == "pass_fail":
            row["adversarial"] = adversarial_verdict(case, answer, evidence, value)
        else:
            row["conditions"] = judged_assertions(case, answer, evidence)
        rows.append(row)
        print(_line(row, ("value", "citation_present", "citation_accurate", "conditions", "faithfulness")))
    return {"ran_at": now_iso(), "model": model, "judge_model": judge_model(),
            "summary": _summary(rows, ("value", "citation_present", "citation_accurate",
                                       "conditions", "faithfulness")),
            "cases": rows}


# --------------------------------------------------------------------------
# layer 3: end to end
# --------------------------------------------------------------------------

POLICY_TOOLS = {"search_policy_documents", "get_document_section"}

SYNTHESIS_ASSERTION = (
    "Synthesis: the answer APPLIES the rule to the database fact -- it reaches a conclusion "
    "that depends on both (e.g. computes the variance and compares it to the tolerance, or "
    "decides the clause applies to this customer). Reporting the rule and the fact side by "
    "side without drawing the conclusion is a FAIL."
)


def _replayed_retrieval(tool_calls: list[dict]) -> list[tuple[str, str]]:
    """Re-issue the agent's own retrieval calls to see what it was shown.

    search_policy_documents is a pure function of its arguments and the
    index, so replaying the recorded arguments reproduces the results
    (up to embedding nondeterminism, which is why this is labelled replayed).
    """
    kn = knowledge()
    seen: list[tuple[str, str]] = []
    for call in tool_calls:
        args = call.get("args") or {}
        try:
            if call.get("name") == "search_policy_documents":
                for h in kn.search_policy_documents(**args):
                    if "error" not in h:
                        seen.append(_key(h["doc_id"], h["section"]))
            elif call.get("name") == "get_document_section":
                sec = kn.get_document_section(**args)
                if "error" not in sec:
                    seen.append(_key(sec["doc_id"], sec["section"]))
        except TypeError:
            continue
    return list(dict.fromkeys(seen))


def layer_e2e(cases: list[dict], when: str, timeout_s: float) -> dict[str, Any]:
    load_env()
    retrieval_mode(False)  # replay with whatever scoring this machine can do
    corpus = corpus_sections()

    async def run_all() -> list[dict]:
        rows = []
        for case in cases:
            run = await run_rung("v5", case["q"], timeout_s)
            answer = run.answer or ""
            policy_calls = [c for c in run.tool_calls if c["name"] in POLICY_TOOLS]
            fired = "policy" in run.lanes or bool(policy_calls) or "policy" in run.authors
            shown = _replayed_retrieval(run.tool_calls)
            relevant, forbidden = _refs(case.get("must_retrieve")), _refs(case.get("must_not_retrieve"))
            facts = live_facts(case, when)
            evidence = {"database_facts": facts,
                        "document_quotes": [{k: s.get(k) for k in ("doc", "section", "page", "quote")}
                                            for s in _sources(case)]}
            truth = _truth(case, when)
            row: dict[str, Any] = {
                "id": case["id"], "category": case["category"], "scoring": case.get("scoring"),
                "answer": answer, "error": run.error, "latency_s": run.latency_s,
                "lanes": run.lanes, "tool_call_count": len(run.tool_calls),
                "policy_tool_calls": len(policy_calls),
                "routing_correct": (fired if case.get("requires_docs") else None),
                "retrieval_replayed": {
                    "shown": [_show((d, s)) for d, s in shown],
                    "recall": round(len(set(shown) & relevant) / len(relevant), 3) if relevant else None,
                    "forbidden_shown": sorted(_show((d, s)) for d, s in set(shown) & forbidden),
                },
            }
            if not answer:
                rows.append(row)
                print(f"  {case['id']}  NO ANSWER {run.error or ''}")
                continue
            value = value_check(case, answer, truth, evidence)
            allowed = set(shown) | relevant | _refs(_sources(case))
            cites = citation_checks(case, answer, corpus, allowed)
            row.update({"value": value,
                        **{k: cites[k] for k in ("citation_present", "citation_accurate")},
                        "citation_detail": cites})
            if case.get("requires_db"):
                s = judge(case["q"], answer, SYNTHESIS_ASSERTION, evidence)
                row["synthesis"] = {"judged": True, **s}
            if case.get("scoring") == "pass_fail":
                row["adversarial"] = adversarial_verdict(case, answer, evidence, value)
            else:
                row["conditions"] = judged_assertions(case, answer, evidence)
            rows.append(row)
            print(_line(row, ("routing_correct", "value", "citation_present", "citation_accurate",
                              "synthesis", "conditions")))
        return rows

    rows = asyncio.run(run_all())
    summary = _summary(rows, ("routing_correct", "value", "citation_present", "citation_accurate",
                              "synthesis", "conditions"))
    rec = [r["retrieval_replayed"]["recall"] for r in rows
           if r.get("retrieval_replayed", {}).get("recall") is not None]
    summary["retrieval_replayed_recall"] = round(sum(rec) / len(rec), 3) if rec else None
    summary["latency_s_total"] = round(sum(r["latency_s"] or 0 for r in rows), 1)
    return {"ran_at": now_iso(), "judge_model": judge_model(), "summary": summary, "cases": rows}


# --------------------------------------------------------------------------
# summaries and printing
# --------------------------------------------------------------------------


def _outcome(row: dict, metric: str) -> tuple[str, bool | None]:
    """(basis, passed) for one metric on one row; passed None = not applicable/unscored."""
    v = row.get(metric)
    if v is None:
        return ("n/a", None)
    if isinstance(v, bool):
        return ("deterministic", v)
    if metric == "value":
        return (v["basis"], v["passed"])
    verdict = v.get("verdict")
    return ("judged", None if verdict in ("error", "unscored") else verdict == "pass")


def _summary(rows: list[dict], metrics: tuple[str, ...]) -> dict[str, Any]:
    """Per metric, deterministic and judged counts kept apart. Adversarial excluded."""
    scored = [r for r in rows if r.get("scoring") != "pass_fail" and not r.get("error")]
    out: dict[str, Any] = {}
    for m in metrics:
        buckets: dict[str, list[bool]] = {}
        for r in scored:
            basis, ok = _outcome(r, m)
            if ok is not None:
                buckets.setdefault(basis, []).append(ok)
        out[m] = {basis: {"passed": sum(v), "of": len(v)} for basis, v in buckets.items()}
    adv = [r for r in rows if r.get("scoring") == "pass_fail"]
    out["adversarial"] = {r["id"]: (r.get("adversarial") or {}).get("verdict", "no answer") for r in adv}
    out["adversarial_failures"] = [i for i, v in out["adversarial"].items() if v != "pass"]
    out["errors"] = [r["id"] for r in rows if r.get("error")]
    return out


def _line(row: dict, metrics: tuple[str, ...]) -> str:
    bits = []
    for m in metrics:
        basis, ok = _outcome(row, m)
        if basis == "n/a":
            continue
        mark = "-" if ok is None else ("ok" if ok else "FAIL")
        bits.append(f"{m}={mark}{'(j)' if basis == 'judged' else ''}")
    if "adversarial" in row:
        bits.append(f"ADVERSARIAL={row['adversarial']['verdict'].upper()}"
                    f"{'(j)' if row['adversarial']['basis'] == 'judged' else ''}")
    return f"  {row['id']}  " + "  ".join(bits)


def print_summary(layer: str, result: dict) -> None:
    s = result["summary"]
    print(f"\n== {layer} ==  (ran {result['ran_at']})")
    if layer == "retrieval":
        k = result["k"]
        print(f"  mode: {result['mode']}  {result.get('mode_note', '')}")
        print(f"  recall@{k}={s[f'recall_at_{k}']}  precision@{k}={s[f'precision_at_{k}']}  "
              f"MRR={s['mrr']}  over {s['scored_cases']} cases")
        print(f"  superseded_leakage HARD FAILS: {s['hard_fails'] or 'none'}")
        return
    for m, buckets in s.items():
        if isinstance(buckets, dict) and m not in ("adversarial",):
            parts = [f"{b}: {v['passed']}/{v['of']}" for b, v in buckets.items()]
            if parts:
                print(f"  {m:<18} " + "   ".join(parts))
    print(f"  adversarial (pass/fail, not averaged): {s['adversarial']}")
    if s.get("retrieval_replayed_recall") is not None:
        print(f"  retrieval recall inside e2e (replayed): {s['retrieval_replayed_recall']}")
    print("  (judged) = model opinion, reported apart from deterministic checks")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Score V5 against rag_cases.yaml, layer by layer")
    ap.add_argument("--layer", choices=LAYERS + ("all",), default="all")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--cases", help="comma-separated case ids")
    ap.add_argument("--keyword-only", action="store_true",
                    help="retrieval: force keyword scoring even if embedding works")
    ap.add_argument("--timeout", type=float, default=600.0)
    args = ap.parse_args()

    cases = load_cases(RAG_CASES)["cases"]
    if args.cases:
        ids = {i.strip() for i in args.cases.split(",")}
        cases = [c for c in cases if c["id"] in ids]
    when = as_of()
    layers = LAYERS if args.layer == "all" else (args.layer,)

    payload = json.loads(RESULTS.read_text()) if RESULTS.exists() else {"kind": "rag", "version": "v5", "layers": {}}
    for layer in layers:
        print(f"\n### layer: {layer}  ({len(cases)} cases)")
        if layer == "retrieval":
            result = layer_retrieval(cases, args.k, args.keyword_only)
        elif layer == "generation":
            result = layer_generation(cases, when)
        else:
            result = layer_e2e(cases, when, args.timeout)
        result["filters"] = {"cases": args.cases}
        payload["layers"][layer] = result
        write_json(RESULTS, payload)  # after each layer, so a later crash keeps it

    for layer in layers:
        print_summary(layer, payload["layers"][layer])
    print(f"\nwrote {RESULTS.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
