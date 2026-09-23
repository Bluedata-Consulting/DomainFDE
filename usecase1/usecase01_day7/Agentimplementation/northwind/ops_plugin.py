"""The operations plugin (Day 7: Operate).

A plugin runs for every agent in an App, including specialists called as tools, so
operational concerns live here rather than in each agent:

  - every model call and tool call span in the trace is stamped with the release tag
    (northwind.release), so a trace always says which release produced it
  - every tool failure is written to runs.jsonl as a tool_error event, so the health
    check can count them against the error budget

It changes no behaviour. Recovering from a failure is the retry plugin's job.
"""
import json
from datetime import datetime, timezone

from google.adk.plugins.base_plugin import BasePlugin
from opentelemetry import trace

from . import release
from .recorder import RUNS_FILE, _session_id


def _stamp():
    span = trace.get_current_span()
    span.set_attribute("northwind.release", release.current_tag())
    span.set_attribute("northwind.release_model", release.model())


class OpsPlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="northwind_ops")

    async def before_model_callback(self, *, callback_context, llm_request):
        _stamp()
        return None

    async def before_tool_callback(self, *, tool, tool_args, tool_context):
        _stamp()
        return None

    async def on_tool_error_callback(self, *, tool, tool_args, tool_context, error):
        line = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "session": _session_id(tool_context), "agent": getattr(tool_context, "agent_name", None),
                "release": release.current_tag(), "event": "tool_error",
                "tool": tool.name, "error": f"{type(error).__name__}: {error}"[:200]}
        with open(RUNS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
        print(f"\n>>> TOOL FAILED: {tool.name} | {type(error).__name__}: {error}\n", flush=True)
        return None   # let the retry plugin decide what happens next
