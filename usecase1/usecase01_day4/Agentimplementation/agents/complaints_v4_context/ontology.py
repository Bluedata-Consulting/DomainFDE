"""The complaints ontology, in code (Day 4: Context).

Plain Python. No ADK, no AI model. It does three jobs:

  1. FOLLOW LINKS: turn a complaint ID into everything that belongs with it, by
     following the relationships in ontology.yaml (complaint -> account -> customer).
  2. VALIDATE: check the data against the rules in ontology.yaml, and report every
     CONTRADICTION.
  3. ANSWER GOLDEN QUESTIONS: each answer is found only by following links. If a
     link is not in the ontology, the question is a GAP.

The files it reads sit in the kit folder: ontology.yaml and data/northwind.json.
"""
import json
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parents[2]
ONTOLOGY = yaml.safe_load((KIT / "ontology.yaml").read_text(encoding="utf-8"))
DATA = json.loads((KIT / "data" / "northwind.json").read_text(encoding="utf-8"))

REFUND_LIMIT_GBP = 25
LEGAL_WORDS = ["ombudsman", "solicitor", "lawyer", "legal action", "trading standards",
               "legal representative"]
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}


class Gap(Exception):
    """The ontology has no relationship to follow for this question."""


# ---------------------------------------------------------------------------
# 1. FOLLOW LINKS
# ---------------------------------------------------------------------------
def _by_key(table, key):
    return {row[key]: row for row in DATA[table]}


def require_link(source, name, target):
    """Stop with a Gap if ontology.yaml does not define this relationship."""
    for rel in ONTOLOGY["relationships"]:
        if (rel["from"], rel["name"], rel["to"]) == (source, name, target):
            return
    raise Gap(f"The ontology has no relationship: {source} {name} {target}.")


def complaint(complaint_id):
    return _by_key("complaints", "complaint_id").get(str(complaint_id).strip().upper())


def customer_of(complaint_id):
    require_link("Complaint", "raised_from", "Account")
    require_link("Account", "belongs_to", "Customer")
    account = _by_key("accounts", "account_id")[complaint(complaint_id)["account_id"]]
    return _by_key("customers", "customer_id")[account["customer_id"]]


def accounts_of(customer_id):
    return [a for a in DATA["accounts"] if a["customer_id"] == customer_id]


def complaints_of(customer_id):
    ids = {a["account_id"] for a in accounts_of(customer_id)}
    return [c for c in DATA["complaints"] if c["account_id"] in ids]


def order_of(complaint_id):
    require_link("Complaint", "about", "Order")
    return _by_key("orders", "order_id")[complaint(complaint_id)["order_id"]]


def refunds_so_far(complaint_id):
    require_link("Refund", "settles", "Complaint")
    return sum(r["amount_gbp"] for r in DATA["refunds"] if r["complaint_id"] == complaint_id)


def consent(customer_id, channel, purpose):
    """True or False if recorded for this channel and purpose; None if not recorded."""
    require_link("Consent", "given_by", "Customer")
    for c in DATA["consents"]:
        if (c["customer_id"], c["channel"], c.get("purpose")) == (customer_id, channel, purpose):
            return c["allowed"]
    return None


def record_refund(complaint_id, amount_gbp):
    """A refund issued by the agent joins the data, so later totals include it."""
    DATA["refunds"].append({
        "refund_id": f"REF-AGENT-{len(DATA['refunds']) + 1:03d}",
        "complaint_id": complaint_id, "amount_gbp": float(amount_gbp),
    })


def complaint_view(complaint_id):
    """Everything the agent and the rules need about one complaint, found by following links."""
    c = complaint(complaint_id)
    if c is None:
        return None
    cid = c["complaint_id"]
    person = customer_of(cid)
    order = order_of(cid)
    so_far = refunds_so_far(cid)
    consents = {f"{k['channel']}/{k['purpose']}": k["allowed"]
                for k in DATA["consents"]
                if k["customer_id"] == person["customer_id"] and k.get("purpose")}
    return {
        "complaint_id": cid,
        "text": c["text"],
        "arrived_via": c["arrived_via"],
        "order": {"order_id": order["order_id"], "value_gbp": order["value_gbp"]},
        "customer": {
            "customer_id": person["customer_id"],
            "name": person["name"],
            "vulnerable": person["vulnerable"],
            "circumstance": person["circumstance"],
            "accounts": [a["account_id"] for a in accounts_of(person["customer_id"])],
        },
        "earlier_complaints_from_this_customer": [
            other["complaint_id"] for other in complaints_of(person["customer_id"])
            if other["complaint_id"] != cid],
        "consent": consents,
        "refunds_so_far_gbp": so_far,
        "refund_headroom_gbp": max(0, REFUND_LIMIT_GBP - so_far),
        "at_risk": is_at_risk(cid),
    }


