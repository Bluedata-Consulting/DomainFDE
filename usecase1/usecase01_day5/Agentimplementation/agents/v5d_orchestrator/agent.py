"""Pattern D: the orchestrator, a multi-agent implementation (Day 5: Build).

A coordinator that owns no business tools of its own. Its three tools ARE the three
specialists, each wrapped as a tool:

    v5d_orchestrator  (coordinator, plans and combines)
        |-- complaints_agent   get_complaint, send_customer_message, escalate_to_human
        |-- returns_agent      get_return, set_disposition, raise_vendor_claim
        +-- billing_agent      get_refunds, issue_refund, request_approval

For one request it can call several specialists, in whatever order the case needs,
then give one combined answer. Each specialist keeps its own instruction, tools and
guardrail, so the coordinator cannot do anything a specialist is not allowed to do.
"""

import sys
from pathlib import Path

# The shared northwind package sits in the kit folder, next to agents/.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from google.adk.agents import Agent  # noqa: E402
from google.adk.tools.agent_tool import AgentTool  # noqa: E402
from google.genai import types  # noqa: E402

from northwind import recorder  # noqa: E402
from northwind.specialists import (  # noqa: E402
    MODEL, instruction, make_billing_agent, make_complaints_agent, make_returns_agent)

root_agent = Agent(
    name="v5d_orchestrator",
    model=MODEL,
    description="Coordinates the complaints, returns and billing specialists for requests that need more than one team.",
    instruction=instruction("coordinator"),
    tools=[
        AgentTool(agent=make_complaints_agent()),
        AgentTool(agent=make_returns_agent()),
        AgentTool(agent=make_billing_agent()),
    ],
    after_model_callback=recorder.after_model_callback,
    before_agent_callback=recorder.before_agent_callback,
    after_agent_callback=recorder.after_agent_callback,
    generate_content_config=types.GenerateContentConfig(temperature=0),
)
