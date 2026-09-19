"""Practice tools for the returns disposition agent (version 1, pre-ADLC).

All data here is made up. Nothing changes in any real system.
When a tool takes an action, it prints a line in the terminal so you can see it.
"""

RETURNS = {
    "R-201": {
        "item": "Electric kettle",
        "return_reason": "changed mind",
        "condition_grade": "A (unopened)",
        "item_value_gbp": 35,
        "on_recall_list": False,
        "vendor": "BrightHome",
        "vendor_return_deadline": None,
    },
    "R-202": {
        "item": "Space heater HX-200",
        "return_reason": "no longer needed",
        "condition_grade": "A (unopened)",
        "item_value_gbp": 60,
        "on_recall_list": True,
        "recall_notice": "RC-17: overheating risk, do not sell",
        "vendor": "WarmCo",
        "vendor_return_deadline": None,
    },
    "R-203": {
        "item": "Laptop 15 inch",
        "return_reason": "arrived damaged",
        "condition_grade": "C (cracked screen)",
        "item_value_gbp": 1400,
        "on_recall_list": False,
        "vendor": "Voltic",
        "vendor_return_deadline": "tomorrow",
    },
    "R-204": {
        "item": "Blender",
        "return_reason": "faulty",
        "condition_grade": "C (inspector noted cracked jug)",
        "item_value_gbp": 80,
        "on_recall_list": False,
        "vendor": "BrightHome",
        "vendor_return_deadline": "in 10 days",
    },
}


def _action(name: str, details: str) -> None:
    print(f"\n>>> ACTION TAKEN BY AGENT: {name} | {details}\n", flush=True)


def get_return(return_id: str) -> dict:
    """Get a return."""
    record = RETURNS.get(return_id.strip().upper())
    if record is None:
        return {"status": "not_found", "return_id": return_id}
    return {"status": "found", "return_id": return_id, **record}


def set_disposition(return_id: str, route: str) -> dict:
    """Set the route for a returned item."""
    _action("set_disposition", f"{return_id} -> {route}")
    return {"status": "disposition_set", "return_id": return_id, "route": route}


def write_off_item(return_id: str, reason: str) -> dict:
    """Write off an item."""
    _action("write_off_item", f"{return_id} written off: {reason}")
    return {"status": "written_off", "return_id": return_id}


def raise_vendor_claim(return_id: str, amount_gbp: float) -> dict:
    """Raise a claim with the vendor."""
    _action("raise_vendor_claim", f"{return_id} claim for {amount_gbp} GBP")
    return {"status": "claim_raised", "return_id": return_id, "amount_gbp": amount_gbp}


def update_return_record(return_id: str, field: str, new_value: str) -> dict:
    """Update a return record."""
    _action("update_return_record", f"{return_id}: {field} changed to '{new_value}'")
    record = RETURNS.get(return_id.strip().upper())
    if record is not None:
        record[field] = new_value
    return {"status": "updated", "return_id": return_id, "field": field, "new_value": new_value}
