"""The complaint decision tree, version 4 (Day 4: Context).

The same five rules as Day 2, but each word now means what ontology.yaml says:

    Rule 1  ESCALATE          Refund or close when the CUSTOMER (any account) is
                              vulnerable, or the complaint mentions legal action.
                              Checked as soon as the complaint is looked up.
    Rule 2  NO_CONSENT        Message on a channel AND purpose the customer has not
                              agreed to. (Day 2: any message on an opted-out channel.)
    Rule 3  NO_OFFER_POLICY   Message offering a discount or compensation.
    Rule 4  NEEDS_APPROVAL    TOTAL refunds on the complaint would go above the limit.
                              (Day 2: each refund on its own.)
    Rule 5  ALLOWED           Anything else: the agent uses its own judgement.

It receives a complaint "view" from ontology.complaint_view(), so it never has to
guess which customer, consent or refunds belong to a complaint. Plain Python.
"""

REFUND_LIMIT_GBP = 25
LEGAL_WORDS = ["ombudsman", "solicitor", "lawyer", "legal action", "trading standards",
               "legal representative"]
OFFER_WORDS = ["discount", "voucher", "compensation", "%"]

TEAM_LEAD = "Complaints team lead"
BILLING = "Billing team"


def check_complaint(view):
    """Rule 1. Returns a result if a person must handle this complaint, else None."""
    legal = any(word in view["text"].lower() for word in LEGAL_WORDS)
    if view["customer"]["vulnerable"] or legal:
        return {
            "allowed": False,
            "rule": "ESCALATE",
            "owner": TEAM_LEAD,
            "reason": "The customer is vulnerable on their record, or legal action is "
                      "mentioned. A person must handle this complaint.",
        }
    return None


def decide(view, tool_name, args):
    # Rule 1
    if tool_name in ("issue_refund", "close_complaint"):
        result = check_complaint(view)
        if result:
            return result

    if tool_name == "send_customer_message":
        channel = str(args.get("channel", "")).lower()
        purpose = str(args.get("purpose", "")).lower()
        message = str(args.get("message", "")).lower()

        # Rule 2
        if view["consent"].get(f"{channel}/{purpose}") is not True:
            return {
                "allowed": False,
                "rule": "NO_CONSENT",
                "owner": TEAM_LEAD,
                "reason": f"The customer has not agreed to {purpose} messages by {channel}.",
            }

        # Rule 3
        if any(word in message for word in OFFER_WORDS):
            return {
                "allowed": False,
                "rule": "NO_OFFER_POLICY",
                "owner": TEAM_LEAD,
                "reason": "The message offers a discount or compensation, and no such "
                          "policy exists.",
            }

    # Rule 4
    if tool_name == "issue_refund":
        amount = float(args.get("amount_gbp", 0))
        total = view["refunds_so_far_gbp"] + amount
        if total > REFUND_LIMIT_GBP:
            return {
                "allowed": False,
                "rule": "NEEDS_APPROVAL",
                "owner": BILLING,
                "reason": f"This refund of {amount:g} GBP would bring the total on this "
                          f"complaint to {total:g} GBP, above the {REFUND_LIMIT_GBP} GBP limit.",
            }

    # Rule 5
    return {"allowed": True, "rule": "ALLOWED", "owner": None, "reason": "Within the agent's limits."}
