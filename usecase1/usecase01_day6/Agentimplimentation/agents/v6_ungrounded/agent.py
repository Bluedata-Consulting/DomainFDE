"""Day 6 BEFORE: the operations assistant with no grounding. It can only answer from
the model and its instruction, so questions about records or policy get "I do not know",
or worse, a guess."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the kit folder, where northwind/ lives

from northwind.grounded import make_agent  # noqa: E402

root_agent = make_agent("v6_ungrounded", None)
