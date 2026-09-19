"""Run the triage assistant over a batch of sample tickets.

    python ex01_prompt_assistant/main.py
    python ex01_prompt_assistant/main.py --ticket TKT-40122
    python ex01_prompt_assistant/main.py --text "my order never arrived"
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

from pydantic import ValidationError  # noqa: E402

from ex01_prompt_assistant.agent import root_agent  # noqa: E402
from ex01_prompt_assistant.config import APP_NAME, DATA_DIR, USER_ID, verify_credentials  # noqa: E402
from ex01_prompt_assistant.runner import run_agent  # noqa: E402
from ex01_prompt_assistant.schemas import TicketTriage  # noqa: E402

PRIORITY_MARK = {"P1": "[P1]", "P2": "[P2]", "P3": "[P3]"}


def load_tickets() -> list[dict]:
    return json.loads((DATA_DIR / "tickets.json").read_text(encoding="utf-8"))


async def triage_one(ticket_text: str) -> TicketTriage | None:
    """Single ticket in, validated object out."""
    raw, _state = await run_agent(
        agent=root_agent,
        prompt=ticket_text,
        app_name=APP_NAME,
        user_id=USER_ID,
    )
    try:
        # Constrained decoding makes this near-certain to parse, but validating
        # anyway is the difference between a demo and something you can page on.
        return TicketTriage.model_validate_json(raw)
    except ValidationError as exc:
        print(f"  !! schema validation failed: {exc}", file=sys.stderr)
        print(f"  !! raw output: {raw[:400]}", file=sys.stderr)
        return None


def render(ticket: dict, triage: TicketTriage) -> None:
    mark = PRIORITY_MARK.get(triage.priority.value, "[??]")
    print(f"\n{'=' * 78}")
    print(f"{mark} {ticket['ticket_id']}  ({ticket['channel']})")
    print(f"{'=' * 78}")
    print(f"  category        : {triage.category.value}")
    print(f"  sentiment       : {triage.sentiment.value}")
    print(f"  order id        : {triage.order_id}")
    print(f"  needs lookup    : {'yes' if triage.policy_dependent else 'no'}")
    print(f"  confidence      : {triage.confidence:.2f}")
    print(f"\n  summary         : {triage.summary}")
    print(f"  internal note   : {triage.internal_note}")
    print("\n  --- draft reply ---")
    for line in _wrap(triage.suggested_reply, 72):
        print(f"  {line}")


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


async def main() -> None:
    parser = argparse.ArgumentParser(description="Aurora ticket triage assistant")
    parser.add_argument("--ticket", help="Run a single ticket ID from the sample set")
    parser.add_argument("--text", help="Run ad-hoc ticket text")
    args = parser.parse_args()

    verify_credentials()

    if args.text:
        triage = await triage_one(args.text)
        if triage:
            render({"ticket_id": "AD-HOC", "channel": "cli"}, triage)
        return

    tickets = load_tickets()
    if args.ticket:
        tickets = [t for t in tickets if t["ticket_id"] == args.ticket]
        if not tickets:
            print(f"No ticket with id {args.ticket}")
            return

    print(f"Triaging {len(tickets)} ticket(s) with {root_agent.model} ...")

    # Tickets are independent, so fan them out. This is also the cheapest
    # latency win available in batch GenAI workloads and costs three lines.
    results = await asyncio.gather(*(triage_one(t["text"]) for t in tickets))

    escalations = 0
    for ticket, triage in zip(tickets, results):
        if triage is None:
            continue
        render(ticket, triage)
        if triage.priority.value == "P1":
            escalations += 1

    ok = sum(1 for r in results if r is not None)
    print(f"\n{'=' * 78}")
    print(f"Done: {ok}/{len(tickets)} triaged, {escalations} flagged P1.")
    print("Note TKT-40124 — the prompt-injection attempt should be caught by")
    print("constraint 5 in prompts.py rather than obeyed.")


if __name__ == "__main__":
    asyncio.run(main())
