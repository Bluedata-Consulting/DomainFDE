"""v3 ontology-driven agent for the Meridian Roasters case, built on Google ADK.

Same tools as v2 -- what changes is the shape. v2 was a single Agent that
answered in one shot; v3 is a `Workflow` graph, so the answer passes through
explicit stages that can be inspected in a trace:

    START -> capture -> resolve -> analyst -> completeness -> authority
                                      ^            |
                                      +-- incomplete

  * `capture` lifts the question out of the invocation and seeds state;
  * `resolve` runs the ontology resolver up front, so the analyst starts
    with the ambiguity note already in hand rather than having to ask;
  * `analyst` is the v2 Agent with the same tools, plus two placeholders so
    it can see the resolution note and whatever a previous pass was judged
    to have missed. Its HOW TO WORK block is the one thing that had to
    change: resolving is now the graph's job, so the analyst is told to read
    the note rather than lead with a `resolve` call of its own;
  * `completeness` asks a small tool-less Agent what the answer does not
    yet cover, and loops back to the analyst while anything is missing;
  * `authority` is a deliberate no-op placeholder -- it exists so v4 can
    fill it in without changing the graph shape.

The ontology is validated against roastery.db at import time -- a drifted
ontology fails here, not three turns into a trace.

Run locally with:
    adk web        (from the Day5Build folder, then pick "v3Agent")
    adk run v3Agent
"""

from google.adk.telemetry.google_cloud import get_gcp_exporters
from google.adk.telemetry.setup import maybe_set_otel_providers

import os
os.environ.setdefault("OTEL_SERVICE_NAME", "v3Agent")
maybe_set_otel_providers([get_gcp_exporters(enable_cloud_tracing=True,
                                            enable_cloud_metrics=True,
                                            enable_cloud_logging=True)])


import json
import logging
from typing import Any

from google.adk.agents import Agent
from google.adk.agents.context import Context
from google.adk.workflow import DEFAULT_ROUTE, START, Workflow, node
from google.genai import types

from .ontology_loader import prompt_core, resolve, typed_tools
from .prompts import INSTRUCTION
from .tools import DOMAIN_TOOLS, SQL_TOOLS

logger = logging.getLogger(__name__)

MODEL = "gemini-3.5-flash"

# How many analyst passes we allow before shipping whatever we have. The
# completeness check is advisory, not a gate -- a question it never judges
# fully covered must not loop forever.
MAX_PASSES = 4

# Derived tools get ontology-generated signatures; the generic SQL fallback
# is left exactly as it is.
TOOLS = [resolve] + typed_tools(DOMAIN_TOOLS) + SQL_TOOLS


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


# --- capture ----------------------------------------------------------------


@node
async def capture(ctx: Context) -> str:
    """Read the question off the invocation and seed the state keys."""
    question = _as_text(ctx.user_content).strip()

    ctx.state["question"] = question
    ctx.state["missing"] = ""
    ctx.state["resolution_note"] = ""
    # A counter, so "empty" is 0 -- `completeness` increments it each pass.
    ctx.state["passes"] = 0

    return question


# --- resolve ----------------------------------------------------------------


@node(name="resolve")
async def resolve_node(ctx: Context) -> str:
    """Run the ontology resolver on the question before the analyst sees it."""
    question = ctx.state.get("question", "")
    note = resolve(question) if question else ""

    ctx.state["resolution_note"] = note

    # The note goes to the analyst through the {resolution_note?} placeholder,
    # not through here: an LlmAgent node turns its input into a user-role turn,
    # so this must be the question or the analyst is asked the wrong thing.
    return question


# --- analyst ----------------------------------------------------------------

# The instruction, plus two placeholders. Both are optional (`?`), so a pass
# where they are empty renders cleanly. `resolution_note` is how the resolve
# node's output reaches the analyst -- see the v3 note in prompts.py for why
# the analyst is told to read it instead of calling `resolve` itself.
ANALYST_INSTRUCTION = (
    INSTRUCTION
    + "\n\n"
    + prompt_core()
    + """

## Resolution note (from the ontology resolver, may be empty)
{resolution_note?}

## Not yet covered by your previous answer (may be empty)
{missing?}

If the section above lists anything, you have already answered this question
once and the answer was judged incomplete. Produce a full replacement answer
that covers those points as well as everything you covered before -- do not
reply with only the gaps.
"""
)

analyst = Agent(
    name="roastery_ontology_agent",
    model=MODEL,
    description="Answers questions about Meridian Roasters using its business ontology.",
    instruction=ANALYST_INSTRUCTION,
    tools=TOOLS,
    output_key="answer",
)


# --- completeness -----------------------------------------------------------

COMPLETENESS_INSTRUCTION = """
You check coverage, not correctness. You are given a question and an answer
that was written for it. List the parts of the question the answer does not
yet address -- a sub-question left unanswered, an entity named in the question
and ignored in the answer, a comparison or date range asked for and not given.

Do NOT list: facts you merely doubt, extra analysis nobody asked for, style
preferences, or a point the answer explicitly says the data cannot support --
that is a covered part, not a missing one.

Reply with a JSON array of short strings and nothing else. If the answer
covers the whole question, reply with exactly: []
"""

completeness_checker = Agent(
    name="completeness_checker",
    model=MODEL,
    description="Lists the parts of a question an answer does not yet cover.",
    instruction=COMPLETENESS_INSTRUCTION,
)


def _parse_gaps(raw: str) -> list[str]:
    """Pull a JSON array of strings out of the checker's reply."""
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
        logger.warning("completeness: could not parse checker reply: %r", raw)
        return []

    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


# `rerun_on_resume` is required to schedule a node dynamically via run_node.
@node(rerun_on_resume=True)
async def completeness(ctx: Context) -> str:
    """Loop back to the analyst while the answer still misses part of the question."""
    passes = int(ctx.state.get("passes") or 0) + 1
    ctx.state["passes"] = passes

    question = ctx.state.get("question", "")
    answer = _as_text(ctx.state.get("answer"))

    if passes >= MAX_PASSES:
        # Out of passes. Ship what we have regardless of what is missing.
        ctx.route = "done"
        return answer

    verdict = await ctx.run_node(
        completeness_checker,
        node_input=f"QUESTION:\n{question}\n\nANSWER:\n{answer}",
    )
    gaps = _parse_gaps(_as_text(verdict))

    if gaps:
        ctx.state["missing"] = gaps
        ctx.route = "incomplete"
        # Routed back to the analyst, so this becomes its next user turn: the
        # question again. The gaps reach it via the {missing?} placeholder.
        return question

    ctx.state["missing"] = ""
    ctx.route = "done"
    return answer


# --- authority --------------------------------------------------------------


@node
async def authority(ctx: Context) -> str:
    """Placeholder for the v4 authority check -- deliberately does nothing yet.

    It sits in the graph so v4 can make it real without rewiring anything.
    """
    ctx.state["authority_flags"] = ""
    # Terminal node, so its output is the workflow's: hand back the answer.
    return _as_text(ctx.state.get("answer"))


# --- graph ------------------------------------------------------------------

root_agent = Workflow(
    name="v3",
    description="Answers questions about Meridian Roasters, checking its own coverage.",
    edges=[
        (START, capture),
        (capture, resolve_node),
        (resolve_node, analyst),
        (analyst, completeness),
        (completeness, {"incomplete": analyst, DEFAULT_ROUTE: authority}),
    ],
)
