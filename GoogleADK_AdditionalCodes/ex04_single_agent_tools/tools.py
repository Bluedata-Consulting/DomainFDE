"""The tools.

Everything the model knows about a tool comes from three things: the function
name, the type hints, and the docstring. ADK turns those into the function
declaration Gemini sees. There is no separate schema file, which is convenient
and also means a lazy docstring is a production bug.

Rules this module follows, all of them learned the hard way:

* **No default argument values.** ADK's automatic declaration builder does not
  express them, and a tool whose signature says a parameter is optional when the
  schema says it is required produces confusing failures. Make everything
  required and handle "not supplied" inside the function.

* **Return a dict, always, with a `status` key.** The return value is fed back
  to the model as text. A bare string gives it nothing to branch on; a dict with
  `status: "error"` and a readable `error_message` lets it recover or explain.

* **Never raise for expected conditions.** An unknown order ID is a normal
  outcome, not an exception. Raising aborts the turn; returning
  `status: "not_found"` lets the model ask the user for a correct ID.

* **Describe when to use it, not just what it does.** The docstring is prompt
  text. "Use this before promising a replacement" changes behaviour; "gets
  inventory" does not.
"""

from __future__ import annotations

from google.adk.tools import ToolContext

from .mock_backend import (
    TODAY,
    best_fulfilment_node,
    days_since,
    fetch_order,
    fetch_sku,
)

# Goodwill a care agent may issue without approval (POL-GDW-001 section 2).
AGENT_GOODWILL_LIMIT_INR = 500.0


def lookup_order(order_id: str) -> dict:
    """Look up an Aurora order: status, delivery dates, carrier and line items.

    Call this first for any question that mentions an order. Never state an
    order's status, delivery date or contents without calling this — you have no
    other source for them.

    Args:
        order_id: The Aurora order reference, for example "AUR-88213". Case
            insensitive. If the customer has not given one, ask for it rather
            than guessing.

    Returns:
        status "success" with the order record, or "not_found" when no such
        order exists.
    """
    order = fetch_order(order_id)
    if not order:
        return {
            "status": "not_found",
            "error_message": (
                f"No order matching '{order_id}'. Ask the customer to confirm the "
                f"reference from their confirmation email."
            ),
        }

    days_late = None
    if order["status"] != "delivered":
        promised = days_since(order["promised_date"])
        days_late = promised if promised and promised > 0 else 0

    return {
        "status": "success",
        "order": order,
        "as_of_date": TODAY.isoformat(),
        "days_past_promised": days_late,
        "days_since_last_scan": days_since(order.get("last_scan")),
        "days_since_delivery": days_since(order.get("delivered_date")),
    }


def check_inventory(sku: str, destination_city_tier: str) -> dict:
    """Check whether a SKU can actually be shipped, from where, and how fast.

    Call this before promising any replacement, exchange or redelivery. A
    promise made without checking is the most expensive mistake in this role:
    the stock may be zero, quarantined, or a discontinued line with no
    replenishment.

    Args:
        sku: The Aurora SKU code, for example "AUR-DIFF-CER-01". Take it from
            the order's line items rather than inventing one.
        destination_city_tier: Either "metro" or "non_metro". Read it from the
            order record returned by lookup_order. Store dispatch is available
            to metro destinations only.

    Returns:
        status "success" with availability, the fastest fulfilment node and
        estimated working days, or "not_found" for an unknown SKU. When the SKU
        is quarantined or discontinued, `fulfillable` is false and `reason`
        explains why — in those cases a refund is the only valid resolution.
    """
    record = fetch_sku(sku)
    if not record:
        return {
            "status": "not_found",
            "error_message": f"No SKU matching '{sku}' in the inventory master.",
        }

    tier = destination_city_tier.strip().lower()
    if tier not in {"metro", "non_metro"}:
        return {
            "status": "error",
            "error_message": "destination_city_tier must be 'metro' or 'non_metro'.",
        }

    total = sum(record["nodes"].values())

    # Business rules the model must not be trusted to remember. Encoding them in
    # the tool rather than the prompt is what makes them reliable.
    if record["status"] == "quarantined":
        return {
            "status": "success",
            "sku": record["sku"],
            "fulfillable": False,
            "reason": (
                f"SKU is under quality quarantine and is blocked at every node. "
                f"{record.get('quarantine_reason', '')} Quarantined stock must never "
                f"be used for a replacement. Resolve with a refund."
            ),
            "units_on_hand": total,
        }

    if record["status"] == "discontinued" or total == 0:
        replenishing = record.get("replenishment") == "active"
        return {
            "status": "success",
            "sku": record["sku"],
            "fulfillable": False,
            "reason": (
                "No stock at any node and no replenishment planned — this is a "
                "discontinued or seasonal line. Resolve with a refund."
                if not replenishing
                else f"No stock at any node. Next inbound is "
                f"{record.get('next_inbound_days')} days away."
            ),
            "units_on_hand": total,
            "next_inbound_days": record.get("next_inbound_days"),
        }

    node, days = best_fulfilment_node(record, tier)
    if node is None:
        return {
            "status": "success",
            "sku": record["sku"],
            "fulfillable": False,
            "reason": (
                "Stock exists but cannot be dispatched to this destination. Store "
                "dispatch is metro-only, and stores on planogram must retain 3 "
                "display units."
            ),
            "units_on_hand": total,
        }

    return {
        "status": "success",
        "sku": record["sku"],
        "description": record["description"],
        "fulfillable": True,
        "units_on_hand": total,
        "fulfil_from": node,
        "estimated_working_days": days,
        "unit_price_inr": record["unit_price_inr"],
    }


