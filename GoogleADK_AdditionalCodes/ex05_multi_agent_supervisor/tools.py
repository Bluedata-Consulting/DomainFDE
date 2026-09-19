"""Tools, grouped by the specialist that owns them.

Tool ownership is the thing that makes the supervisor pattern work. Each
specialist gets only the tools for its domain, which does two things:

  * The model's choice is easier. Picking from three tools in one domain is a
    far more reliable decision than picking from nine across three domains.
  * The boundary is enforceable. The demand analyst cannot read a shipment
    record, so it cannot quietly start answering logistics questions badly —
    it has to say it does not know, which routes the work back to the supervisor.

Same tool-design rules as example 4: no default arguments, always return a dict
with a `status`, never raise for an expected condition, and write the docstring
as prompt text.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


@lru_cache(maxsize=3)
def _load(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _not_found(sku: str, source: str) -> dict:
    return {
        "status": "not_found",
        "error_message": (
            f"No record for SKU '{sku}' in {source}. Confirm the SKU code — Aurora "
            f"codes look like AUR-DIFF-CER-01."
        ),
    }


# ---------------------------------------------------------------------------
# Demand analyst tools
# ---------------------------------------------------------------------------


def get_sales_velocity(sku: str) -> dict:
    """Get sales velocity, trend and 30-day forecast for one SKU.

    Use this to establish how fast a product is actually moving before anyone
    reasons about stock cover. Compare the 7-day rate against the 8-week average
    to spot acceleration that a cover calculation based on the average would
    miss.

    Args:
        sku: Aurora SKU code, for example "AUR-DIFF-CER-01".

    Returns:
        status "success" with daily rates, trend, seasonality notes and the
        30-day unit forecast, or "not_found".
    """
    record = _load("demand.json")["skus"].get(sku.strip().upper())
    if not record:
        return _not_found(sku, "the demand history")

    avg = record["units_per_day_8wk_avg"]
    recent = record["units_per_day_last_7d"]
    swing = ((recent - avg) / avg * 100) if avg else 0.0

    return {
        "status": "success",
        "sku": sku.strip().upper(),
        **record,
        "recent_vs_average_pct": round(swing, 1),
    }


def get_promotions(sku: str) -> dict:
    """Get planned promotions affecting a SKU, with uplift and commitment status.

    Always check this before judging whether stock cover is adequate. A locked
    promotion is a commitment Aurora has already spent money on, so the demand
    it creates is not optional — the stock plan has to move to meet it, not the
    other way round.

    Args:
        sku: Aurora SKU code. Pass "ALL" to list every planned promotion.

    Returns:
        status "success" with the matching promotions. A promotion with status
        "locked" cannot be cancelled or rescheduled; "draft" still can be.
    """
    promotions = _load("demand.json")["promotions"]
    target = sku.strip().upper()
    matches = (
        promotions
        if target == "ALL"
        else [p for p in promotions if target in p["skus"]]
    )
    return {
        "status": "success",
        "count": len(matches),
        "promotions": matches,
        "note": "No promotions found for this SKU." if not matches else None,
    }


# ---------------------------------------------------------------------------
# Inventory planner tools
# ---------------------------------------------------------------------------


def get_stock_position(sku: str) -> dict:
    """Get on-hand stock by node, quantity already on order, and product status.

    Call this before any statement about availability. A SKU with healthy total
    stock can still be unusable: check the `status` field, because quarantined
    stock is blocked at every node and must never be counted as available.

    Args:
        sku: Aurora SKU code, for example "AUR-DIFF-CER-01".

    Returns:
        status "success" with per-node quantities, on-order units, supplier and
        product status, or "not_found".
    """
    record = _load("inventory.json")["skus"].get(sku.strip().upper())
    if not record:
        return _not_found(sku, "the inventory master")

    on_hand = sum(record["nodes"].values())
    available = 0 if record["status"] != "active" else on_hand

    return {
        "status": "success",
        "sku": sku.strip().upper(),
        **record,
        "total_on_hand_units": on_hand,
        "available_units": available,
        "availability_note": (
            record.get("quarantine_reason")
            if record["status"] == "quarantined"
            else None
        ),
    }


def compute_stock_cover(sku: str, daily_demand_units: float) -> dict:
    """Compute days of forward cover and whether a reorder is triggered.

    Do the arithmetic here rather than in your head. Pass the daily demand rate
    the demand analyst gave you — use the recent 7-day rate, not the 8-week
    average, when the trend is accelerating, or you will understate the risk.

    Args:
        sku: Aurora SKU code.
        daily_demand_units: Expected units sold per day. Include promotional
            uplift where a locked promotion applies.

    Returns:
        status "success" with days of cover, the safety-stock threshold for the
        SKU's class, whether a reorder is triggered, and the shortfall in units
        against 45 days of cover.
    """
    data = _load("inventory.json")
    record = data["skus"].get(sku.strip().upper())
    if not record:
        return _not_found(sku, "the inventory master")

    if daily_demand_units <= 0:
        return {
            "status": "error",
            "error_message": "daily_demand_units must be greater than zero.",
        }

    on_hand = sum(record["nodes"].values()) if record["status"] == "active" else 0
    safety_days = data["safety_stock_days"][record["class"]]
    cover_days = on_hand / daily_demand_units
    target_units = daily_demand_units * 45

    return {
        "status": "success",
        "sku": sku.strip().upper(),
        "available_units": on_hand,
        "daily_demand_units": daily_demand_units,
        "days_of_cover": round(cover_days, 1),
        "safety_stock_days": safety_days,
        "reorder_triggered": cover_days < safety_days,
        "units_short_of_45d_cover": max(0, round(target_units - on_hand)),
        "on_order_units": record["on_order_units"],
        "note": (
            record.get("quarantine_reason")
            if record["status"] != "active"
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Logistics coordinator tools
# ---------------------------------------------------------------------------


def get_open_shipments(sku: str) -> dict:
    """Get inbound shipments for a SKU, with contracted versus current ETA.

    Check this before concluding that on-order stock will arrive in time. The
    gap between contracted_eta and current_eta is the slippage, and it is the
    number that matters for a promotion date.

    Args:
        sku: Aurora SKU code. Pass "ALL" for every open shipment.

    Returns:
        status "success" with matching shipments, each carrying its slippage in
        days and a delay reason where one exists.
    """
    from datetime import date

    shipments = _load("logistics.json")["shipments"]
    target = sku.strip().upper()
    matches = shipments if target == "ALL" else [s for s in shipments if s["sku"] == target]

    enriched = []
    for shipment in matches:
        contracted = date.fromisoformat(shipment["contracted_eta"])
        current = date.fromisoformat(shipment["current_eta"])
        enriched.append({**shipment, "slippage_days": (current - contracted).days})

    return {
        "status": "success",
        "count": len(enriched),
        "shipments": enriched,
        "note": "No open inbound shipments for this SKU." if not enriched else None,
    }


def get_supplier_performance(supplier_id: str) -> dict:
    """Get a supplier's reliability, real lead times and expedite options.

    Use this when a shipment is late or a reorder is urgent. Contracted lead
    time is frequently fiction — judge by actual_lead_time_last_3_orders_days
    and the on-time rate. Where air freight is available, this returns the
    premium per unit so the cost of expediting can be quantified rather than
    hand-waved.

    Args:
        supplier_id: Supplier reference, for example "SUP-CERAM-04". Take it
            from the stock position record rather than guessing.

    Returns:
        status "success" with contracted and actual lead times, on-time rate and
        air freight options, or "not_found".
    """
    suppliers = _load("logistics.json")["suppliers"]
    record = suppliers.get(supplier_id.strip().upper())
    if not record:
        return {
            "status": "not_found",
            "error_message": (
                f"No supplier '{supplier_id}'. Known suppliers: "
                f"{', '.join(sorted(suppliers))}."
            ),
        }

    actuals = record["actual_lead_time_last_3_orders_days"]
    return {
        "status": "success",
        "supplier_id": supplier_id.strip().upper(),
        **record,
        "mean_actual_lead_time_days": round(sum(actuals) / len(actuals), 1),
        "lead_time_variance_vs_contract_days": round(
            sum(actuals) / len(actuals) - record["contracted_lead_time_days"], 1
        ),
    }
