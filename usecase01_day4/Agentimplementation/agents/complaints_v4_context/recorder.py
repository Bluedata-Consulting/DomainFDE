"""Recorder: writes what the agent did to runs.jsonl, so it can be measured.

Unchanged from Day 3, except that each line also names the agent, so v3 and v4
runs can be told apart.

It does not change what the agent does. The Day 2 guardrail still decides every
tool call; this file only watches and writes one JSON line per event:

    lookup       a complaint was looked up, and whether it is at risk
    model_call   one call to Gemini, with its input and output tokens
    tool_call    one tool call, and whether it ran or was blocked (and by which rule)
    escalation   a complaint was handed to a person (by a rule, or by the agent)
    turn         one user message answered, with how many seconds it took

Every line carries the session id. metrics.py turns the lines into one case per
session.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .guardrails import before_tool_callback as guardrail
from .ontology import complaint_view

RUNS_FILE = Path(__file__).resolve().parents[2] / "runs.jsonl"

_turn_started = {}   # invocation id -> start time


def _session_id(context):
    """The chat session id. Works across ADK versions."""
    session = getattr(context, "session", None)
    if session is None:
        invocation = getattr(context, "_invocation_context", None)
        session = getattr(invocation, "session", None)
    return getattr(session, "id", None) or getattr(context, "invocation_id", "unknown")


def _write(context, event, **fields):
    line = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session": _session_id(context),
        "agent": getattr(context, "agent_name", None),
        "event": event,
        **fields,
    }
    with open(RUNS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


def _escalated_keys(state):
    return {key for key in state.to_dict() if key.startswith("escalated:")}


# ---- Turns: time from the user's message to the agent's final reply --------

def before_agent_callback(callback_context):
    _turn_started[callback_context.invocation_id] = time.monotonic()
    return None


def after_agent_callback(callback_context):
    started = _turn_started.pop(callback_context.invocation_id, None)
    if started is not None:
        _write(callback_context, "turn", seconds=round(time.monotonic() - started, 2))
    return None


# ---- Model calls: tokens ----------------------------------------------------

def after_model_callback(callback_context, llm_response):
    usage = getattr(llm_response, "usage_metadata", None)
    if usage is None or getattr(llm_response, "partial", False):
        return None   # streamed pieces carry no final count
    input_tokens = usage.prompt_token_count or 0
    output_tokens = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
    _write(callback_context, "model_call", input_tokens=input_tokens, output_tokens=output_tokens)
    return None


# ---- Tool calls: ran or blocked, and escalations -----------------------------

def before_tool_callback(tool, args, tool_context):
    complaint_id = str(args.get("complaint_id", "")).strip().upper()
    before = _escalated_keys(tool_context.state)

    # The Day 2 guardrail decides. The recorder only writes down what it decided.
    result = guardrail(tool=tool, args=args, tool_context=tool_context)

    # Escalations made by a rule inside the guardrail
    for key in sorted(_escalated_keys(tool_context.state) - before):
        _, cid, rule = key.split(":", 2)
        _write(tool_context, "escalation", complaint_id=cid, rule=rule, source="rule")

    view = complaint_view(complaint_id) if tool.name == "get_complaint" else None
    if view is not None:
        _write(tool_context, "lookup", complaint_id=complaint_id, at_risk=view["at_risk"])

    status = result.get("status") if isinstance(result, dict) else None
    if status == "blocked":
        _write(tool_context, "tool_call", tool=tool.name, complaint_id=complaint_id,
               result="blocked", rule=result.get("rule"))
    elif status == "already_escalated":
        _write(tool_context, "tool_call", tool=tool.name, complaint_id=complaint_id,
               result="skipped")
    else:
        _write(tool_context, "tool_call", tool=tool.name, complaint_id=complaint_id, result="ran")
        # Escalations the agent chose to make by itself
        if tool.name == "escalate_to_human":
            _write(tool_context, "escalation", complaint_id=complaint_id, rule="AGENT", source="agent")
    return result
