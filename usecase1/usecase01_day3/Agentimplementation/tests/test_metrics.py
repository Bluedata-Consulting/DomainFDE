"""Test the five metrics on the five hand-made cases. No AI model is used.

Run from the kit folder:  python3 tests/test_metrics.py

The expected values below were worked out by hand from tests/sample_cases.csv,
using the contracts written in metrics.py. If a test fails, either the code or
the contract is wrong. The expected values are the specification: they are not
edited to make a test pass.
"""
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
import metrics  # noqa: E402

cases = metrics.load_sample(KIT / "tests" / "sample_cases.csv")

# (metric, function, expected value, how it was worked out by hand)
CHECKS = [
    ("1 Correct autonomous resolution", metrics.correct_autonomous_resolution, 0.40,
     "S1 and S5 closed with no block or escalation: 2 of 5"),
    ("2 Escalation rate", metrics.escalation_rate, 0.60,
     "S2, S3, S4 escalated at least once: 3 of 5 (S4 counts once)"),
    ("3 Must-escalate coverage", metrics.must_escalate_coverage, 0.50,
     "At risk: S3 and S5. Only S3 reached a person: 1 of 2"),
    ("4 Cost per decision (GBP)", metrics.cost_per_decision, 0.0136,
     "34,000 tokens x 0.002 per 1,000 = 0.068, over 5 cases"),
    ("5 Response time, 95th pct (s)", metrics.response_time_p95, 18.0,
     "Sorted 5, 6, 9, 12, 18. Position ceil(0.95 x 5) = 5: 18"),
]

failures = 0
for name, function, expected, working in CHECKS:
    got = function(cases)
    ok = got is not None and round(got, 4) == round(expected, 4)
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name:<32} expected {expected:<7g} got {got if got is None else round(got, 4):<7g}  {working}")

print(f"\n{len(CHECKS) - failures} of {len(CHECKS)} metrics matched.")
sys.exit(1 if failures else 0)
