"""Run the delivery-exception resolution pipeline.

    python ex02_workflow_pipeline/main.py
    python ex02_workflow_pipeline/main.py --case EXC-7704
    python ex02_workflow_pipeline/main.py --no-trace
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Run as a script, import as a package: the repo root goes on sys.path so
# that `python exNN_x/main.py` and `adk web .` resolve imports identically.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ex02_workflow_pipeline.agent import root_agent  # noqa: E402
from ex02_workflow_pipeline.config import APP_NAME, DATA_DIR, USER_ID, verify_credentials  # noqa: E402
from ex02_workflow_pipeline.runner import run_pipeline  # noqa: E402

RULE = "=" * 78
THIN = "-" * 78


def load_cases() -> list[dict]:
    return json.loads((DATA_DIR / "exceptions.json").read_text(encoding="utf-8"))


def block(title: str, body: str) -> None:
    print(f"\n{THIN}\n{title}\n{THIN}")
    print(body.strip() if isinstance(body, str) else json.dumps(body, indent=2))


async def resolve(case: dict, trace: bool) -> dict:
    print(f"\n{RULE}")
    print(f"CASE {case['case_id']}  order {case['order']['order_id']}  "
          f"{case['order']['customer_name']}")
    print(RULE)

    # The pipeline's input is the whole raw payload. Stage 1 is responsible for
    # turning it into something typed — deliberately, so that upstream format
    # changes only ever break one agent.
    state = await run_pipeline(
        agent=root_agent,
        prompt=json.dumps(case, indent=2),
        app_name=APP_NAME,
        user_id=USER_ID,
        trace=trace,
    )

    block("STAGE 1 — normalised case", state.get("case", "(missing)"))
    block("STAGE 2a — policy desk", state.get("policy_assessment", "(missing)"))
    block("STAGE 2b — supply desk", state.get("supply_assessment", "(missing)"))
    block("STAGE 2c — customer value desk", state.get("customer_assessment", "(missing)"))
    block("STAGE 3 — resolution", state.get("resolution", "(missing)"))
    block("STAGE 4 — approved customer message", state.get("draft_reply", "(missing)"))

    feedback = state.get("review_feedback", "")
    if isinstance(feedback, str) and feedback.strip().upper() != "APPROVED":
        block("STAGE 4 — reviewer's last word (loop hit max_iterations)", feedback)

    return state


async def main() -> None:
    parser = argparse.ArgumentParser(description="Aurora exception resolution pipeline")
    parser.add_argument("--case", help="Run a single case ID, e.g. EXC-7704")
    parser.add_argument("--no-trace", action="store_true", help="Hide the stage trace")
    args = parser.parse_args()

    verify_credentials()

    cases = load_cases()
    if args.case:
        cases = [c for c in cases if c["case_id"] == args.case]
        if not cases:
            print(f"No case with id {args.case}")
            return

    # Cases run one at a time here so the trace stays readable. In production you
    # would fan out across cases exactly as example 1 does — the pipeline itself
    # is stateless between cases.
    results = []
    for case in cases:
        results.append(await resolve(case, trace=not args.no_trace))

    print(f"\n{RULE}\nSUMMARY\n{RULE}")
    for case, state in zip(cases, results):
        resolution = state.get("resolution") or {}
        if isinstance(resolution, str):
            try:
                resolution = json.loads(resolution)
            except json.JSONDecodeError:
                resolution = {}
        action = resolution.get("action", "?")
        cost = resolution.get("expected_cost_inr", 0)
        flag = " [NEEDS SIGN-OFF]" if resolution.get("policy_exception_required") else ""
        print(f"  {case['case_id']}  {action:<22} INR {cost:>9,.0f}{flag}")

    print("\nWatch for: EXC-7704 should reach escalate_to_human (allergic reaction +")
    print("quarantined SKU), and EXC-7701 should not promise a diffuser replacement")
    print("from a DC that has zero stock.")


if __name__ == "__main__":
    asyncio.run(main())
