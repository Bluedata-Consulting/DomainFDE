"""ADK execution helper with tool tracing and a persistent conversation session.

Two things this adds over the example 1 runner:

  * **Tool tracing.** With the model choosing the tool sequence, the sequence is
    the thing you need to see. "Why did it promise a replacement?" is almost
    always answered by "it never called check_inventory".

  * **A session that survives turns.** A Session holds the event history and the
    state dict. Reusing one across turns is what makes the agent remember that
    it already looked the order up -- and what lets the cumulative goodwill
    guardrail in agent.py work at all.
"""

from __future__ import annotations

import json
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


def _short(value: Any, limit: int = 88) -> str:
    text = json.dumps(value, default=str) if not isinstance(value, str) else value
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


class Conversation:
    """One agent, one session, many turns."""

    def __init__(self, agent: BaseAgent, app_name: str, user_id: str) -> None:
        self._agent = agent
        self._app_name = app_name
        self._user_id = user_id
        self._session_service = InMemorySessionService()
        self._session_id: str | None = None
        self._runner = Runner(
            app_name=app_name, agent=agent, session_service=self._session_service
        )

    async def start(self, initial_state: dict[str, Any] | None = None) -> None:
        session = await self._session_service.create_session(
            app_name=self._app_name,
            user_id=self._user_id,
            state=initial_state or {},
        )
        self._session_id = session.id

    async def send(self, message: str, trace: bool = True) -> str:
        if self._session_id is None:
            await self.start()

        final_text = ""
        async for event in self._runner.run_async(
            user_id=self._user_id,
            session_id=self._session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        ):
            if trace:
                for call in event.get_function_calls() or []:
                    args = {k: v for k, v in (call.args or {}).items()}
                    print(f"    -> {call.name}({_short(args)})")
                for response in event.get_function_responses() or []:
                    payload = response.response or {}
                    status = payload.get("status", "?") if isinstance(payload, dict) else "?"
                    marker = {
                        "success": "ok",
                        "blocked": "BLOCKED",
                        "held_for_approval": "HELD",
                    }.get(status, status)
                    print(f"    <- {response.name}: {marker}  {_short(payload)}")

            if event.is_final_response() and event.content and event.content.parts:
                text = "".join(p.text or "" for p in event.content.parts)
                if text.strip():
                    final_text = text

        return final_text

    async def state(self) -> dict[str, Any]:
        session = await self._session_service.get_session(
            app_name=self._app_name, user_id=self._user_id, session_id=self._session_id
        )
        return dict(session.state) if session else {}


async def run_agent(
    agent: BaseAgent,
    prompt: str,
    app_name: str,
    user_id: str,
    initial_state: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Single-turn convenience wrapper over Conversation."""
    conversation = Conversation(agent, app_name, user_id)
    await conversation.start(initial_state)
    text = await conversation.send(prompt)
    return text, await conversation.state()
