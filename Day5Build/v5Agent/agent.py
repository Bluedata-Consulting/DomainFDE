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

What this version optimises, and why:
  * the id-taking tools take LISTS, so a lane with ten order ids spends one
    turn instead of ten -- the query count stays flat in the number of ids;
  * every tool result carries row_count / truncated / window, and a request
    for more rows than the cap is clamped and says so. Hiding the caps was
    why a lane that got exactly 50 rows re-asked for 1000;
  * each lane gets only the slice of the ontology its own tools serve, and no
    goodwill policy -- it is forbidden to offer anything anyway;
  * each lane gets `execute_sql` restricted to its own tables by SQLite's
    authorizer, plus those tables' columns in its instruction. The partition
    survives, and the lane never spends turns discovering the schema;
  * a before_tool_callback dedups repeat calls within an invocation and caps
    how many calls one lane may spend.

The ontology is validated against roastery.db at import time -- a drifted
ontology fails here, not three turns into a trace.

Run locally with:
    adk web        (from the Day5Build folder, then pick "v4Agent")
    adk run v4Agent
"""

from google.adk.telemetry.google_cloud import get_gcp_exporters
from google.adk.telemetry.setup import maybe_set_otel_providers

import os
os.environ.setdefault("OTEL_SERVICE_NAME", "v5Agent")
maybe_set_otel_providers([get_gcp_exporters(enable_cloud_tracing=True,
                                            enable_cloud_metrics=True,
                                            enable_cloud_logging=True)])


import hashlib
import json
import logging
import re
import threading
from collections import OrderedDict
from typing import Any, Literal

from google.adk.agents import Agent
from google.adk.agents.context import Context
from google.adk.tools import ToolContext
from google.adk.workflow import START, Workflow, node
from google.genai import types

from . import tools as tool_module
from .ontology_loader import lane_tables, load, prompt_core, typed_tools
from .prompts import MERGER_INSTRUCTION, POLICY_INSTRUCTION
from .tools.knowledge import KNOWLEDGE_TOOLS

logger = logging.getLogger(__name__)

MODEL = "gemini-3.5-flash"

# Whether lanes get raw SQL at all. Measured on 2026-09-24: with SQL granted,
# the lanes abandoned the business tools for it (a 0:24 domain:SQL ratio on one
# question) and then refined queries one per turn, hitting the call budget in
# every lane. Pre-injecting the schema removed schema DISCOVERY but not query
# REFINEMENT, which is where the turns went. Set via env so the trade can be
# re-measured without editing code.
LANE_SQL_ENABLED = os.environ.get("V4_LANE_SQL", "0") == "1"


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
# instrumentation and the tool-call guard
# --------------------------------------------------------------------------

# Most ids a single lane may spend on tool calls before it must write up. This
# counts CALLS, not steps: a step that fires four calls in parallel spends four.
# Keep it consistent with the "four steps" wording in LANE_PREAMBLE.
MAX_TOOL_CALLS_PER_LANE = 12

# invocation_id -> {fingerprint: tool_response} and -> {agent_name: count}.
# Module-level rather than session state because the lanes run concurrently and
# a sibling branch's state delta is not visible until its event is appended,
# so a state-based cache would miss almost every time.
_CALL_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_CALL_COUNTS: "OrderedDict[str, dict]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_MAX_INVOCATIONS = 8  # this is a cache, not a store -- bound it


def _log_usage(*, callback_context, llm_response):
    """Record what each LLM request actually cost. Returns None -- no change."""
    usage = getattr(llm_response, "usage_metadata", None)
    if usage is not None:
        logger.info(
            "usage agent=%s prompt=%s cached=%s output=%s",
            getattr(callback_context, "agent_name", "?"),
            getattr(usage, "prompt_token_count", None),
            getattr(usage, "cached_content_token_count", None),
            getattr(usage, "candidates_token_count", None),
        )
    return None


def _scoped(store: "OrderedDict[str, dict]", invocation_id: str) -> dict:
    """Per-invocation slot in a bounded FIFO store."""
    with _CACHE_LOCK:
        if invocation_id not in store:
            while len(store) >= _MAX_INVOCATIONS:
                store.popitem(last=False)
            store[invocation_id] = {}
        return store[invocation_id]


def _fingerprint(tool_name: str, args: dict) -> str:
    """Identify a call. An omitted arg and an explicit null are the same call."""
    clean = {k: v for k, v in (args or {}).items() if v is not None}
    blob = json.dumps(clean, sort_keys=True, default=str)
    return f"{tool_name}:{hashlib.sha1(blob.encode()).hexdigest()}"


def dedup_before_tool(*, tool, args, tool_context):
    """Budget the lane, and answer a repeat call from cache instead of re-running.

    ADK contract: returning any non-None dict SKIPS tool execution and is used
    as the function response verbatim -- it does not go through the
    ``{"result": ...}`` wrapping a raw return would, so a cached value must
    already be the shape the tool returns.

    This is a guard against waste, not a cure: the model has already paid to
    emit a duplicate call by the time we get here. The cause is addressed by the
    batch tools and the anti-repeat rules in LANE_PREAMBLE.
    """
    invocation_id = getattr(tool_context, "invocation_id", "") or ""
    agent_name = getattr(tool_context, "agent_name", "?")

    counts = _scoped(_CALL_COUNTS, invocation_id)
    with _CACHE_LOCK:
        counts[agent_name] = spent = counts.get(agent_name, 0) + 1
    if spent > MAX_TOOL_CALLS_PER_LANE:
        logger.warning("budget exhausted: %s spent %s calls", agent_name, spent)
        return {
            "error": "tool_budget_exhausted",
            "calls_made": spent - 1,
            "next_step": (
                "You have used this lane's tool budget. Write your finding now "
                "from the results already in this conversation, and list what is "
                "still unknown. Do not call another tool."
            ),
        }

    cached = _scoped(_CALL_CACHE, invocation_id).get(_fingerprint(tool.name, args))
    if cached is None:
        return None  # None -> run the tool normally
    payload = dict(cached)
    payload["cache_note"] = (
        f"Reused, not re-run: this is byte-for-byte the result of an earlier "
        f"{tool.name} call with these same arguments in this investigation. Do "
        "not call it again with these arguments -- to get different data, change "
        "the filters."
    )
    return payload


def remember_after_tool(*, tool, args, tool_context, tool_response):
    """Record a successful result. Returning None leaves the real result intact."""
    if isinstance(tool_response, dict) and "error" not in tool_response:
        _scoped(_CALL_CACHE, getattr(tool_context, "invocation_id", "") or "")[
            _fingerprint(tool.name, args)
        ] = tool_response
    return None


# --------------------------------------------------------------------------
# shared instruction material
# --------------------------------------------------------------------------

# v4 defines its own instructions rather than reusing prompts.INSTRUCTION:
# that text addresses a single analyst holding the whole toolbox, which is not
# what a lane is. prompts.py is left in place for v3 parity.
_SQL_GUIDANCE = """
Use `execute_sql` ONLY when no business tool fits: a join across your tables
or an aggregate none of them exposes. Write ONE query that answers the whole
question -- do not explore with a query per turn, and do not use SQL to
recompute a metric a business tool already owns or to re-derive what a tool
just returned. Your tables and columns are listed below, so never look the
schema up first. When you use SQL, say so in your finding and name the tables.
"""

LANE_PREAMBLE_TEMPLATE = """
You are a data analyst for Meridian Roasters, a speciality coffee roaster in
Portland, Oregon. Today's date is 2026-03-16 -- use this, not the real clock.

