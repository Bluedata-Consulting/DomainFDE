"""The tools, three per team (Day 5: Build).

Each specialist agent gets exactly three tools. That is a design choice, not a limit
of ADK: a small tool set keeps each agent's context short, and makes it obvious which
team is allowed to do what.

    COMPLAINTS    get_complaint    send_customer_message    escalate_to_human
    RETURNS       get_return       set_disposition          raise_vendor_claim
    BILLING       get_refunds      issue_refund             request_approval

There is no tool that changes an inspector's grade. A tool that does not exist
cannot be misused.

All data is made up. Nothing changes in any real system.
When a tool takes an action, it prints a line in the terminal so you can see it.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from . import release
from .data import complaint_view, record_decision, record_refund, return_view

KIT = Path(__file__).resolve().parents[1]
ESCALATION_LOG = KIT / "escalations.log"


def _operating(tool):
    """Honour the release's operating setting for this tool (Day 7). A setting of
    'timeout' makes the tool fail, as it would if the system behind it stopped responding."""
    if release.tool_setting(tool) == "timeout":
        raise TimeoutError(f"{tool}: the system behind this tool did not respond")


def _action(tool, detail):
    print(f"\n>>> ACTION TAKEN BY AGENT: {tool} | {detail}\n", flush=True)


def hand_to_person(subject_id, owner, reason):
    """Record a handover to a named person. Used by the tools and by the guardrail."""
    time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(ESCALATION_LOG, "a", encoding="utf-8") as log:
        log.write(f"{time} | {subject_id} | {owner} | {reason}\n")
    print(f"\n>>> ESCALATED TO HUMAN: {subject_id} -> {owner} | {reason}\n", flush=True)


# ---------------------------------------------------------------------------
# COMPLAINTS: customer experience
# ---------------------------------------------------------------------------
def get_complaint(complaint_id: str) -> dict:
    """Look up one complaint and everything that belongs with it. Always call this first.

    Returns the complaint text, the order and its value, the CUSTOMER behind it (one
    real person, who may have several accounts; vulnerability and consent belong to
    the customer), consent by channel and purpose, and refunds already made.
    """
    _operating("get_complaint")
    view = complaint_view(complaint_id)
    return {"status": "not_found", "complaint_id": complaint_id} if view is None else {"status": "found", **view}


def send_customer_message(
    complaint_id: str,
    channel: Literal["email", "chat", "phone"],
    purpose: Literal["service", "marketing"],
    message: str,
) -> dict:
    """Send a message to the customer behind this complaint.

    purpose "service" is about their own order or complaint, such as an apology or an
    update. "marketing" is anything that offers something else, including any
    discount or voucher. Only send if their consent for that channel AND purpose is true.
    """
    _operating("send_customer_message")
    _action("send_customer_message", f"{complaint_id} via {channel} ({purpose}): {message[:60]}")
    return {"status": "sent", "complaint_id": complaint_id, "channel": channel, "purpose": purpose}


def escalate_to_human(complaint_id: str, owner: str, reason: str) -> dict:
    """Hand a complaint to a named person for a decision, with the reason."""
    _operating("escalate_to_human")
    hand_to_person(complaint_id, owner, reason)
    return {"status": "escalated", "complaint_id": complaint_id, "owner": owner}


# ---------------------------------------------------------------------------
# RETURNS: supply chain
# ---------------------------------------------------------------------------
def get_return(return_id: str) -> dict:
    """Look up one returned item. Always call this first.

    Returns the item, its value, the inspector's condition grade (A is as new, C is
    damaged; the grade cannot be changed), whether it is on the recall list, the
    vendor, the days left to claim from the vendor, and which dispositions are allowed.
    """
    _operating("get_return")
    view = return_view(return_id)
    return {"status": "not_found", "return_id": return_id} if view is None else {"status": "found", **view}


def set_disposition(
    return_id: str,
    disposition: Literal["restock", "refurbish", "return_to_vendor", "liquidate", "recycle", "quarantine"],
    reason: str,
) -> dict:
    """Decide where a returned item goes. restock puts it back on sale, and is only for
    grade A items. A recalled item may only be quarantined. Give the reason."""
    _operating("set_disposition")
    record_decision("dispositions", return_id=return_id, disposition=disposition, reason=reason)
    _action("set_disposition", f"{return_id} -> {disposition}: {reason[:60]}")
    return {"status": "disposition_set", "return_id": return_id, "disposition": disposition}


def raise_vendor_claim(return_id: str, reason: str) -> dict:
    """Claim the cost of a faulty item back from its vendor. Only possible before the
    vendor's deadline. Give the fault as the reason."""
    _operating("raise_vendor_claim")
    record_decision("claims", return_id=return_id, reason=reason)
    _action("raise_vendor_claim", f"{return_id}: {reason[:60]}")
    return {"status": "claim_raised", "return_id": return_id}


# ---------------------------------------------------------------------------
# BILLING: finance
# ---------------------------------------------------------------------------
def get_refunds(complaint_id: str) -> dict:
    """Look up the money side of a complaint: the order value, refunds already made,
    and how much more may be refunded without approval. Always call this first."""
    _operating("get_refunds")
    view = complaint_view(complaint_id)
    if view is None:
        return {"status": "not_found", "complaint_id": complaint_id}
    return {"status": "found", "complaint_id": view["complaint_id"], "order": view["order"],
            "refunds_so_far_gbp": view["refunds_so_far_gbp"],
            "refund_headroom_gbp": view["refund_headroom_gbp"]}


def issue_refund(complaint_id: str, amount_gbp: float) -> dict:
    """Return money for the order this complaint is about. amount_gbp is this single
    refund, not a running total. The total per complaint may not go above 25 GBP
    without approval, and may never exceed the order value. It is not compensation."""
    _operating("issue_refund")
    record_refund(complaint_id, amount_gbp)
    _action("issue_refund", f"{complaint_id} refunded {amount_gbp} GBP")
    return {"status": "refund_issued", "complaint_id": complaint_id, "amount_gbp": amount_gbp}


def request_approval(complaint_id: str, amount_gbp: float, reason: str) -> dict:
    """Ask the Billing team lead to approve a refund above the limit. Nothing is paid
    until they approve. Use this instead of issue_refund when the total would go above
    25 GBP."""
    _operating("request_approval")
    record_decision("approvals", complaint_id=complaint_id, amount_gbp=amount_gbp, reason=reason)
    hand_to_person(complaint_id, "Billing team lead", f"Approve a refund of {amount_gbp:g} GBP: {reason}")
    return {"status": "approval_requested", "complaint_id": complaint_id, "amount_gbp": amount_gbp,
            "owner": "Billing team lead"}


COMPLAINTS_TOOLS = [get_complaint, send_customer_message, escalate_to_human]
RETURNS_TOOLS = [get_return, set_disposition, raise_vendor_claim]
BILLING_TOOLS = [get_refunds, issue_refund, request_approval]
