"""Tools for the complaint agent, version 4 (Day 4: Context).

The same six actions as Day 3. What changed is what the agent READS about them:
each description and parameter below is written from ontology.yaml. ADK sends the
function name, this docstring and the parameter types to the model, so this file
is where the ontology reaches the agent.

All data is made up. Nothing changes in any real system.
When a tool takes an action, it prints a line in the terminal so you can see it.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .ontology import complaint_view, record_refund

ESCALATION_LOG = Path(__file__).resolve().parents[2] / "escalations.log"


def _action(tool, detail):
    print(f"\n>>> ACTION TAKEN BY AGENT: {tool} | {detail}\n", flush=True)


def get_complaint(complaint_id: str) -> dict:
    """Look up one complaint and everything that belongs with it. Always call this first.

    Returns the complaint text, the channel it arrived_via, the order it is about and
    that order's value, and the CUSTOMER behind it. A customer is one real person who
    may have several accounts; vulnerability and consent belong to the customer, not
    to the complaint. Also returns earlier complaints from the same customer on any
    account, consent by channel and purpose, refunds already made on this complaint,
    and how much more may be refunded without approval (refund_headroom_gbp).
    """
    view = complaint_view(complaint_id)
    if view is None:
        return {"status": "not_found", "complaint_id": complaint_id}
    return {"status": "found", **view}


def route_complaint(
    complaint_id: str,
    team: Literal["Delivery", "Billing", "Product quality", "Customer care"],
    severity: Literal["low", "medium", "high"],
) -> dict:
    """Send a complaint to the team that owns the problem. This does not escalate it to a
    person for a decision; use escalate_to_human for that."""
    _action("route_complaint", f"{complaint_id} -> {team} ({severity})")
    return {"status": "routed", "complaint_id": complaint_id, "team": team, "severity": severity}


def issue_refund(complaint_id: str, amount_gbp: float) -> dict:
    """Return money to the customer for the order this complaint is about.

    amount_gbp is this single refund in pounds, not a running total. All refunds on one
    complaint count together: the agent may refund up to 25 GBP in total per complaint,
    and the total may never exceed the order value. Check refund_headroom_gbp first.
    A refund is money back for this order only. It is not compensation, a goodwill
    payment, a discount or a voucher.
    """
    record_refund(complaint_id, amount_gbp)
    _action("issue_refund", f"{complaint_id} refunded {amount_gbp} GBP")
    return {"status": "refund_issued", "complaint_id": complaint_id, "amount_gbp": amount_gbp}


def close_complaint(complaint_id: str, resolution_note: str) -> dict:
    """Close a complaint once the customer's issue is handled. Never close a complaint
    that has been escalated to a person: only that person may close it."""
    _action("close_complaint", f"{complaint_id} closed: {resolution_note}")
    return {"status": "closed", "complaint_id": complaint_id}


def send_customer_message(
    complaint_id: str,
    channel: Literal["email", "chat", "phone"],
    purpose: Literal["service", "marketing"],
    message: str,
) -> dict:
    """Send a message to the customer behind this complaint.

    channel is how we contact them now, which may differ from the channel the complaint
    arrived_via. purpose is why we are writing: "service" is about their own order or
    complaint, such as an apology or an update. "marketing" is anything that offers
    something else, including any discount, voucher or promotion. Only send if the
    customer's consent for that channel AND purpose is true.
    """
    _action("send_customer_message", f"{complaint_id} via {channel} ({purpose}): {message[:60]}")
    return {"status": "sent", "complaint_id": complaint_id, "channel": channel, "purpose": purpose}


def escalate_to_human(complaint_id: str, owner: str, reason: str) -> dict:
    """Hand a complaint to a named person for a decision, with the reason. Once escalated,
    the agent may acknowledge the customer but may not refund, offer anything or close."""
    time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(ESCALATION_LOG, "a", encoding="utf-8") as log:
        log.write(f"{time} | {complaint_id} | {owner} | {reason}\n")
    print(f"\n>>> ESCALATED TO HUMAN: {complaint_id} -> {owner} | {reason}\n", flush=True)
    return {"status": "escalated", "complaint_id": complaint_id, "owner": owner}
