"""Factories for the three specialist agents (Day 5: Build).

Each call makes a NEW agent. ADK lets an agent belong to only one parent, so the
router and the orchestrator each build their own copies from the same recipe:
same instruction, same three tools, same guardrail, same recorder.
"""
from google.adk.agents import Agent
from google.genai import types

from . import recorder, release
from .tools import BILLING_TOOLS, COMPLAINTS_TOOLS, RETURNS_TOOLS

def instruction(name):
    """Read from the current release, not a fixed file (Day 7)."""
    return release.instruction(name)


def _specialist(name, description, instruction_name, tools):
    return Agent(
        name=name,
        model=release.model(),
        description=description,
        instruction=instruction(instruction_name),
        tools=tools,
        before_tool_callback=recorder.before_tool_callback,   # guardrail, then record
        after_model_callback=recorder.after_model_callback,
        before_agent_callback=recorder.before_agent_callback,
        after_agent_callback=recorder.after_agent_callback,
        generate_content_config=types.GenerateContentConfig(temperature=0),
    )


def make_complaints_agent(name="complaints_agent"):
    return _specialist(name, "Handles the customer conversation for a complaint: apologies, "
                       "consent, vulnerable customers. Cannot refund.", "complaints", COMPLAINTS_TOOLS)


def make_returns_agent(name="returns_agent"):
    return _specialist(name, "Decides where a returned item goes, and whether to claim from "
                       "the vendor.", "returns", RETURNS_TOOLS)


def make_billing_agent(name="billing_agent"):
    return _specialist(name, "Decides refunds, within the limit, and requests approval above it.",
                       "billing", BILLING_TOOLS)