def check_return_eligibility(order_id: str, reason: str, item_opened: str) -> dict:
    """Decide whether an item on an order is still eligible for return.

    Applies Aurora's returns policy to the actual delivery date on the order.
    Use this instead of reasoning about dates yourself — arithmetic on delivery
    windows is exactly the kind of thing to push into code.

    Args:
        order_id: The Aurora order reference, for example "AUR-90455".
        reason: The customer's stated reason, in their own words, for example
            "arrived cracked" or "did not like the fragrance".
        item_opened: "yes" if the customer has opened or used the item, "no" if
            it is unopened and in original packaging, "unknown" if they have not
            said. Ask rather than assuming.

    Returns:
        status "success" with `eligible`, the governing rule, and the days
        remaining in the window. `requires_approval` is true when a supervisor
        must sign off before anything is promised.
    """
    order = fetch_order(order_id)
    if not order:
        return {"status": "not_found", "error_message": f"No order '{order_id}'."}

    if order["status"] != "delivered":
        return {
            "status": "success",
            "eligible": False,
            "rule": "Returns start at the delivery scan. This order is not delivered.",
            "requires_approval": False,
        }

    since = days_since(order["delivered_date"]) or 0
    opened = item_opened.strip().lower()
    defect_words = ("crack", "leak", "damag", "broken", "seal", "odour", "odor",
                    "contaminat", "separat", "wrong", "short", "missing")
    claims_defect = any(word in reason.lower() for word in defect_words)

    if opened == "no":
        return {
            "status": "success",
            "eligible": since <= 30,
            "rule": "Unopened items: 30 days from the delivery scan (POL-RET-004 s1).",
            "days_since_delivery": since,
            "days_remaining": max(0, 30 - since),
            "requires_approval": False,
        }

    if opened == "yes":
        return {
            "status": "success",
            "eligible": since <= 7 and claims_defect,
            "rule": (
                "Opened personal care items: 7 days from delivery, and only where a "
                "manufacturing defect is claimed (POL-RET-004 s2). Dissatisfaction "
                "with fragrance or texture is not a defect."
            ),
            "days_since_delivery": since,
            "days_remaining": max(0, 7 - since),
            "defect_claimed": claims_defect,
            "requires_approval": since <= 7 and not claims_defect,
        }

    return {
        "status": "needs_input",
        "error_message": (
            "Ask the customer whether the item has been opened — the window is 30 "
            "days unopened but only 7 days opened."
        ),
    }


def raise_service_request(
    order_id: str,
    action: str,
    sku: str,
    goodwill_inr: float,
    justification: str,
    tool_context: ToolContext,
) -> dict:
    """Raise a service request: replacement, redelivery, refund or escalation.

    This is the only tool that changes anything. Call it once you have checked
    the order, and — for any replacement or redelivery — confirmed with
    check_inventory that the item can actually ship. Never call it to promise a
    replacement of a SKU that came back as not fulfillable.

    Args:
        order_id: The Aurora order reference.
        action: One of "replacement", "redelivery", "refund", "escalate".
        sku: The affected SKU code, or "ALL" when the whole order is affected.
        goodwill_inr: Goodwill store credit in INR. Pass 0.0 when none applies.
            Anything above 500 needs supervisor approval and will be held.
        justification: One sentence citing what you checked and why this action
            follows. This is written to the audit log.
        tool_context: Injected by ADK. Do not pass this yourself.

    Returns:
        status "success" with a request reference, or "held_for_approval" when
        the request exceeds what a care agent may authorise.
    """
    order = fetch_order(order_id)
    if not order:
        return {"status": "not_found", "error_message": f"No order '{order_id}'."}

    valid = {"replacement", "redelivery", "refund", "escalate"}
    if action not in valid:
        return {
            "status": "error",
            "error_message": f"action must be one of {sorted(valid)}.",
        }

    # ToolContext.state is the session's scratchpad, shared across turns and
    # across agents. Writing here is how a tool leaves a trail the rest of the
    # conversation — and your audit log — can see.
    log = list(tool_context.state.get("service_requests", []))
    reference = f"SR-{order_id.split('-')[-1]}-{len(log) + 1:02d}"

    record = {
        "reference": reference,
        "order_id": order["order_id"],
        "action": action,
        "sku": sku,
        "goodwill_inr": goodwill_inr,
        "justification": justification,
    }

    if goodwill_inr > AGENT_GOODWILL_LIMIT_INR:
        record["state"] = "held_for_approval"
        log.append(record)
        tool_context.state["service_requests"] = log
        return {
            "status": "held_for_approval",
            "reference": reference,
            "error_message": (
                f"Goodwill of INR {goodwill_inr:,.0f} exceeds the INR "
                f"{AGENT_GOODWILL_LIMIT_INR:,.0f} an agent may authorise. The request "
                f"is logged and queued for a team lead. Tell the customer a colleague "
                f"will confirm within one working day — do not promise the amount."
            ),
        }

    record["state"] = "raised"
    log.append(record)
    tool_context.state["service_requests"] = log

    return {
        "status": "success",
        "reference": reference,
        "action": action,
        "goodwill_inr": goodwill_inr,
        "message": f"Service request {reference} raised for order {order['order_id']}.",
    }
