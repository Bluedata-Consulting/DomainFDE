"""The health check (Day 7: Operate). Is the current release keeping its contract?

    python3 -m ops.check                run the behaviour contract, then score the SLIs
    python3 -m ops.check --sli-only     score the SLIs from recorded traffic only (no model calls)

  1. The behaviour contract (ops/contract.yaml): five short cases, run against the
     current release in fresh sessions. This calls the model, and costs a few pence.
  2. The SLIs: measured from runs.jsonl for the current release (the contract run
     adds to it), and compared with the SLOs in ops/slo.yaml.

The verdict is HEALTHY or DEGRADED. DEGRADED says what breached, and recommends a
rollback when a must-never case failed or an SLO with no budget was breached.
"""
import asyncio
import importlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / "agents"))
sys.path.insert(0, str(KIT))

from northwind import release as rel  # noqa: E402
from northwind.recorder import RUNS_FILE  # noqa: E402


def _load(name):
    return yaml.safe_load((KIT / "ops" / name).read_text(encoding="utf-8"))


async def run_contract():
    from google.adk.runners import InMemoryRunner
    from google.genai import types
    module = importlib.import_module("v7_operations.agent")
    app = module.app
    results = []
    for case in _load("contract.yaml")["cases"]:
        runner = InMemoryRunner(app=app)
        session = await runner.session_service.create_session(app_name=app.name, user_id="check")
        called, answer = [], ""
        message = types.Content(role="user", parts=[types.Part(text=case["prompt"])])
        async for event in runner.run_async(user_id="check", session_id=session.id, new_message=message):
            for part in (event.content.parts if event.content else []):
                if part.function_call and event.author == app.root_agent.name:
                    called.append(part.function_call.name)
                elif part.text and event.author == app.root_agent.name:
                    answer = part.text
        text = answer.lower()
        missing = [s for s in case.get("expect_specialists", []) if s not in called]
        any_ok = not case.get("any_of") or any(str(a).lower() in text for a in case["any_of"])
        broken = [n for n in case.get("never", []) if str(n).lower() in text]
        passed = not missing and any_ok and not broken
        why = ([f"did not call {', '.join(missing)}"] if missing else []) + \
              ([] if any_ok else [f"answer lacks {case['any_of']}"]) + \
              ([f"answer says {broken}"] if broken else [])
        results.append({"id": case["id"], "kind": case["kind"], "case": case["case"], "passed": passed,
                        "called": called, "why": "; ".join(why), "answer": answer.strip()[:300]})
        print(f"  {case['id']:<4}{case['kind']:<16}{'PASS' if passed else 'FAIL':<6}{case['case'][:52]:<54}"
              f"{('  ' + '; '.join(why)) if why else ''}")
    for tool in module.root_agent.tools:
        for inner in getattr(tool.agent, "tools", []):
            if hasattr(inner, "close"):
                await inner.close()
    return results


def slis(tag):
    events = [json.loads(l) for l in open(RUNS_FILE, encoding="utf-8")] if RUNS_FILE.exists() else []
    events = [e for e in events if e.get("release") == tag]
    calls = sum(1 for e in events if e["event"] == "tool_call")
    errors = sum(1 for e in events if e["event"] == "tool_error")
    turns = sorted(e["seconds"] for e in events if e["event"] == "turn")
    model_calls = [e for e in events if e["event"] == "model_call"]
    tokens = [e["input_tokens"] + e["output_tokens"] for e in model_calls]
    p95 = turns[math.ceil(0.95 * len(turns)) - 1] if turns else None
    return {"events": len(events), "tool_calls": calls, "tool_errors": errors,
            "tool_error_rate": errors / (calls + errors) if calls + errors else 0.0,
            "p95_seconds_per_turn": p95,
            "tokens_per_model_call": sum(tokens) / len(tokens) if tokens else None}


def main():
    tag = rel.current_tag()
    slo = _load("slo.yaml")
    print(f"\nHealth check for release {tag}  (model {rel.model()})\n")
    drifted = rel.drift(tag)
    if drifted:
        print("  WARNING: the release has drifted from its fingerprints:", ", ".join(drifted), "\n")

    breaches, rollback = [], False
    contract = []
    if "--sli-only" not in sys.argv:
        print("  Behaviour contract")
        contract = asyncio.run(run_contract())
        for kind, target in (("must_never", slo["contract_must_never_pass_rate"]),
                             ("should_usually", slo["contract_should_pass_rate"])):
            group = [c for c in contract if c["kind"] == kind]
            rate = sum(c["passed"] for c in group) / len(group) if group else 1.0
            if rate < target:
                breaches.append(f"{kind} cases: {sum(c['passed'] for c in group)} of {len(group)} passed")
                rollback = rollback or kind == "must_never"
        print()

    s = slis(tag)
    print(f"  SLIs from {s['events']} recorded events for {tag}")
    rows = [
        ("Tool error rate", s["tool_error_rate"], slo["tool_error_rate_max"], f"{s['tool_error_rate']:.1%}",
         f"<= {slo['tool_error_rate_max']:.0%}", f"{s['tool_errors']} of {s['tool_calls'] + s['tool_errors']} calls"),
        ("p95 seconds per answer", s["p95_seconds_per_turn"], slo["p95_seconds_per_turn_max"],
         "n/a" if s["p95_seconds_per_turn"] is None else f"{s['p95_seconds_per_turn']:.1f} s",
         f"<= {slo['p95_seconds_per_turn_max']} s", ""),
        ("Tokens per model call", s["tokens_per_model_call"], slo["tokens_per_model_call_max"],
         "n/a" if s["tokens_per_model_call"] is None else f"{s['tokens_per_model_call']:,.0f}",
         f"<= {slo['tokens_per_model_call_max']:,}", ""),
    ]
    for name, value, limit, shown, target, note in rows:
        ok = value is None or value <= limit
        if not ok:
            breaches.append(f"{name} {shown}, target {target}")
            rollback = rollback or name == "Tool error rate"
        print(f"    {name:<24}{shown:<12}{target:<12}{'PASS' if ok else 'BREACH':<8}{note}")

    healthy = not breaches
    print(f"\n  {'HEALTHY' if healthy else 'DEGRADED'}: release {tag}")
    for b in breaches:
        print(f"    - {b}")
    if rollback:
        print("\n  Recommendation: roll back now.   python3 -m ops.release rollback")
    elif not healthy:
        print("\n  Recommendation: investigate the traces before deciding to roll back.")
    (KIT / "ops" / "last_check.json").write_text(json.dumps({
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), "release": tag,
        "model": rel.model(), "healthy": healthy, "breaches": breaches, "contract": contract, "slis": s},
        indent=2), encoding="utf-8")
    print()


if __name__ == "__main__":
    main()
