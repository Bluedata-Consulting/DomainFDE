-- Meridian Roasters Co. -- Domain FDE build database
-- Deliberate design notes for coaches:
--   * "order"    is ambiguous: sales_orders (outbound) vs purchase_orders (inbound)
--   * "shipment" is ambiguous: shipments (outbound parcel) vs inbound_shipments (sea container)
--   * "contact"  is ambiguous: wholesale_contacts vs supplier_contacts
--   * "lead time" is ambiguous: supplier target vs supplier actual vs customer delivery promise
--   * "lot" (green coffee) vs "batch" (roast run) are distinct and often confused
--   * A person named "Jane" exists in BOTH customers and wholesale_contacts

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- CXM side

CREATE TABLE customers (
    customer_id     TEXT PRIMARY KEY,
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    email           TEXT NOT NULL,
    city            TEXT,
    state           TEXT,
    country         TEXT NOT NULL,
    postcode        TEXT,
    signup_date     TEXT NOT NULL,
    channel         TEXT NOT NULL,          -- d2c | wholesale
    loyalty_tier    TEXT,                   -- bronze | silver | gold
    account_id      TEXT                    -- set when channel = wholesale
);

CREATE TABLE wholesale_accounts (
    account_id          TEXT PRIMARY KEY,
    account_name        TEXT NOT NULL,
    city                TEXT,
    country             TEXT NOT NULL,
    currency            TEXT NOT NULL,
    credit_terms_days   INTEGER,
    tier                TEXT,               -- flagship | standard | trial
    onboarded_at        TEXT
);

CREATE TABLE wholesale_contacts (
    contact_id      TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES wholesale_accounts(account_id),
    contact_name    TEXT NOT NULL,
    email           TEXT,
    role            TEXT
);

CREATE TABLE subscriptions (
    subscription_id TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES customers(customer_id),
    product_id      TEXT NOT NULL,
    plan            TEXT NOT NULL,          -- solo | duo | office
    frequency_days  INTEGER NOT NULL,
    status          TEXT NOT NULL,          -- active | paused | cancelled
    started_at      TEXT NOT NULL,
    paused_at       TEXT,
    cancelled_at    TEXT,
    cancel_reason   TEXT
);

CREATE TABLE sales_orders (
    sales_order_id  TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES customers(customer_id),
    account_id      TEXT REFERENCES wholesale_accounts(account_id),
    order_date      TEXT NOT NULL,
    status          TEXT NOT NULL,          -- placed|roasted|shipped|delivered|returned|cancelled
    channel         TEXT NOT NULL,
    currency        TEXT NOT NULL,
    total_amount    REAL NOT NULL,
    ship_city       TEXT,
    ship_state      TEXT,
    ship_country    TEXT,
    ship_postcode   TEXT
);

CREATE TABLE sales_order_lines (
    line_id         TEXT PRIMARY KEY,
    sales_order_id  TEXT NOT NULL REFERENCES sales_orders(sales_order_id),
    product_id      TEXT NOT NULL REFERENCES products(product_id),
    batch_id        TEXT REFERENCES roast_batches(batch_id),
    qty             INTEGER NOT NULL,
    unit_price      REAL NOT NULL
);

CREATE TABLE shipments (
    shipment_id     TEXT PRIMARY KEY,
    sales_order_id  TEXT NOT NULL REFERENCES sales_orders(sales_order_id),
    carrier         TEXT NOT NULL,
    tracking_ref    TEXT,
    shipped_at      TEXT,
    promised_at     TEXT NOT NULL,
    delivered_at    TEXT,
    status          TEXT NOT NULL,          -- in_transit | delivered | exception | lost
    dest_postcode   TEXT,
    exception_code  TEXT
);

CREATE TABLE tickets (
    ticket_id       TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES customers(customer_id),
    sales_order_id  TEXT REFERENCES sales_orders(sales_order_id),
    opened_at       TEXT NOT NULL,
    channel         TEXT NOT NULL,          -- email | chat | phone
    category        TEXT NOT NULL,          -- delivery | quality | billing | subscription | other
    subject         TEXT NOT NULL,
    status          TEXT NOT NULL,          -- open | pending | resolved | escalated
    resolved_at     TEXT,
    sentiment       TEXT                    -- positive | neutral | negative
);

CREATE TABLE ticket_messages (
    message_id      TEXT PRIMARY KEY,
    ticket_id       TEXT NOT NULL REFERENCES tickets(ticket_id),
    author          TEXT NOT NULL,          -- customer | agent
    sent_at         TEXT NOT NULL,
    body            TEXT NOT NULL
);

