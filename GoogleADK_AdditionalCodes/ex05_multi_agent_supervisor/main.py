"""Run the supply chain control tower.

    python ex05_multi_agent_supervisor/main.py           # scripted scenarios
    python ex05_multi_agent_supervisor/main.py --chat    # interactive
    python ex05_multi_agent_supervisor/main.py --ask "..."
    python ex05_multi_agent_supervisor/main.py --no-trace
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Run as a script, import as a package: the repo root goes on sys.path so
# that `python exNN_x/main.py` and `adk web .` resolve imports identically.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ex05_multi_agent_supervisor.agent import root_agent  # noqa: E402
from ex05_multi_agent_supervisor.config import APP_NAME, USER_ID, verify_credentials  # noqa: E402
from ex05_multi_agent_supervisor.runner import Conversation  # noqa: E402

RULE = "=" * 78

SCENARIOS: list[tuple[str, str]] = [
    (
        "All three domains — the flagship case",
        "The festive home fragrance promotion starts on 2 March. Are we going to "
        "be able to supply the ceramic diffuser, and if not, what are our options?",
        # Expect: demand first (68/day accelerating, 2.2x uplift = ~150/day),
        # inventory second with that rate (98 units, well under a day of cover),
        # logistics third (PO-55210 slipped 14 days to 6 March, supplier at 58%
        # on-time, air freight at INR 310/unit). Synthesis: stock runs out before
        # the promo starts, sea freight lands after it, air freight on 900 units
        # is INR 279,000 -- under the escalation ceiling but the promotion is
        # locked with INR 1.85m committed, so this is a human call.
    ),
    (
        "Single domain — no over-delegation",
        "When is PO-55210 actually going to land?",
        # Expect exactly one specialist call. A supervisor that asks all three
        # here is burning tokens and latency on a question with one owner.
    ),
    (
        "Dependency ordering",
        "How many days of cover do we have on the lavender oil?",
        # Cover needs a demand rate, so the supervisor must ask demand_analyst
        # before inventory_planner, and pass the rate through. Watch the trace
        # for the rate appearing in the second request.
    ),
    (
        "Quarantine — availability is not stock",
        "What's the position on the charcoal scrub? Can we plan any volume on it?",
        # 910 units on hand but quarantined, so available is zero. Any answer
        # that treats the on-hand number as usable stock is wrong.
    ),
    (
        "Attach effect — does it spot the second-order risk?",
        "If the diffuser promotion goes ahead as planned, is there anything else "
        "we should be worried about?",
        # Lavender oil attaches at 0.8 per diffuser and is already accelerating
        # at 143/day with zero on order. The good answer catches that.
    ),
]


async def run_scenarios(trace: bool) -> None:
    for title, message in SCENARIOS:
        print(f"\n{RULE}\n{title}\n{RULE}")
        print(f"planner > {message}\n")

        conversation = Conversation(root_agent, APP_NAME, USER_ID)
        await conversation.start()
        answer = await conversation.send(message, trace=trace)
        print(f"\n{answer}\n")


async def chat(trace: bool) -> None:
    conversation = Conversation(root_agent, APP_NAME, USER_ID)
    await conversation.start()
    print("Supply chain control tower. Type 'exit' to quit.\n")

    while True:
        try:
            line = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line.lower() in {"exit", "quit"}:
            return
        print()
        print(f"\n{await conversation.send(line, trace=trace)}\n")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Aurora supply chain control tower")
    parser.add_argument("--chat", action="store_true", help="Interactive session")
    parser.add_argument("--ask", help="One question and exit")
    parser.add_argument("--no-trace", action="store_true", help="Hide delegation trace")
    args = parser.parse_args()

    verify_credentials()
    trace = not args.no_trace

    if args.chat:
        await chat(trace)
        return

    if args.ask:
        conversation = Conversation(root_agent, APP_NAME, USER_ID)
        await conversation.start()
        print(await conversation.send(args.ask, trace=trace))
        return

    await run_scenarios(trace)

    print(f"\n{RULE}")
    print("Judge the delegation, not just the prose. Three things to check:")
    print("  1. Scenario 2 should use ONE specialist. Over-delegation is the")
    print("     characteristic failure of this pattern.")
    print("  2. Scenario 3 should ask demand first and pass the rate into the")
    print("     inventory request. Wrong order = cover computed against baseline.")
    print("  3. Scenario 1 should escalate rather than recommend: the promotion")
    print("     is locked with INR 1.85m committed and cannot be supplied.")


if __name__ == "__main__":
    asyncio.run(main())
