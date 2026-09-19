"""Minimal, reusable ADK execution helper.

Every ADK invocation needs the same four moving parts: a session service, a
session, a Runner, and an async loop over the event stream. This wraps them so
the examples can stay focused on agent design.
"""

from __future__ import annotations

from typing import Any

from google.adk.agents import BaseAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


async def run_agent(
    agent: BaseAgent,
    prompt: str,
    app_name: str,
    user_id: str,
    initial_state: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Run an agent once and return (final_text, final_session_state).

    In production you would swap InMemorySessionService for
    DatabaseSessionService or VertexAiSessionService — the Runner API is
    identical, which is exactly why sessions are a service and not a global.
    """
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        state=initial_state or {},
    )

    runner = Runner(
        app_name=app_name,
        agent=agent,
        session_service=session_service,
    )

    final_text = ""
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
    ):
        # is_final_response() marks the end of a turn for the agent that is
        # currently in control — that is the text you show to the user.
        if event.is_final_response() and event.content and event.content.parts:
            text = "".join(p.text or "" for p in event.content.parts)
            if text.strip():
                final_text = text

    refreshed = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session.id
    )
    return final_text, dict(refreshed.state) if refreshed else {}