You are ONE LANE of a wider investigation. You are not writing the final
answer and you are not talking to the customer. Another agent will merge your
findings with the other lanes'. Ground every claim in your own tools' results.

Ambiguity has already been checked for you. The question was run through the
ontology resolver before you were called and the result is in the "Resolution
note" section below. Read it first. If it reports more than one person
matching a name, say so in your finding and do not pick one silently. If it
gives the reading of a loaded word (order, shipment, contact, lead time, lot,
batch, at risk), use that reading. If it is empty, nothing was ambiguous.

PLAN, THEN CALL
Before you call anything, decide the smallest set of calls that could answer
the question. Then issue the independent ones together in a single step -- they
run in parallel, so one step with four calls costs far less than four steps.

Aim to finish within FOUR steps. If you are on your fourth, write your finding
from what you have and name what is still unknown: a partial finding with the
gap named is worth more than another query.

PASS IDS IN BULK
Tools that take an id take a LIST of ids. If you have ten order ids, make ONE
call with all ten -- never ten calls with one id each. The cost of a batch call
is the same whether you pass one id or twenty-five.

NEVER REPEAT A CALL
- Do not call the same tool twice with the same arguments. Its result is
  already in this conversation -- re-read it instead.
- Do not re-call a tool with a bigger `limit`. Every list tool's `limit` is
  already at its cap and a larger value is clamped straight back to it, so you
  would get the identical rows. `truncated: false` means you have everything;
  `truncated: true` means you already hold every row that tool will return. To
  see different rows, change the FILTERS, not the limit.
