"""Tool set for the v0 agent.

`domaintools` holds business-named tools (one per business question).
`sqltools` holds the generic SQL escape hatch, kept as a fallback.
"""

from .db import DB_PATH
from .domaintools import (
    find_customers,
    find_late_shipments,
    find_purchase_orders,
    find_roast_batches,
    find_sales_orders,
    find_suppliers,
    find_tickets,
    find_wholesale_contacts,
    get_customer_360,
    get_inbound_shipments,
    get_inventory_position,
    get_sales_order_detail,
    get_shipment_status,
    get_supplier_performance,
    get_ticket_thread,
    ticket_trend,
    trace_product_to_lot,
)
from .sqltools import execute_sql, get_table_schemas, list_tables

DOMAIN_TOOLS = [
    # customers
    find_customers,
    get_customer_360,
    find_wholesale_contacts,
    # sales orders
    find_sales_orders,
    get_sales_order_detail,
    # outbound shipments
    get_shipment_status,
    find_late_shipments,
    # tickets
    find_tickets,
    get_ticket_thread,
    ticket_trend,
    # suppliers and inbound
    find_suppliers,
    find_purchase_orders,
    get_inbound_shipments,
    get_supplier_performance,
    # traceability, production, inventory
    trace_product_to_lot,
    find_roast_batches,
    get_inventory_position,
]

# Generic SQL fallback -- only for questions no domain tool covers.
SQL_TOOLS = [list_tables, get_table_schemas, execute_sql]

ALL_TOOLS = DOMAIN_TOOLS + SQL_TOOLS

__all__ = ["DB_PATH", "DOMAIN_TOOLS", "SQL_TOOLS", "ALL_TOOLS"] + [
    tool.__name__ for tool in ALL_TOOLS
]
