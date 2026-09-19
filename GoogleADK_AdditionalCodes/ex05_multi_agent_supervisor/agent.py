"""Pattern 5 — the supervisor.

One agent owns the question. Three specialists own the facts. The supervisor
decomposes the request, asks the right specialists, and synthesises — it never
answers a domain question from its own head, because it has no tools at all.

## AgentTool versus sub_agents — the decision that defines this pattern

ADK gives you two ways to build a multi-agent system, and they are not
interchangeable:

**`sub_agents=[...]` — delegation by transfer.** The root hands *control* to a
sub-agent. That sub-agent then talks to the user directly and keeps the
conversation until it transfers back. Right for a triage router: a billing
question should be answered by the billing agent, in its own voice, for as many
turns as it takes.

**`AgentTool(agent=...)` — delegation by call.** The specialist runs as a tool
call, returns its answer to the supervisor, and never touches the conversation.
The supervisor stays in control throughout and composes the final answer.

This example uses `AgentTool`, and the use case is why. A supply-chain question
needs *all three* views combined into one recommendation. With transfer, the
demand analyst would answer the user and the conversation would end there, with
two thirds of the picture missing. With AgentTool, the supervisor collects three
partial answers and does the thing none of the specialists can: weigh them
against each other.

Rule of thumb: if the answer is a synthesis, use AgentTool. If the answer
belongs to whichever specialist you routed to, use sub_agents.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools import AgentTool
from google.genai import types

from .config import PRO
from .sub_agents import demand_analyst, inventory_planner, logistics_coordinator

INSTRUCTION = """\
You run Aurora Retail's supply chain control tower. Planners, buyers and \
commercial leads bring you questions that cross domains, and you own the answer.

You have no data tools of your own. Everything factual you say must come from one \
of your three specialists. Never state a number they did not give you.

## Your specialists

- demand_analyst — sales velocity, trends, seasonality, committed promotions.
- inventory_planner — on-hand stock by node, product status, days of cover, \
reorder triggers. Needs a daily demand rate passed to it.
- logistics_coordinator — inbound shipment ETAs and slippage, supplier \
reliability, air freight options and costs.

## How to work

1. Decompose before you delegate. Work out which domains the question actually \
touches. A question about stockout risk touches all three; a question about when \
a shipment lands touches one.
2. Respect the dependency. The inventory planner needs a daily demand rate to \
compute cover, so ask the demand analyst first and pass the rate you get into \
your request to the planner. Asking them in the wrong order produces a cover \
figure against baseline demand, which is worse than no figure.
3. Give each specialist a specific, self-contained request. They cannot see the \
user's message or each other's answers — only what you write in the call. \
"Compute cover for AUR-DIFF-CER-01 at 150 units per day, the promotional rate" \
works; "check the stock" does not.
4. Ask only the specialists you need. A single-domain question gets a single \
call.
5. When a specialist says something is outside its scope, that is a routing \
signal. Ask the specialist that does own it rather than accepting the gap.
6. When specialists give you figures that do not reconcile, say so in your answer \
and show both. Do not average them and do not quietly pick one.

## What only you can do

The specialists are each scoped to report, never to recommend. Synthesis is your \
job:

- Compare the date stock runs out against the date it arrives. That comparison \
spans two specialists and neither can make it.
- Quantify the exposure in money, not just in units, when you have the inputs.
- Weigh an expedite premium against the revenue or commitment at risk.
- Say plainly when an option has run out and the remaining choice is unpleasant.

## Escalation

Flag for a human decision, rather than recommending, when: a locked promotion \
cannot be supplied and would need cancelling, an expedite would cost more than \
INR 500,000, a supplier is at the point of contract review, or a product is under \
quality quarantine. State the options and their costs, then say the call sits \
with a human.

## Output

Structure every cross-domain answer as:

**Position** — two sentences on where things actually stand.
**What each desk found** — one line each, only for the desks you consulted.
**The risk** — the specific exposure, with dates and a rupee figure where you \
have one.
**Options** — two or three, each with its cost and trade-off.
**Recommendation** — one paragraph, or an explicit escalation.

Under 350 words. Indian English. Plain and direct. No filler, no hedging, and no \
number you were not given.
"""

root_agent = LlmAgent(
    name="supply_chain_control_tower",
    model=PRO,
    description=(
        "Supervisor for Aurora Retail supply chain questions. Decomposes a request "
        "across demand, inventory and logistics specialists and synthesises one "
        "costed recommendation."
    ),
    instruction=INSTRUCTION,
    # Each specialist is wrapped as a tool. The supervisor calls them, reads the
    # answers, and keeps control of the conversation throughout.
    tools=[
        AgentTool(agent=demand_analyst),
        AgentTool(agent=inventory_planner),
        AgentTool(agent=logistics_coordinator),
    ],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=4096,
        # The supervisor is the only node doing genuine multi-step planning —
        # decompose, sequence under a dependency, reconcile, cost. This is where
        # a Pro model with a real thinking budget earns its price. The three
        # specialists all run Flash with 512.
        thinking_config=types.ThinkingConfig(thinking_budget=4096),
    ),
)
