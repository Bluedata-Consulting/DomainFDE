"""
Build data/roastery.db for the Meridian Roasters domain-FDE case.

Deterministic: fixed seed, fixed "today". Re-running produces an identical file.

    python data/generate.py

PLANTED STORY (coach-only -- do not hand this to participants)
--------------------------------------------------------------
PO-2043 (Finca La Esperanza, Colombia) sails 2026-01-06, ETA 2026-01-28,
actually arrives 2026-02-16 -- 19 days late, port congestion at Cartagena.

Cascadia Blend (SKU MR-BLD-001) is normally roasted from Colombian lots.
With no Colombian green in the silo, roast batches from 2026-02-02 to
2026-02-20 substitute LOT-BR-0118 (Brazil, cupping 79.5 vs the usual 86+).
QA passed them but flagged a note.

Those batches ship to D2C subscribers and two wholesale accounts.
From ~2026-02-20 a spike of `quality` tickets appears, concentrated on
customers whose order lines point at the substituted batches.

Separately and coincidentally: a cold snap + carrier holiday cutoff in the
US Northeast (2026-02-14 to 2026-02-19) causes late outbound deliveries in
NY / MA / CT. This is a DIFFERENT root cause and is there to punish agents
that assume a single explanation.

Rosewood Coffee House (Toronto, CAD, flagship tier) takes both hits and is
the churn-risk account.

AMBIGUITY PLANTS
    Jane Okafor    -- D2C customer, Denver CO
    Jane Mensah    -- wholesale contact, Rosewood Coffee House, Toronto
    "order"        -- sales_orders vs purchase_orders
    "shipment"     -- shipments vs inbound_shipments
    "lead time"    -- suppliers.lead_time_days_target vs actual vs promised_at
"""

import os
import random
import sqlite3
import uuid
from datetime import date, datetime, timedelta

SEED = 20260316
TODAY = date(2026, 3, 16)
HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "roastery.db")
SCHEMA = os.path.join(HERE, "schema.sql")

rnd = random.Random(SEED)


def d(x: date) -> str:
    return x.isoformat()


def ts(x: date, hour=10, minute=0) -> str:
    return datetime(x.year, x.month, x.day, hour, minute).isoformat(sep=" ")


def uid(prefix: str, n: int, width: int = 4) -> str:
    return f"{prefix}-{n:0{width}d}"


# --------------------------------------------------------------- reference data

US_CITIES = [
    ("Portland", "OR", "US", "97209"), ("Seattle", "WA", "US", "98101"),
    ("Denver", "CO", "US", "80202"), ("Austin", "TX", "US", "78701"),
    ("Chicago", "IL", "US", "60601"), ("Brooklyn", "NY", "US", "11201"),
    ("Boston", "MA", "US", "02108"), ("Hartford", "CT", "US", "06103"),
    ("San Diego", "CA", "US", "92101"), ("Minneapolis", "MN", "US", "55401"),
    ("Atlanta", "GA", "US", "30303"), ("Phoenix", "AZ", "US", "85004"),
]
NORTHEAST = {"NY", "MA", "CT"}

CA_CITIES = [("Toronto", "ON", "CA", "M5V"), ("Vancouver", "BC", "CA", "V6B")]
UK_CITIES = [("London", None, "GB", "EC1A"), ("Bristol", None, "GB", "BS1")]

FIRST = ["Ana", "Marcus", "Priya", "Tomás", "Lena", "Jonah", "Mei", "Fiona",
         "Diego", "Nadia", "Owen", "Greta", "Kwame", "Sara", "Ivan", "Rosa",
         "Theo", "Yuki", "Amara", "Felix", "Noor", "Hugo", "Clara", "Dev"]
LAST = ["Okafor", "Reyes", "Hartley", "Nakamura", "Bianchi", "Fenwick", "Osei",
        "Lindqvist", "Maroney", "Delacroix", "Whitcombe", "Adeyemi", "Prasad",
        "Sørensen", "Vance", "Tomlin", "Ibrahim", "Calloway", "Мenon", "Duarte"]