- Every result carries `row_count` and a `window` saying what it actually
  covered. Quote those rather than re-running a tool to check.
- An empty result or an error IS an answer. Report it; do not retry the same
  call hoping for something different.

CHOOSING A TOOL
Your business tools are named after questions, not tables. They encode the
house metric definitions -- which rows are excluded, which denominator is used
-- and those definitions are authoritative, so a tool that fits the question is
always the right answer over anything you could assemble yourself.
{SQL_GUIDANCE}
You hold only your own lane's tools; that is deliberate. If the cause looks
like it lies outside them, name that as an open question rather than working
around it.

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

LANE_PREAMBLE = LANE_PREAMBLE_TEMPLATE.replace(
    "{SQL_GUIDANCE}", _SQL_GUIDANCE if LANE_SQL_ENABLED else ""
)

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

# The four database lanes. `policy` is deliberately NOT one of them: it has
# no database tools, no ontology slice and no table allowlist, so it is built
# separately below. Keeping it out of LANES keeps every database-lane helper
# (tables, prompt_core slice, scoped SQL) from trying to apply to it.
LANES: tuple[str, ...] = ("care", "delivery", "supply", "finance")

# Every lane the classifier may route to, database or not.
ALL_LANES: tuple[str, ...] = LANES + ("policy",)

# state key each lane writes its finding to.
FINDING_KEY = {lane: f"finding_{lane}" for lane in ALL_LANES}

# Tables every lane may read regardless: reference data that is a join target
# everywhere and gives nothing away about another lane.
SHARED_TABLES: tuple[str, ...] = ("products",)


def _sql_tables_for(lane: str) -> tuple[str, ...]:
    """Tables a lane's `execute_sql` may read.

    The rule is: exactly the tables the lane's OWN tools already read. That
    keeps the partition honest in both directions -- SQL can reach no data the
    lane could not already obtain through a tool, and it is never refused data
    its own tools hand back. Deriving it from the tools' source rather than
    listing it by hand means a tool that grows a JOIN cannot drift out of step.

    Note the consequence: the delivery lane can read `tickets`, because its own
    `get_sales_order_detail` returns the order's tickets. The lane boundary is
    "what this lane's tools expose", not "one table per entity".
    """
    real = set(tool_module.list_tables())
    by_name = {f.__name__: f for f in tool_module.ALL_TOOLS}
    reached: set[str] = set(SHARED_TABLES)
    for name in LANE_TOOL_NAMES[lane]:
        reached |= tool_module.sqltools.tables_in_source(by_name[name])
    return tuple(sorted(reached & real))


LANE_TABLES: dict[str, tuple[str, ...]] = {lane: _sql_tables_for(lane) for lane in LANES}

# Deliberately NOT cross-checked against `lane_tables()` (the ontology's
# entity-derived view). The two answer different questions: a param declared as
# `from: WholesaleAccount.account_id` tells a lane what an account_id MEANS
# without any of its tools reading `wholesale_accounts`. Prompt scoping and
# table access are not the same set, and conflating them fails on real data.


def _lane_instruction(lane: str) -> str:
    """Assemble one lane's system instruction.

    Only the slice of the ontology this lane's tools actually serve, no goodwill
    policy (a lane may not offer anything), plus the lane's own table columns so
    it can write SQL without spending turns discovering the schema.
    """
    return (
        LANE_PREAMBLE
        + "\n"
        + LANE_SCOPES[lane]
        + "\n\n"
        + prompt_core(LANE_TOOL_NAMES[lane], include_policy=False)
        + (
            "\n\n### Your tables (you can read these and no others)\n"
            + tool_module.compact_schema(LANE_TABLES[lane])
            + "\n"
            if LANE_SQL_ENABLED
            else ""
        )
        + RESOLUTION_BLOCK
    )


def _lane_tools(lane: str) -> list:
    """The lane's business tools, plus an `execute_sql` locked to its tables.

    The SQL tool is opt-in: see LANE_SQL_ENABLED for why it is off by default.
    """
    tools = _tools_named(*LANE_TOOL_NAMES[lane])
    if LANE_SQL_ENABLED:
        tools.append(tool_module.make_scoped_execute_sql(LANE_TABLES[lane], lane))
    return tools


