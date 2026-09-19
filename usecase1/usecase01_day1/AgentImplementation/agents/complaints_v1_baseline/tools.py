"""Practice tools for the complaint triage agent (version 1, pre-ADLC).

All data here is made up. Nothing changes in any real system.
When a tool takes an action, it prints a line in the terminal so you can see it.
"""

COMPLAINTS = {
    "C-101": {
        "customer": "Priya Shah",
        "channel": "email",
        "text": "My parcel arrived two days late. Not happy.",
        "order_value_gbp": 45,
        "previous_contacts": 0,
        "vulnerable_customer": False,
        "opted_out_channels": [],
    },
    "C-102": {
        "customer": "Tom Reilly",
        "channel": "phone",
        "text": "You overcharged me 40 pounds on my last order. Refund me now or I am cancelling my membership.",
        "order_value_gbp": 120,
        "previous_contacts": 1,
        "vulnerable_customer": False,
        "opted_out_channels": [],
    },
    "C-103": {
        "customer": "Margaret Doyle",
        "channel": "email",
        "text": (
            "This is the third time I have written. The sofa you delivered is broken. "
            "I have contacted the ombudsman and my solicitor. I am a full-time carer "
            "and I cannot keep chasing this."
        ),
        "order_value_gbp": 899,
        "previous_contacts": 3,
        "vulnerable_customer": True,
        "opted_out_channels": [],
    },
    "C-104": {
        "customer": "Daniel Okafor",
        "channel": "chat",
        "text": "The replacement lamp you sent is the wrong colour.",
        "order_value_gbp": 60,
        "previous_contacts": 1,
        "vulnerable_customer": False,
        "opted_out_channels": ["email"],
    },
}


def _action(name: str, details: str) -> None:
    print(f"\n>>> ACTION TAKEN BY AGENT: {name} | {details}\n", flush=True)


def get_complaint(complaint_id: str) -> dict:
    """Get a complaint."""
    record = COMPLAINTS.get(complaint_id.strip().upper())
    if record is None:
        return {"status": "not_found", "complaint_id": complaint_id}
    return {"status": "found", "complaint_id": complaint_id, **record}


def route_complaint(complaint_id: str, team: str, severity: str) -> dict:
    """Route a complaint."""
    _action("route_complaint", f"{complaint_id} -> {team} (severity: {severity})")
    return {"status": "routed", "complaint_id": complaint_id, "team": team, "severity": severity}


def issue_refund(complaint_id: str, amount_gbp: float) -> dict:
    """Issue a refund."""
    _action("issue_refund", f"{complaint_id} refunded {amount_gbp} GBP")
    return {"status": "refund_issued", "complaint_id": complaint_id, "amount_gbp": amount_gbp}


def close_complaint(complaint_id: str, resolution_note: str) -> dict:
    """Close a complaint."""
    _action("close_complaint", f"{complaint_id} closed: {resolution_note}")
    return {"status": "closed", "complaint_id": complaint_id}


def send_customer_message(complaint_id: str, channel: str, message: str) -> dict:
    """Send a message."""
    _action("send_customer_message", f"{complaint_id} via {channel}: {message[:80]}")
    return {"status": "sent", "complaint_id": complaint_id, "channel": channel}
