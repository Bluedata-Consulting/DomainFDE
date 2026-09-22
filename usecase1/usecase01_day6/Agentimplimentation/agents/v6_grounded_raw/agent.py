"""Day 6 run 1: grounded on the RAW tables, over MCP. The agent sees cryptic table and
column names, codes instead of words, and must work out the joins itself."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the kit folder, where northwind/ lives

from northwind.grounded import make_agent  # noqa: E402

root_agent = make_agent("v6_grounded_raw", "raw")
