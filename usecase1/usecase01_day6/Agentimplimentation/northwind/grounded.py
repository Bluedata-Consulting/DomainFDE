"""Builds the Day 6 operations assistant, with or without grounding.

    make_agent(name, None)         no tools: answers from the model alone (the "before")
    make_agent(name, "raw")        grounded on the raw tables, through the MCP server
    make_agent(name, "semantic")   grounded on the ontology-aligned views, through the MCP server

The grounded agents do not import the database or the policies. They start the MCP
server and use whatever tools it offers, exactly as they would with another team's
server. That keeps the three variants identical apart from what they can see.
"""
import os
import sys
from pathlib import Path

from google.adk.agents import Agent
from google.genai import types

from . import recorder

KIT = Path(__file__).resolve().parents[1]
MODEL = os.getenv("AGENT_MODEL", "gemini-2.5-flash")


def _instruction(name):
    return (KIT / "northwind" / "instructions" / f"{name}.txt").read_text(encoding="utf-8")


def mcp_toolset(mode):
    """Connect to the Northwind MCP server, started as a local process in the given mode."""
    from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
    from mcp import StdioServerParameters
    env = {**os.environ, "NORTHWIND_GROUNDING": mode}
    return McpToolset(connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable, args=[str(KIT / "mcp_server" / "northwind_mcp.py")], env=env),
        timeout=30))


def make_agent(name, mode):
    grounded = mode is not None
    return Agent(
        name=name,
        model=MODEL,
        description=("Northwind operations assistant, " +
                     (f"grounded on {mode} data and policies over MCP." if grounded else "not grounded.")),
        instruction=_instruction("operations_assistant" if grounded else "ungrounded"),
        tools=[mcp_toolset(mode)] if grounded else [],
        after_model_callback=recorder.after_model_callback,
        before_agent_callback=recorder.before_agent_callback,
        after_agent_callback=recorder.after_agent_callback,
        generate_content_config=types.GenerateContentConfig(temperature=0),
    )
