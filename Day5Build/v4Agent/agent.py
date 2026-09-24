"""v4 ontology-driven agent for the Meridian Roasters case, built on Google ADK.

v3 was one analyst holding every tool. v4 splits it into four lane agents that
each see only their own corner of the business, runs only the lanes a question
actually needs, and merges their findings:

    START -> capture -> resolve -> classify
                                     |
              +----------+-----------+-----------+
              v          v           v           v
            care     delivery      supply     finance      (only those chosen)
              +----------+-----------+-----------+
                                     v
                                   join -> merger -> authority

Why the split. A lane that cannot see the tickets table cannot blame a ticket
for a late shipment, so each lane's finding is grounded in the data it was
actually given. `merger` is the only agent that sees all four findings, and
the only one allowed to propose an action.

Two things carry over from v3 and matter here:
  * resolution is a graph stage, not something an agent asks for -- the
    `resolve` node runs first and lanes read its note from state;
  * nothing in this graph may act. `create_case_action` proposes, and
    `authority` checks that proposal against the ontology's goodwill policy.

The ontology is validated against roastery.db at import time -- a drifted
ontology fails here, not three turns into a trace.

Run locally with:
    adk web        (from the Day5Build folder, then pick "v4Agent")
    adk run v4Agent
"""

from google.adk.telemetry.google_cloud import get_gcp_exporters
from google.adk.telemetry.setup import maybe_set_otel_providers

import os
os.environ.setdefault("OTEL_SERVICE_NAME", "v4Agent")
maybe_set_otel_providers([get_gcp_exporters(enable_cloud_tracing=True,
                                            enable_cloud_metrics=True,
                                            enable_cloud_logging=True)])


import json
import logging
import re
from typing import Any, Literal

from google.adk.agents import Agent
from google.adk.agents.context import Context
from google.adk.tools import ToolContext
from google.adk.workflow import START, Workflow, node
from google.genai import types

from . import tools as tool_module
from .ontology_loader import load, prompt_core, typed_tools

logger = logging.getLogger(__name__)

MODEL = "gemini-3.5-flash"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _as_text(value: Any) -> str:
    """Flatten whatever a node or agent handed back into plain text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, types.Content):
        return "".join(p.text for p in (value.parts or []) if p.text)
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value)


def _parse_json_array(raw: str) -> list[str]:
    """Pull a JSON array of strings out of a model reply."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip()

    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _tools_named(*names: str) -> list:
    """Look tools up by name and give them ontology-generated signatures.

    Fails loudly: a lane that asks for a tool the tool module does not export
    is a typo, and should not quietly become a lane with fewer tools.
    """
    by_name = {func.__name__: func for func in tool_module.ALL_TOOLS}
    missing = [n for n in names if n not in by_name]
    if missing:
        raise ValueError(f"unknown tool(s): {', '.join(missing)}")
    return typed_tools([by_name[n] for n in names])


# --------------------------------------------------------------------------
# shared instruction material
# --------------------------------------------------------------------------

# v4 defines its own instructions rather than reusing prompts.INSTRUCTION:
# that text tells a single analyst to pick from the whole toolbox and to fall
# back to raw SQL, and neither applies to a lane that holds seven tools and no
# SQL escape hatch. prompts.py is left in place for v3 parity.
LANE_PREAMBLE = """
You are a data analyst for Meridian Roasters, a speciality coffee roaster in
Portland, Oregon. Today's date is 2026-03-16 -- use this, not the real clock.

You are ONE LANE of a wider investigation. You are not writing the final
answer and you are not talking to the customer. Another agent will merge your
findings with the other lanes'. Report what your own tools show and nothing
else.

Ambiguity has already been checked for you. The question was run through the
ontology resolver before you were called and the result is in the "Resolution
note" section below. Read it first. If it reports more than one person
matching a name, say so in your finding and do not pick one silently. If it
gives the reading of a loaded word (order, shipment, contact, lead time, lot,
batch, at risk), use that reading. If it is empty, nothing was ambiguous.

HOW TO WORK
Use only the tools you have been given. They are named after business
questions, not tables -- read their descriptions and choose the closest fit,
and chain them when a finding needs more than one step. You have no raw-SQL
access and no tools outside your lane; that is deliberate.

If the question does not touch your lane at all, say exactly that in one
line. Do not speculate about another lane's territory -- if you think the
cause lies outside your tools, name that as an open question rather than
asserting it.

REPORTING
- Base every claim on a tool result. Never invent numbers or ids.
- Name the tools you used and the date range you covered.
- Give the ids (order, shipment, lot, ticket, supplier) behind each claim, so
  the merger can line your finding up against the other lanes'.
- If your tools do not answer the question, say so plainly.
- Do not offer the customer anything. You may not promise a refund, a credit
  or a replacement -- that is not a lane's decision.
- Be short and concrete.
"""

