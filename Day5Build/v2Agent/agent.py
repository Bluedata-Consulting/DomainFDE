"""v2 ontology-driven agent for the Meridian Roasters case, built on Google ADK.

Same tools as v0, but the business vocabulary now comes from
ontology/ontology.yaml rather than from the model's guesswork:

  * the derived tools are re-signatured by `typed_tools()`, so a
    vocabulary-backed parameter is a Literal the model cannot mis-spell;
  * `prompt_core()` appends the ambiguity notes, metric definitions and
    goodwill policy to the instruction;
  * `resolve()` is itself a tool, so the agent can ask what a name or a
    loaded word might mean before it answers.

The ontology is validated against roastery.db at import time -- a drifted
ontology fails here, not three turns into a trace.

Run locally with:
    adk web        (from the Day5Build folder, then pick "v2Agent")
    adk run v2Agent
"""

from google.adk.telemetry.google_cloud import get_gcp_exporters
from google.adk.telemetry.setup import maybe_set_otel_providers

import os
os.environ.setdefault("OTEL_SERVICE_NAME", "v2Agent")
maybe_set_otel_providers([get_gcp_exporters(enable_cloud_tracing=True,
                                            enable_cloud_metrics=True,
                                            enable_cloud_logging=True)])



from google.adk.agents import Agent

from .ontology_loader import prompt_core, resolve, typed_tools
from .prompts import INSTRUCTION
from .tools import DOMAIN_TOOLS, SQL_TOOLS

MODEL = "gemini-3.5-flash"

# Derived tools get ontology-generated signatures; the generic SQL fallback
# is left exactly as it is.
TOOLS = [resolve] + typed_tools(DOMAIN_TOOLS) + SQL_TOOLS

root_agent = Agent(
    name="roastery_ontology_agent",
    model=MODEL,
    description="Answers questions about Meridian Roasters using its business ontology.",
    instruction=INSTRUCTION + "\n\n" + prompt_core(),
    tools=TOOLS,
)
