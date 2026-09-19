"""Validate the ontology. No AI model is used.

Run from the kit folder, with the ADK environment active:
    python3 tests/test_ontology.py

Part 1 checks the data against the rules in ontology.yaml. Five contradictions are
planted in data/northwind.json on purpose; the test passes only if all five are found,
and nothing else is.

Part 2 answers the golden questions in tests/golden_questions.csv by following links.
A question whose link is not in the ontology is a GAP. G6 is expected to be one.
"""
import csv
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT / "agents" / "complaints_v4_context"))
import ontology  # noqa: E402

# The contradictions planted on purpose: (rule, record)
PLANTED = {
    ("complaint_order_same_customer", "C-104"),
    ("refunds_within_order_value", "C-105"),
    ("vulnerability_one_value_per_customer", "ACC-003B"),
    ("consent_has_purpose", "CUST-002"),
    ("contacts_match_text", "C-103"),
}

failures = 0

print("Part 1: does the data conform to the ontology?\n")
findings = ontology.validate()
for rule, record, result, detail in findings:
    print(f"  {result:<14} {rule:<38} {record:<12} {detail}")
found = {(rule, record) for rule, record, result, _ in findings if result == "CONTRADICTION"}
missed, unexpected = PLANTED - found, found - PLANTED
if missed or unexpected:
    failures += 1
    print(f"\n  FAIL  missed: {sorted(missed)}  unexpected: {sorted(unexpected)}")
else:
    print(f"\n  PASS  {len(found)} contradictions found: all {len(PLANTED)} planted ones, and nothing else.")

print("\nPart 2: can every golden question be answered by following links?\n")
answered = gaps = 0
with open(KIT / "tests" / "golden_questions.csv", newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        function = getattr(ontology, row["function"])
        try:
            got = function(*row["args"].split("|"))
            answered += 1
        except ontology.Gap as gap:
            got = "GAP"
            gaps += 1
            row["path"] = f"{row['path']}. {gap}"
        ok = got == row["expected"]
        failures += not ok
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {row['id']}  {row['question']:<64} expected {row['expected']:<4} got {got:<4}")
        print(f"              path: {row['path']}")

print(f"\n  {answered} answered by following links, {gaps} gap{'s' if gaps != 1 else ''}.")
print(f"\n{'ALL CHECKS PASSED' if not failures else f'{failures} CHECK(S) FAILED'}")
sys.exit(1 if failures else 0)