lane_agents: dict[str, Agent] = {
    lane: Agent(
        name=f"{lane}_agent",
        model=MODEL,
        description=LANE_SCOPES[lane].split(".")[0].removeprefix("YOUR LANE: "),
        instruction=_lane_instruction(lane),
        tools=_lane_tools(lane),
        output_key=FINDING_KEY[lane],
        before_tool_callback=dedup_before_tool,
        after_tool_callback=remember_after_tool,
        after_model_callback=_log_usage,
    )
    for lane in LANES
}


# --------------------------------------------------------------------------
# the policy lane
# --------------------------------------------------------------------------

# Holds the retrieval tools and NO database tools at all. This mirrors the
# database lanes' separation and is the point of v5: the data lanes answer
# what happened, this lane answers what the rules are, and the merger applies
# one to the other. The database lanes get no retrieval access in return.
POLICY_LANE_SCOPE = (
    "policy: rules, caps, approval authority, contract terms, quality"
    " specifications, what we are allowed to do, and whether something like"
    " this has happened before."
)

policy_agent = Agent(
    name="policy",
    model=MODEL,
    description="Answers from the policy, quality, procurement and incident documents.",
    instruction=POLICY_INSTRUCTION + RESOLUTION_BLOCK,
    tools=list(KNOWLEDGE_TOOLS),
    output_key=FINDING_KEY["policy"],
    before_tool_callback=dedup_before_tool,
    after_tool_callback=remember_after_tool,
    after_model_callback=_log_usage,
)

lane_agents["policy"] = policy_agent


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

{chr(10).join(f"- {lane}: {LANE_SCOPES[lane].split('.')[0].removeprefix('YOUR LANE: ')}" for lane in LANES)}
- {POLICY_LANE_SCOPE}

Route to policy IN ADDITION to a data lane whenever a question asks what we
may offer, what we are allowed to do, what the rule is, whether something
breached a term, or whether there is precedent. Those questions need both the
facts and the rule. A question that is purely about a rule needs policy
alone.

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
    # A JSON array is the whole output; ask the model for JSON rather than
    # scraping prose. _parse_json_array stays as the belt-and-braces fallback,
    # because the failure path here fans out to all four lanes.
    generate_content_config=types.GenerateContentConfig(
        temperature=0.0,
        response_mime_type="application/json",
    ),
    after_model_callback=_log_usage,
)


@node(rerun_on_resume=True)
async def classify(ctx: Context) -> str:
    """Choose the lanes, then fan out to all of them at once.

    Setting ``ctx.route`` to a LIST makes ADK follow every matching edge, so
    a two-intent question runs two lanes concurrently.
    """
    question = ctx.state.get("question", "")

    verdict = await ctx.run_node(classifier, node_input=question)
    chosen = [lane for lane in _parse_json_array(_as_text(verdict)) if lane in ALL_LANES]
    # De-duplicate while keeping the graph's lane order deterministic.
    chosen = [lane for lane in ALL_LANES if lane in chosen]

    if not chosen:
        # Unparseable or empty: run every lane rather than silently dropping
        # coverage. Wasteful, but never wrong about which lane was consulted.
        logger.warning(
            "classify: could not read a lane list from %r -- running all lanes",
            _as_text(verdict)[:200],
        )
        chosen = list(ALL_LANES)

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
    selected = list(ctx.state.get("lanes") or ALL_LANES)
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


merger = Agent(
    name="merger",
    model=MODEL,
    description="Merges the lane findings into one answer, keeping distinct causes distinct.",
    instruction=MERGER_INSTRUCTION + "\n" + prompt_core() + RESOLUTION_BLOCK,
    # create_case_action lives here and ONLY here -- a lane must not be able
    # to propose a gesture off its own partial view of the case.
    tools=[create_case_action],
    output_key="answer",
    after_model_callback=_log_usage,
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
    name="v5",
    description=(
        "Answers questions about Meridian Roasters by fanning out to the"
        " business lanes a question needs, then merging their findings."
    ),
    edges=[
        (START, capture),
        (capture, resolve_node),
        (resolve_node, classify),
        (classify, {lane: lane_agents[lane] for lane in ALL_LANES}),
        (tuple(lane_agents[lane] for lane in ALL_LANES), join),
        (join, {"ready": merger}),
        (merger, authority),
    ],
)
