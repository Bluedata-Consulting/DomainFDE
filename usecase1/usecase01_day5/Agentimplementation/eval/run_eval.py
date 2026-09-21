"""Run the Day 5 eval set against the four agents, and record a baseline.

    python3 eval/run_eval.py                 run every case
    python3 eval/run_eval.py A2 C1           run some cases
    python3 eval/run_eval.py --no-save       run without writing a baseline file

Each case runs in its own fresh session, exactly as if you typed it in the chat.
Four things are checked:

    forbidden    did a tool run that this case says must never run?
    path         how many of the expected steps appeared, in order (or in any order)
    state        did the run leave behind the facts it should, such as route_taken?
    response     how many of the expected phrases appear in the final answer

This calls the real model, so it needs the ADK environment and your Google Cloud
setup. It costs a few pence. Nothing in any real system changes.
"""
import asyncio
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT / "agents"))
sys.path.insert(0, str(KIT))

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from northwind.specialists import MODEL  # noqa: E402


def load(name):
    return yaml.safe_load((KIT / "eval" / name).read_text(encoding="utf-8"))


_AGENTS = {}


def agent(name):
    if name not in _AGENTS:
        _AGENTS[name] = importlib.import_module(f"{name}.agent").root_agent
    return _AGENTS[name]


async def run_case(agent_name, prompt):
    """Run one prompt in a new session. Returns the path, the blocked calls, the answer and the state."""
    runner = InMemoryRunner(agent=agent(agent_name), app_name=agent_name)
    session = await runner.session_service.create_session(app_name=agent_name, user_id="eval")
    path, blocked, answer = [], [], ""
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    async for event in runner.run_async(user_id="eval", session_id=session.id, new_message=message):
        for part in (event.content.parts if event.content else []):
            if part.function_response:
                response = part.function_response.response or {}
                status = response.get("status") if isinstance(response, dict) else None
                name = part.function_response.name
                (blocked if status in ("blocked", "already_escalated") else path).append(name)
                if isinstance(response, dict) and (response.get("escalated_to") or status in ("escalated", "approval_requested")):
                    if "escalated" not in path:
                        path.append("escalated")
            elif part.text:
                answer = part.text
    state = (await runner.session_service.get_session(
        app_name=agent_name, user_id="eval", session_id=session.id)).state
    return path, blocked, answer, dict(state)


def path_score(expected, actual, any_order):
    if not expected:
        return 1.0
    if any_order:
        return sum(1 for step in expected if step in actual) / len(expected)
    position, matched = 0, 0
    for step in expected:
        if step in actual[position:]:
            position = actual.index(step, position) + 1
            matched += 1
    return matched / len(expected)


def state_ok(expected, state):
    """Every expected fact must match. A list means any of those values is fine."""
    wrong = []
    for key, want in (expected or {}).items():
        got = state.get(key)
        if not (got in want if isinstance(want, list) else got == want):
            wrong.append(f"{key}={got}")
    return wrong


def response_score(phrases, answer):
    if not phrases:
        return 1.0
    return sum(1 for p in phrases if str(p).lower() in answer.lower()) / len(phrases)


async def main():
    wanted = [a.upper() for a in sys.argv[1:] if not a.startswith("--")]
    save = "--no-save" not in sys.argv
    cases = [c for c in load("cases.yaml")["cases"] if not wanted or c["id"] in wanted]
    config = load("config.yaml")

    print(f"\nRunning {len(cases)} cases on {MODEL}\n")
    print(f"  {'#':<4}{'Agent':<18}{'Kind':<16}{'Path':<6}{'State':<7}{'Answer':<8}{'Forbidden ran':<16}Result")
    print(f"  {'-' * 4}{'-' * 18}{'-' * 16}{'-' * 6}{'-' * 7}{'-' * 8}{'-' * 16}------")

    results = []
    for case in cases:
        path, blocked, answer, state = await run_case(case["agent"], case["prompt"])
        rules = config[case["kind"]]
        forbidden = [t for t in case.get("forbid_tools", []) if t in path]
        p = path_score(case.get("expect_steps", []), path, case.get("any_order", False))
        wrong_state = state_ok(case.get("expect_state"), state)
        r = response_score(case.get("expect_phrases", []), answer)
        passed = not forbidden and not wrong_state and p >= rules["path_min"] and r >= rules["response_min"]
        results.append({
            "id": case["id"], "agent": case["agent"], "kind": case["kind"], "case": case["case"],
            "path": path, "blocked": blocked, "forbidden_that_ran": forbidden,
            "state_mismatches": wrong_state, "path_score": round(p, 2), "response_score": round(r, 2),
            "passed": passed, "answer": answer.strip(),
        })
        print(f"  {case['id']:<4}{case['agent']:<18}{case['kind']:<16}{p:<6.2f}"
              f"{('ok' if not wrong_state else 'WRONG'):<7}{r:<8.2f}"
              f"{(', '.join(forbidden) or 'none')[:14]:<16}{'PASS' if passed else 'FAIL'}")
        for w in wrong_state:
            print(f"        state: {w}")

    def rate(kind):
        group = [x for x in results if x["kind"] == kind]
        return sum(x["passed"] for x in group), len(group)

    must_pass, must_total = rate("must_never")
    should_pass, should_total = rate("should_usually")
    print(f"\n  Must never     {must_pass} of {must_total} passed"
          f"{'' if must_pass == must_total else '   <-- a safety failure'}")
    print(f"  Should usually {should_pass} of {should_total} passed")
    for pattern, prefix in [("A loop agent", "A"), ("B loop graph", "B"), ("C router", "C"), ("D orchestrator", "D")]:
        group = [x for x in results if x["id"].startswith(prefix)]
        if group:
            print(f"    {pattern:<16}{sum(x['passed'] for x in group)} of {len(group)}")

    if save and not wanted:
        baseline = {
            "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "model": MODEL, "eval_set": load("cases.yaml")["eval_set"],
            "must_never_passed": f"{must_pass} of {must_total}",
            "should_usually_passed": f"{should_pass} of {should_total}",
            "cases": results,
        }
        out = KIT / "baseline" / "baseline_v1.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
        print(f"\n  Baseline written to {out.relative_to(KIT)}")
        print("  Tomorrow's run is compared with this file. Do not edit it by hand.\n")
    else:
        print("\n  No baseline written.\n")


if __name__ == "__main__":
    asyncio.run(main())
