"""v0 SQL agent for the Meridian Roasters case, built on Google ADK.

A single ReAct-style LlmAgent that answers business questions with
business-named tools over data/roastery.db (tools/domaintools.py), with the
generic SQL tools (tools/sqltools.py) kept as a fallback.

Run locally with:
    adk web        (from the Day5Build folder, then pick "v0Agent")
    adk run v0Agent
"""

from google.adk.telemetry.google_cloud import get_gcp_exporters
from google.adk.telemetry.setup import maybe_set_otel_providers

import os
os.environ.setdefault("OTEL_SERVICE_NAME", "v0Agent")
maybe_set_otel_providers([get_gcp_exporters(enable_cloud_tracing=True,
                                            enable_cloud_metrics=True,
                                            enable_cloud_logging=True)])



from google.adk.agents import Agent

from .prompts import INSTRUCTION
from .tools import ALL_TOOLS

MODEL = "gemini-3.5-flash"

root_agent = Agent(
    name="roastery_sql_agent",
    model=MODEL,
    description="Answers questions about Meridian Roasters by querying its SQLite database.",
    instruction=INSTRUCTION,
    tools=ALL_TOOLS,
)
