"""Pattern A: the agent loop, the Agent approach (Day 5: Build).

One specialist, three tools. The model runs the loop itself: it calls a tool, reads
the result, decides what to do next, and repeats until it can answer. ADK's runner
provides the loop; nothing in this file draws it.

This is the complaints specialist on its own. Compare it with v5b_loop_graph, which
does the same job with the loop drawn explicitly.
"""

import sys
from pathlib import Path

# The shared northwind package sits in the kit folder, next to agents/.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from northwind.specialists import make_complaints_agent  # noqa: E402

root_agent = make_complaints_agent(name="v5a_loop_agent")