CREATE TABLE refunds (
    refund_id       TEXT PRIMARY KEY,
    sales_order_id  TEXT NOT NULL REFERENCES sales_orders(sales_order_id),
    amount          REAL NOT NULL,
    currency        TEXT NOT NULL,
    reason_code     TEXT NOT NULL,          -- late_delivery | quality | damaged | goodwill | other
    approved_by     TEXT,
    created_at      TEXT NOT NULL
);

-- ---------------------------------------------------------------- SCM side

CREATE TABLE suppliers (
    supplier_id             TEXT PRIMARY KEY,
    supplier_name           TEXT NOT NULL,
    country                 TEXT NOT NULL,
    origin_region           TEXT,
    port                    TEXT,
    currency                TEXT NOT NULL,
    lead_time_days_target   INTEGER NOT NULL,
    relationship_since      TEXT
);

CREATE TABLE supplier_contacts (
    contact_id      TEXT PRIMARY KEY,
    supplier_id     TEXT NOT NULL REFERENCES suppliers(supplier_id),
    contact_name    TEXT NOT NULL,
    email           TEXT,
    role            TEXT
);

CREATE TABLE purchase_orders (
    purchase_order_id   TEXT PRIMARY KEY,
    supplier_id         TEXT NOT NULL REFERENCES suppliers(supplier_id),
    po_date             TEXT NOT NULL,
    incoterm            TEXT,
    currency            TEXT NOT NULL,
    total_amount        REAL NOT NULL,
    fx_rate_at_po       REAL,
    status              TEXT NOT NULL,      -- open | in_transit | received | cancelled
    expected_arrival    TEXT,
    actual_arrival      TEXT
);

CREATE TABLE inbound_shipments (
    inbound_id          TEXT PRIMARY KEY,
    purchase_order_id   TEXT NOT NULL REFERENCES purchase_orders(purchase_order_id),
    container_ref       TEXT,
    origin_port         TEXT,
    dest_port           TEXT,
    etd                 TEXT,
    eta                 TEXT,
    actual_arrival      TEXT,
    status              TEXT NOT NULL,      -- booked | sailing | delayed | arrived | cleared
    delay_reason        TEXT
);

CREATE TABLE green_lots (
    lot_id              TEXT PRIMARY KEY,
    purchase_order_id   TEXT REFERENCES purchase_orders(purchase_order_id),
    origin              TEXT NOT NULL,
    varietal            TEXT,
    grade               TEXT,
    cupping_score       REAL,
    kg_received         REAL NOT NULL,
    kg_remaining        REAL NOT NULL,
    received_at         TEXT
);

CREATE TABLE products (
    product_id      TEXT PRIMARY KEY,
    sku             TEXT NOT NULL,
    name            TEXT NOT NULL,
    roast_profile   TEXT,                   -- light | medium | dark
    bag_size_g      INTEGER,
    category        TEXT,                   -- single_origin | blend | decaf
    list_price_usd  REAL,
    active          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE roast_batches (
    batch_id        TEXT PRIMARY KEY,
    product_id      TEXT NOT NULL REFERENCES products(product_id),
    lot_id          TEXT NOT NULL REFERENCES green_lots(lot_id),
    roast_date      TEXT NOT NULL,
    kg_input        REAL NOT NULL,
    units_output    INTEGER NOT NULL,
    qa_pass         INTEGER NOT NULL,
    qa_note         TEXT
);

CREATE TABLE inventory_snapshots (
    snapshot_id     TEXT PRIMARY KEY,
    product_id      TEXT NOT NULL REFERENCES products(product_id),
    as_of_date      TEXT NOT NULL,
    units_on_hand   INTEGER NOT NULL,
    units_allocated INTEGER NOT NULL
);

-- ---------------------------------------------------------------- agent writes

CREATE TABLE case_actions (
    action_id       TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    created_by      TEXT NOT NULL,          -- agent name
    entity_type     TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    action_type     TEXT NOT NULL,          -- goodwill_credit|replacement|escalate|note|supplier_review
    payload_json    TEXT NOT NULL,
    status          TEXT NOT NULL,          -- proposed | approved | rejected | executed
    approved_by     TEXT
);

CREATE INDEX idx_so_customer   ON sales_orders(customer_id);
CREATE INDEX idx_ship_so       ON shipments(sales_order_id);
CREATE INDEX idx_tickets_cust  ON tickets(customer_id);
CREATE INDEX idx_lines_so      ON sales_order_lines(sales_order_id);
CREATE INDEX idx_batches_prod  ON roast_batches(product_id);
