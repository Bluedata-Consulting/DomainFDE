"""Business-named tools over the Meridian Roasters database.

Each tool answers a business question rather than exposing a table, and each
docstring states what the tool is NOT for, because the vocabulary here is
deliberately ambiguous (order, shipment, contact, lead time, lot vs batch).
`sqltools.py` stays available as a generic fallback.

Metric definitions -- do not redefine them elsewhere:
    on_time_delivery = delivered_at IS NOT NULL
                       AND date(delivered_at) <= date(promised_at)
                       -- in-transit shipments are EXCLUDED, not late
    supplier lead time (actual)
                     = julianday(actual_arrival) - julianday(po_date)
"""

from .db import TODAY, like, one, rows

# ----------------------------------------------------- result envelopes

# The row cap each list tool will ever return. A caller asking for more is
# clamped to this and told so, rather than quietly getting the cap: a model
# that receives exactly `limit` rows and no truncation flag has every reason
# to try again with a bigger number, which is the loop this removes.
HARD_CAPS = {
    "find_customers": 25,
    "find_sales_orders": 50,
    "find_late_shipments": 50,
    "find_tickets": 50,
    "find_purchase_orders": 50,
}

# Most ids a batch tool accepts in one call.
MAX_IDS_PER_CALL = 25


def _capped(limit: int | None, tool_name: str) -> int:
    """Clamp a requested row limit to the tool's hard cap."""
    cap = HARD_CAPS[tool_name]
    if limit is None:
        return cap
    return max(1, min(int(limit), cap))


def _envelope(
    data: list[dict],
    *,
    limit: int | None = None,
    window: dict | None = None,
    note: str | None = None,
) -> dict:
    """Wrap rows with the facts needed to decide whether to ask again.

    Args:
        data: The rows the query returned.
        limit: The row cap actually applied, if this tool caps rows.
        window: What period or scope was actually covered, so a narrowed
            answer never looks like a complete one.
        note: Any caveat that belongs with the numbers.

    Returns:
        A dict with ``row_count`` and ``rows`` always, plus ``limit_applied``
        / ``truncated`` / ``next_step`` when a cap was in play.
    """
    out: dict = {"row_count": len(data), "rows": data}
    if limit is not None:
        out["limit_applied"] = limit
        out["truncated"] = len(data) >= limit
        if out["truncated"]:
            out["next_step"] = (
                f"You now hold every row this tool will return: {limit} is its hard "
                "cap and a larger limit is clamped back to it, so calling again with "
                "a bigger limit returns exactly these same rows. To see different "
                "rows, narrow the filters (since/until, state, status, customer_id) "
                "or ask for an aggregate instead."
            )
    if window is not None:
        out["window"] = window
    if note is not None:
        out["note"] = note
    return out


def _ids(value, param_name: str) -> tuple[list[str], dict]:
    """Normalise a batch id parameter to a capped list.

    Accepts a bare string as well as a list, so existing single-id callers and
    tests keep working even though the schema now advertises a list.

    Returns:
        (ids, meta) where meta carries any clamp note for the envelope.
    """
    if value is None:
        return [], {}
    if isinstance(value, str):
        value = [value]
    ids = [str(v) for v in dict.fromkeys(value) if str(v).strip()]
    meta: dict = {}
    if len(ids) > MAX_IDS_PER_CALL:
        meta["ids_dropped"] = ids[MAX_IDS_PER_CALL:]
        meta["note"] = (
            f"{param_name} was clamped to the first {MAX_IDS_PER_CALL} ids; "
            "call again with the rest if you still need them."
        )
        ids = ids[:MAX_IDS_PER_CALL]
    return ids, meta


def _placeholders(ids: list[str]) -> str:
    """`?, ?, ?` for an IN (...) clause."""
    return ", ".join("?" for _ in ids)


def _batch(
    results: dict,
    requested: list[str],
    meta: dict,
    *,
    note: str | None = None,
) -> dict:
    """Envelope for a batch lookup, naming the ids that had no match."""
    out: dict = {
        "requested": len(requested),
        "returned": len(results),
        "results": results,
        "not_found": [i for i in requested if i not in results],
    }
    if note or meta.get("note"):
        out["note"] = " ".join(x for x in (note, meta.get("note")) if x)
    if meta.get("ids_dropped"):
        out["ids_dropped"] = meta["ids_dropped"]
    return out


# --------------------------------------------------------------- customers


def find_customers(
    name: str | None = None,
    email: str | None = None,
    city: str | None = None,
    channel: str | None = None,
    limit: int = 25,
) -> list[dict]:
    """Resolve a person to a customer_id. Names repeat -- show all candidates.

    NOT wholesale contacts (`find_wholesale_contacts`) or supplier contacts.

    Args:
        name: Partial first/last name.
        email: Partial email.
        city: Partial city.
        channel: 'd2c' or 'wholesale'.
        limit: Max rows; default AND hard cap 25. A larger value is
            clamped back to 25, so asking for more returns the same rows.

    Returns:
        {row_count, rows, truncated, limit_applied, window}. `rows` are
        customers: customer_id, customer_name, email, city, state, country,
        channel, loyalty_tier, signup_date, account_id.
    """
    clauses, params = [], []
    if name:
        clauses.append("(first_name LIKE ? OR last_name LIKE ? "
                       "OR (first_name || ' ' || last_name) LIKE ?)")
        params += [like(name), like(name), like(name)]
    if email:
        clauses.append("email LIKE ?")
        params.append(like(email))
    if city:
        clauses.append("city LIKE ?")
        params.append(like(city))
    if channel:
        clauses.append("channel = ?")
        params.append(channel)

    limit = _capped(limit, "find_customers")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    found = rows(
        f"""
        SELECT customer_id,
               first_name || ' ' || last_name AS customer_name,
               email, city, state, country, channel, loyalty_tier,
               signup_date, account_id
        FROM customers
        {where}
        ORDER BY last_name, first_name
        LIMIT ?
        """,
        params + [limit],
    )
    return _envelope(
        found,
        limit=limit,
        window={"name": name, "email": email, "city": city, "channel": channel},
    )


