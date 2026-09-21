import sys
from pathlib import Path

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools.mcp_tool import MCPToolset, StdioConnectionParams

# Launch the server that ships next to this file, with the same interpreter that is
# running the agent -- an absolute path to someone else's home directory does not
# survive being copied to another machine.
SERVER_SCRIPT = Path(__file__).parent / "mcpserver.py"

server_params = {"command": sys.executable,
                 "args": [str(SERVER_SCRIPT), "stdio"]}

conn = StdioConnectionParams(server_params=server_params, timeout=120)
tools = MCPToolset(connection_params=conn)



agent_prompt = """ You are an expert agentic assistant to human users which provides correct and precise information.
you are provided with multiple tools, use the tools wherever it suits."""

root_agent = LlmAgent(name='customerServiceWorkflow',
                      model = "gemini-2.5-flash",
                      instruction=agent_prompt,
                                          
                      description = "Assistant Agent",
                      tools=[tools]
                      )

app = root_agent