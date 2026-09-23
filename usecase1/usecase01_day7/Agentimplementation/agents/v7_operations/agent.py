"""The Day 7 production agent: the Day 5 team with the Day 6 knowledge agent, operated.

    v7_operations  (coordinator: plans, calls specialists, combines)
        |-- complaints_agent   acts: 3 tools, complaints rules
        |-- returns_agent      acts: 3 tools, returns rules
        |-- billing_agent      acts: 3 tools, billing rules
        +-- knowledge_agent    answers: RAG and SQL over MCP, read only

It is exposed as an App, not a bare agent, so two plugins apply to every agent in it:
  - OpsPlugin: stamps the release tag on every trace span, and records tool failures
  - ReflectAndRetryToolPlugin: when a tool fails, the model sees the error and may
    retry, at most twice. After that the failure is returned to the model instead of
    crashing the run, so it can say plainly what could not be done

Everything that shapes behaviour (model, instructions, policies, tool settings) comes
from the current release in releases/. The coordinator has four tools: the only agent
that does not keep to three, because its tools are agents, not actions.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the kit folder

from google.adk.agents import Agent  # noqa: E402
from google.adk.apps import App  # noqa: E402
from google.adk.plugins.reflect_retry_tool_plugin import ReflectAndRetryToolPlugin  # noqa: E402
from google.adk.tools.agent_tool import AgentTool  # noqa: E402
from google.genai import types  # noqa: E402

from northwind import recorder, release  # noqa: E402
from northwind.grounded import make_agent  # noqa: E402
from northwind.ops_plugin import OpsPlugin  # noqa: E402
from northwind.specialists import make_billing_agent, make_complaints_agent, make_returns_agent  # noqa: E402

knowledge_agent = make_agent("knowledge_agent", "semantic")
knowledge_agent.description = ("Answers questions from Northwind's records (by read-only SQL) and written "
                               "policies (by search), and says which source it used. Changes nothing.")

root_agent = Agent(
    name="v7_operations",
    model=release.model(),
    description=f"Northwind customer operations, release {release.current_tag()}.",
    instruction=release.instruction("coordinator"),
    tools=[
        AgentTool(agent=make_complaints_agent()),
        AgentTool(agent=make_returns_agent()),
        AgentTool(agent=make_billing_agent()),
        AgentTool(agent=knowledge_agent),
    ],
    after_model_callback=recorder.after_model_callback,
    before_agent_callback=recorder.before_agent_callback,
    after_agent_callback=recorder.after_agent_callback,
    generate_content_config=types.GenerateContentConfig(temperature=0),
)

app = App(
    name="v7_operations",
    root_agent=root_agent,
    plugins=[OpsPlugin(), ReflectAndRetryToolPlugin(max_retries=2, throw_exception_if_retry_exceeded=False)],
)
