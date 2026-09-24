"""v0 SQL agent for the Meridian Roasters case, built on Google ADK.

A single ReAct-style LlmAgent that answers business questions by exploring
the SQLite database with three tools: list tables -> fetch schemas -> run SQL.

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
from .tools.sqltools import execute_sql, get_table_schemas, list_tables

MODEL = "gemini-3.5-flash"

root_agent = Agent(
    name="roastery_sql_agent",
    model=MODEL,
    description="Answers questions about Meridian Roasters by querying its SQLite database.",
    instruction=INSTRUCTION,
    tools=[list_tables, get_table_schemas, execute_sql],
)