RESOLUTION_BLOCK = """

## Question
{question?}

## Resolution note (from the ontology resolver, may be empty)
{resolution_note?}
"""


# --------------------------------------------------------------------------
# lanes
# --------------------------------------------------------------------------

LANE_SCOPES: dict[str, str] = {
    "care": (
        "YOUR LANE: customer care. Who the customer is, what they have"
        " complained about, the ticket history and its trend, and which of"
        " their orders the complaint concerns. You own the customer's account"
        " and their words -- not the physical shipment and not the coffee."
    ),
    "delivery": (
        "YOUR LANE: fulfilment and delivery. Where an outbound shipment is,"
        " whether it is late and by how much, and which orders are affected."
        " You own what happened to the parcel after it left -- not why the"
        " coffee was short and not what the customer said about it."
    ),
    "supply": (
        "YOUR LANE: procurement and production. Suppliers, purchase orders,"
        " inbound green coffee, supplier performance, the lot behind a"
        " product, roast batches and stock on hand. You own everything"
        " upstream of the sale -- not the outbound parcel and not the ticket."
    ),
    "finance": (
        "YOUR LANE: finance. Order values, what was charged, discounts and"
        " the customer's commercial standing and tier. You own the money --"
        " not the logistics and not the coffee. State the tier and segment"
        " (d2c or wholesale) when you can find them, because the goodwill cap"
        " depends on them."
    ),
}

LANE_TOOL_NAMES: dict[str, tuple[str, ...]] = {
    "care": (
        "find_customers",
        "get_customer_360",
        "find_wholesale_contacts",
        "find_tickets",
        "get_ticket_thread",
        "ticket_trend",
        "find_sales_orders",
        "get_sales_order_detail",
    ),
    "delivery": (
        "get_shipment_status",
        "find_late_shipments",
        "find_sales_orders",
        "get_sales_order_detail",
    ),
    "supply": (
        "find_suppliers",
        "find_purchase_orders",
        "get_inbound_shipments",
        "get_supplier_performance",
        "trace_product_to_lot",
        "find_roast_batches",
        "get_inventory_position",
    ),
    "finance": (
        "find_sales_orders",
        "get_sales_order_detail",
        "get_customer_360",
    ),
}

LANES: tuple[str, ...] = ("care", "delivery", "supply", "finance")

# state key each lane writes its finding to.
FINDING_KEY = {lane: f"finding_{lane}" for lane in LANES}

lane_agents: dict[str, Agent] = {
    lane: Agent(
        name=f"{lane}_agent",
        model=MODEL,
        description=LANE_SCOPES[lane].split(".")[0].removeprefix("YOUR LANE: "),
        instruction=(
            LANE_PREAMBLE
            + "\n"
            + LANE_SCOPES[lane]
            + "\n\n"
            + prompt_core()
            + RESOLUTION_BLOCK
        ),
        tools=_tools_named(*LANE_TOOL_NAMES[lane]),
        output_key=FINDING_KEY[lane],
    )
    for lane in LANES
}


# --------------------------------------------------------------------------
# capture / resolve
# --------------------------------------------------------------------------


@node
async def capture(ctx: Context) -> str:
    """Read the question off the invocation and seed the state keys."""
    question = _as_text(ctx.user_content).strip()

    ctx.state["question"] = question
    ctx.state["resolution_note"] = ""
    ctx.state["lanes"] = []
    ctx.state["arrived"] = []
    ctx.state["proposal"] = {}
    ctx.state["authority_flags"] = ""
    for key in FINDING_KEY.values():
        ctx.state[key] = ""

    return question


@node(name="resolve")
async def resolve_node(ctx: Context) -> str:
    """Run the ontology resolver on the question before any lane sees it."""
    from .ontology_loader import resolve as resolve_tool

    question = ctx.state.get("question", "")
    ctx.state["resolution_note"] = resolve_tool(question) if question else ""
    return question


# --------------------------------------------------------------------------
# classify
# --------------------------------------------------------------------------

CLASSIFIER_INSTRUCTION = f"""
You route a business question to the lanes that must investigate it. The
lanes are:

{chr(10).join(f"- {lane}: {LANE_SCOPES[lane]}" for lane in LANES)}

Pick EVERY lane whose tools are needed. Most questions need one. A question
with two intents ("why was it late, and what do we owe them?") needs two or
more -- pick them all rather than guessing which matters most. Do not pick a
lane merely because it might be interesting.

Reply with a JSON array of lane names and nothing else, for example:
["delivery","supply"]
"""