def get_customer_360(customer_id: list[str]) -> dict:
    """Full picture of one or MANY customers: profile, last 10 orders, last 10 tickets, subscriptions.

    Start here for "what is going on with this customer". NOT line-level or
    shipment detail on one order (`get_sales_order_detail`).

    Pass EVERY customer you care about in one call -- this costs the same six
    queries for twenty-five customers as for one. Do not call it once per
    customer.

    Args:
        customer_id: One or more customer_ids from `find_customers`. A bare
            string is accepted; at most 25 ids are answered per call.

    Returns:
        {requested, returned, results, not_found} where `results` maps each
        customer_id to {customer, account, recent_orders, recent_tickets,
        subscriptions, totals}. `totals` carries order_count/ticket_count for
        the WHOLE history, and orders_truncated/tickets_truncated say whether
        the 10 shown are all there are -- when they are not, use
        `find_sales_orders(customer_id=...)` / `find_tickets(customer_id=...)`
        rather than calling this again, which would return the same 10.
    """
    ids, meta = _ids(customer_id, "customer_id")
    if not ids:
        return {"error": "Give at least one customer_id."}

    ph = _placeholders(ids)
    customers = rows(
        f"""
        SELECT customer_id,
               first_name || ' ' || last_name AS customer_name,
               email, city, state, country, postcode, channel,
               loyalty_tier, signup_date, account_id
        FROM customers WHERE customer_id IN ({ph})
        """,
        ids,
    )
    if not customers:
        return _batch({}, ids, meta)

    account_ids = [c["account_id"] for c in customers if c["account_id"]]
    accounts = {}
    if account_ids:
        accounts = {
            a["account_id"]: a
            for a in rows(
                f"SELECT * FROM wholesale_accounts WHERE account_id IN "
                f"({_placeholders(account_ids)})",
                account_ids,
            )
        }

    # One windowed query for every customer's last 10, rather than one query
    # per customer: batching the model's turns is pointless if it just moves
    # the N+1 into the database.
    order_rows = rows(
        f"""
        SELECT * FROM (
            SELECT customer_id, sales_order_id, order_date, status, channel,
                   currency, total_amount, ship_city, ship_state, ship_country,
                   ROW_NUMBER() OVER (
                       PARTITION BY customer_id ORDER BY date(order_date) DESC
                   ) AS rn
            FROM sales_orders WHERE customer_id IN ({ph})
        ) WHERE rn <= 10
        """,
        ids,
    )
    ticket_rows = rows(
        f"""
        SELECT * FROM (
            SELECT customer_id, ticket_id, sales_order_id, opened_at, category,
                   status, subject, sentiment, resolved_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY customer_id ORDER BY datetime(opened_at) DESC
                   ) AS rn
            FROM tickets WHERE customer_id IN ({ph})
        ) WHERE rn <= 10
        """,
        ids,
    )
    subscription_rows = rows(
        f"""
        SELECT s.customer_id, s.subscription_id, s.product_id,
               p.name AS product_name, s.plan, s.frequency_days, s.status,
               s.started_at, s.paused_at, s.cancelled_at, s.cancel_reason
        FROM subscriptions s
        LEFT JOIN products p ON p.product_id = s.product_id
        WHERE s.customer_id IN ({ph})
        ORDER BY s.started_at DESC
        """,
        ids,
    )
    order_counts = {
        r["customer_id"]: r["n"]
        for r in rows(
            f"SELECT customer_id, COUNT(*) AS n FROM sales_orders "
            f"WHERE customer_id IN ({ph}) GROUP BY customer_id",
            ids,
        )
    }
    ticket_counts = {
        r["customer_id"]: r["n"]
        for r in rows(
            f"SELECT customer_id, COUNT(*) AS n FROM tickets "
            f"WHERE customer_id IN ({ph}) GROUP BY customer_id",
            ids,
        )
    }

    def _grouped(source: list[dict]) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {}
        for row in source:
            row = {k: v for k, v in row.items() if k != "rn"}
            grouped.setdefault(row.pop("customer_id"), []).append(row)
        return grouped

    by_order = _grouped(order_rows)
    by_ticket = _grouped(ticket_rows)
    by_subscription = _grouped(subscription_rows)

    results = {}
    for customer in customers:
        cid = customer["customer_id"]
        shown_orders = by_order.get(cid, [])
        shown_tickets = by_ticket.get(cid, [])
        order_count = order_counts.get(cid, 0)
        ticket_count = ticket_counts.get(cid, 0)
        results[cid] = {
            "customer": customer,
            "account": accounts.get(customer["account_id"]),
            "recent_orders": shown_orders,
            "recent_tickets": shown_tickets,
            "subscriptions": by_subscription.get(cid, []),
            "totals": {
                "order_count": order_count,
                "ticket_count": ticket_count,
                "orders_shown": len(shown_orders),
                "tickets_shown": len(shown_tickets),
                "orders_truncated": order_count > len(shown_orders),
                "tickets_truncated": ticket_count > len(shown_tickets),
            },
        }

    truncated = any(
        r["totals"]["orders_truncated"] or r["totals"]["tickets_truncated"]
        for r in results.values()
    )
    return _batch(
        results,
        ids,
        meta,
        note=(
            "Only the 10 most recent orders and tickets are shown per customer. "
            "Where totals say truncated, call find_sales_orders(customer_id=...) "
            "or find_tickets(customer_id=...) for the rest -- calling this tool "
            "again returns the same 10."
        ) if truncated else None,
    )


