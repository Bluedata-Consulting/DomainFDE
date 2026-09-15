"""Test the decision tree with 5 scenarios, one per rule. No AI model is used.

Each scenario checks two things: which rule decided, and who it escalates to.

Run:  python3 tests/test_decision_tree.py
"""
import sys
from pathlib import Path

# Load the two plain Python files directly (not the ADK agent).
sys.path.insert(0, str(Path(__file__).parent.parent / "agents" / "complaints_v2_decision"))
from decision_tree import decide  # noqa: E402
from tools import COMPLAINTS      # noqa: E402

# (scenario, complaint, action the agent tries, arguments, expected rule, escalates to)
SCENARIOS = [
    ("S1 Close complaint of a vulnerable customer", "C-103",
     "close_complaint", {}, "ESCALATE", "Complaints team lead"),
    ("S2 Email a customer who opted out of email", "C-104",
     "send_customer_message", {"channel": "email", "message": "Sorry about the lamp."},
     "OPTED_OUT_CHANNEL", "Complaints team lead"),
    ("S3 Offer a 20% discount on chat", "C-104",
     "send_customer_message", {"channel": "chat", "message": "Here is a 20% discount."},
     "NO_OFFER_POLICY", "Complaints team lead"),
    ("S4 Refund 40 GBP", "C-102",
     "issue_refund", {"amount_gbp": 40}, "NEEDS_APPROVAL", "Billing team"),
    ("S5 Close a routine complaint", "C-101",
     "close_complaint", {}, "ALLOWED", None),
]

failures = 0
for name, complaint_id, tool_name, args, rule, owner in SCENARIOS:
    result = decide(COMPLAINTS[complaint_id], tool_name, args)
    ok = result["rule"] == rule and result["owner"] == owner
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name:<44} rule {result['rule']:<18} "
          f"escalates to {result['owner'] or '(nobody)'}")

print(f"\n{len(SCENARIOS) - failures} of {len(SCENARIOS)} scenarios passed.")
sys.exit(1 if failures else 0)
