"""Score one rung of the agent ladder against eval/agent_cases.yaml.

    python -m eval.run_agent_eval --version v2
    python -m eval.run_agent_eval --version v2 --only A,B     # deterministic tiers only
    python -m eval.run_agent_eval --version v2 --cases A01,C03
    python -m eval.run_agent_eval --dry-run                   # no LLM, no rung import
    python -m eval.run_agent_eval --version v2 --sample-judged   # spot-check an existing run

Per case: run the rung and capture the final answer and every tool call;
score Tier A/B deterministically (truth_sql re-run now; value + citation by
rule); score Tier C with one judge call PER ASSERTION; attribute failures to
the eight reporting classes with the evidence for each.

Deterministic and judged results are kept apart everywhere -- per case, in
the tallies and in the JSON. A judged verdict is an opinion from a model and
is labelled as one.

Output: eval/results_{version}.json (eval/results_dryrun.json for --dry-run).
The case file is read, never written.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections import Counter
from typing import Any

from .common import (
    AGENT_CASES, EVAL_DIR, FAILURE_CLASSES, VERSIONS, WATCH_TO_CLASS, as_of,
    authority_evidence, citations_in, contains, expect_all, fold, has_number,
    is_number, judge, judge_model, live_facts, load_cases, now_iso, numbers_in,
    run_rung, run_sql, section_matches, vocab_evidence, write_json,
)

DETERMINISTIC_CHECKS = {"answer_contains_number", "answer_contains_all",
                        "answer_excludes_naive", "citation_matches_source"}


# --------------------------------------------------------------------------
# deterministic scoring
# --------------------------------------------------------------------------


def _checks(case: dict) -> list[str]:
    c = case.get("check") or []
    return [c] if isinstance(c, str) else list(c)


def _sources(case: dict) -> list[dict]:
    out = [case["source"]] if isinstance(case.get("source"), dict) else []
    return out + list(case.get("sources") or [])


def _number_targets(case: dict, truth: Any) -> list[float]:
    field = case.get("score_field")
    if isinstance(truth, list):
        return [float(r[field]) for r in truth if isinstance(r, dict) and field in r
                and is_number(r[field])] if field else [float(x) for x in truth if is_number(x)]
    if isinstance(truth, dict):
        return [float(truth[field])] if field and is_number(truth.get(field)) else []
    return [float(truth)] if is_number(truth) else []


def _all_numbers(value: Any) -> set[float]:
    if isinstance(value, dict):
        return set().union(*[_all_numbers(v) for v in value.values()]) if value else set()
    if isinstance(value, list):
        return set().union(*[_all_numbers(v) for v in value]) if value else set()
    return {float(value)} if is_number(value) and not isinstance(value, str) else set()


def live_truth(case: dict, when: str) -> dict[str, Any]:
    """Re-run truth_sql and every naive/alt query now. Report drift; never fix it."""
    out: dict[str, Any] = {"truth": case.get("truth"), "naive": [], "alt": [], "drift": []}
    if case.get("truth_sql"):
        out["truth"] = run_sql(case["truth_sql"], case.get("truth_shape", "scalar"), when)
        if out["truth"] != case.get("truth"):
            out["drift"].append("truth")
    for group in ("naive", "alt"):
        for item in case.get(group) or []:
            value = (run_sql(item["sql"], item.get("shape", "scalar"), when)
                     if item.get("sql") else item.get("value"))
            if item.get("sql") and value != item.get("value"):
                out["drift"].append(f"{group}:{item.get('label')}")
            out[group].append({"label": item.get("label"), "value": value})
    return out


def score_deterministic(case: dict, answer: str, lt: dict[str, Any]) -> dict | None:
    """Rule-based checks. None when the case has none (pure Tier C)."""
    wanted = [c for c in _checks(case) if c in DETERMINISTIC_CHECKS]
    if not wanted:
        return None
    truth, tol = lt["truth"], case.get("tolerance") or 0.0
    results = []
    notes = []

    for check in wanted:
        if check == "answer_contains_number":
            targets = _number_targets(case, truth)
            ok = bool(targets) and all(has_number(answer, t, tol) for t in targets)
            detail = f"want {targets} (tol {tol})"
            if not ok:
                for alt in lt["alt"]:
                    alt_targets = _number_targets(case, alt["value"])
                    if alt_targets and all(has_number(answer, t, tol) for t in alt_targets):
                        ok, detail = True, f"matched alternative reading: {alt['label']}"
                        notes.append("alt_reading")
                        break
            results.append({"check": check, "passed": ok, "detail": detail})

        elif check == "answer_contains_all":
            cols = case.get("expect_all_from") or []
            needles = expect_all(truth, cols) if case.get("truth_sql") else list(case.get("expect_all") or [])
            missing = [n for n in needles if not contains(answer, n, tol)]
            ok = bool(needles) and not missing
            detail = f"missing {missing}" if missing else f"all {len(needles)} present"
            if not ok:
                for alt in lt["alt"]:
                    alt_needles = expect_all(alt["value"], cols)
                    if alt_needles and all(contains(answer, n, tol) for n in alt_needles):
                        ok, detail = True, f"matched alternative reading: {alt['label']}"
                        notes.append("alt_reading")
                        break
            results.append({"check": check, "passed": ok, "detail": detail})

        elif check == "answer_excludes_naive":
            correct = _number_targets(case, truth)
            correct_present = bool(correct) and all(has_number(answer, t, tol) for t in correct)
            truth_numbers = _all_numbers(truth)
            hits = []
            for item in lt["naive"]:
                value = item["value"]
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    # A naive TABLE (e.g. fan-out-inflated counts): flag its
                    # distinctive numbers, the ones the true answer never contains.
                    distinctive = {n for n in _all_numbers(value) if n >= 10} - truth_numbers
                    seen = sorted(n for n in distinctive if has_number(answer, n))
                    if seen:
                        hits.append(f"{item['label']}: {seen}")
                elif is_number(value) and not isinstance(value, str):
                    v = float(value)
                    if v != 0 and v not in truth_numbers and has_number(answer, v, tol):
                        hits.append(f"{item['label']}: {value}")
            # Naming a naive value as the wrong reading is allowed; presenting it
            # INSTEAD of the right one is not. Both present -> pass, flagged.
            ok = not hits or correct_present
            if hits and correct_present:
                notes.append("naive_value_also_mentioned")
            results.append({"check": check, "passed": ok,
                            "detail": ("naive values present: " + "; ".join(hits)) if hits else "no naive value"})

        elif check == "citation_matches_source":
            cited = citations_in(answer)
            upper = (answer or "").upper()
            ok, hit = False, None
            for src in _sources(case):
                for doc, sec in cited:
                    if sec and section_matches(sec, str(src["section"])) and (
                            doc == src["doc"] or (doc == "" and src["doc"] in upper)):
                        ok, hit = True, f"{src['doc']} §{src['section']}"
                        break
                if ok:
                    break
            want = [f"{s['doc']} §{s['section']}" for s in _sources(case)]
            results.append({"check": check, "passed": ok,
                            "detail": f"cited {hit}" if ok else f"want one of {want}; found {cited[:6]}"})

    return {"checks": results, "notes": notes,
            "verdict": "pass" if all(r["passed"] for r in results) else "fail"}


# --------------------------------------------------------------------------
# judged scoring
# --------------------------------------------------------------------------


def score_judged(case: dict, answer: str, facts: dict[str, Any], tool_calls: list[dict]) -> dict | None:
    """One judge call per assertion, so a partial pass is visible."""
    assertions = list(case.get("assertions") or [])
    if not assertions:
        return None
    evidence = {
        "facts": facts,
        "document_quotes": [{k: s.get(k) for k in ("doc", "version", "section", "page", "quote")}
                            for s in _sources(case)],
        "tool_calls_made": [c.get("name") for c in tool_calls],
    }
    if case.get("truth") is not None and not case.get("truth_sql"):
        evidence["reference_answer"] = case["truth"]
    rows = []
    for text in assertions:
        verdict = judge(case["q"], answer, text, evidence)
        rows.append({"assertion": text, **verdict})
    passed = sum(r["verdict"] == "pass" for r in rows)
    errors = sum(r["verdict"] == "error" for r in rows)
    if any(r["verdict"] == "fail" for r in rows):
        overall = "fail"
    elif errors:
        overall = "unscored"
    else:
        overall = "pass"
    return {"judged": True, "judge_model": judge_model(), "assertions": rows,
            "passed": passed, "total": len(rows), "errors": errors, "verdict": overall}


# --------------------------------------------------------------------------
# failure attribution
# --------------------------------------------------------------------------


def attribute(case: dict, det: dict | None, jdg: dict | None, answer: str,
              tool_calls: list[dict], state: dict) -> dict[str, list[str]]:
    """Reporting classes for a failed case, each with the basis for it.

    Evidence (a tool argument outside its vocabulary, a naive value, a missing
    citation, an action claimed) is recorded as such. Where there is none, the
    case's own failure_watch is used and labelled 'watch_list' -- a suspicion
    the dataset declared, not an observation.
    """
    classes: dict[str, list[str]] = {}

    def add(cls: str, basis: str):
        classes.setdefault(cls, []).append(basis)

    for ev in vocab_evidence(tool_calls):
        add(ev["kind"], f"evidence: {ev['tool']}.{ev['param']}={ev['value']!r}")
    for ev in authority_evidence(answer, state):
        add("authority", f"evidence: {ev}")
    if det:
        for r in det["checks"]:
            if r["passed"]:
                continue
            if r["check"] == "citation_matches_source":
                add("citation", f"evidence: {r['detail']}")
            elif r["check"] == "answer_excludes_naive":
                add("metric", f"evidence: {r['detail']}")
    if not classes:
        for w in case.get("failure_watch") or []:
            cls = WATCH_TO_CLASS.get(w)
            if cls:
                add(cls, f"watch_list: {w}")
    return classes


# --------------------------------------------------------------------------
# one case
# --------------------------------------------------------------------------


def primary_verdict(case: dict, det: dict | None, jdg: dict | None) -> tuple[str, str]:
    """(verdict, basis). Tier A/B are decided by rule; Tier C by the judge."""
    if det is not None and case["tier"] in ("A", "B"):
        return det["verdict"], "deterministic"
    if jdg is not None:
        return jdg["verdict"], "judged"
    if det is not None:
        return det["verdict"], "deterministic"
    return "unscored", "none"


async def score_case(case: dict, version: str, when: str, *, use_judge: bool,
                     timeout_s: float) -> dict[str, Any]:
    run = await run_rung(version, case["q"], timeout_s)
    lt = live_truth(case, when)
    answer = run.answer or ""
    det = score_deterministic(case, answer, lt)
    facts = live_facts(case, when)
    jdg = score_judged(case, answer, facts, run.tool_calls) if use_judge else None
    verdict, basis = primary_verdict(case, det, jdg)
    failed = verdict == "fail" or bool(run.error and not answer)
    classes = attribute(case, det, jdg, answer, run.tool_calls, run.state) if failed else {}
    by_name = Counter(c["name"] for c in run.tool_calls)
    return {
        "id": case["id"], "tier": case["tier"], "category": case["category"],
        "q": case["q"],
        "expected_pass_from": case.get("expected_pass_from"),
        "expected_fail": bool(case.get("expected_fail")),
        "verdict": verdict, "verdict_basis": basis,
        "deterministic": det, "judged": jdg,
        "judge_skipped": (not use_judge) and bool(case.get("assertions")),
        "failure_classes": classes,
        "truth_drift": lt["drift"],
        "answer": answer,
        "tool_calls": run.tool_calls,
        "tool_call_count": len(run.tool_calls),
        "tool_calls_by_name": dict(by_name),
        "state_tool_call_count": len(run.state_tool_calls),
        "event_function_calls": run.event_function_calls,
        "vocab_evidence": vocab_evidence(run.tool_calls),
        "lanes": run.lanes, "authors": run.authors,
        "latency_s": run.latency_s, "error": run.error,
    }


def case_line(r: dict) -> str:
    tag = {"deterministic": "det", "judged": "JUDGED", "none": "-"}[r["verdict_basis"]]
    extra = ""
    if r["judged"]:
        extra = f" judged {r['judged']['passed']}/{r['judged']['total']}"
    if r["failure_classes"]:
        extra += "  [" + ",".join(sorted(r["failure_classes"])) + "]"
    if r["truth_drift"]:
        extra += "  DRIFT:" + ",".join(r["truth_drift"])
    if r["error"]:
        extra += f"  ERROR: {r['error'][:80]}"
    return (f"  {r['id']:<4} {r['verdict'].upper():<8} {tag:<6} "
            f"{r['tool_call_count']:>3} calls {r['latency_s']:>7.1f}s{extra}")


def summarise(results: list[dict]) -> dict[str, Any]:
    det = [r for r in results if r["verdict_basis"] == "deterministic"]
    jud = [r for r in results if r["verdict_basis"] == "judged"]
    tally = {cls: {"deterministic": 0, "judged": 0} for cls in FAILURE_CLASSES}
    for r in results:
        side = "judged" if r["verdict_basis"] == "judged" else "deterministic"
        for cls in r["failure_classes"]:
            if cls in tally:
                tally[cls][side] += 1
    assertions = [a for r in results if r["judged"] for a in r["judged"]["assertions"]]
    return {
        "deterministic": {"cases": len(det), "passed": sum(r["verdict"] == "pass" for r in det)},
        "judged": {"cases": len(jud), "passed": sum(r["verdict"] == "pass" for r in jud),
                   "assertions": len(assertions),
                   "assertions_passed": sum(a["verdict"] == "pass" for a in assertions),
                   "assertions_unscored": sum(a["verdict"] == "error" for a in assertions),
                   "note": "judged verdicts are model opinions, not measurements"},
        "failure_tally": tally,
        "tool_calls": {"total": sum(r["tool_call_count"] for r in results),
                       "by_name": dict(sum((Counter(r["tool_calls_by_name"]) for r in results), Counter())),
                       "state_recorded_total": sum(r["state_tool_call_count"] for r in results),
                       "event_function_calls_total": sum(r["event_function_calls"] for r in results)},
        "latency_s_total": round(sum(r["latency_s"] for r in results), 1),
        "errors": sum(1 for r in results if r["error"]),
        "truth_drift_cases": [r["id"] for r in results if r["truth_drift"]],
    }


# --------------------------------------------------------------------------
# dry run: everything but the model
# --------------------------------------------------------------------------


def _oracle_answer(case: dict, lt: dict) -> str:
    """An answer built from the truth, which every deterministic check must pass."""
    parts = [json.dumps(lt["truth"], default=str, ensure_ascii=False)]
    if case.get("truth_sql") and case.get("expect_all_from"):
        parts.append(" ".join(expect_all(lt["truth"], case["expect_all_from"])))
    for s in _sources(case):
        parts.append(f"Source: {s['doc']} §{s['section']}")
    return "\n".join(parts)


def _naive_answer(case: dict, lt: dict) -> str | None:
    vals = [n["value"] for n in lt["naive"] if n["value"] not in (None, 0, [], {})]
    return json.dumps(vals, default=str) if vals else None


def dry_run(cases: list[dict], when: str) -> list[dict]:
    known = DETERMINISTIC_CHECKS | {"llm_judge", "pass_fail"}
    out = []
    for case in cases:
        lt = live_truth(case, when)
        problems = []
        unknown = [c for c in _checks(case) if c not in known]
        if unknown:
            problems.append(f"unknown check(s) {unknown}")
        if case["tier"] == "C" and len(case.get("assertions") or []) < 2:
            problems.append("Tier C with fewer than two assertions")
        facts = live_facts(case, when)
        det_oracle = score_deterministic(case, _oracle_answer(case, lt), lt)
        naive_text = _naive_answer(case, lt)
        det_naive = score_deterministic(case, naive_text, lt) if (naive_text and det_oracle) else None
        rec = {
            "id": case["id"], "tier": case["tier"], "category": case["category"],
            "expected_pass_from": case.get("expected_pass_from"),
            "expected_fail": bool(case.get("expected_fail")),
            "plan": {"deterministic_checks": [c for c in _checks(case) if c in DETERMINISTIC_CHECKS],
                     "judge_calls": len(case.get("assertions") or [])},
            "truth_drift": lt["drift"],
            "facts_resolved": sorted(facts),
            "self_test": {"oracle_passes": det_oracle["verdict"] == "pass" if det_oracle else None,
                          "naive_caught": (det_naive["verdict"] == "fail") if det_naive else None,
                          "oracle_detail": det_oracle["checks"] if det_oracle and det_oracle["verdict"] != "pass" else None},
            "problems": problems,
        }
        out.append(rec)
        st = rec["self_test"]
        print(f"  {case['id']:<4} tier {case['tier']}  det={len(rec['plan']['deterministic_checks'])} "
              f"judge={rec['plan']['judge_calls']:<2} "
              f"oracle={'ok' if st['oracle_passes'] else ('-' if st['oracle_passes'] is None else 'FAIL')} "
              f"naive={'caught' if st['naive_caught'] else ('-' if st['naive_caught'] is None else 'MISSED')}"
              + (f"  DRIFT:{','.join(lt['drift'])}" if lt["drift"] else "")
              + (f"  PROBLEM: {'; '.join(problems)}" if problems else ""))
    return out


# --------------------------------------------------------------------------
# spot-check
# --------------------------------------------------------------------------


def sample_judged(version: str, n: int, seed: int) -> int:
    path = EVAL_DIR / f"results_{version}.json"
    if not path.exists():
        print(f"no {path.name}; run the eval first", file=sys.stderr)
        return 1
    data = json.loads(path.read_text())
    judged = [r for r in data["cases"] if r.get("judged")]
    if not judged:
        print("no judged cases in that run")
        return 1
    picks = random.Random(seed).sample(judged, min(n, len(judged)))
    print(f"# Spot-check: {len(picks)} judged cases from {path.name} "
          f"(judge: {picks[0]['judged']['judge_model']})")
    print("# These verdicts are a model's opinion. Check each against the answer.\n")
    for r in picks:
        print(f"## {r['id']} -- {r['q']}")
        print(f"verdict (judged): {r['judged']['verdict']} "
              f"({r['judged']['passed']}/{r['judged']['total']} assertions)\n")
        print("answer:\n" + "\n".join("  > " + line for line in (r["answer"] or "(empty)").splitlines()[:40]))
        print()
        for a in r["judged"]["assertions"]:
            print(f"  [{a['verdict'].upper():<5}] {a['assertion']}\n          reason: {a['reason']}")
        print()
    return 0


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Score a rung against agent_cases.yaml")
    ap.add_argument("--version", choices=VERSIONS)
    ap.add_argument("--only", help="comma-separated tiers to run, e.g. A,B (skips judged)")
    ap.add_argument("--cases", help="comma-separated case ids")
    ap.add_argument("--dry-run", action="store_true", help="no LLM: truth drift + scorer self-test")
    ap.add_argument("--no-judge", action="store_true", help="run the rung but skip judge calls")
    ap.add_argument("--sample-judged", action="store_true",
                    help="print 5 judged cases from results_{version}.json for human spot-check")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--timeout", type=float, default=600.0, help="seconds per case")
    args = ap.parse_args()

    if args.sample_judged:
        if not args.version:
            ap.error("--sample-judged needs --version")
        return sample_judged(args.version, 5, args.seed)

    data = load_cases(AGENT_CASES)
    cases = data["cases"]
    if args.only:
        tiers = {t.strip().upper() for t in args.only.split(",")}
        cases = [c for c in cases if c["tier"] in tiers]
    if args.cases:
        ids = {i.strip() for i in args.cases.split(",")}
        cases = [c for c in cases if c["id"] in ids]
    when = as_of()
    started = now_iso()

    if args.dry_run:
        print(f"dry run: {len(cases)} cases, as_of {when}, no model calls")
        recs = dry_run(cases, when)
        payload = {"kind": "agent", "mode": "dry_run", "started": started, "as_of": when,
                   "cases": recs,
                   "summary": {"cases": len(recs),
                               "drift": [r["id"] for r in recs if r["truth_drift"]],
                               "oracle_failures": [r["id"] for r in recs if r["self_test"]["oracle_passes"] is False],
                               "naive_missed": [r["id"] for r in recs if r["self_test"]["naive_caught"] is False],
                               "problems": {r["id"]: r["problems"] for r in recs if r["problems"]}}}
        write_json(EVAL_DIR / "results_dryrun.json", payload)
        s = payload["summary"]
        print(f"\nwrote results_dryrun.json  drift={s['drift'] or 'none'}  "
              f"oracle_failures={s['oracle_failures'] or 'none'}  naive_missed={s['naive_missed'] or 'none'}")
        return 1 if (s["oracle_failures"] or s["problems"]) else 0

    if not args.version:
        ap.error("--version is required unless --dry-run")
    use_judge = not args.no_judge
    print(f"{args.version}: {len(cases)} cases, as_of {when}, "
          f"judge {'off' if not use_judge else judge_model()}")

    async def run_all() -> list[dict]:
        out = []
        for case in cases:
            r = await score_case(case, args.version, when, use_judge=use_judge,
                                 timeout_s=args.timeout)
            print(case_line(r), flush=True)
            out.append(r)
        return out

    results = asyncio.run(run_all())
    summary = summarise(results)
    payload = {"kind": "agent", "mode": "live", "version": args.version,
               "started": started, "finished": now_iso(), "as_of": when,
               "filters": {"only": args.only, "cases": args.cases},
               "judge": {"enabled": use_judge, "model": judge_model() if use_judge else None},
               "failure_class_mapping": WATCH_TO_CLASS,
               "summary": summary, "cases": results}
    out = EVAL_DIR / f"results_{args.version}.json"
    write_json(out, payload)
    d, j = summary["deterministic"], summary["judged"]
    print(f"\ndeterministic: {d['passed']}/{d['cases']} passed")
    print(f"judged:        {j['passed']}/{j['cases']} passed "
          f"({j['assertions_passed']}/{j['assertions']} assertions; model opinion, not a measurement)")
    print("failure tally (deterministic + judged): " + ", ".join(
        f"{k}={v['deterministic']}+{v['judged']}" for k, v in summary["failure_tally"].items()
        if v["deterministic"] or v["judged"]) or "none")
    print(f"tool calls: {summary['tool_calls']['total']}   latency: {summary['latency_s_total']}s   "
          f"wrote {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