def find_wholesale_contacts(
    name: str | None = None,
    account_id: str | None = None,
) -> list[dict]:
    """Named people at wholesale (trade) accounts -- cafes, hotels, offices.

    NOT D2C customers (`find_customers`) or supplier contacts. The same
    first name exists on both sides, so say which one you used.

    Args:
        name: Partial contact name.
        account_id: Restrict to one account.

    Returns:
        {row_count, rows, window}. `rows` are contacts: contact_id, contact_name, email, role, plus account_id,
        account_name, city, country, currency, tier.
    """
    clauses, params = [], []
    if name:
        clauses.append("c.contact_name LIKE ?")
        params.append(like(name))
    if account_id:
        clauses.append("c.account_id = ?")
        params.append(account_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    found = rows(
        f"""
        SELECT c.contact_id, c.contact_name, c.email, c.role,
               a.account_id, a.account_name, a.city, a.country,
               a.currency, a.tier
        FROM wholesale_contacts c
        JOIN wholesale_accounts a ON a.account_id = c.account_id
        {where}
        ORDER BY a.account_name, c.contact_name
        """,
        params,
    )
    return _envelope(
        found,
        window={"name": name, "account_id": account_id},
        note="The same first name exists on the customer side too -- say which side you used.",
    )


# ------------------------------------------------------------ sales orders


def find_sales_orders(
    customer_id: str | None = None,
    account_id: str | None = None,
    status: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Orders sold TO customers (outbound). NOT supplier purchase orders
    (`find_purchase_orders`).

    Args:
        customer_id: Restrict to one customer.
        account_id: Restrict to one wholesale account.
        status: placed|roasted|shipped|delivered|returned|cancelled.
        since: Earliest order_date, 'YYYY-MM-DD'.
        until: Latest order_date, 'YYYY-MM-DD'.
        limit: Max rows; default AND hard cap 50. A larger value is
            clamped back to 50, so asking for more returns the same rows.

    Returns:
        {row_count, rows, truncated, limit_applied, window}. `rows` are orders
        (newest first): sales_order_id, customer_id, customer_name,
        account_id, order_date, status, channel, currency, total_amount,
        ship_city/state/country.
    """
    clauses, params = [], []
    if customer_id:
        clauses.append("o.customer_id = ?")
        params.append(customer_id)
    if account_id:
        clauses.append("o.account_id = ?")
        params.append(account_id)
    if status:
        clauses.append("o.status = ?")
        params.append(status)
    if since:
        clauses.append("date(o.order_date) >= date(?)")
        params.append(since)
    if until:
        clauses.append("date(o.order_date) <= date(?)")
        params.append(until)

    limit = _capped(limit, "find_sales_orders")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    found = rows(
        f"""
        SELECT o.sales_order_id, o.customer_id,
               c.first_name || ' ' || c.last_name AS customer_name,
               o.account_id, o.order_date, o.status, o.channel,
               o.currency, o.total_amount,
               o.ship_city, o.ship_state, o.ship_country
        FROM sales_orders o
        LEFT JOIN customers c ON c.customer_id = o.customer_id
        {where}
        ORDER BY date(o.order_date) DESC
        LIMIT ?
        """,
        params + [limit],
    )
    return _envelope(
        found,
        limit=limit,
        window={"customer_id": customer_id, "account_id": account_id,
                "status": status, "since": since or "all time",
                "until": until or TODAY, "order": "newest first"},
    )


def get_sales_order_detail(sales_order_id: list[str]) -> dict:
    """Everything about one or MANY customer orders: header, lines, batches, shipment, refunds.

    NOT supplier purchase orders (`find_purchase_orders`).

    Pass EVERY order id you care about in one call -- this costs the same five
    queries for twenty-five orders as for one. Do not call it once per order.

    Its `shipment` block holds the same fields as `get_shipment_status`, and its
    `lines` block already carries batch_id/lot_id/qa_pass/qa_note -- so if you
    have called this, do not also call `get_shipment_status` or
    `trace_product_to_lot` for the same order.

    Args:
        sales_order_id: One or more order ids. A bare string is accepted; at
            most 25 ids are answered per call.

    Returns:
        {requested, returned, results, not_found} where `results` maps each
        sales_order_id to {order, lines, shipment, refunds, tickets}. An order
        with several shipments returns them all under `shipments`.
    """
    ids, meta = _ids(sales_order_id, "sales_order_id")
    if not ids:
        return {"error": "Give at least one sales_order_id."}

    ph = _placeholders(ids)
    orders = rows(
        f"""
        SELECT o.*, c.first_name || ' ' || c.last_name AS customer_name,
               c.email AS customer_email
        FROM sales_orders o
        LEFT JOIN customers c ON c.customer_id = o.customer_id
        WHERE o.sales_order_id IN ({ph})
        """,
        ids,
    )
    if not orders:
        return _batch({}, ids, meta)

    line_rows = rows(
        f"""
        SELECT l.sales_order_id, l.line_id, l.product_id, p.sku,
               p.name AS product_name, p.category, l.batch_id, b.roast_date,
               b.lot_id, b.qa_pass, b.qa_note,
               l.qty, l.unit_price, (l.qty * l.unit_price) AS line_amount
        FROM sales_order_lines l
        LEFT JOIN products p ON p.product_id = l.product_id
        LEFT JOIN roast_batches b ON b.batch_id = l.batch_id
        WHERE l.sales_order_id IN ({ph})
        """,
        ids,
    )
    shipment_rows = rows(
        f"""
        SELECT sales_order_id, shipment_id, carrier, tracking_ref, shipped_at,
               promised_at, delivered_at, status, dest_postcode, exception_code,
               CASE
                   WHEN delivered_at IS NULL THEN NULL
                   WHEN date(delivered_at) <= date(promised_at) THEN 1
                   ELSE 0
               END AS on_time,
               CASE
                   WHEN delivered_at IS NULL THEN NULL
                   ELSE CAST(julianday(delivered_at) - julianday(promised_at) AS INTEGER)
               END AS slip_days
        FROM shipments WHERE sales_order_id IN ({ph})
        """,
        ids,
    )
    refund_rows = rows(
        f"""
        SELECT sales_order_id, refund_id, amount, currency, reason_code,
               approved_by, created_at
        FROM refunds WHERE sales_order_id IN ({ph})
        ORDER BY created_at
        """,
        ids,
    )
    ticket_rows = rows(
        f"""
        SELECT sales_order_id, ticket_id, opened_at, category, status, subject,
               sentiment
        FROM tickets WHERE sales_order_id IN ({ph})
        ORDER BY opened_at
        """,
        ids,
    )

    def _grouped(source: list[dict]) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {}
        for row in source:
            row = dict(row)
            grouped.setdefault(row.pop("sales_order_id"), []).append(row)
        return grouped

    by_line = _grouped(line_rows)
    by_shipment = _grouped(shipment_rows)
    by_refund = _grouped(refund_rows)
    by_ticket = _grouped(ticket_rows)

    results = {}
    for order in orders:
        oid = order["sales_order_id"]
        shipments = by_shipment.get(oid, [])
        results[oid] = {
            "order": order,
            "lines": by_line.get(oid, []),
            # `shipment` is kept for the common one-parcel case; `shipments`
            # is the truth, because an order CAN have more than one and the
            # old single-row version silently hid the rest.
            "shipment": shipments[0] if shipments else None,
            "shipments": shipments,
            "refunds": by_refund.get(oid, []),
            "tickets": by_ticket.get(oid, []),
        }
    return _batch(results, ids, meta)


# --------------------------------------------------------------- shipments


def get_shipment_status(sales_order_id: list[str]) -> dict:
    """Where are these customer orders and did they arrive on time?

    OUTBOUND parcels to customers. NOT the inbound green-coffee container
    (`get_inbound_shipments`). In-transit parcels return on_time = None:
    they are not counted late.

    Pass EVERY order id in one call -- this is a single query however many you
    give it. Do not call it once per order. If you have already called
    `get_sales_order_detail` for these orders, its `shipment` block has these
    same fields and you do not need this tool as well.

    Args:
        sales_order_id: One or more customer order ids. A bare string is
            accepted; at most 25 ids are answered per call.

    Returns:
        {requested, returned, results, not_found} where `results` maps each
        sales_order_id to carrier, tracking_ref, shipped_at, promised_at,
        delivered_at, status, exception_code, on_time (1/0/None) and slip_days
        (negative = early). Orders with no shipment row appear in `not_found`.
    """
    ids, meta = _ids(sales_order_id, "sales_order_id")
    if not ids:
        return {"error": "Give at least one sales_order_id."}

    found = rows(
        f"""
        SELECT s.shipment_id, s.sales_order_id, s.carrier, s.tracking_ref,
               s.shipped_at, s.promised_at, s.delivered_at, s.status,
               s.dest_postcode, s.exception_code,
               o.ship_city, o.ship_state, o.ship_country,
               CASE
                   WHEN s.delivered_at IS NULL THEN NULL
                   WHEN date(s.delivered_at) <= date(s.promised_at) THEN 1
                   ELSE 0
               END AS on_time,
               CASE
                   WHEN s.delivered_at IS NULL THEN NULL
                   ELSE CAST(julianday(s.delivered_at) - julianday(s.promised_at) AS INTEGER)
               END AS slip_days
        FROM shipments s
        JOIN sales_orders o ON o.sales_order_id = s.sales_order_id
        WHERE s.sales_order_id IN ({_placeholders(ids)})
        """,
        ids,
    )
    results: dict = {}
    for row in found:
        results.setdefault(row["sales_order_id"], []).append(row)
    # Collapse the common one-parcel case, keep the list when there are several.
    collapsed = {k: (v[0] if len(v) == 1 else v) for k, v in results.items()}
    return _batch(collapsed, ids, meta)


def find_late_shipments(
    since: str | None = None,
    state: str | None = None,
    min_slip_days: int = 1,
    limit: int = 50,
) -> list[dict]:
    """Customer parcels DELIVERED LATE, by region and period -- delivery problems.

    Late = delivered past promised_at; in-transit parcels are EXCLUDED, not
    counted late. NOT taste complaints (`find_tickets` category 'quality')
    and NOT late inbound containers (`get_supplier_performance`).

    Args:
        since: Earliest shipped_at, 'YYYY-MM-DD'.
        state: Ship-to state/province, e.g. 'NY'.
        min_slip_days: Minimum days past the promise.
        limit: Max rows; default AND hard cap 50. A larger value is
            clamped back to 50, so asking for more returns the same rows.

    Returns:
        {row_count, rows, truncated, limit_applied, window, note}. `rows` are
        late parcels (worst slip first): sales_order_id, customer_id,
        customer_name, carrier, shipped_at, promised_at, delivered_at,
        slip_days, exception_code, ship_city/state/country.
    """
    clauses = [
        "s.delivered_at IS NOT NULL",
        "date(s.delivered_at) > date(s.promised_at)",
        "julianday(s.delivered_at) - julianday(s.promised_at) >= ?",
    ]
    params: list = [min_slip_days]
    if since:
        clauses.append("date(s.shipped_at) >= date(?)")
        params.append(since)
    if state:
        clauses.append("o.ship_state = ?")
        params.append(state)

    limit = _capped(limit, "find_late_shipments")
    found = rows(
        f"""
        SELECT s.sales_order_id, o.customer_id,
               c.first_name || ' ' || c.last_name AS customer_name,
               s.carrier, s.shipped_at, s.promised_at, s.delivered_at,
               CAST(julianday(s.delivered_at) - julianday(s.promised_at) AS INTEGER) AS slip_days,
               s.status, s.exception_code,
               o.ship_city, o.ship_state, o.ship_country
        FROM shipments s
        JOIN sales_orders o ON o.sales_order_id = s.sales_order_id
        LEFT JOIN customers c ON c.customer_id = o.customer_id
        WHERE {' AND '.join(clauses)}
        ORDER BY slip_days DESC
        LIMIT ?
        """,
        params + [limit],
    )
    return _envelope(
        found,
        limit=limit,
        window={"shipped_at_since": since or "all time", "until": TODAY,
                "state": state or "all states", "min_slip_days": min_slip_days,
                "order": "worst slip first"},
        note=("Delivered-late parcels only. In-transit parcels are EXCLUDED, not "
              "counted late, so this is not a count of everything running behind."),
    )


# ----------------------------------------------------------------- tickets


def find_tickets(
    customer_id: str | None = None,
    category: str | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Customer complaints and support tickets. What customers reported.

    'quality' = tasted wrong, 'delivery' = late/damaged: different root
    causes, do not merge. NOT actual delivery performance
    (`find_late_shipments`) and NOT a supplier issue log.

    Args:
        customer_id: Restrict to one customer.
        category: delivery|quality|billing|subscription|other.
        status: open|pending|resolved|escalated.
        since: Earliest opened_at, 'YYYY-MM-DD'.
        limit: Max rows; default AND hard cap 50. A larger value is
            clamped back to 50, so asking for more returns the same rows.

    Returns:
        {row_count, rows, truncated, limit_applied, window, note}. `rows` are
        tickets (newest first): ticket_id, customer_id, customer_name,
        sales_order_id, opened_at, channel, category, subject, status,
        sentiment, resolved_at.
    """
    clauses, params = [], []
    if customer_id:
        clauses.append("t.customer_id = ?")
        params.append(customer_id)
    if category:
        clauses.append("t.category = ?")
        params.append(category)
    if status:
        clauses.append("t.status = ?")
        params.append(status)
    if since:
        clauses.append("date(t.opened_at) >= date(?)")
        params.append(since)

    limit = _capped(limit, "find_tickets")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    found = rows(
        f"""
        SELECT t.ticket_id, t.customer_id,
               c.first_name || ' ' || c.last_name AS customer_name,
               t.sales_order_id, t.opened_at, t.channel, t.category,
               t.subject, t.status, t.sentiment, t.resolved_at
        FROM tickets t
        LEFT JOIN customers c ON c.customer_id = t.customer_id
        {where}
        ORDER BY datetime(t.opened_at) DESC
        LIMIT ?
        """,
        params + [limit],
    )
    return _envelope(
        found,
        limit=limit,
        window={"customer_id": customer_id, "category": category or "all categories",
                "status": status or "all statuses", "since": since or "all time",
                "until": TODAY, "order": "newest first"},
        note=("A ticket is what the customer REPORTED, in the category the agent "
              "typed. It is evidence of a perception, not proof of a cause."),
    )


def get_ticket_thread(ticket_id: list[str]) -> dict:
    """Read what customers actually said -- the full message thread of one or MANY tickets.

    Use when wording matters: the category field is only as good as the
    agent who set it. NOT aggregate volume (`ticket_trend`).

    Pass EVERY ticket id in one call -- this is two queries however many you
    give it. Do not call it once per ticket.

    Args:
        ticket_id: One or more ticket ids. A bare string is accepted; at most
            25 ids are answered per call.

    Returns:
        {requested, returned, results, not_found} where `results` maps each
        ticket_id to {ticket, messages}, messages in time order.
    """
    ids, meta = _ids(ticket_id, "ticket_id")
    if not ids:
        return {"error": "Give at least one ticket_id."}

    ph = _placeholders(ids)
    tickets = rows(
        f"""
        SELECT t.*, c.first_name || ' ' || c.last_name AS customer_name,
               c.email AS customer_email, c.channel AS customer_channel
        FROM tickets t
        LEFT JOIN customers c ON c.customer_id = t.customer_id
        WHERE t.ticket_id IN ({ph})
        """,
        ids,
    )
    if not tickets:
        return _batch({}, ids, meta)

    message_rows = rows(
        f"""
        SELECT ticket_id, message_id, author, sent_at, body
        FROM ticket_messages WHERE ticket_id IN ({ph})
        ORDER BY datetime(sent_at)
        """,
        ids,
    )
    by_ticket: dict[str, list[dict]] = {}
    for row in message_rows:
        row = dict(row)
        by_ticket.setdefault(row.pop("ticket_id"), []).append(row)

    results = {
        t["ticket_id"]: {"ticket": t, "messages": by_ticket.get(t["ticket_id"], [])}
        for t in tickets
    }
    return _batch(results, ids, meta)


def ticket_trend(category: str | None = None, months: int = 6) -> list[dict]:
    """Monthly complaint volume -- when did a problem start?

    Counts by month opened. NOT root cause: a spike says when, not why --
    follow with `get_ticket_thread` or `trace_product_to_lot`.

    Args:
        category: delivery|quality|billing|subscription|other. Omit for all,
            broken out.
        months: Months back from today (2026-03-16). Default 6.

    Returns:
        {row_count, rows, window} where each row is {month, category,
        ticket_count, negative_count, escalated_count}, oldest first, and
        `window` states the months actually covered -- anything opened before
        that is NOT in these counts.
    """
    clauses = [f"date(t.opened_at) >= date('2026-03-16', '-{int(months)} months')"]
    params: list = []
    if category:
        clauses.append("t.category = ?")
        params.append(category)

    found = rows(
        f"""
        SELECT strftime('%Y-%m', t.opened_at) AS month,
               t.category,
               COUNT(*) AS ticket_count,
               SUM(CASE WHEN t.sentiment = 'negative' THEN 1 ELSE 0 END) AS negative_count,
               SUM(CASE WHEN t.status = 'escalated' THEN 1 ELSE 0 END) AS escalated_count
        FROM tickets t
        WHERE {' AND '.join(clauses)}
        GROUP BY month, t.category
        ORDER BY month, t.category
        """,
        params,
    )
    return _envelope(
        found,
        window={"months_back": months, "from": f"{months} months before {TODAY}",
                "to": TODAY, "category": category or "all, broken out"},
        note=("A spike says WHEN, not why. Counts exclude anything opened before "
              "the window above -- raise `months` to see earlier."),
    )


# --------------------------------------------------------------- suppliers


def find_suppliers(name: str | None = None, country: str | None = None) -> list[dict]:
    """Farms and exporters Meridian buys green coffee from, with their contacts.

    SUPPLY side. NOT customers (`find_customers`,
    `find_wholesale_contacts`).

    Args:
        name: Partial supplier name.
        country: Origin country, e.g. 'Colombia'.

    Returns:
        {row_count, rows, window, note}. `rows` are suppliers: supplier_id, supplier_name, country, origin_region, port,
        currency, lead_time_days_target (AGREED target, not actual --
        see `get_supplier_performance`), relationship_since, contacts.
    """
    clauses, params = [], []
    if name:
        clauses.append("supplier_name LIKE ?")
        params.append(like(name))
    if country:
        clauses.append("country LIKE ?")
        params.append(like(country))

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    suppliers = rows(
        f"""
        SELECT supplier_id, supplier_name, country, origin_region, port,
               currency, lead_time_days_target, relationship_since
        FROM suppliers
        {where}
        ORDER BY supplier_name
        """,
        params,
    )
    # One query for every supplier's contacts, not one per supplier.
    supplier_ids = [s["supplier_id"] for s in suppliers]
    by_supplier: dict[str, list[dict]] = {}
    if supplier_ids:
        for row in rows(
            f"""
            SELECT supplier_id, contact_id, contact_name, email, role
            FROM supplier_contacts
            WHERE supplier_id IN ({_placeholders(supplier_ids)})
            """,
            supplier_ids,
        ):
            row = dict(row)
            by_supplier.setdefault(row.pop("supplier_id"), []).append(row)
    for supplier in suppliers:
        supplier["contacts"] = by_supplier.get(supplier["supplier_id"], [])

    return _envelope(
        suppliers,
        window={"name": name, "country": country or "all countries"},
        note=("lead_time_days_target is the AGREED target, not what actually "
              "happened -- use get_supplier_performance for actuals."),
    )


def find_purchase_orders(
    supplier_id: str | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Green-coffee orders Meridian placed WITH SUPPLIERS (inbound). NOT
    orders sold to customers (`find_sales_orders`).

    Args:
        supplier_id: Restrict to one supplier.
        status: open|in_transit|received|cancelled.
        since: Earliest po_date, 'YYYY-MM-DD'.
        limit: Max rows; default AND hard cap 50. A larger value is
            clamped back to 50, so asking for more returns the same rows.

    Returns:
        {row_count, rows, truncated, limit_applied, window, note}. `rows` are
        POs (newest first): purchase_order_id, supplier_id, supplier_name,
        country, po_date, incoterm, currency, total_amount, status,
        expected_arrival, actual_arrival, days_late (vs expected),
        actual_lead_time_days (arrival - po_date).
    """
    clauses, params = [], []
    if supplier_id:
        clauses.append("po.supplier_id = ?")
        params.append(supplier_id)
    if status:
        clauses.append("po.status = ?")
        params.append(status)
    if since:
        clauses.append("date(po.po_date) >= date(?)")
        params.append(since)

    limit = _capped(limit, "find_purchase_orders")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    found = rows(
        f"""
        SELECT po.purchase_order_id, po.supplier_id, s.supplier_name,
               s.country, po.po_date, po.incoterm, po.currency,
               po.total_amount, po.fx_rate_at_po, po.status,
               po.expected_arrival, po.actual_arrival,
               CASE WHEN po.actual_arrival IS NULL OR po.expected_arrival IS NULL THEN NULL
                    ELSE CAST(julianday(po.actual_arrival) - julianday(po.expected_arrival) AS INTEGER)
               END AS days_late,
               CASE WHEN po.actual_arrival IS NULL THEN NULL
                    ELSE CAST(julianday(po.actual_arrival) - julianday(po.po_date) AS INTEGER)
               END AS actual_lead_time_days
        FROM purchase_orders po
        JOIN suppliers s ON s.supplier_id = po.supplier_id
        {where}
        ORDER BY date(po.po_date) DESC
        LIMIT ?
        """,
        params + [limit],
    )
    return _envelope(
        found,
        limit=limit,
        window={"supplier_id": supplier_id, "status": status or "all statuses",
                "since": since or "all time", "until": TODAY,
                "order": "newest first"},
        note=("days_late is measured against the PO's expected_arrival. That is a "
              "different denominator from get_supplier_performance (agreed target) "
              "and from get_inbound_shipments (container ETA) -- do not mix them."),
    )


def get_inbound_shipments(
    purchase_order_id: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """Sea containers bringing green coffee from origin to Portland.

    INBOUND only. NOT parcels sent to customers (`get_shipment_status`,
    `find_late_shipments`).

    Args:
        purchase_order_id: Containers for one PO.
        status: booked|sailing|delayed|arrived|cleared.

    Returns:
        {row_count, rows, window, note}. `rows` carry inbound_id,
        purchase_order_id, supplier_name, container_ref,
        origin_port, dest_port, etd, eta, actual_arrival, status,
        delay_reason, days_late_vs_eta.
    """
    clauses, params = [], []
    if purchase_order_id:
        clauses.append("i.purchase_order_id = ?")
        params.append(purchase_order_id)
    if status:
        clauses.append("i.status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    found = rows(
        f"""
        SELECT i.inbound_id, i.purchase_order_id, s.supplier_name,
               i.container_ref, i.origin_port, i.dest_port,
               i.etd, i.eta, i.actual_arrival, i.status, i.delay_reason,
               CASE WHEN i.actual_arrival IS NULL OR i.eta IS NULL THEN NULL
                    ELSE CAST(julianday(i.actual_arrival) - julianday(i.eta) AS INTEGER)
               END AS days_late_vs_eta
        FROM inbound_shipments i
        JOIN purchase_orders po ON po.purchase_order_id = i.purchase_order_id
        JOIN suppliers s ON s.supplier_id = po.supplier_id
        {where}
        ORDER BY date(i.etd) DESC
        """,
        params,
    )
    return _envelope(
        found,
        window={"purchase_order_id": purchase_order_id, "status": status or "all statuses"},
        note="days_late_vs_eta is measured against the container ETA -- a different denominator from find_purchase_orders (expected_arrival) and get_supplier_performance (agreed target).",
    )


def get_supplier_performance(
    supplier_id: str | None = None,
    since: str | None = None,
) -> list[dict]:
    """Are suppliers delivering on time? Actual lead time vs agreed target.

    Actual lead time = actual_arrival - po_date, averaged over arrived POs;
    POs not yet arrived are excluded from averages, counted in
    open_po_count. This is the SUPPLIER promise (origin to Portland), NOT
    the delivery date promised to a customer (`find_late_shipments`).

    Args:
        supplier_id: Restrict to one supplier. Omit for all.
        since: Earliest po_date to count, 'YYYY-MM-DD'.

    Returns:
        {row_count, rows, window, note}. `rows` are per supplier: supplier_id, supplier_name, country,
        lead_time_days_target, received_po_count, open_po_count,
        avg_actual_lead_time_days, worst_actual_lead_time_days,
        avg_days_over_target (positive = slower than agreed).
    """
    clauses, params = [], []
    if supplier_id:
        clauses.append("s.supplier_id = ?")
        params.append(supplier_id)
    if since:
        clauses.append("(po.po_date IS NULL OR date(po.po_date) >= date(?))")
        params.append(since)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    found = rows(
        f"""
        SELECT s.supplier_id, s.supplier_name, s.country,
               s.lead_time_days_target,
               SUM(CASE WHEN po.actual_arrival IS NOT NULL THEN 1 ELSE 0 END) AS received_po_count,
               SUM(CASE WHEN po.purchase_order_id IS NOT NULL
                         AND po.actual_arrival IS NULL THEN 1 ELSE 0 END) AS open_po_count,
               ROUND(AVG(CASE WHEN po.actual_arrival IS NOT NULL
                              THEN julianday(po.actual_arrival) - julianday(po.po_date)
                         END), 1) AS avg_actual_lead_time_days,
               MAX(CASE WHEN po.actual_arrival IS NOT NULL
                        THEN CAST(julianday(po.actual_arrival) - julianday(po.po_date) AS INTEGER)
                   END) AS worst_actual_lead_time_days,
               ROUND(AVG(CASE WHEN po.actual_arrival IS NOT NULL
                              THEN julianday(po.actual_arrival) - julianday(po.po_date)
                                   - s.lead_time_days_target
                         END), 1) AS avg_days_over_target
        FROM suppliers s
        LEFT JOIN purchase_orders po ON po.supplier_id = s.supplier_id
        {where}
        GROUP BY s.supplier_id, s.supplier_name, s.country, s.lead_time_days_target
        ORDER BY avg_days_over_target DESC
        """,
        params,
    )
    return _envelope(
        found,
        window={"supplier_id": supplier_id, "since": since or "all time", "until": TODAY},
        note="Actual lead time vs AGREED target. Open POs are excluded from the averages.",
    )


# --------------------------------------------------- traceability / product


def trace_product_to_lot(
    sales_order_id: str | None = None,
    product_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> list[dict]:
    """Trace what a customer received back to its green coffee and supplier.

    The ONLY path from the customer world to the supply world:
    order line -> roast batch -> green lot -> purchase order -> supplier.
    Use it for why coffee tasted different, which origin a customer got, or
    whether a supply problem reached customers. Pass sales_order_id for one
    order, or product_id (+ since/until on roast_date) for a period.

    Args:
        sales_order_id: Trace one customer order.
        product_id: Trace one product.
        since: Earliest roast_date, 'YYYY-MM-DD'.
        until: Latest roast_date, 'YYYY-MM-DD'.

    Returns:
        {row_count, rows, window, note}. `rows` are per order line:
        sales_order_id, order_date, customer_id,
        customer_name, product_id, sku, product_name, qty, batch_id,
        roast_date, qa_pass, qa_note, lot_id, origin, varietal, grade,
        cupping_score, lot_received_at, purchase_order_id, po_date,
        expected_arrival, actual_arrival, po_days_late, supplier_id,
        supplier_name, supplier_country.
    """
    if not sales_order_id and not product_id:
        return {"error": "Give either sales_order_id or product_id (with an optional date range)."}

    clauses, params = [], []
    if sales_order_id:
        clauses.append("l.sales_order_id = ?")
        params.append(sales_order_id)
    if product_id:
        clauses.append("l.product_id = ?")
        params.append(product_id)
    if since:
        clauses.append("date(b.roast_date) >= date(?)")
        params.append(since)
    if until:
        clauses.append("date(b.roast_date) <= date(?)")
        params.append(until)

    found = rows(
        f"""
        SELECT l.sales_order_id, o.order_date, o.customer_id,
               c.first_name || ' ' || c.last_name AS customer_name,
               l.product_id, p.sku, p.name AS product_name, l.qty,
               b.batch_id, b.roast_date, b.qa_pass, b.qa_note,
               g.lot_id, g.origin, g.varietal, g.grade, g.cupping_score,
               g.received_at AS lot_received_at,
               po.purchase_order_id, po.po_date, po.expected_arrival,
               po.actual_arrival,
               CASE WHEN po.actual_arrival IS NULL OR po.expected_arrival IS NULL THEN NULL
                    ELSE CAST(julianday(po.actual_arrival) - julianday(po.expected_arrival) AS INTEGER)
               END AS po_days_late,
               s.supplier_id, s.supplier_name, s.country AS supplier_country
        FROM sales_order_lines l
        JOIN sales_orders o ON o.sales_order_id = l.sales_order_id
        LEFT JOIN customers c ON c.customer_id = o.customer_id
        LEFT JOIN products p ON p.product_id = l.product_id
        LEFT JOIN roast_batches b ON b.batch_id = l.batch_id
        LEFT JOIN green_lots g ON g.lot_id = b.lot_id
        LEFT JOIN purchase_orders po ON po.purchase_order_id = g.purchase_order_id
        LEFT JOIN suppliers s ON s.supplier_id = po.supplier_id
        WHERE {' AND '.join(clauses)}
        ORDER BY date(o.order_date), l.sales_order_id
        """,
        params,
    )
    return _envelope(
        found,
        window={"sales_order_id": sales_order_id, "product_id": product_id, "since": since or "all time", "until": until or TODAY},
        note="get_sales_order_detail already returns batch_id/lot_id/qa_pass per line -- if you called it for this order you do not need this too.",
    )


def find_roast_batches(
    product_id: str | None = None,
    flagged_only: bool = False,
    since: str | None = None,
) -> list[dict]:
    """Roast runs for a product, with the green lot each used and its QA note.

    A "batch" is a roast run; a "lot" is the green coffee it consumed.
    `flagged_only` surfaces QA failures and notes -- where substitutions
    show up. Does NOT say who received a batch (`trace_product_to_lot`).

    Args:
        product_id: Restrict to one product.
        flagged_only: Only batches that failed QA or carry a note.
        since: Earliest roast_date, 'YYYY-MM-DD'.

    Returns:
        {row_count, rows, window, note}. `rows` are batches (newest first): batch_id, product_id, sku, product_name,
        roast_date, kg_input, units_output, qa_pass, qa_note, lot_id,
        origin, varietal, cupping_score, supplier_name.
    """
    clauses, params = [], []
    if product_id:
        clauses.append("b.product_id = ?")
        params.append(product_id)
    if flagged_only:
        clauses.append("(b.qa_pass = 0 OR (b.qa_note IS NOT NULL AND b.qa_note != ''))")
    if since:
        clauses.append("date(b.roast_date) >= date(?)")
        params.append(since)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    found = rows(
        f"""
        SELECT b.batch_id, b.product_id, p.sku, p.name AS product_name,
               b.roast_date, b.kg_input, b.units_output, b.qa_pass, b.qa_note,
               g.lot_id, g.origin, g.varietal, g.cupping_score,
               s.supplier_name
        FROM roast_batches b
        LEFT JOIN products p ON p.product_id = b.product_id
        LEFT JOIN green_lots g ON g.lot_id = b.lot_id
        LEFT JOIN purchase_orders po ON po.purchase_order_id = g.purchase_order_id
        LEFT JOIN suppliers s ON s.supplier_id = po.supplier_id
        {where}
        ORDER BY date(b.roast_date) DESC
        """,
        params,
    )
    return _envelope(
        found,
        window={"product_id": product_id, "flagged_only": flagged_only, "since": since or "all time"},
        note="flagged_only=False (the default) returns every batch, passed or failed.",
    )


def get_inventory_position(
    product_id: str | None = None,
    as_of: str | None = None,
) -> list[dict]:
    """How much finished coffee was on hand, and when did we run short?

    Latest snapshot on or before `as_of` per product. FINISHED product in
    units -- NOT green coffee in the silo (kg, via `find_roast_batches`).

    Args:
        product_id: Restrict to one product. Omit for all.
        as_of: 'YYYY-MM-DD'. Defaults to today (2026-03-16). One snapshot
            date, not a range -- see the note in the result.

    Returns:
        {row_count, rows, window, note}. `rows` carry product_id, sku,
        product_name, as_of_date, units_on_hand,
        units_allocated, units_available.
    """
    as_of = as_of or "2026-03-16"
    clauses = ["date(i.as_of_date) <= date(?)"]
    params: list = [as_of]
    if product_id:
        clauses.append("i.product_id = ?")
        params.append(product_id)

    found = rows(
        f"""
        SELECT i.product_id, p.sku, p.name AS product_name, i.as_of_date,
               i.units_on_hand, i.units_allocated,
               (i.units_on_hand - i.units_allocated) AS units_available
        FROM inventory_snapshots i
        LEFT JOIN products p ON p.product_id = i.product_id
        WHERE {' AND '.join(clauses)}
          AND date(i.as_of_date) = (
              SELECT MAX(date(i2.as_of_date))
              FROM inventory_snapshots i2
              WHERE i2.product_id = i.product_id
                AND date(i2.as_of_date) <= date(?)
          )
        ORDER BY p.sku
        """,
        params + [as_of],
    )
    return _envelope(
        found,
        window={"product_id": product_id, "as_of": as_of},
        note="A point-in-time snapshot as at the date above, not a history. To find WHEN stock ran short, query several as_of dates or use SQL over inventory_snapshots.",
    )
