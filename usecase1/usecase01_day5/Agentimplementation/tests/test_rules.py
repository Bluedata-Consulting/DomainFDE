"""Component test: every team's rules, and the code router (Days 2 and 5). No AI model.

Run from the kit folder, with the ADK environment active:
    python3 tests/test_rules.py

Part 1: one proposed action on one complaint or return. Facts in, rule out.
Part 2: one request. Words in, team out. "unsure" means the model decides.
"""
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
from northwind import rules  # noqa: E402
from northwind.data import complaint_view, return_view  # noqa: E402

failures = 0


def check(name, got, expected):
    global failures
    ok = got == expected
    failures += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<52} expected {str(expected):<30} got {got}")


print("Part 1: the rules, one team at a time\n")
c = complaint_view
check("C1 Complaint from a vulnerable customer (C-105)", rules.check_complaint(c("C-105"))["rule"], "ESCALATE")
check("C2 Chat marketing message to C-104", rules.decide_message(c("C-104"), "chat", "marketing", "New range")["rule"], "NO_CONSENT")
check("C3 A discount in a service email to C-104", rules.decide_message(c("C-104"), "email", "service", "20% off")["rule"], "NO_OFFER_POLICY")
check("B1 Refund 50 on a 45 pound order (C-101)", (rules.decide_refund(c("C-101"), 50)["rule"], rules.decide_refund(c("C-101"), 50)["owner"]), ("OVER_ORDER_VALUE", "Billing team lead"))
check("B2 Refund 35 on C-106 (limit 25)", (rules.decide_refund(c("C-106"), 35)["rule"], rules.decide_refund(c("C-106"), 35)["owner"]), ("NEEDS_APPROVAL", "Billing team lead"))
r = return_view
check("R1 Restock the recalled heater (R-202)", (rules.decide_disposition(r("R-202"), "restock")["rule"], rules.decide_disposition(r("R-202"), "restock")["owner"]), ("RECALLED", "Returns supervisor"))
check("R1 Quarantine the recalled heater (R-202)", rules.decide_disposition(r("R-202"), "quarantine")["rule"], "ALLOWED")
check("R2 Any decision on the 1,400 pound laptop (R-203)", rules.decide_disposition(r("R-203"), "refurbish")["rule"], "HIGH_VALUE")
check("R3 Restock a grade C kettle (R-206)", rules.decide_disposition(r("R-206"), "restock")["rule"], "GRADE_NOT_FIT")
check("R4 Vendor claim after the deadline (R-204)", rules.decide_claim(r("R-204"))["rule"], "CLAIM_EXPIRED")
check("   Send the kettle back to its vendor (R-206)", rules.decide_disposition(r("R-206"), "return_to_vendor")["rule"], "ALLOWED")

print("\nPart 2: the code router\n")
route = lambda text: rules.route_by_rules(text)[0]  # noqa: E731
check("A return ID goes to returns", route("What should happen to return R-202?"), "returns")
check("Money words go to billing", route("Complaint C-102: I want my money back"), "billing")
check("A complaint ID goes to complaints", route("Please apologise to the customer on C-104"), "complaints")
check("Nothing to go on: the model decides", route("Nobody is helping me with my order"), "unsure")
check("Several teams at once: the model decides", route("C-106 wants a refund and R-206 came back"), "unsure")

total = 16
print(f"\n{total - failures} of {total} checks passed.")
sys.exit(1 if failures else 0)
