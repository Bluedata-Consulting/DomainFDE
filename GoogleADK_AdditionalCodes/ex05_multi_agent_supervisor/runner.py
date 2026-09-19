"""ADK execution helper with delegation tracing.

In a multi-agent system the trace is the product. Two questions come up on every
bad answer -- which specialists did the supervisor ask, and in what order -- and
both are answerable only from the event stream.

`event.author` names the agent that produced each event, so an AgentTool call
shows up as the supervisor calling a tool named after the specialist, followed by
events authored by that specialist as it works.
"""

from __future__ import annotations

import json
import time
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

SPECIALISTS = {"demand_analyst", "inventory_planner", "logistics_coordinator"}


def _short(value: Any, limit: int = 150) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


class Conversation:
    """One supervisor, one session, many turns."""

    def __init__(self, agent: BaseAgent, app_name: str, user_id: str) -> None:
        self._app_name = app_name
        self._user_id = user_id
        self._session_service = InMemorySessionService()
        self._session_id: str | None = None
        self._runner = Runner(
            app_name=app_name, agent=agent, session_service=self._session_service
        )

    async def start(self, initial_state: dict[str, Any] | None = None) -> None:
        session = await self._session_service.create_session(
            app_name=self._app_name, user_id=self._user_id, state=initial_state or {}
        )
        self._session_id = session.id

    async def send(self, message: str, trace: bool = True) -> str:
        if self._session_id is None:
            await self.start()

        final_text = ""
        started = time.perf_counter()

        async for event in self._runner.run_async(
            user_id=self._user_id,
            session_id=self._session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        ):
            if trace:
                clock = time.perf_counter() - started

                for call in event.get_function_calls() or []:
                    if call.name in SPECIALISTS:
                        # An AgentTool call: the supervisor asking a specialist.
                        request = (call.args or {}).get("request", call.args)
                        print(f"  [{clock:6.2f}s] ASK {call.name}")
                        print(f"            \"{_short(request)}\"")
                    else:
                        # A data tool call, made by whichever specialist is running.
                        print(f"  [{clock:6.2f}s]     {event.author} -> "
                              f"{call.name}({_short(call.args, 70)})")

                for response in event.get_function_responses() or []:
                    if response.name in SPECIALISTS:
                        payload = response.response
                        if isinstance(payload, dict):
                            payload = payload.get("result", payload)
                        print(f"  [{clock:6.2f}s] GOT {response.name}: "
                              f"{_short(payload, 120)}")

            if event.is_final_response() and event.content and event.content.parts:
                text = "".join(p.text or "" for p in event.content.parts)
                if text.strip():
                    final_text = text

        if trace:
            print(f"  [{time.perf_counter() - started:6.2f}s] synthesis complete")

        return final_text

    async def state(self) -> dict[str, Any]:
        session = await self._session_service.get_session(
            app_name=self._app_name, user_id=self._user_id, session_id=self._session_id
        )
        return dict(session.state) if session else {}