classifier = Agent(
    name="classifier",
    model=MODEL,
    description="Chooses which lanes must investigate a question.",
    instruction=CLASSIFIER_INSTRUCTION,
)


@node(rerun_on_resume=True)
async def classify(ctx: Context) -> str:
    """Choose the lanes, then fan out to all of them at once.

    Setting ``ctx.route`` to a LIST makes ADK follow every matching edge, so
    a two-intent question runs two lanes concurrently.
    """
    question = ctx.state.get("question", "")

    verdict = await ctx.run_node(classifier, node_input=question)
    chosen = [lane for lane in _parse_json_array(_as_text(verdict)) if lane in LANES]
    # De-duplicate while keeping the graph's lane order deterministic.
    chosen = [lane for lane in LANES if lane in chosen]

    if not chosen:
        # Unparseable or empty: run every lane rather than silently dropping
        # coverage. Wasteful, but never wrong about which lane was consulted.
        logger.warning(
            "classify: could not read a lane list from %r -- running all lanes",
            _as_text(verdict)[:200],
        )
        chosen = list(LANES)

    ctx.state["lanes"] = chosen
    ctx.state["arrived"] = []
    ctx.route = chosen
    return question


# --------------------------------------------------------------------------
# join
# --------------------------------------------------------------------------

# NOTE: this is deliberately NOT google.adk.workflow.JoinNode. JoinNode sets
# `_requires_all_predecessors`, which waits for all four *static* predecessors
# to reach COMPLETED. A lane that classify never routed to never runs, so it
# never completes, the barrier never fires, and join/merger/authority are
# silently skipped -- the workflow ends with no answer and no error. This node
# waits for the lanes that were actually triggered. ADK serialises repeat runs
# of the same node, so the arrival count below is not racing.
@node(name="join")
async def join(ctx: Context, node_input: Any = None) -> str:
    """Wait for every lane classify actually chose, then release the merger."""
    selected = list(ctx.state.get("lanes") or LANES)
    arrived = list(ctx.state.get("arrived") or [])
    arrived.append(len(arrived))
    ctx.state["arrived"] = arrived

    if len(arrived) < len(selected):
        # No edge matches "wait", so this branch ends here; the next lane to
        # finish re-triggers this node. ADK logs that no edge matched -- that
        # log line is this barrier working, not a misconfiguration.
        ctx.route = "wait"
        return ""

    findings = [
        f"### Finding from the {lane} lane\n{_as_text(ctx.state.get(FINDING_KEY[lane])).strip()}"
        for lane in selected
        if _as_text(ctx.state.get(FINDING_KEY[lane])).strip()
    ]
    ctx.route = "ready"
    return "\n\n".join(findings) if findings else "No lane returned a finding."


# --------------------------------------------------------------------------
# merger
# --------------------------------------------------------------------------


def create_case_action(
    customer_id: str,
    segment: Literal["d2c", "wholesale"],
    tier: str,
    amount_usd: float,
    reason: str,
    tool_context: ToolContext,
    approved_by: str = "",
) -> dict:
    """Propose a goodwill gesture as a case action for a human to approve.

    This PROPOSES only. It does not issue a refund, a credit or a
    replacement, and nothing downstream of it will. Call it when the findings
    justify offering the customer something, then tell the customer it has
    been proposed for approval -- never that it has been done.

    Args:
        customer_id: The customer the gesture is for.
        segment: Which cap table applies -- "d2c" or "wholesale".
        tier: The customer's tier, which sets the cap (for example "gold").
        amount_usd: The gesture in USD.
        reason: Why this gesture, in one sentence, citing the findings.
        approved_by: The named human who already approved it, if one has.
            Leave empty if nobody has approved it yet.

    Returns:
        The proposal as recorded, for you to describe in your answer.
    """
    proposal = {
        "customer_id": customer_id,
        "segment": segment,
        "tier": tier,
        "amount_usd": float(amount_usd),
        "reason": reason,
        "approved_by": approved_by,
        "status": "proposed",
    }
    tool_context.state["proposal"] = proposal
    return {
        "recorded": proposal,
        "note": (
            "Proposed only. No refund, credit or replacement has been issued."
            " Describe this as awaiting approval."
        ),
    }


