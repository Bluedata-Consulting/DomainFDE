# Run below command on terminal to install npm
# sudo apt install npm

# create GITHUB token and store into .enb file as GITHUB_PERSONAL_ACCESS_TOKEN


# app.py
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import MCPToolset, StdioConnectionParams
import os
import warnings
from pathlib import Path

from dotenv import load_dotenv
from .prompt import prompt

# Bare load_dotenv() only searches upward from the *current working directory*, so it
# misses the repo .env whenever adk web is started from anywhere else. Be explicit.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Warn rather than raise: `adk web .` imports every agent folder at startup, so an
# exception here would take the whole dev UI down instead of just this one lab.
GITHUB_PERSONAL_ACCESS_TOKEN = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")
if not GITHUB_PERSONAL_ACCESS_TOKEN:
    warnings.warn(
        "GITHUB_PERSONAL_ACCESS_TOKEN is not set in .env -- the GitHub MCP tools will "
        "fail to connect. Create a token at https://github.com/settings/tokens.",
        stacklevel=2,
    )


server_params = {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github", "stdio"],
        # The server reads GITHUB_PERSONAL_ACCESS_TOKEN, not GITHUB_TOKEN.
        "env": {**os.environ, "GITHUB_PERSONAL_ACCESS_TOKEN": GITHUB_PERSONAL_ACCESS_TOKEN},
    }

conn = StdioConnectionParams(server_params=server_params, timeout=120)


github_toolset = MCPToolset(connection_params=conn)

# Minimal instruction; keep it simple.
instruction = (
    "You are a GitHub assistant. "
    "Use MCP tools when available. "
    "For directory listings, call get_file_contents with a directory path."
)

root_agent = LlmAgent(
    name="github_agent",
    model="gemini-2.5-flash",
    instruction=instruction+prompt,
    tools=[github_toolset],
)