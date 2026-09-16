"""Complaint agent, version 3 (Day 3: Measure).

Behaves exactly like version 2: same instruction, tools, rules and guardrail.
What is new is recorder.py, attached through four ADK callbacks. It writes every
model call, tool call, block, escalation and turn to runs.jsonl, so that
metrics.py can score the agent against its budgets.
"""
import os
from pathlib import Path

from google.adk.agents import Agent
from google.genai import types

from . import recorder
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
    name="complaints_v3_measured",
    model=os.getenv("AGENT_MODEL", "gemini-2.5-flash"),
    description="Handles customer complaints for Northwind Home within a decision tree, and records every step.",
    instruction=INSTRUCTION,
    tools=[
        get_complaint,
        route_complaint,
        issue_refund,
        close_complaint,
        send_customer_message,
        escalate_to_human,
    ],
    # Guardrail, wrapped by the recorder: the guardrail decides, the recorder writes it down
    before_tool_callback=recorder.before_tool_callback,
    # Tokens per model call
    after_model_callback=recorder.after_model_callback,
    # Seconds per user message
    before_agent_callback=recorder.before_agent_callback,
    after_agent_callback=recorder.after_agent_callback,
    generate_content_config=types.GenerateContentConfig(temperature=0),
)
