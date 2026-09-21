"""Pattern B: the agent loop, the Graph API approach (Day 5: Build).

The same job as v5a (apologise to a customer) but the loop is drawn as a graph, so
every step and every way round the loop is visible and testable:

    START -> prepare -+-> drafter -> check -+-> send
                      |      ^              |
                      |      +--- retry ----+          (at most 3 drafts)
                      +-> person <----------+
                      +-> no_complaint

    prepare   code    finds the complaint; hands vulnerable or legal cases to a person
    drafter   model   writes the apology, and nothing else (no tools)
    check     code    runs the Day 2 message rules on the draft
    send      code    sends it; only reached if the check passed
    person    code    hands the complaint to the complaints team lead

The model only writes words. Code decides whether they go out.
"""

import sys
from pathlib import Path

# The shared northwind package sits in the kit folder, next to agents/.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import re  # noqa: E402

from google.adk.agents import Agent  # noqa: E402
from google.adk.events.event import Event  # noqa: E402
from google.adk.workflow import START, Workflow  # noqa: E402
from google.genai import types  # noqa: E402

from northwind import rules  # noqa: E402
from northwind.data import complaint_view  # noqa: E402
from northwind.specialists import MODEL, instruction  # noqa: E402
from northwind.tools import hand_to_person, send_customer_message  # noqa: E402

MAX_DRAFTS = 3


def _text(node_input):
    if isinstance(node_input, str):
        return node_input
    return " ".join(p.text or "" for p in (getattr(node_input, "parts", None) or []))


def prepare(node_input: types.Content):
    """Code: find the complaint and channel in the request, and stop early if needed."""
    text = _text(node_input)
    found = re.search(r"\bC-\d{3}\b", text, re.IGNORECASE)
    view = complaint_view(found.group(0)) if found else None
    if view is None:
        return Event(route="no_complaint")
    channel = "chat" if "chat" in text.lower() else "phone" if "phone" in text.lower() else "email"
    facts = {"complaint_id": view["complaint_id"], "channel": channel, "tries": 0, "sent": False,
             "customer_name": view["customer"]["name"], "complaint_text": view["text"],
             "feedback": "", "handed_to_person": False}
    risk = rules.check_complaint(view)
    if risk:
        return Event(route="person", state={**facts, "person_reason": risk["reason"]})
    return Event(route="draft", state=facts)


drafter = Agent(
    name="reply_drafter",
    model=MODEL,
    instruction=instruction("drafter"),
    generate_content_config=types.GenerateContentConfig(temperature=0),
)


def check(node_input, ctx):
    """Code: the Day 2 message rules, applied to the draft. Decides the next step."""
    draft = _text(node_input).strip()
    tries = ctx.state.get("tries", 0) + 1
    view = complaint_view(ctx.state["complaint_id"])
    result = rules.decide_message(view, ctx.state["channel"], "service", draft)
    state = {"tries": tries, "draft": draft, "last_check": result["rule"]}
    if result["rule"] == "NO_CONSENT":
        return Event(route="person", state={**state, "person_reason": result["reason"]})
    if not result["allowed"] or len(draft.split()) > 120:
        if tries >= MAX_DRAFTS:
            return Event(route="person", state={**state, "person_reason":
                         f"No acceptable draft after {tries} tries: {result['reason']}"})
        problem = result["reason"] if not result["allowed"] else "The draft is too long."
        return Event(route="retry", state={**state, "feedback":
                     f"Your last draft was rejected: {problem} Write it again, and fix that."})
    return Event(route="send", state=state)


def send(node_input, ctx):
    """Code: only reached when the check passed."""
    send_customer_message(ctx.state["complaint_id"], ctx.state["channel"], "service", ctx.state["draft"])
    return Event(message=f"Sent to the customer on {ctx.state['complaint_id']} by "
                         f"{ctx.state['channel']}, after {ctx.state['tries']} draft(s):\n\n"
                         f"{ctx.state['draft']}", state={"sent": True})


def person(node_input, ctx):
    """Code: hand the complaint to a named person, and say so."""
    cid, reason = ctx.state.get("complaint_id", "UNKNOWN"), ctx.state.get("person_reason", "")
    hand_to_person(cid, rules.TEAM_LEAD, reason)
    return Event(message=f"Nothing was sent on {cid}. {reason} It has been handed to the "
                         f"{rules.TEAM_LEAD}.", state={"handed_to_person": True, "sent": False})


def no_complaint(node_input):
    return Event(message="Please give a complaint ID, such as C-104, and say which channel to use.")


root_agent = Workflow(
    name="v5b_loop_graph",
    description="Writes and sends an apology, with the loop drawn as a graph: draft, check in code, retry or send.",
    edges=[
        (START, prepare, {"draft": drafter, "person": person, "no_complaint": no_complaint}),
        (drafter, check, {"retry": drafter, "send": send, "person": person}),
    ],
)
