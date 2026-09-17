"""Complaint agent, version 4 (Day 4: Context).

Same rules, guardrail and recorder as version 3. What changed:
  ontology.py        follows the links in ontology.yaml, so every complaint arrives
                     with its customer, consent and refunds attached
  tools.py           tool descriptions and parameter types written from the ontology
  instruction.txt    a short glossary of the words that cut across every tool
  decision_tree.py   the same five rules, using the defined meanings
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
    name="complaints_v4_context",
    model=os.getenv("AGENT_MODEL", "gemini-2.5-flash"),
    description="Handles customer complaints for Northwind Home, using the complaints ontology.",
    instruction=INSTRUCTION,
    tools=[
        get_complaint,
        route_complaint,
        issue_refund,
        close_complaint,
        send_customer_message,
        escalate_to_human,
    ],
    before_tool_callback=recorder.before_tool_callback,
    after_model_callback=recorder.after_model_callback,
    before_agent_callback=recorder.before_agent_callback,
    after_agent_callback=recorder.after_agent_callback,
    generate_content_config=types.GenerateContentConfig(temperature=0),
)
