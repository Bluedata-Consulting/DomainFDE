"""ADK execution helper with stage tracing.

Same Runner plumbing as example 1, plus a live view of which stage is running.
In a workflow that is not a nicety: when stage 3 produces something odd, the
first question is always "what did stages 1 and 2 actually hand it", and the
event stream is where that answer lives.
"""

from __future__ import annotations

import time
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


async def run_pipeline(
    agent: BaseAgent,
    prompt: str,
    app_name: str,
    user_id: str,
    initial_state: dict[str, Any] | None = None,
    trace: bool = True,
) -> dict[str, Any]:
    """Run a workflow agent and return the final session state.

    In a SequentialAgent the useful result is not the last text response -- it is
    the accumulated state, because each stage wrote its output under its own key.
    """
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=app_name, user_id=user_id, state=initial_state or {}
    )
    runner = Runner(app_name=app_name, agent=agent, session_service=session_service)

    seen: set[str] = set()
    started = time.perf_counter()

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
    ):
        if not trace:
            continue

        # event.author is the agent that produced the event, which makes the
        # stream readable as a stage-by-stage trace of the pipeline.
        if event.author and event.author not in seen:
            seen.add(event.author)
            elapsed = time.perf_counter() - started
            print(f"  [{elapsed:6.2f}s] -> {event.author}")

        # Tool calls are worth surfacing: in this pipeline the only tool is
        # exit_loop, so seeing it is how you know the reviewer approved.
        for call in event.get_function_calls() or []:
            print(f"            tool: {call.name}()")

    refreshed = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session.id
    )
    state = dict(refreshed.state) if refreshed else {}

    if trace:
        print(f"  [{time.perf_counter() - started:6.2f}s] pipeline complete")

    return state
