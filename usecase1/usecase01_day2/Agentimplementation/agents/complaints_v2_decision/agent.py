"""Complaint agent, version 2 (Day 2: Model the decision).

Same model and tools as version 1, plus:
  decision_tree.py   the rules, as plain Python
  guardrails.py      checks every tool call against the rules before it runs,
                     and escalates to a person whenever a rule applies
  escalate_to_human  hands a complaint to a person and writes escalations.log
"""
import os
from pathlib import Path

from google.adk.agents import Agent
from google.genai import types

from .guardrails import before_tool_callback
from .tools import (
    close_complaint,
    escalate_to_human,
    get_complaint,
    issue_refund,
    route_complaint,
    send_customer_message,
)

INSTRUCTION = (Path(__file__).parent / "instruction.txt").read_text(encoding="utf-8")

root_agent = Agent(
    name="complaints_v2_decision",
    model=os.getenv("AGENT_MODEL", "gemini-2.5-flash"),
    description="Handles customer complaints for Northwind Home within a decision tree.",
    instruction=INSTRUCTION,
    tools=[
        get_complaint,
        route_complaint,
        issue_refund,
        close_complaint,
        send_customer_message,
        escalate_to_human,
    ],
    before_tool_callback=before_tool_callback,   # every tool call is checked first
    generate_content_config=types.GenerateContentConfig(temperature=0),
)
