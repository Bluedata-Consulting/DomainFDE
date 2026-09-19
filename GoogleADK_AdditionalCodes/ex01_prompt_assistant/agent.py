"""Pattern 1 — the prompt-based GenAI assistant.

One model call. No tools, no retrieval, no memory of anything outside the ticket.
Every piece of knowledge the agent has was written into the prompt by a human.

Why this deserves to be pattern 1 rather than a footnote: a very large share of
enterprise GenAI value is exactly this — a well-specified transform from messy
input to a validated object, running at volume, with a human reviewing the
output. It is cheap, it is deterministic enough to evaluate, and it has no
failure mode more exotic than "the model was wrong".
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from .config import FLASH
from .prompts import SYSTEM_INSTRUCTION
from .schemas import TicketTriage

root_agent = LlmAgent(
    name="ticket_triage_assistant",
    model=FLASH,
    description=(
        "Classifies an inbound Aurora Retail customer-care ticket and drafts a "
        "reply for a human agent to review."
    ),
    # `instruction` is re-sent on every turn and supports {state} injection.
    # For a single-shot transform that is exactly what you want.
    instruction=SYSTEM_INSTRUCTION,
    # Constrained decoding against the Pydantic model. The model cannot return
    # prose, a missing field, or an out-of-range enum value.
    output_schema=TicketTriage,
    # Writes the result into session state under this key. Not strictly needed
    # for a single call, but it is how pattern 2 chains nodes together — worth
    # getting into the habit here.
    output_key="triage",
    generate_content_config=types.GenerateContentConfig(
        # Classification wants repeatability, not creativity. The drafting part
        # of the task tolerates 0.2 fine; going to 0.0 tends to produce stiffer
        # replies without measurably better labels.
        temperature=0.2,
        top_p=0.95,
        max_output_tokens=1024,
        # Flash thinks by default. This task is pattern-matching against an
        # explicit rubric, so thinking adds latency and cost for no accuracy.
        # Raise this budget for genuinely ambiguous classification taxonomies.
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        safety_settings=[
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            ),
        ],
    ),
)
