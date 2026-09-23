"""Metrics for the complaints agent (Day 3: Measure).

Plain Python. No ADK, no AI model. It turns what the agent did into five numbers,
compares them with their budgets, and prints a scorecard.

    python3 metrics.py tests/sample_cases.csv    the five hand-made cases
    python3 metrics.py runs.jsonl                what the agent really did

A CASE is one complaint handled in one chat session. Every metric is calculated
over cases. Each metric below carries its contract: what it counts, out of what,
where the data comes from, how fresh it must be, and who owns its meaning.
"""
import csv
import json
import math
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# BUDGETS
# Assumptions waiting for sign-off by the complaints team lead and Finance.
# Do not change them during the exercise; propose changes in ADR-3.
# ---------------------------------------------------------------------------
ESCALATION_CEILING = 0.30            # Metric 2: at most 30% of cases sent to a person
MUST_ESCALATE_FLOOR = 1.00           # Metric 3: every at-risk case reaches a person
COST_BUDGET_GBP = 0.02               # Metric 4: model cost per decision
RESPONSE_P95_BUDGET_SECONDS = 15     # Metric 5: 95th percentile response time
PRICE_PER_1000_TOKENS_GBP = 0.002    # Finance's assumed blended price


# ---------------------------------------------------------------------------
# LOADING CASES
# ---------------------------------------------------------------------------
def _yes(value):
    return str(value).strip().lower() in ("yes", "true", "1")


def load_sample(path):
    """Cases from a CSV file, one row per case (tests/sample_cases.csv)."""
    with open(path, newline="", encoding="utf-8") as f:
        return [{
            "case": row["case"],
            "complaint": row["complaint"],
            "closed_by_agent": _yes(row["closed_by_agent"]),
            "blocked": int(row["blocked"]),
            "escalated": int(row["escalated"]),
            "at_risk": _yes(row["at_risk"]),
            "reached_person": _yes(row["reached_person"]),
            "tokens": int(row["tokens"]),
            "seconds": float(row["seconds"]),
        } for row in csv.DictReader(f)]


def load_runs(path):
    """Cases from runs.jsonl, written by the agent's recorder. One case per session."""
    sessions = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            s = sessions.setdefault(e["session"], {
                "case": e["session"][:8], "complaint": "", "closed_by_agent": False,
                "blocked": 0, "escalated": 0, "at_risk": False, "reached_person": False,
                "tokens": 0, "seconds": 0.0,
            })
            kind = e["event"]
            if kind == "lookup":
                s["complaint"] = s["complaint"] or e["complaint_id"]
                s["at_risk"] = s["at_risk"] or e["at_risk"]
            elif kind == "tool_call":
                s["complaint"] = s["complaint"] or e.get("complaint_id", "")
                if e["result"] == "blocked":
                    s["blocked"] += 1
                if e["tool"] == "close_complaint" and e["result"] == "ran":
                    s["closed_by_agent"] = True
            elif kind == "escalation":
                s["escalated"] += 1
                s["reached_person"] = True
            elif kind == "model_call":
                s["tokens"] += e["input_tokens"] + e["output_tokens"]
            elif kind == "turn":
                s["seconds"] += e["seconds"]
    # A session that never touched a complaint is not a case.
    return [s for s in sessions.values() if s["complaint"]]


def load_cases(path):
    return load_sample(path) if str(path).endswith(".csv") else load_runs(path)


# ---------------------------------------------------------------------------
# METRIC 1 · GOAL
# ---------------------------------------------------------------------------
def correct_autonomous_resolution(cases):
    """Share of cases the agent closed itself, with no block and no escalation.

    Counts:    cases where closed_by_agent is yes, blocked is 0 and escalated is 0
    Out of:    all cases
    Grain:     one complaint in one session
    Source:    close_complaint, blocked tool calls and escalations in runs.jsonl
    Freshness: daily
    Owner:     complaints team lead
    Decided:   an at-risk case closed without a person still counts here.
               That failure is caught by metric 3, not hidden by this one.
    """
    good = [c for c in cases if c["closed_by_agent"] and c["blocked"] == 0 and c["escalated"] == 0]
    return len(good) / len(cases)


# ---------------------------------------------------------------------------
# METRIC 2 · LIMIT
# ---------------------------------------------------------------------------
def escalation_rate(cases):
    """Share of cases sent to a person at least once.

    Counts:    cases with one or more escalations
    Out of:    all cases
    Grain:     one complaint in one session
    Source:    escalation events in runs.jsonl
    Freshness: daily
    Owner:     complaints team lead
    Decided:   a case escalated twice (C-104) counts once. The same complaint
               in two sessions counts twice.
    """
    return len([c for c in cases if c["escalated"] > 0]) / len(cases)


# ---------------------------------------------------------------------------
# METRIC 3 · LIMIT
# ---------------------------------------------------------------------------
def must_escalate_coverage(cases):
    """Share of at-risk cases (vulnerable or legal) that reached a person.

    Counts:    at-risk cases where reached_person is yes
    Out of:    at-risk cases only
    Grain:     one complaint in one session
    Source:    lookup events (at_risk) and escalation events in runs.jsonl
    Freshness: real time: one miss is one too many
    Owner:     complaints team lead, with Legal
    Decided:   with no at-risk cases the metric has nothing to measure, and
               returns None rather than 100%.
    """
    at_risk = [c for c in cases if c["at_risk"]]
    if not at_risk:
        return None
    return len([c for c in at_risk if c["reached_person"]]) / len(at_risk)


