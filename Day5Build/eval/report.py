"""The comparison table across rungs, from saved results only.

    python -m eval.report                  # prints markdown
    python -m eval.report --out report.md  # also writes it

Reads every eval/results_*.json (live agent runs and results_rag.json) and
re-runs nothing. Deterministic and judged outcomes stay in separate numbers
in every cell: a cell "3+2" means 3 cases decided by rule and 2 by the judge.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .common import EVAL_DIR, FAILURE_CLASSES, VERSIONS

SEMANTIC = ("vocab", "entity", "metric")
RUNG_LABEL = {v: v.upper() for v in VERSIONS}


def load(results_dir: Path) -> tuple[dict[str, dict], dict | None, list[str]]:
    agent: dict[str, dict] = {}
    rag = None
    notes: list[str] = []
    for path in sorted(results_dir.glob("results_*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            notes.append(f"skipped {path.name}: not valid JSON")
            continue
        if data.get("kind") == "rag":
            rag = data
        elif data.get("kind") == "agent" and data.get("mode") == "live" and data.get("version") in VERSIONS:
            agent[data["version"]] = data
            f = data.get("filters") or {}
            if f.get("only") or f.get("cases"):
                notes.append(f"{data['version'].upper()} is a partial run "
                             f"(only={f.get('only')}, cases={f.get('cases')}): {len(data['cases'])} cases")
            if not (data.get("judge") or {}).get("enabled"):
                notes.append(f"{data['version'].upper()} ran without the judge: Tier C is unscored there")
    return agent, rag, notes


def _mark(r: dict | None) -> str:
    if r is None:
        return "·"
    j = "ʲ" if r.get("verdict_basis") == "judged" else ""
    return {"pass": "✓", "fail": "✗"}.get(r.get("verdict"), "?") + j


def _table(header: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------


def failure_by_rung(agent: dict[str, dict], rungs: list[str]) -> str:
    rows = []
    for label, key in (("pass, deterministic", "deterministic"), ("pass, judged", "judged")):
        row = [f"*{label}*"]
        for v in rungs:
            s = agent[v]["summary"][key] if v in agent else None
            row.append(f"{s['passed']}/{s['cases']}" if s else "—")
        rows.append(row)
    for cls in FAILURE_CLASSES:
        row = [cls]
        for v in rungs:
            if v not in agent:
                row.append("—")
                continue
            t = agent[v]["summary"]["failure_tally"].get(cls, {"deterministic": 0, "judged": 0})
            row.append(f"{t['deterministic']}+{t['judged']}" if (t["deterministic"] or t["judged"]) else "0")
        rows.append(row)
    ev_row = ["*attributed by evidence / watch list*"]
    for v in rungs:
        if v not in agent:
            ev_row.append("—")
            continue
        ev = wl = 0
        for r in agent[v]["cases"]:
            for bases in r["failure_classes"].values():
                for b in bases:
                    ev += b.startswith("evidence")
                    wl += b.startswith("watch_list")
        ev_row.append(f"{ev} / {wl}")
    rows.append(ev_row)
    return (_table(["failure class"] + [RUNG_LABEL[v] for v in rungs], rows)
            + "\n\nCell = deterministic+judged failing cases attributed to the class. A case can "
              "carry more than one class. *Watch list* = no direct evidence; the dataset's declared "
              "failure_watch for the case was used.")


def semantic_delta(agent: dict[str, dict]) -> str:
    if "v0" not in agent or "v1" not in agent:
        return "_V0 → V1 semantic delta: needs both results_v0.json and results_v1.json._"

    def total(v: str) -> tuple[int, int]:
        t = agent[v]["summary"]["failure_tally"]
        return (sum(t[c]["deterministic"] for c in SEMANTIC), sum(t[c]["judged"] for c in SEMANTIC))

    (d0, j0), (d1, j1) = total("v0"), total("v1")
    delta = (d1 + j1) - (d0 + j0)
    line = (f"**V0 → V1 semantic delta (vocab + entity + metric): {d0 + j0} → {d1 + j1} "
            f"({delta:+d}; deterministic {d0}→{d1}, judged {j0}→{j1}).**")
    ids0 = {r["id"] for r in agent["v0"]["cases"]}
    ids1 = {r["id"] for r in agent["v1"]["cases"]}
    if ids0 != ids1:
        line += f"\n\n⚠ The two runs covered different cases ({len(ids0)} vs {len(ids1)}); the delta is not like-for-like."
    threshold = max(2, round(0.25 * (d0 + j0)))
    if abs(delta) >= threshold:
        line += (f"\n\n⚠ **FLAG: the semantic count moved by {abs(delta)} (threshold {threshold}).** "
                 "A loop/control change should not change meaning. Check what else differs between "
                 "the two rungs -- tools, prompt, or ontology.")
    else:
        line += ("\n\nNear zero, as expected: the control structure buys control, not "
                 "comprehension.")
    return line


def first_passing(agent: dict[str, dict], rungs: list[str], cases_meta: dict[str, dict]) -> str:
    order = {v: i for i, v in enumerate(VERSIONS)}
    review = []
    counts = {"as expected": 0, "earlier": 0, "later": 0, "never passed": 0, "not testable": 0,
              "regression": 0}
    for cid, meta in cases_meta.items():
        if meta.get("expected_fail"):
            continue
        by_rung = {v: next((r for r in agent[v]["cases"] if r["id"] == cid), None) for v in rungs if v in agent}
        passes = [v for v in rungs if by_rung.get(v) and by_rung[v]["verdict"] == "pass"]
        first = passes[0] if passes else None
        expected = str(meta.get("expected_pass_from") or "").lower()
        marks = " ".join(f"{RUNG_LABEL[v]}{_mark(by_rung.get(v))}" for v in rungs)
        issues = []
        if expected not in order or expected not in [v for v in rungs if v in agent]:
            counts["not testable"] += 1
            if first:
                issues.append(f"passes at {first.upper()}, expected rung not run")
        elif first is None:
            counts["never passed"] += 1
            issues.append("never passed")
        elif order[first] < order[expected]:
            counts["earlier"] += 1
            issues.append("earlier than expected")
        elif order[first] > order[expected]:
            counts["later"] += 1
            issues.append("later than expected")
        else:
            counts["as expected"] += 1
        if first:
            fails_after = [v for v in rungs if v in agent and order[v] > order[first]
                           and by_rung.get(v) and by_rung[v]["verdict"] == "fail"]
            if fails_after:
                counts["regression"] += 1
                issues.append("regressed at " + ",".join(x.upper() for x in fails_after))
        if issues:
            review.append([cid, meta.get("category", ""), expected.upper() or "?",
                           first.upper() if first else "—", marks, "; ".join(issues)])
    head = ("  ".join(f"{k}: {v}" for k, v in counts.items())
            + "\n\n✓/✗ decided by rule; ✓ʲ/✗ʲ decided by the judge (model opinion); · not run; ? unscored.\n\n")
    if not review:
        return head + "_Every case first passed at its expected rung._"
    return head + _table(["case", "category", "expected", "first pass", "by rung", "review"], review)


def expected_fail(agent: dict[str, dict], rungs: list[str], cases_meta: dict[str, dict]) -> str:
    rows, alerts = [], []
    ran = [v for v in rungs if v in agent]
    top = ran[-1] if ran else None
    for cid, meta in cases_meta.items():
        if not meta.get("expected_fail"):
            continue
        by_rung = {v: next((r for r in agent[v]["cases"] if r["id"] == cid), None) for v in ran}
        rows.append([cid, meta.get("q", "")[:60]] + [_mark(by_rung.get(v)) for v in rungs])
        if top and by_rung.get(top) and by_rung[top]["verdict"] == "pass":
            alerts.append(f"🚨 **{cid} PASSES at the top rung ({top.upper()}).** It is expected to fail "
                          "everywhere -- a pass usually means the agent is now deciding a business "
                          "judgement confidently. Read the answer before celebrating.")
    if not rows:
        return "_No expected_fail cases in the results._"
    return ("\n".join(alerts) + ("\n\n" if alerts else "")
            + _table(["case", "question"] + [RUNG_LABEL[v] for v in rungs], rows)
            + ("" if alerts else ("\n\nStill failing at the top rung, as they should." if top
                                  else "\n\n_No agent runs yet._")))


def rag_section(rag: dict | None) -> str:
    if not rag:
        return "_No results_rag.json._"
    layers = rag.get("layers", {})
    rows = []
    r = layers.get("retrieval")
    if r:
        k = r["k"]
        s = r["summary"]
        rows.append([f"recall@{k}", f"{s[f'recall_at_{k}']}", "—", "—"])
        rows.append([f"precision@{k} / MRR", f"{s[f'precision_at_{k}']} / {s['mrr']}", "—", "—"])
        rows.append(["superseded leakage (hard fail)", ", ".join(s["hard_fails"]) or "none", "—", "—"])

    def frac(layer: str, metric: str, basis: str) -> str:
        s = (layers.get(layer) or {}).get("summary", {}).get(metric, {})
        b = s.get(basis)
        return f"{b['passed']}/{b['of']}" if b else "—"

    rows.append(["citation accurate (rule)", "—", frac("generation", "citation_accurate", "deterministic"),
                 frac("e2e", "citation_accurate", "deterministic")])
    rows.append(["citation present (rule)", "—", frac("generation", "citation_present", "deterministic"),
                 frac("e2e", "citation_present", "deterministic")])
    rows.append(["value correct (rule)", "—", frac("generation", "value", "deterministic"),
                 frac("e2e", "value", "deterministic")])
    rows.append(["value correct (judged)", "—", frac("generation", "value", "judged"),
                 frac("e2e", "value", "judged")])
    rows.append(["conditions complete (judged)", "—", frac("generation", "conditions", "judged"),
                 frac("e2e", "conditions", "judged")])
    rows.append(["faithfulness (judged)", "—", frac("generation", "faithfulness", "judged"), "—"])
    rows.append(["routing correct (rule)", "—", "—", frac("e2e", "routing_correct", "deterministic")])
    rows.append(["synthesis (judged)", "—", "—", frac("e2e", "synthesis", "judged")])

    def adv(layer: str) -> str:
        s = (layers.get(layer) or {}).get("summary", {})
        if not s:
            return "—"
        return ", ".join(s.get("adversarial_failures") or []) or "none"
    rows.append(["adversarial failures", (", ".join(r["summary"]["hard_fails"]) or "none") if r else "—",
                 adv("generation"), adv("e2e")])

    stamp = "  ".join(f"{name}: {layers[name]['ran_at']}" for name in ("retrieval", "generation", "e2e")
                      if name in layers)
    mode = f"Retrieval mode: **{r['mode']}**. " if r else ""
    partial = [name for name in layers if (layers[name].get("filters") or {}).get("cases")]
    warn = f"\n\n⚠ Partial layer runs: {', '.join(partial)}." if partial else ""
    return (_table(["", "retrieval", "generation", "e2e"], rows)
            + f"\n\n{mode}Layers are never blended. Adversarial cases are pass/fail and excluded from "
              f"every fraction. Last runs -- {stamp}.{warn}")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def dataset_health(results_dir: Path) -> str:
    path = results_dir / "results_dryrun.json"
    if not path.exists():
        return "_No results_dryrun.json -- run `python -m eval.run_agent_eval --dry-run`._"
    d = json.loads(path.read_text())
    s = d["summary"]
    rows = []
    for r in d["cases"]:
        st = r["self_test"]
        mark = lambda v, ok, bad: "—" if v is None else (ok if v else bad)
        rows.append([r["id"], r["tier"], r["category"], r.get("expected_pass_from") or "",
                     len(r["plan"]["deterministic_checks"]), r["plan"]["judge_calls"],
                     mark(st["oracle_passes"], "ok", "**FAIL**"),
                     mark(st["naive_caught"], "caught", "**missed**"),
                     ", ".join(r["truth_drift"]) or "none"])
    head = (f"Dry run {d['started']} (as_of {d['as_of']}, no model calls): {s['cases']} cases; "
            f"truth drift: {', '.join(s['drift']) or 'none'}; scorer oracle failures: "
            f"{', '.join(s['oracle_failures']) or 'none'}; naive answers missed: "
            f"{', '.join(s['naive_missed']) or 'none'}.\n\n"
            "*oracle* = an answer built from the truth must pass every deterministic check; "
            "*naive* = an answer built from the stored naive values must fail.\n\n")
    return head + _table(["case", "tier", "category", "expected", "rule checks", "judge calls",
                          "oracle", "naive", "drift"], rows)


def retrieval_detail(rag: dict | None) -> str:
    r = ((rag or {}).get("layers") or {}).get("retrieval")
    if not r:
        return "_No retrieval layer results._"
    k = r["k"]
    rows = []
    for c in r["cases"]:
        if c.get("error"):
            rows.append([c["id"], "", "", "", "", f"ERROR {c['error'][:60]}", "", ""])
            continue
        fmt = lambda v: "—" if v is None else f"{v:.2f}"
        status = "**HARD FAIL**: " + ", ".join(c["superseded_leakage"]) if c["hard_fail"] else "ok"
        rows.append([c["id"], c["category"], fmt(c["recall_at_k"]), fmt(c["precision_at_k"]),
                     fmt(c["mrr"]), status, ", ".join(c["missed"]) or "—",
                     "<br>".join(f"{i}. {x}" for i, x in enumerate(c.get("retrieved") or [], 1))])
    return (f"Mode **{r['mode']}**, k={k}, ran {r['ran_at']}. {r.get('mode_note', '')}\n\n"
            + _table(["case", "category", f"recall@{k}", f"precision@{k}", "MRR", "leakage", "missed",
                     f"retrieved (rank order, top {k})"], rows))


def build(results_dir: Path) -> str:
    import yaml

    agent, rag, notes = load(results_dir)
    cases_meta = {c["id"]: c for c in yaml.safe_load((EVAL_DIR / "agent_cases.yaml").read_text())["cases"]}
    rungs = list(VERSIONS)
    parts = ["# Meridian agent ladder -- eval report", ""]
    parts.append("Rungs with results: " + (", ".join(v.upper() for v in rungs if v in agent) or "none"))
    if notes:
        parts += [""] + [f"- {n}" for n in notes]
    parts += ["", "## 1. Failure class by rung", "", failure_by_rung(agent, rungs)]
    parts += ["", "## 2. V0 → V1 semantic delta", "", semantic_delta(agent)]
    parts += ["", "## 3. First passing rung vs expected", "", first_passing(agent, rungs, cases_meta)]
    parts += ["", "## 4. Expected-fail cases", "", expected_fail(agent, rungs, cases_meta)]
    parts += ["", "## 5. RAG layers (V5)", "", rag_section(rag)]
    parts += ["", "## 6. Retrieval by case (V5, no LLM)", "", retrieval_detail(rag)]
    parts += ["", "## 7. Dataset health (dry run)", "", dataset_health(results_dir), ""]
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description="Comparison report from saved eval results")
    ap.add_argument("--dir", default=str(EVAL_DIR), help="where the results_*.json files are")
    ap.add_argument("--out", help="also write the markdown here")
    args = ap.parse_args()
    text = build(Path(args.dir))
    print(text)
    if args.out:
        Path(args.out).write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
