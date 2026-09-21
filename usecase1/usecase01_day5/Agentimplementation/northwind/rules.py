"""Every rule the agents must follow, for all three teams (Day 5: Build).

Plain Python. No ADK, no AI model. Each team owns its own rules, and each rule that
stops an action names the person who takes over.

    COMPLAINTS (customer experience)
      C1  ESCALATE          The customer is vulnerable, or legal action is mentioned
      C2  NO_CONSENT        A message on a channel and purpose not agreed to
      C3  NO_OFFER_POLICY   A message offering a discount or compensation

    BILLING (finance)
      B1  OVER_ORDER_VALUE  Total refunds would be more than the order was worth
      B2  NEEDS_APPROVAL    Total refunds on the complaint would go above 25 GBP

    RETURNS (supply chain)
      R1  RECALLED          A recalled item may only be quarantined
      R2  HIGH_VALUE        Items worth more than 500 GBP need the returns supervisor
      R3  GRADE_NOT_FIT     Only grade A items go back on the shelf
      R4  CLAIM_EXPIRED     No vendor claim after the vendor's deadline

Rules are checked in the order listed within each team. The first match decides.
The router at the bottom decides which team a request goes to.
"""
import re

LEGAL_WORDS = ["ombudsman", "solicitor", "lawyer", "legal action", "trading standards",
               "legal representative"]
OFFER_WORDS = ["discount", "voucher", "compensation", "%"]
REFUND_LIMIT_GBP = 25
HIGH_VALUE_GBP = 500

TEAM_LEAD = "Complaints team lead"
BILLING_LEAD = "Billing team lead"
RETURNS_SUPERVISOR = "Returns supervisor"

ALLOWED = {"allowed": True, "rule": "ALLOWED", "owner": None, "reason": "Within the agent's limits."}


def _stop(rule, owner, reason):
    return {"allowed": False, "rule": rule, "owner": owner, "reason": reason}


# ---------------------------------------------------------------------------
# COMPLAINTS
# ---------------------------------------------------------------------------
def check_complaint(view):
    """C1. Returns a result if a person must handle this complaint, else None."""
    legal = any(word in view["text"].lower() for word in LEGAL_WORDS)
    if view["customer"]["vulnerable"] or legal:
        return _stop("ESCALATE", TEAM_LEAD, "The customer is vulnerable, or legal action is "
                     "mentioned. A person must handle this complaint.")
    return None


def decide_message(view, channel, purpose, message):
    # C2
    if view["consent"].get(f"{channel}/{purpose}") is not True:
        return _stop("NO_CONSENT", TEAM_LEAD, f"The customer has not agreed to {purpose} "
                     f"messages by {channel}.")
    # C3
    if any(word in message.lower() for word in OFFER_WORDS):
        return _stop("NO_OFFER_POLICY", TEAM_LEAD, "The message offers a discount or "
                     "compensation, and no such policy exists.")
    return ALLOWED


# ---------------------------------------------------------------------------
# BILLING
# ---------------------------------------------------------------------------
def decide_refund(view, amount_gbp):
    total = view["refunds_so_far_gbp"] + float(amount_gbp)
    # B1
    if total > view["order"]["value_gbp"]:
        return _stop("OVER_ORDER_VALUE", BILLING_LEAD, f"Refunds would total {total:g} GBP on "
                     f"an order worth {view['order']['value_gbp']:g} GBP.")
    # B2
    if total > REFUND_LIMIT_GBP:
        return _stop("NEEDS_APPROVAL", BILLING_LEAD, f"Refunds would total {total:g} GBP, above "
                     f"the {REFUND_LIMIT_GBP} GBP limit. Use request_approval instead.")
    return ALLOWED


# ---------------------------------------------------------------------------
# RETURNS
# ---------------------------------------------------------------------------
def decide_disposition(view, disposition):
    # R1
    if view["on_recall_list"] and disposition != "quarantine":
        return _stop("RECALLED", RETURNS_SUPERVISOR, f"{view['item']} is on the recall list "
                     f"({view['recall_notice']}). It may only be quarantined.")
    # R2
    if view["value_gbp"] > HIGH_VALUE_GBP:
        return _stop("HIGH_VALUE", RETURNS_SUPERVISOR, f"{view['item']} is worth "
                     f"{view['value_gbp']:g} GBP. The returns supervisor decides.")
    # R3
    if disposition == "restock" and view["condition_grade"] != "A":
        return _stop("GRADE_NOT_FIT", RETURNS_SUPERVISOR, f"The inspector graded it "
                     f"{view['condition_grade']}. Only grade A goes back on the shelf.")
    return ALLOWED


def decide_claim(view):
    # R2
    if view["value_gbp"] > HIGH_VALUE_GBP:
        return _stop("HIGH_VALUE", RETURNS_SUPERVISOR, f"{view['item']} is worth "
                     f"{view['value_gbp']:g} GBP. The returns supervisor decides.")
    # R4
    if view["days_to_vendor_deadline"] < 0:
        return _stop("CLAIM_EXPIRED", RETURNS_SUPERVISOR, f"The vendor's deadline passed "
                     f"{-view['days_to_vendor_deadline']} days ago.")
    return ALLOWED


# ---------------------------------------------------------------------------
# THE ROUTER: which team does a request belong to?
# Code decides when the words are clear. Only an unclear request goes to the model.
# ---------------------------------------------------------------------------
MONEY_WORDS = ["refund", "money back", "charged", "overcharge", "reimburse", "repay"]


def route_by_rules(text):
    """Returns (route, reason). route is complaints, returns, billing or unsure."""
    t = text.lower()
    has_return = bool(re.search(r"\br-\d{3}\b", t))
    has_complaint = bool(re.search(r"\bc-\d{3}\b", t))
    wants_money = any(word in t for word in MONEY_WORDS)
    contexts = sum([has_return, has_complaint and not wants_money, wants_money])
    if contexts > 1:
        return "unsure", "The request touches more than one team"
    if has_return:
        return "returns", "It names a return (R-...)"
    if wants_money:
        return "billing", "It asks for money back"
    if has_complaint:
        return "complaints", "It names a complaint (C-...)"
    return "unsure", "No complaint or return is named, and no refund is asked for"