# ---------------------------------------------------------------------------
# METRIC 4 · LIMIT
# ---------------------------------------------------------------------------
def case_cost_gbp(case):
    return case["tokens"] / 1000 * PRICE_PER_1000_TOKENS_GBP


def cost_per_decision(cases):
    """Average model cost of handling one case, in pounds.

    Counts:    tokens across every model call, times the price per 1,000 tokens
    Out of:    all cases
    Grain:     one complaint in one session
    Source:    model_call events in runs.jsonl (input plus output tokens)
    Freshness: daily
    Owner:     Finance
    Decided:   the AVERAGE is compared with the budget, not each case. The most
               expensive case is shown as a Watch line. People's time on
               escalations is not included.
    """
    return sum(case_cost_gbp(c) for c in cases) / len(cases)


# ---------------------------------------------------------------------------
# METRIC 5 · LIMIT
# ---------------------------------------------------------------------------
def response_time_p95(cases):
    """95th percentile of seconds per case.

    Counts:    seconds from each user message to the agent's final reply, added
               up across the session
    Out of:    all cases
    Grain:     one complaint in one session
    Source:    turn events in runs.jsonl
    Freshness: hourly
    Owner:     complaints team lead
    Decided:   nearest-rank method: sort the times, take the value at position
               ceil(0.95 x number of cases). With 5 cases that is the slowest one.
    """
    times = sorted(c["seconds"] for c in cases)
    rank = math.ceil(0.95 * len(times))
    return times[rank - 1]


# ---------------------------------------------------------------------------
# WATCH ONLY: no budget, nothing fails on these
# ---------------------------------------------------------------------------
def blocked_per_case(cases):
    return sum(c["blocked"] for c in cases) / len(cases)


def tokens_per_decision(cases):
    return sum(c["tokens"] for c in cases) / len(cases)


def most_expensive_case_gbp(cases):
    return max(case_cost_gbp(c) for c in cases)


# ---------------------------------------------------------------------------
# SCORECARD
# ---------------------------------------------------------------------------
def scorecard(cases):
    """Rows of (label, value text, budget text, result)."""
    cov = must_escalate_coverage(cases)
    esc = escalation_rate(cases)
    cost = cost_per_decision(cases)
    p95 = response_time_p95(cases)
    return [
        ("1  Correct autonomous resolution", f"{correct_autonomous_resolution(cases):.0%}", "goal", "GOAL"),
        ("2  Escalation rate", f"{esc:.0%}", f"<= {ESCALATION_CEILING:.0%}",
         "PASS" if esc <= ESCALATION_CEILING else "BREACH"),
        ("3  Must-escalate coverage", "no at-risk cases" if cov is None else f"{cov:.0%}",
         f">= {MUST_ESCALATE_FLOOR:.0%}",
         "PASS" if cov is None or cov >= MUST_ESCALATE_FLOOR else "BREACH"),
        ("4  Cost per decision", f"£{cost:.4f}", f"<= £{COST_BUDGET_GBP:.2f}",
         "PASS" if cost <= COST_BUDGET_GBP else "BREACH"),
        ("5  Response time, 95th pct", f"{p95:g} s", f"<= {RESPONSE_P95_BUDGET_SECONDS} s",
         "PASS" if p95 <= RESPONSE_P95_BUDGET_SECONDS else "BREACH"),
        ("   Watch: blocked per case", f"{blocked_per_case(cases):.1f}", "none", "WATCH"),
        ("   Watch: tokens per decision", f"{tokens_per_decision(cases):,.0f}", "none", "WATCH"),
        ("   Watch: most expensive case", f"£{most_expensive_case_gbp(cases):.4f}", "none", "WATCH"),
    ]


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("runs.jsonl")
    if not path.exists():
        print(f"No file at {path}. Run the agent first, or try: python3 metrics.py tests/sample_cases.csv")
        sys.exit(1)
    cases = load_cases(path)
    if not cases:
        print(f"{path} has no cases yet. Ask the agent about a complaint, then try again.")
        sys.exit(1)

    print(f"\nScorecard for {path}  ({len(cases)} cases)\n")
    print(f"  {'Metric':<34} {'Value':<18} {'Budget':<10} Result")
    print(f"  {'-' * 34} {'-' * 18} {'-' * 10} ------")
    rows = scorecard(cases)
    for label, value, budget, result in rows:
        print(f"  {label:<34} {value:<18} {budget:<10} {result}")

    breaches = [r for r in rows if r[3] == "BREACH"]
    verdict = "READY: every limit is within budget." if not breaches else \
        f"NOT READY: {len(breaches)} limit{'s' if len(breaches) > 1 else ''} breached."
    print(f"\n  {verdict}\n")


if __name__ == "__main__":
    main()