def is_at_risk(complaint_id):
    person = customer_of(complaint_id)
    text = complaint(complaint_id)["text"].lower()
    return bool(person["vulnerable"]) or any(w in text for w in LEGAL_WORDS)


# ---------------------------------------------------------------------------
# 2. VALIDATE
# ---------------------------------------------------------------------------
def validate():
    """Check the data against every rule in ontology.yaml.

    Returns a list of findings: (rule_id, record_id, result, detail).
    result is CONTRADICTION for each broken rule, or CONFORMS for a rule with none.
    """
    customers = _by_key("customers", "customer_id")
    accounts = _by_key("accounts", "account_id")
    orders = _by_key("orders", "order_id")
    found = []

    def bad(rule, record, detail):
        found.append((rule, record, "CONTRADICTION", detail))

    for a in DATA["accounts"]:
        if a["customer_id"] not in customers:
            bad("account_has_customer", a["account_id"], f"customer {a['customer_id']} does not exist")

    for c in DATA["complaints"]:
        complaint_owner = accounts[c["account_id"]]["customer_id"]
        order_owner = accounts[orders[c["order_id"]]["account_id"]]["customer_id"]
        if complaint_owner != order_owner:
            bad("complaint_order_same_customer", c["complaint_id"],
                f"complaint is from {complaint_owner}, but {c['order_id']} belongs to {order_owner}")

    for c in DATA["complaints"]:
        total = sum(r["amount_gbp"] for r in DATA["refunds"] if r["complaint_id"] == c["complaint_id"])
        value = orders[c["order_id"]]["value_gbp"]
        if total > value:
            bad("refunds_within_order_value", c["complaint_id"],
                f"refunds total {total:g} GBP, but the order is worth {value:g} GBP")

    for a in DATA["accounts"]:
        if "vulnerable" in a and a["vulnerable"] != customers[a["customer_id"]]["vulnerable"]:
            bad("vulnerability_one_value_per_customer", a["account_id"],
                f"account says vulnerable={a['vulnerable']}, customer {a['customer_id']} says "
                f"vulnerable={customers[a['customer_id']]['vulnerable']}")

    for k in DATA["consents"]:
        if not k.get("purpose") or not k.get("channel") or "allowed" not in k:
            bad("consent_has_purpose", k["customer_id"],
                f"consent for channel '{k.get('channel')}' has no purpose")

    for c in DATA["complaints"]:
        text = c["text"].lower()
        for word, n in ORDINALS.items():
            if f"{word} time" in text and c["reported_previous_contacts"] != n - 1:
                bad("contacts_match_text", c["complaint_id"],
                    f"text says the {word} time ({n - 1} previous), data says "
                    f"{c['reported_previous_contacts']} previous")

    broken = {f[0] for f in found}
    for rule in ONTOLOGY["rules"]:
        if rule["id"] not in broken:
            found.append((rule["id"], "all records", "CONFORMS", rule["rule"]))
    return found


# ---------------------------------------------------------------------------
# 3. GOLDEN QUESTIONS: answered only by following links
# ---------------------------------------------------------------------------
def can_message(complaint_id, channel, purpose):
    allowed = consent(customer_of(complaint_id)["customer_id"], channel, purpose)
    return "yes" if allowed else "no"


def at_risk(complaint_id):
    return "yes" if is_at_risk(complaint_id) else "no"


def refund_headroom(complaint_id):
    return f"{max(0, REFUND_LIMIT_GBP - refunds_so_far(complaint_id)):g}"


def complaints_by_same_person(complaint_id):
    return str(len(complaints_of(customer_of(complaint_id)["customer_id"])))


def reopened_within_14_days(complaint_id):
    require_link("Complaint", "reopens", "Complaint")
    return "no"
