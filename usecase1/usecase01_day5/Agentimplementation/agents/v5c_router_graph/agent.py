"""Pattern C: the router, the Graph API approach (Day 5: Build).

One entry point. A node decides which team the request belongs to, and the graph
sends it to that one specialist:

    START -> route_by_rules --complaints--> complaints_agent
                   |         --returns----> returns_agent
                   |         --billing----> billing_agent
                   +--unsure--> route_classifier -> parse_route --> (the same three)
                                                             +--several--> hand_over
                                                             +--unclear--> ask_again

Code decides first, from complaint and return IDs and money words: predictable, free,
and testable without a model. Only a request code cannot place goes to the model.
That is the Day 2 principle applied to routing: deterministic where you can be.

A router sends each request to ONE team. A request that needs several teams is
handed over here; v5d_orchestrator is the pattern that can handle it.
"""

import sys
from pathlib import Path

# The shared northwind package sits in the kit folder, next to agents/.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from google.adk.agents import Agent  # noqa: E402
from google.adk.events.event import Event  # noqa: E402
from google.adk.workflow import START, Workflow  # noqa: E402
from google.genai import types  # noqa: E402

from northwind import rules  # noqa: E402
from northwind.specialists import (  # noqa: E402
    MODEL, instruction, make_billing_agent, make_complaints_agent, make_returns_agent)
from northwind.tools import hand_to_person  # noqa: E402

TEAMS = ["complaints", "returns", "billing"]


def _text(node_input):
    if isinstance(node_input, str):
        return node_input
    return " ".join(p.text or "" for p in (getattr(node_input, "parts", None) or []))


def route_by_rules(node_input: types.Content):
    """Code: route from IDs and money words. Says 'unsure' rather than guess."""
    route, reason = rules.route_by_rules(_text(node_input))
    print(f"\n>>> ROUTED BY CODE: {route} | {reason}\n", flush=True)
    state = {"route_source": "code" if route != "unsure" else "model", "route_reason": reason,
             "request": _text(node_input)}
    if route != "unsure":
        state["route_taken"] = route
    return Event(route=route, state=state)


route_classifier = Agent(
    name="route_classifier",
    model=MODEL,
    instruction=instruction("classifier"),
    generate_content_config=types.GenerateContentConfig(temperature=0),
)


def parse_route(node_input):
    """Code: turn the classifier's one word into a route. Anything odd is 'unclear'."""
    word = _text(node_input).strip().lower()
    route = next((r for r in TEAMS + ["several", "unclear"] if r in word), "unclear")
    print(f"\n>>> ROUTED BY MODEL: {route} | classifier said '{word[:30]}'\n", flush=True)
    return Event(route=route, state={"route_taken": route})


def hand_over(node_input, ctx):
    hand_to_person("REQUEST", rules.TEAM_LEAD, "Needs more than one team: " + ctx.state.get("request", "")[:80])
    return Event(message="This request needs more than one team, so a router cannot handle it "
                         "alone. It has been handed to the complaints team lead. "
                         "(The orchestrator, v5d, is the pattern built for this.)")


def ask_again(node_input):
    return Event(message="I could not tell which team this is for. Please include a complaint "
                         "ID (C-...), a return ID (R-...), or say if it is about a refund.")


complaints_agent = make_complaints_agent()
returns_agent = make_returns_agent()
billing_agent = make_billing_agent()
specialists = {"complaints": complaints_agent, "returns": returns_agent, "billing": billing_agent}

root_agent = Workflow(
    name="v5c_router_graph",
    description="One entry point that routes each request to the complaints, returns or billing specialist.",
    edges=[
        (START, route_by_rules, {**specialists, "unsure": route_classifier}),
        (route_classifier, parse_route, {**specialists, "several": hand_over, "unclear": ask_again}),
    ],
)
