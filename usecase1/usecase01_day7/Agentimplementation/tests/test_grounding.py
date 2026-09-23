"""Component test: the grounding parts, without any AI model (Day 6: Ground).

Run from the kit folder, with the ADK environment active:
    python3 tests/test_grounding.py

  Part 1  the database: the answers the golden questions depend on
  Part 2  the SQL guardrail: only safe, read-only queries run
  Part 3  policy search: the right passage comes first
  Part 4  the MCP server: it starts, and offers the three tools in both modes
"""
import asyncio
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
from northwind import database, policy_search, sql  # noqa: E402

failures = 0


def check(name, got, expected):
    global failures
    ok = got == expected
    failures += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<56} expected {str(expected)[:34]:<36} got {str(got)[:40]}")


def rows(query, mode="semantic"):
    return [r[0] for r in sql.run(query, mode)["rows"]]


print("Part 1: the database\n")
database.build()
check("G1 vulnerable complaints, from the semantic view", rows("SELECT complaint_id FROM complaints_v WHERE customer_is_vulnerable='yes' ORDER BY 1"), ["C-103", "C-105"])
check("G1 trap: the raw account flag finds none", rows("SELECT c.cid FROM cmp_tbl c JOIN acc_tbl a ON a.aref=c.aref WHERE a.vuln=1", "raw"), [])
check("G4 grade C returns", rows("SELECT COUNT(*) FROM returns_v WHERE condition_grade='C'"), [3])
check("G4 trap: raw grades are codes, not letters", rows("SELECT COUNT(*) FROM rtn_tbl WHERE grd='C'", "raw"), [0])
check("G5 grade C with the vendor claim still open", rows("SELECT return_id FROM returns_v WHERE condition_grade='C' AND vendor_claim_open='yes' ORDER BY 1"), ["R-203", "R-206"])
check("G9 order value on C-106", rows("SELECT order_value_gbp FROM complaints_v WHERE complaint_id='C-106'"), [35.0])

print("\nPart 2: the SQL guardrail\n")
check("A SELECT on a view, in semantic mode", sql.check("SELECT * FROM returns_v", "semantic"), None)
check("A raw table, in semantic mode", sql.check("SELECT * FROM rtn_tbl", "semantic") is not None, True)
check("A view, in raw mode", sql.check("SELECT * FROM returns_v", "raw") is not None, True)
check("A DELETE", sql.check("DELETE FROM rtn_tbl", "raw") is not None, True)
check("Two statements", sql.check("SELECT 1 FROM rtn_tbl; DROP TABLE rtn_tbl", "raw") is not None, True)
check("A WITH query over allowed views", sql.check("WITH c AS (SELECT * FROM returns_v) SELECT * FROM c", "semantic"), None)
check("A bad column returns an error, not a crash", sql.run("SELECT nope FROM returns_v", "semantic")["status"], "error")

print("\nPart 3: policy search\n")
top = lambda q: policy_search.search(q)["passages"][0]["source"]  # noqa: E731
check("G6 what grade C means", top("What does condition grade C mean?"), "returns_grading.md#Condition grades")
check("G7 compensation for a late delivery", top("Can we give compensation for a delivery five days late?"), "delivery_delays.md#Goodwill credit for long delays")
check("G8 liquidation recovery rate", top("What recovery rate do we get when we liquidate small electricals?"), "returns_grading.md#Liquidation recovery")
check("Synonym: money back finds the refund limits", top("Can I give the customer their money back above 25 pounds?"), "refunds.md#Refund limits")


async def mcp_tools(mode):
    from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
    from mcp import StdioServerParameters
    import os
    toolset = McpToolset(connection_params=StdioConnectionParams(server_params=StdioServerParameters(
        command=sys.executable, args=[str(KIT / "mcp_server" / "northwind_mcp.py")],
        env={**os.environ, "NORTHWIND_GROUNDING": mode}), timeout=30))
    tools = await toolset.get_tools()
    names = sorted(t.name for t in tools)
    describe = next(t for t in tools if t.name == "describe_data").description
    await toolset.close()
    return names, describe


print("\nPart 4: the MCP server\n")
for mode in ("raw", "semantic"):
    names, describe = asyncio.run(mcp_tools(mode))
    check(f"The {mode} server offers three tools", names, ["describe_data", "run_sql", "search_policy"])
    check(f"The {mode} server describes the data its own way", "views" in describe, mode == "semantic")

total = 21
print(f"\n{total - failures} of {total} checks passed.")
sys.exit(1 if failures else 0)
