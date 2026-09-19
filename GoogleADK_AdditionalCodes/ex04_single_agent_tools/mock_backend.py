"""Stand-in for Aurora's order management and inventory systems.

Everything an agent touches in the real world sits behind a network call that
can be slow, stale, or down. Isolating those calls in one module means the tool
layer above — which is the part the model sees — never changes when you swap
JSON files for a real OMS client.

This is also where you put the boring realism that makes agents behave: an
inventory system that returns a quarantine flag, an order lookup that can miss.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# Frozen "today" so the examples produce stable output. In production this is
# datetime.now() and your test fixtures freeze the clock instead.
TODAY = date(2026, 2, 11)

# Dispatch lead times in working days, by source node type and destination tier.
DISPATCH_DAYS = {
    ("dc", "metro"): 2,
    ("dc", "non_metro"): 5,
    ("store", "metro"): 1,
    ("store", "non_metro"): None,  # store dispatch is metro-only
}


@lru_cache(maxsize=1)
def _orders() -> dict:
    return json.loads((DATA_DIR / "orders.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _inventory() -> dict:
    return json.loads((DATA_DIR / "inventory.json").read_text(encoding="utf-8"))


def fetch_order(order_id: str) -> dict | None:
    return _orders().get(order_id.strip().upper())


def fetch_sku(sku: str) -> dict | None:
    return _inventory().get(sku.strip().upper())


def days_since(iso_date: str | None) -> int | None:
    if not iso_date:
        return None
    parsed = datetime.fromisoformat(iso_date).date()
    return (TODAY - parsed).days


def dispatch_estimate(node: str, city_tier: str) -> int | None:
    """Working days from a given node to a destination of a given tier."""
    node_type = "store" if node.startswith("STORE") else "dc"
    return DISPATCH_DAYS.get((node_type, city_tier))


def best_fulfilment_node(sku_record: dict, city_tier: str) -> tuple[str | None, int | None]:
    """Pick the fastest node holding stock. Returns (node, working_days)."""
    options: list[tuple[str, int]] = []
    for node, qty in sku_record["nodes"].items():
        if qty <= 0:
            continue
        # Store dispatch may not drop a planogram store below 3 display units.
        if node.startswith("STORE") and qty <= 3:
            continue
        days = dispatch_estimate(node, city_tier)
        if days is not None:
            options.append((node, days))

    if not options:
        return None, None
    node, days = min(options, key=lambda pair: pair[1])
    return node, days