MERGER_INSTRUCTION = """
You are the analyst who answers the business. Several lanes have each
investigated the question with their own tools, and their findings are below.
You have no data tools of your own: use ONLY what the findings contain. If
they do not establish something, you do not know it.

KEEP DISTINCT CAUSES DISTINCT
Do not blend two problems into one explanation. Two things can go wrong at
the same time for unrelated reasons -- a late parcel and a short lot are two
findings, not one story. If the lanes point at different causes, report them
as separate causes, each with the ids and the lane that found it. Only join
them into one explanation if a finding actually shows the link; if you are
inferring the link, say that you are inferring it.

If the lanes disagree, say so and give both readings. Do not average them and
do not pick the tidier one. If a lane reported an unresolved ambiguity (two
people matching a name, for example), carry it through to your answer and ask
which was meant.

PROPOSING A GESTURE
If the findings justify offering the customer something, call
`create_case_action` to propose it. You may propose; you may not act. Never
write "I have issued", "a credit has been applied", or anything else implying
the money has moved -- say it has been proposed for approval. The goodwill
caps in the ontology are ceilings, not defaults, and a tier does not entitle
a customer to its cap.

ANSWERING
- Attribute each claim to the lane and the ids behind it.
- Say which lanes ran and over what date range.
- If the findings do not answer the question, say so plainly.
- Keep it short and in business language, with the numbers that matter.
"""

merger = Agent(
    name="merger",
    model=MODEL,
    description="Merges the lane findings into one answer, keeping distinct causes distinct.",
    instruction=MERGER_INSTRUCTION + "\n" + prompt_core() + RESOLUTION_BLOCK,
    # create_case_action lives here and ONLY here -- a lane must not be able
    # to propose a gesture off its own partial view of the case.
    tools=[create_case_action],
    output_key="answer",
)


# --------------------------------------------------------------------------
# authority
# --------------------------------------------------------------------------

# Phrases that claim the money already moved. The system may propose, never act.
_ACTION_CLAIMS = (
    re.compile(r"\bI\s+have\s+issued\b", re.I),
    re.compile(r"\bcredit\s+has\s+been\s+applied\b", re.I),
)


@node
async def authority(ctx: Context) -> str:
    """Check the proposal against the ontology's goodwill policy.

    Reads the policy block from the ontology rather than hard-coding the
    numbers, so a change to ontology.yaml changes the gate.
    """
    policy = load()["policy"]
    caps = policy["goodwill_caps"]
    currency = policy["currency"]
    approval_above = policy["human_approval_required_above"]

    flags: list[str] = []
    existing = _as_text(ctx.state.get("authority_flags")).strip()
    if existing:
        flags.append(existing)

    proposal = ctx.state.get("proposal") or {}
    if isinstance(proposal, dict) and proposal.get("amount_usd") is not None:
        amount = float(proposal["amount_usd"])
        segment = str(proposal.get("segment", "")).lower()
        tier = str(proposal.get("tier", "")).lower()
        approver = str(proposal.get("approved_by", "")).strip()

        tier_caps = caps.get(segment, {})
        cap = tier_caps.get(tier)

        if cap is None:
            flags.append(
                f"APPROVAL REQUIRED: {amount:.2f} {currency} proposed, but"
                f" segment/tier {segment or '?'}/{tier or '?'} is not in the"
                " goodwill policy, so no cap could be applied. A human must"
                " confirm the customer's tier before this is offered."
            )
        elif amount > cap:
            flags.append(
                f"BLOCKED: {amount:.2f} {currency} proposed, above the"
                f" {segment} {tier} cap of {cap} {currency}. This may not be"
                " offered to the customer."
            )

        if amount > approval_above and not approver:
            flags.append(
                f"APPROVAL REQUIRED: {amount:.2f} {currency} proposed, above"
                f" the {approval_above} {currency} threshold, with no named"
                " approver. A named human must approve it before it is"
                " offered."
            )

    answer = _as_text(ctx.state.get("answer"))
    for pattern in _ACTION_CLAIMS:
        if pattern.search(answer):
            flags.append(
                f"BLOCKED: the answer claims an action was taken"
                f' ("{pattern.search(answer).group(0)}"). This system may'
                " propose a gesture, never act on one. Rewrite it as"
                " proposed-for-approval before it reaches the customer."
            )
            break

    ctx.state["authority_flags"] = "\n".join(flags)

    if not flags:
        return answer
    # Terminal node, so this is the workflow's output: a flag nobody sees is
    # not a control, so surface it alongside the answer.
    return answer + "\n\n---\nAUTHORITY FLAGS\n" + "\n".join(flags)


# --------------------------------------------------------------------------
# graph
# --------------------------------------------------------------------------

root_agent = Workflow(
    name="v4",
    description=(
        "Answers questions about Meridian Roasters by fanning out to the"
        " business lanes a question needs, then merging their findings."
    ),
    edges=[
        (START, capture),
        (capture, resolve_node),
        (resolve_node, classify),
        (classify, {lane: lane_agents[lane] for lane in LANES}),
        (tuple(lane_agents[lane] for lane in LANES), join),
        (join, {"ready": merger}),
        (merger, authority),
    ],
)
