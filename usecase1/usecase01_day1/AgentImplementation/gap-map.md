# Gap map: what is missing from this agent?

Tick each gap you found. In the right-hand column, write the prompt number or the
line of code that proved it. A tick with no evidence does not count.

## Fix today (Day 1: Frame)

| | Missing piece | Evidence (prompt number or file and line) |
|---|---|---|
| [ ] | **A defined decision.** The agent does not know what it decides and what it does not. | |
| [ ] | **Autonomy per sub-decision.** Every tool runs with the same freedom, refunds and write-offs included. | |
| [ ] | **A must-never list.** Nothing says what the agent is forbidden to do. | |
| [ ] | **A human boundary.** There is no way to hand over to a person, and no named owner. | |
| [ ] | **Real questions to test it with.** There is no test set in the repo, only whatever someone types. | |

## Fix later in the programme

| | Missing piece | Day | Evidence |
|---|---|---|---|
| [ ] | Decision logic that can be tested on its own | Day 2 | |
| [ ] | A measurable objective and its limits (what does "happy customer" or "stocked shelf" actually mean?) | Day 3 | |
| [ ] | Tool descriptions that say when *not* to use a tool (look at the one-line docstrings in `tools.py`) | Day 4 | |
| [ ] | An eval set and a baseline score | Day 5 | |
| [ ] | Grounding in real policy and data (see P5) | Day 6 | |
| [ ] | Versioning, tracing and rollback | Day 7 | |
| [ ] | An approval gate and an audit trail | Day 9 | |

---

**The single most dangerous gap, in one sentence:**

```

```

**Which gap, if fixed alone, would have prevented the worst thing you saw?**

```

```

> Carry both answers into `improvement-proposal.md`. The first becomes a must-never
> rule in Part A6; the second usually becomes your first backlog item in Part B2.