PRODUCTS = [
    ("MR-BLD-001", "Cascadia Blend",        "medium", 340, "blend",         19.50),
    ("MR-BLD-002", "Nightwatch Blend",      "dark",   340, "blend",         18.00),
    ("MR-BLD-003", "Harbour Espresso",      "medium", 1000, "blend",        42.00),
    ("MR-SO-011",  "Yirgacheffe Kochere",   "light",  250, "single_origin", 24.00),
    ("MR-SO-012",  "Huila Reserva",         "light",  250, "single_origin", 23.00),
    ("MR-SO-013",  "Sumatra Lintong",       "dark",   250, "single_origin", 21.50),
    ("MR-SO-014",  "Cerrado Amarelo",       "medium", 250, "single_origin", 19.00),
    ("MR-DEC-001", "Quietwater Decaf",      "medium", 250, "decaf",         20.00),
]

SUPPLIERS = [
    ("SUP-01", "Finca La Esperanza",   "Colombia",  "Huila",       "Cartagena",  "USD", 42),
    ("SUP-02", "Kochere Cooperative",  "Ethiopia",  "Yirgacheffe", "Djibouti",   "USD", 55),
    ("SUP-03", "Fazenda Serra Verde",  "Brazil",    "Cerrado",     "Santos",     "USD", 38),
    ("SUP-04", "Lintong Highlands",    "Indonesia", "Sumatra",     "Belawan",    "USD", 48),
    ("SUP-05", "Antigua Valley Mill",  "Guatemala", "Antigua",     "Puerto Quetzal", "USD", 40),
]

