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

from .db import like, one, rows

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
        limit: Max rows.

    Returns:
        Customers: customer_id, customer_name, email, city, state, country,
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

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return rows(
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


def get_customer_360(customer_id: str) -> dict:
    """Full picture of one customer: profile, last 10 orders, last 10 tickets, subscriptions.

    Start here for "what is going on with this customer". NOT line-level or
    shipment detail on one order (`get_sales_order_detail`).

    Args:
        customer_id: From `find_customers`.

    Returns:
        {customer, account, recent_orders, recent_tickets, subscriptions,
        totals}, or {error}.
    """
    customer = one(
        """
        SELECT customer_id,
               first_name || ' ' || last_name AS customer_name,
               email, city, state, country, postcode, channel,
               loyalty_tier, signup_date, account_id
        FROM customers WHERE customer_id = ?
        """,
        (customer_id,),
    )
    if customer is None:
        return {"error": f"No customer with customer_id '{customer_id}'."}

    account = None
    if customer["account_id"]:
        account = one(
            "SELECT * FROM wholesale_accounts WHERE account_id = ?",
            (customer["account_id"],),
        )

    recent_orders = rows(
        """
        SELECT sales_order_id, order_date, status, channel, currency,
               total_amount, ship_city, ship_state, ship_country
        FROM sales_orders
        WHERE customer_id = ?
        ORDER BY order_date DESC
        LIMIT 10
        """,
        (customer_id,),
    )
    recent_tickets = rows(
        """
        SELECT ticket_id, sales_order_id, opened_at, category, status,
               subject, sentiment, resolved_at
        FROM tickets
        WHERE customer_id = ?
        ORDER BY opened_at DESC
        LIMIT 10
        """,
        (customer_id,),
    )
    subscriptions = rows(
        """
        SELECT s.subscription_id, s.product_id, p.name AS product_name,
               s.plan, s.frequency_days, s.status, s.started_at,
               s.paused_at, s.cancelled_at, s.cancel_reason
        FROM subscriptions s
        LEFT JOIN products p ON p.product_id = s.product_id
        WHERE s.customer_id = ?
        ORDER BY s.started_at DESC
        """,
        (customer_id,),
    )
    totals = one(
        """
        SELECT (SELECT COUNT(*) FROM sales_orders WHERE customer_id = ?) AS order_count,
               (SELECT COUNT(*) FROM tickets WHERE customer_id = ?) AS ticket_count
        """,
        (customer_id, customer_id),
    )

    return {
        "customer": customer,
        "account": account,
        "recent_orders": recent_orders,
        "recent_tickets": recent_tickets,
        "subscriptions": subscriptions,
        "totals": totals,
    }


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
        Contacts: contact_id, contact_name, email, role, plus account_id,
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
    return rows(
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
        limit: Max rows.

    Returns:
        Orders (newest first): sales_order_id, customer_id, customer_name,
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

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return rows(
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


def get_sales_order_detail(sales_order_id: str) -> dict:
    """Everything about one customer order: header, lines, batches, shipment, refunds.

    NOT supplier purchase orders (`find_purchase_orders`).

    Args:
        sales_order_id: The order id.

    Returns:
        {order, lines, shipment, refunds, tickets}, or {error}.
    """
    order = one(
        """
        SELECT o.*, c.first_name || ' ' || c.last_name AS customer_name,
               c.email AS customer_email
        FROM sales_orders o
        LEFT JOIN customers c ON c.customer_id = o.customer_id
        WHERE o.sales_order_id = ?
        """,
        (sales_order_id,),
    )
    if order is None:
        return {"error": f"No sales order with sales_order_id '{sales_order_id}'."}

    lines = rows(
        """
        SELECT l.line_id, l.product_id, p.sku, p.name AS product_name,
               p.category, l.batch_id, b.roast_date, b.lot_id,
               b.qa_pass, b.qa_note,
               l.qty, l.unit_price, (l.qty * l.unit_price) AS line_amount
        FROM sales_order_lines l
        LEFT JOIN products p ON p.product_id = l.product_id
        LEFT JOIN roast_batches b ON b.batch_id = l.batch_id
        WHERE l.sales_order_id = ?
        """,
        (sales_order_id,),
    )
    shipment = one(
        """
        SELECT shipment_id, carrier, tracking_ref, shipped_at, promised_at,
               delivered_at, status, dest_postcode, exception_code,
               CASE
                   WHEN delivered_at IS NULL THEN NULL
                   WHEN date(delivered_at) <= date(promised_at) THEN 1
                   ELSE 0
               END AS on_time,
               CASE
                   WHEN delivered_at IS NULL THEN NULL
                   ELSE CAST(julianday(delivered_at) - julianday(promised_at) AS INTEGER)
               END AS slip_days
        FROM shipments WHERE sales_order_id = ?
        """,
        (sales_order_id,),
    )
    refunds = rows(
        """
        SELECT refund_id, amount, currency, reason_code, approved_by, created_at
        FROM refunds WHERE sales_order_id = ?
        ORDER BY created_at
        """,
        (sales_order_id,),
    )
    order_tickets = rows(
        """
        SELECT ticket_id, opened_at, category, status, subject, sentiment
        FROM tickets WHERE sales_order_id = ?
        ORDER BY opened_at
        """,
        (sales_order_id,),
    )

    return {
        "order": order,
        "lines": lines,
        "shipment": shipment,
        "refunds": refunds,
        "tickets": order_tickets,
    }


# --------------------------------------------------------------- shipments


def get_shipment_status(sales_order_id: str) -> dict:
    """Where is this customer order and did it arrive on time?

    OUTBOUND parcel to a customer. NOT the inbound green-coffee container
    (`get_inbound_shipments`). In-transit parcels return on_time = None:
    they are not counted late.

    Args:
        sales_order_id: The customer order.

    Returns:
        carrier, tracking_ref, shipped_at, promised_at, delivered_at,
        status, exception_code, on_time (1/0/None), slip_days (negative =
        early), or {error}.
    """
    shipment = one(
        """
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
        WHERE s.sales_order_id = ?
        """,
        (sales_order_id,),
    )
    if shipment is None:
        return {"error": f"No shipment found for sales order '{sales_order_id}'."}
    return shipment


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
        limit: Max rows.

    Returns:
        Late parcels (worst slip first): sales_order_id, customer_id,
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

    return rows(
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
        limit: Max rows.

    Returns:
        Tickets (newest first): ticket_id, customer_id, customer_name,
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

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return rows(
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


def get_ticket_thread(ticket_id: str) -> dict:
    """Read what the customer actually said -- the full message thread of one ticket.

    Use when wording matters: the category field is only as good as the
    agent who set it. NOT aggregate volume (`ticket_trend`).

    Args:
        ticket_id: The ticket id.

    Returns:
        {ticket, messages} in time order, or {error}.
    """
    ticket = one(
        """
        SELECT t.*, c.first_name || ' ' || c.last_name AS customer_name,
               c.email AS customer_email, c.channel AS customer_channel
        FROM tickets t
        LEFT JOIN customers c ON c.customer_id = t.customer_id
        WHERE t.ticket_id = ?
        """,
        (ticket_id,),
    )
    if ticket is None:
        return {"error": f"No ticket with ticket_id '{ticket_id}'."}

    messages = rows(
        """
        SELECT message_id, author, sent_at, body
        FROM ticket_messages WHERE ticket_id = ?
        ORDER BY datetime(sent_at)
        """,
        (ticket_id,),
    )
    return {"ticket": ticket, "messages": messages}


def ticket_trend(category: str | None = None, months: int = 6) -> list[dict]:
    """Monthly complaint volume -- when did a problem start?

    Counts by month opened. NOT root cause: a spike says when, not why --
    follow with `get_ticket_thread` or `trace_product_to_lot`.

    Args:
        category: delivery|quality|billing|subscription|other. Omit for all,
            broken out.
        months: Months back from today (2026-03-16).

    Returns:
        {month, category, ticket_count, negative_count, escalated_count},
        oldest first.
    """
    clauses = [f"date(t.opened_at) >= date('2026-03-16', '-{int(months)} months')"]
    params: list = []
    if category:
        clauses.append("t.category = ?")
        params.append(category)

    return rows(
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


# --------------------------------------------------------------- suppliers


def find_suppliers(name: str | None = None, country: str | None = None) -> list[dict]:
    """Farms and exporters Meridian buys green coffee from, with their contacts.

    SUPPLY side. NOT customers (`find_customers`,
    `find_wholesale_contacts`).

    Args:
        name: Partial supplier name.
        country: Origin country, e.g. 'Colombia'.

    Returns:
        Suppliers: supplier_id, supplier_name, country, origin_region, port,
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
    for supplier in suppliers:
        supplier["contacts"] = rows(
            """
            SELECT contact_id, contact_name, email, role
            FROM supplier_contacts WHERE supplier_id = ?
            """,
            (supplier["supplier_id"],),
        )
    return suppliers


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
        limit: Max rows.

    Returns:
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

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return rows(
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
        inbound_id, purchase_order_id, supplier_name, container_ref,
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
    return rows(
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
        Per supplier: supplier_id, supplier_name, country,
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
    return rows(
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
        Per order line: sales_order_id, order_date, customer_id,
        customer_name, product_id, sku, product_name, qty, batch_id,
        roast_date, qa_pass, qa_note, lot_id, origin, varietal, grade,
        cupping_score, lot_received_at, purchase_order_id, po_date,
        expected_arrival, actual_arrival, po_days_late, supplier_id,
        supplier_name, supplier_country.
    """
    if not sales_order_id and not product_id:
        return [{"error": "Give either sales_order_id or product_id (with an optional date range)."}]

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

    return rows(
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
        Batches (newest first): batch_id, product_id, sku, product_name,
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
    return rows(
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


def get_inventory_position(
    product_id: str | None = None,
    as_of: str | None = None,
) -> list[dict]:
    """How much finished coffee was on hand, and when did we run short?

    Latest snapshot on or before `as_of` per product. FINISHED product in
    units -- NOT green coffee in the silo (kg, via `find_roast_batches`).

    Args:
        product_id: Restrict to one product. Omit for all.
        as_of: 'YYYY-MM-DD'. Defaults to today (2026-03-16).

    Returns:
        product_id, sku, product_name, as_of_date, units_on_hand,
        units_allocated, units_available.
    """
    as_of = as_of or "2026-03-16"
    clauses = ["date(i.as_of_date) <= date(?)"]
    params: list = [as_of]
    if product_id:
        clauses.append("i.product_id = ?")
        params.append(product_id)

    return rows(
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
