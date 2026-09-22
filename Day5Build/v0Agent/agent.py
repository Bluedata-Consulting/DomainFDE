"""v0 SQL agent for the Meridian Roasters case, built on Google ADK.

A single ReAct-style LlmAgent that answers business questions by exploring
the SQLite database with three tools: list tables -> fetch schemas -> run SQL.

Run locally with:
    adk web        (from the Day5Build folder, then pick "v0Agent")
    adk run v0Agent
"""

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
