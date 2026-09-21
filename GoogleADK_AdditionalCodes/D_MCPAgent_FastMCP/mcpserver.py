"""A small stdio MCP server for the D_MCPAgent_FastMCP lab.

The agent originally pointed at /home/zadmin/Desktop/B7_GAAP_GCP/mcpserver/mcpserver2.py,
which does not exist on this machine. This is a self-contained replacement that
exposes a few trivially verifiable tools, so the lab demonstrates the thing it is
actually about: an ADK agent discovering and calling tools over the MCP protocol.

Run standalone to sanity-check it:  python D_MCPAgent_FastMCP/mcpserver.py stdio
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

# mcp 2.x renamed FastMCP to MCPServer. On mcp<2 this is `from mcp.server.fastmcp import FastMCP`.
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("aurora-demo-tools")


@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers and return the sum."""
    return a + b


@mcp.tool()
def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


@mcp.tool()
def stock_on_hand(sku: str) -> dict:
    """Look up on-hand inventory for an Aurora Retail SKU.

    Args:
        sku: SKU code, for example "AUR-1001".
    """
    catalogue = {
        "AUR-1001": {"name": "Citrus Hand Wash 250ml", "on_hand": 412, "warehouse": "BLR-DC1"},
        "AUR-1002": {"name": "Aloe Body Lotion 400ml", "on_hand": 87, "warehouse": "BLR-DC1"},
        "AUR-2010": {"name": "Bamboo Kitchen Towel 2pk", "on_hand": 0, "warehouse": "KUL-DC2"},
    }
    record = catalogue.get(sku.upper())
    if record is None:
        return {"sku": sku, "found": False, "known_skus": sorted(catalogue)}
    return {"sku": sku.upper(), "found": True, **record}


if __name__ == "__main__":
    # ADK launches this with "stdio" as argv[1]; accept it and ignore anything else.
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    mcp.run(transport=transport)