CARRIERS = ["Cascade Parcel", "NorthStar Freight", "Postal Standard"]


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    con = sqlite3.connect(DB_PATH)
    con.executescript(open(SCHEMA).read())
    cur = con.cursor()

    # ----------------------------------------------------------- products
    products = []
    for i, (sku, name, roast, size, cat, price) in enumerate(PRODUCTS, start=1):
        pid = uid("PRD", i, 3)
        products.append(pid)
        cur.execute(
            "INSERT INTO products VALUES (?,?,?,?,?,?,?,1)",
            (pid, sku, name, roast, size, cat, price),
        )
    CASCADIA = products[0]

    # ----------------------------------------------------------- suppliers
    for sid, name, country, region, port, ccy, lt in SUPPLIERS:
        cur.execute(
            "INSERT INTO suppliers VALUES (?,?,?,?,?,?,?,?)",
            (sid, name, country, region, port, ccy, lt, "2019-04-01"),
        )
    sup_contacts = [
        ("SC-001", "SUP-01", "Camila Restrepo", "camila@laesperanza.co", "Export Manager"),
        ("SC-002", "SUP-02", "Dawit Bekele", "dawit@kocherecoop.et", "Mill Lead"),
        ("SC-003", "SUP-03", "Rafael Moraes", "rafael@serraverde.br", "Commercial"),
        ("SC-004", "SUP-04", "Sari Panjaitan", "sari@lintong.id", "Export Manager"),
        ("SC-005", "SUP-05", "Jorge Alvarado", "jorge@antiguavalley.gt", "Commercial"),
    ]
    cur.executemany("INSERT INTO supplier_contacts VALUES (?,?,?,?,?)", sup_contacts)

    # ----------------------------------------------------------- purchase orders + inbound + lots
    po_rows, inb_rows, lot_rows = [], [], []
    lot_n = 100
    po_n = 2000

    # routine history: Sep 2025 -> Mar 2026
    schedule = []
    for month_offset in range(-7, 1):
        base = date(2026, 3, 1) + timedelta(days=30 * month_offset)
        for sid, *_ in [(s[0],) for s in SUPPLIERS]:
            schedule.append((base + timedelta(days=rnd.randint(0, 20)), sid))

    for po_date, sid in sorted(schedule):
        po_n += 1
        po_id = uid("PO", po_n)
        sup = next(s for s in SUPPLIERS if s[0] == sid)
        target_lt = sup[6]
        eta = po_date + timedelta(days=target_lt)

        # The incident: the Colombian container whose ETA falls on 2026-01-21
        # arrives 26 days late, emptying the Colombian silo for most of February.
        is_the_incident = (sid == "SUP-01" and eta == date(2026, 1, 21))
        if is_the_incident:
            delay = 26
            delay_reason = "Port congestion at Cartagena; vessel roll-over (2 sailings missed)"
        else:
            delay = rnd.choice([0, 0, 0, 1, 2, 3, -1, 5])
            delay_reason = None
        actual = eta + timedelta(days=delay)
        arrived = actual <= TODAY

        status = "received" if arrived else ("in_transit" if po_date <= TODAY else "open")
        kg = rnd.choice([6000, 9000, 12000])
        price_per_kg = round(rnd.uniform(5.2, 9.4), 2)
        po_rows.append((
            po_id, sid, d(po_date), "FOB", "USD", round(kg * price_per_kg, 2),
            round(rnd.uniform(0.92, 1.08), 4), status,
            d(eta), d(actual) if arrived else None,
        ))
        inb_rows.append((
            uid("INB", po_n), po_id, f"MSKU{rnd.randint(1000000, 9999999)}",
            sup[4], "Port of Portland", d(po_date + timedelta(days=6)), d(eta),
            d(actual) if arrived else None,
            "arrived" if arrived else ("delayed" if delay > 7 else "sailing"),
            delay_reason,
        ))
        if arrived:
            lot_n += 1
            origin_code = {"Colombia": "CO", "Ethiopia": "ET", "Brazil": "BR",
                           "Indonesia": "ID", "Guatemala": "GT"}[sup[2]]
            lot_id = f"LOT-{origin_code}-{lot_n:04d}"
            if sup[2] == "Brazil":
                cup = round(rnd.uniform(78.5, 81.0), 1)
            else:
                cup = round(rnd.uniform(84.0, 88.5), 1)
            lot_rows.append((
                lot_id, po_id, sup[2], sup[3], "Grade 1" if cup > 83 else "Grade 2",
                cup, kg, round(kg * rnd.uniform(0.05, 0.6), 1), d(actual),
            ))

    # force the substitute lot to be a known id with a known low score
    for i, r in enumerate(lot_rows):
        if r[2] == "Brazil" and date.fromisoformat(r[8]) <= date(2026, 2, 1):
            lot_rows[i] = ("LOT-BR-0118", r[1], r[2], r[3], "Grade 2", 79.5,
                           r[6], r[7], r[8])
            break

    cur.executemany("INSERT INTO purchase_orders VALUES (?,?,?,?,?,?,?,?,?,?)", po_rows)
    cur.executemany("INSERT INTO inbound_shipments VALUES (?,?,?,?,?,?,?,?,?,?)", inb_rows)
    cur.executemany("INSERT INTO green_lots VALUES (?,?,?,?,?,?,?,?,?)", lot_rows)

    colombian_lots = [r[0] for r in lot_rows if r[2] == "Colombia"]
    other_lots = [r[0] for r in lot_rows if r[2] != "Colombia"]
    sub_lot = "LOT-BR-0118" if any(r[0] == "LOT-BR-0118" for r in lot_rows) else other_lots[0]

    # ----------------------------------------------------------- roast batches
    batch_rows = []
    bn = 5000
    batch_by_product_date = {}
    day = date(2025, 10, 1)
    while day <= TODAY:
        if day.weekday() < 5:
            for pid in products:
                if rnd.random() < 0.45:
                    bn += 1
                    bid = uid("BAT", bn)
                    if pid == CASCADIA:
                        in_gap = date(2026, 2, 2) <= day <= date(2026, 2, 20)
                        lot = sub_lot if in_gap else (
                            rnd.choice(colombian_lots) if colombian_lots else sub_lot)
                        note = ("Substitute origin used -- Colombian lot unavailable "
                                "(PO-2043 delayed). Cup profile flatter than spec."
                                if in_gap else None)
                    else:
                        lot = rnd.choice(other_lots or colombian_lots)
                        note = None
                    kg_in = round(rnd.uniform(40, 120), 1)
                    batch_rows.append((bid, pid, lot, d(day), kg_in,
                                       int(kg_in * 1000 / 340), 1, note))
                    batch_by_product_date.setdefault(pid, []).append((day, bid))
        day += timedelta(days=1)
    cur.executemany("INSERT INTO roast_batches VALUES (?,?,?,?,?,?,?,?)", batch_rows)
    tainted_batches = {b[0] for b in batch_rows if b[7] is not None}

    def pick_batch(pid, order_day):
        opts = [b for (bd, b) in batch_by_product_date.get(pid, [])
                if 0 <= (order_day - bd).days <= 12]
        return opts[-1] if opts else None

    # ----------------------------------------------------------- wholesale accounts
    accounts = [
        ("ACC-001", "Rosewood Coffee House", "Toronto", "CA", "CAD", 30, "flagship", "2021-06-14"),
        ("ACC-002", "Ridgeline Hotel Group", "Denver", "US", "USD", 45, "flagship", "2020-02-03"),
        ("ACC-003", "Marlowe & Sons", "London", "GB", "GBP", 30, "standard", "2023-09-01"),
        ("ACC-004", "Pike Street Cafe", "Seattle", "US", "USD", 14, "standard", "2022-11-20"),
        ("ACC-005", "Foundry Workspace", "Brooklyn", "US", "USD", 30, "standard", "2024-03-11"),
        ("ACC-006", "Quayside Roasthouse", "Bristol", "GB", "GBP", 30, "trial", "2025-12-05"),
    ]
    cur.executemany("INSERT INTO wholesale_accounts VALUES (?,?,?,?,?,?,?,?)", accounts)
    wcontacts = [
        ("WC-001", "ACC-001", "Jane Mensah", "jane@rosewoodcoffee.ca", "Owner"),
        ("WC-002", "ACC-001", "Peter Lund", "peter@rosewoodcoffee.ca", "Head Barista"),
        ("WC-003", "ACC-002", "Alicia Frank", "a.frank@ridgelinehotels.com", "F&B Director"),
        ("WC-004", "ACC-003", "Sam Marlowe", "sam@marloweandsons.co.uk", "Director"),
        ("WC-005", "ACC-004", "Dana Cho", "dana@pikestreet.coffee", "Manager"),
        ("WC-006", "ACC-005", "Ben Ortiz", "ben@foundryworkspace.com", "Ops Lead"),
        ("WC-007", "ACC-006", "Iris Tandy", "iris@quayside.co.uk", "Owner"),
    ]
    cur.executemany("INSERT INTO wholesale_contacts VALUES (?,?,?,?,?)", wcontacts)

    # ----------------------------------------------------------- customers
    customers = []
    # planted D2C Jane
    customers.append(("CUS-0001", "Jane", "Okafor", "jane.okafor@example.com",
                      "Denver", "CO", "US", "80202", "2023-05-11", "d2c", "gold", None))
    # wholesale buying customers, one per account
    for i, (aid, name, city, country, ccy, *_rest) in enumerate(accounts, start=2):
        wc = next(w for w in wcontacts if w[1] == aid)
        fn, ln = wc[2].split(" ", 1)
        state = "ON" if city == "Toronto" else ("CO" if city == "Denver" else
                 ("WA" if city == "Seattle" else ("NY" if city == "Brooklyn" else None)))
        pc = {"Toronto": "M5V", "Denver": "80202", "London": "EC1A",
              "Seattle": "98101", "Brooklyn": "11201", "Bristol": "BS1"}[city]
        customers.append((uid("CUS", i), fn, ln, wc[3], city, state, country, pc,
                          _rest[-1] if False else "2022-01-10", "wholesale", "gold", aid))

    n = len(customers)
    while n < 420:
        n += 1
        pool = US_CITIES * 6 + CA_CITIES * 2 + UK_CITIES
        city, state, country, pc = rnd.choice(pool)
        fn, ln = rnd.choice(FIRST), rnd.choice(LAST)
        signup = TODAY - timedelta(days=rnd.randint(30, 1100))
        customers.append((
            uid("CUS", n), fn, ln,
            f"{fn.lower()}.{ln.lower()}{n}@example.com".replace("ó", "o").replace("ø", "o"),
            city, state, country, pc, d(signup), "d2c",
            rnd.choices(["bronze", "silver", "gold"], [6, 3, 1])[0], None,
        ))
    cur.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", customers)
    d2c = [c for c in customers if c[9] == "d2c"]
    wholesale_cust = [c for c in customers if c[9] == "wholesale"]

    # ----------------------------------------------------------- subscriptions
    subs = []
    for i, c in enumerate(d2c, start=1):
        if rnd.random() < 0.55:
            started = date.fromisoformat(c[8]) + timedelta(days=rnd.randint(0, 60))
            status = rnd.choices(["active", "paused", "cancelled"], [8, 1, 2])[0]
            subs.append((
                uid("SUB", i), c[0], rnd.choice(products),
                rnd.choice(["solo", "duo", "office"]),
                rnd.choice([14, 28, 56]), status, d(started),
                d(TODAY - timedelta(days=rnd.randint(5, 90))) if status == "paused" else None,
                d(TODAY - timedelta(days=rnd.randint(5, 300))) if status == "cancelled" else None,
                rnd.choice(["price", "quality", "too much coffee", "moving", None])
                if status == "cancelled" else None,
            ))
    cur.executemany("INSERT INTO subscriptions VALUES (?,?,?,?,?,?,?,?,?,?)", subs)

    # ----------------------------------------------------------- sales orders
    so_rows, line_rows, ship_rows = [], [], []
    so_n, ln_n, sh_n = 7000, 0, 0
    tainted_orders, late_ne_orders = [], []

    day = date(2025, 11, 1)
    while day <= TODAY:
        n_orders = rnd.randint(6, 14)
        # wholesale drops weekly
        if day.weekday() == 1:
            n_orders += 6
        for _ in range(n_orders):
            wholesale = rnd.random() < 0.22
            cust = rnd.choice(wholesale_cust if wholesale else d2c)
            so_n += 1
            so_id = uid("SO", so_n, 5)
            ccy = {"US": "USD", "CA": "CAD", "GB": "GBP"}[cust[6]]
            n_lines = rnd.randint(2, 5) if wholesale else rnd.randint(1, 3)
            total = 0.0
            chosen = rnd.sample(products, k=min(n_lines, len(products)))
            has_tainted = False
            for pid in chosen:
                ln_n += 1
                qty = rnd.randint(6, 30) if wholesale else rnd.randint(1, 3)
                price = next(p[5] for p in PRODUCTS if uid("PRD", products.index(pid) + 1, 3) == pid)
                bid = pick_batch(pid, day)
                if bid in tainted_batches:
                    has_tainted = True
                total += qty * price
                line_rows.append((uid("LN", ln_n, 6), so_id, pid, bid, qty, price))

            promised = day + timedelta(days=rnd.randint(3, 6))
            ne = cust[5] in NORTHEAST
            cold_snap = ne and date(2026, 2, 14) <= promised <= date(2026, 2, 19)
            if cold_snap:
                actual_delivery = promised + timedelta(days=rnd.randint(4, 9))
                ship_status, exc = "delivered", "WEATHER_HOLD"
            else:
                slip = rnd.choices([0, 0, 0, 1, 2, 4], [60, 15, 10, 8, 5, 2])[0]
                actual_delivery = promised + timedelta(days=slip)
                ship_status, exc = "delivered", ("CARRIER_DELAY" if slip >= 2 else None)

            delivered = actual_delivery <= TODAY
            status = "delivered" if delivered else "shipped"
            so_rows.append((so_id, cust[0], cust[11], d(day), status,
                            "wholesale" if wholesale else "d2c", ccy, round(total, 2),
                            cust[4], cust[5], cust[6], cust[7]))
            sh_n += 1
            ship_rows.append((
                uid("SHP", sh_n, 5), so_id, rnd.choice(CARRIERS),
                f"1Z{rnd.randint(10**9, 10**10 - 1)}", d(day + timedelta(days=1)),
                d(promised), d(actual_delivery) if delivered else None,
                "delivered" if delivered else "in_transit", cust[7], exc,
            ))
            if has_tainted:
                tainted_orders.append((so_id, cust))
            if cold_snap:
                late_ne_orders.append((so_id, cust))
        day += timedelta(days=1)

    cur.executemany("INSERT INTO sales_orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", so_rows)
    cur.executemany("INSERT INTO sales_order_lines VALUES (?,?,?,?,?,?)", line_rows)
    cur.executemany("INSERT INTO shipments VALUES (?,?,?,?,?,?,?,?,?,?)", ship_rows)

    # ----------------------------------------------------------- tickets
    tk_rows, msg_rows, refund_rows = [], [], []
    tk_n, msg_n, rf_n = 0, 0, 0

    QUALITY_BODIES = [
        "This bag tastes flat compared to what I usually get. Almost papery.",
        "Something is off with the last delivery -- no sweetness at all, very dull.",
        "My usual Cascadia has always been great but this batch is disappointing.",
        "The cup is noticeably weaker. Same grinder, same recipe, different result.",
        "We have had complaints from our customers about the espresso this month.",
    ]
    DELIVERY_BODIES = [
        "My order still has not arrived and it is well past the promised date.",
        "Tracking has not moved in four days. Can you check where this is?",
        "This was supposed to arrive last week. What is happening?",
    ]

    def add_ticket(cust, so_id, opened, category, subject, body, sentiment, status="resolved"):
        nonlocal tk_n, msg_n
        tk_n += 1
        tid = uid("TKT", tk_n, 5)
        resolved = (opened + timedelta(days=rnd.randint(1, 4))) if status == "resolved" else None
        tk_rows.append((tid, cust[0], so_id, ts(opened, rnd.randint(8, 19)),
                        rnd.choice(["email", "chat", "phone"]), category, subject,
                        status, ts(resolved) if resolved else None, sentiment))
        msg_n += 1
        msg_rows.append((uid("MSG", msg_n, 6), tid, "customer", ts(opened, 9), body))
        msg_n += 1
        msg_rows.append((uid("MSG", msg_n, 6), tid, "agent", ts(opened, 14),
                         "Thanks for flagging this -- looking into it now."))
        return tid

    # quality spike from the substituted batches
    for so_id, cust in tainted_orders:
        if rnd.random() < 0.34:
            od = date.fromisoformat(next(r[3] for r in so_rows if r[0] == so_id))
            opened = od + timedelta(days=rnd.randint(8, 24))
            if opened <= TODAY:
                add_ticket(cust, so_id, opened, "quality",
                           "Coffee tastes flat / off-profile",
                           rnd.choice(QUALITY_BODIES), "negative")

    # delivery tickets from the cold snap
    for so_id, cust in late_ne_orders:
        if rnd.random() < 0.55:
            od = date.fromisoformat(next(r[3] for r in so_rows if r[0] == so_id))
            opened = od + timedelta(days=rnd.randint(6, 10))
            if opened <= TODAY:
                add_ticket(cust, so_id, opened, "delivery", "Order has not arrived",
                           rnd.choice(DELIVERY_BODIES), "negative")

    # routine background tickets
    for _ in range(260):
        cust = rnd.choice(d2c)
        opened = TODAY - timedelta(days=rnd.randint(1, 300))
        cat = rnd.choices(["delivery", "billing", "subscription", "quality", "other"],
                          [3, 3, 3, 1, 2])[0]
        add_ticket(cust, None, opened, cat, f"{cat.title()} question",
                   "Hello, I have a question about my account.",
                   rnd.choices(["neutral", "negative", "positive"], [6, 2, 2])[0])

    # Rosewood: the churn-risk account, explicit escalation
    rosewood_cust = next(c for c in wholesale_cust if c[11] == "ACC-001")
    rosewood_orders = [r[0] for r in so_rows
                       if r[1] == rosewood_cust[0]
                       and date.fromisoformat(r[3]) >= date(2026, 2, 1)]
    for i, so_id in enumerate(rosewood_orders[:3]):
        add_ticket(rosewood_cust, so_id, date(2026, 2, 24) + timedelta(days=i * 6),
                   "quality", "Espresso profile has changed -- customers noticing",
                   "We have had complaints two weeks running. This is affecting our bar.",
                   "negative", status="escalated" if i == 2 else "resolved")

    cur.executemany("INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?,?)", tk_rows)
    cur.executemany("INSERT INTO ticket_messages VALUES (?,?,?,?,?)", msg_rows)

    # ----------------------------------------------------------- refunds
    for t in tk_rows:
        if t[5] in ("quality", "delivery") and t[2] and rnd.random() < 0.4:
            so = next((r for r in so_rows if r[0] == t[2]), None)
            if so:
                rf_n += 1
                refund_rows.append((
                    uid("REF", rf_n, 5), so[0],
                    round(so[7] * rnd.choice([0.15, 0.25, 0.5, 1.0]), 2), so[6],
                    "quality" if t[5] == "quality" else "late_delivery",
                    "care.supervisor", t[3][:10],
                ))
    cur.executemany("INSERT INTO refunds VALUES (?,?,?,?,?,?,?)", refund_rows)

    # ----------------------------------------------------------- inventory
    inv = []
    for pid in products:
        for w in range(26):
            as_of = TODAY - timedelta(days=7 * w)
            on_hand = rnd.randint(40, 900)
            inv.append((str(uuid.UUID(int=rnd.getrandbits(128))), pid, d(as_of),
                        on_hand, int(on_hand * rnd.uniform(0.05, 0.4))))
    cur.executemany("INSERT INTO inventory_snapshots VALUES (?,?,?,?,?)", inv)

    con.commit()

    counts = {t: cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in [
        "customers", "wholesale_accounts", "wholesale_contacts", "subscriptions",
        "sales_orders", "sales_order_lines", "shipments", "tickets",
        "ticket_messages", "refunds", "suppliers", "supplier_contacts",
        "purchase_orders", "inbound_shipments", "green_lots", "products",
        "roast_batches", "inventory_snapshots", "case_actions"]}
    con.close()

    print(f"wrote {DB_PATH}")
    for k, v in counts.items():
        print(f"  {k:24s} {v:>6d}")
    print(f"\n  tainted batches: {len(tainted_batches)}  "
          f"orders touching them: {len(tainted_orders)}  "
          f"cold-snap late orders: {len(late_ne_orders)}")


if __name__ == "__main__":
    main()
