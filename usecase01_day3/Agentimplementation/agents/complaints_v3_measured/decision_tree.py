"""The complaint decision tree (Day 2: Model the decision).

Plain Python. No ADK, no AI model. Given a complaint and an action the agent
wants to take, it answers: is this action allowed, which rule decided, and if
not, which person must take over.

The rules are checked in this order. The first rule that matches decides.

    Rule 1  ESCALATE            Vulnerable customer, or the complaint mentions legal
                                action. Checked as soon as the complaint is looked up.
    Rule 2  OPTED_OUT_CHANNEL   Message on a channel the customer opted out of
    Rule 3  NO_OFFER_POLICY     Message offering a discount or compensation
    Rule 4  NEEDS_APPROVAL      Refund above the limit
    Rule 5  ALLOWED             Anything else: the agent uses its own judgement

Every rule that stops the agent names an owner. The guardrail escalates to that
owner automatically.
"""

# Assumptions, to be confirmed by the complaints team lead.
REFUND_LIMIT_GBP = 25
LEGAL_WORDS = ["ombudsman", "solicitor", "lawyer", "legal action", "trading standards"]
OFFER_WORDS = ["discount", "voucher", "compensation", "%"]

TEAM_LEAD = "Complaints team lead"
BILLING = "Billing team"


def check_complaint(complaint: dict):
    """Rule 1. Returns a result if a person must handle this complaint, else None."""
    text = complaint["text"].lower()
    legal = any(word in text for word in LEGAL_WORDS)
    if complaint["vulnerable_customer"] or legal:
        return {
            "allowed": False,
            "rule": "ESCALATE",
            "owner": TEAM_LEAD,
            "reason": "Vulnerable customer or legal action mentioned. "
                      "A person must handle this complaint.",
        }
    return None


def decide(complaint: dict, tool_name: str, args: dict) -> dict:
    # Rule 1
    if tool_name in ("issue_refund", "close_complaint"):
        result = check_complaint(complaint)
        if result:
            return result

    if tool_name == "send_customer_message":
        channel = args.get("channel", "").lower()
        message = args.get("message", "").lower()

        # Rule 2
        if channel in complaint["opted_out_channels"]:
            return {
                "allowed": False,
                "rule": "OPTED_OUT_CHANNEL",
                "owner": TEAM_LEAD,
                "reason": f"The customer opted out of {channel}.",
            }

        # Rule 3
        if any(word in message for word in OFFER_WORDS):
            return {
                "allowed": False,
                "rule": "NO_OFFER_POLICY",
                "owner": TEAM_LEAD,
                "reason": "Message offers a discount or compensation, "
                          "and no such policy exists.",
            }

    # Rule 4
    if tool_name == "issue_refund":
        amount = float(args.get("amount_gbp", 0))
        if amount > REFUND_LIMIT_GBP:
            return {
                "allowed": False,
                "rule": "NEEDS_APPROVAL",
                "owner": BILLING,
                "reason": f"Refund of {amount:g} GBP is above the "
                          f"{REFUND_LIMIT_GBP} GBP limit and needs approval.",
            }

    # Rule 5
    return {"allowed": True, "rule": "ALLOWED", "owner": None,
            "reason": "Within the agent's limits."}
