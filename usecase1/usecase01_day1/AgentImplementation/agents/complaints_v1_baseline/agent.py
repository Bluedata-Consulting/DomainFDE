"""Complaint triage agent, VERSION 1 (pre-ADLC baseline).

This is the agent as most teams write it the first time: a short instruction
and a set of useful tools, with no decision definition, no autonomy levels and
no human boundary. Run it, watch what it does, and record what is missing.

Do not change this file during Activity 1. Your proposed changes go in
improvement-proposal.md, not in the code.

Architecture note: this module is the composition layer only. The wording of
the decision lives in instruction.txt, and the actions the agent can take live
in tools.py. Those are the two seams you will argue about later.
"""
import os
from pathlib import Path

from google.adk.agents import Agent
from google.adk.agents.readonly_context import ReadonlyContext
from google.genai import types

from .tools import (
    get_complaint,
    route_complaint,
    issue_refund,
    close_complaint,
    send_customer_message,
)

INSTRUCTION_FILE = Path(__file__).parent / "instruction.txt"


def load_instruction(context: ReadonlyContext) -> str:
    """Reads instruction.txt before every reply, so edits apply without a restart."""
    return INSTRUCTION_FILE.read_text(encoding="utf-8")


# TOOL LIST
# Every tool below acts on its own the moment the model decides to call it.
# Nothing here proposes, asks or escalates. Note that while you test.
root_agent = Agent(
    name="complaints_v1_baseline",
    model=os.getenv("AGENT_MODEL", "gemini-2.5-flash"),
    description="Handles customer complaints for Northwind Home.",
    instruction=load_instruction,
    tools=[
        get_complaint,
        route_complaint,
        issue_refund,
        close_complaint,
        send_customer_message,
    ],
    generate_content_config=types.GenerateContentConfig(temperature=0),
)
