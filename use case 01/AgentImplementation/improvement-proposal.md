# Improvement proposal

**Pair / name:** ______________________  **Domain:** SCM (returns) / CXM (complaints)
**Date:** ____________  **Agent tested:** `returns_v1_baseline` / `complaints_v1_baseline`

---

## How to use this form

You have just watched an agent act on its own in ways it should not. This form is
where you turn that into something a team could actually build.

It has two parts, and the order matters.

| Part | What it is | Time |
|---|---|---|
| **Part A** | Write the requirement properly. This is the artefact that was missing from the agent you tested. | 15 min |
| **Part B** | List the improvements you would make, and say whether each one is a request or an enforcement. | 10 min |

**Do Part A before Part B.** Most improvement lists are wishes until somebody has
written down what the agent is actually for. If you find yourself unable to fill in
a Part B row, it is usually because a Part A field is still blank.

Fill this in from the failures you saw, not from theory. A blank left honest is
worth more than a field filled in with something that sounds right. If you do not
know an answer, write it in Part D as an open question and name who could answer it.

There is a completed version in `improvement-proposal-EXAMPLE.md`. Read it if you
get stuck, but write your own answers first.

---

# PART A: how to define the agentic AI requirement

> **The test for every field below:** could an engineer who was not in this room
> build the agent from what you wrote, and could a reviewer tell whether the result
> passes or fails? If either answer is no, the field is not finished.

---

## A1. The decision, in one sentence

Not the task. Not the tool. The **decision** the agent is being trusted with.

Use this shape:

> *The agent decides* **[what]** *for* **[which cases]** *using* **[which inputs]**,
> *so that* **[what outcome]**.

| | |
|---|---|
| **Weak** | "The agent handles complaints." (This is a job title, not a decision. It cannot be tested, scoped or refused.) |
| **Strong** | "The agent decides the routing team and severity for inbound complaints under 100 pounds in value, using the complaint record and the customer history, so that each complaint reaches the right team within 15 minutes." |

**Your decision statement:**

```
The agent decides ____________________________________________________

for __________________________________________________________________

using ________________________________________________________________

so that ______________________________________________________________
```

**Explicitly out of scope** (three things this agent must not decide, even though it
could be asked to):

1.
2.
3.

---

## A2. Trigger, volume and who owns it today

| Field | Your answer |
|---|---|
| **What starts it** (an event, a message, a queue, a schedule) | |
| **How many per day** | |
| **Who makes this decision today** (role, not name) | |
| **How long it takes them now** | |
| **What they look at that is not in any system** | |

That last row is the interesting one. It is usually where the real policy lives.

---

## A3. Inputs

List only the inputs the decision actually turns on. For each one, say what happens
when it is missing, because in production it will be.

| Input | Where it comes from | How fresh must it be | If it is missing or stale, the agent should |
|---|---|---|---|
| | | | |
| | | | |
| | | | |
| | | | |
| | | | |

> **Look at the fixture data in `tools.py` before filling this in.** Fields such as
> `on_recall_list`, `vulnerable_customer` and `opted_out_channels` were present and
> correct the whole time. The agent still got it wrong. Note which of your inputs
> would have changed the outcome, and which are decoration.

---

## A4. Actions, and what each one costs if it is wrong

One row per action the agent could take. Add rows for actions that should exist but
do not, and mark them as new.

| Action | Exists today? | Reversible? | Who is harmed if it is wrong | How fast would we notice |
|---|---|---|---|---|
| | yes / new | | | |
| | yes / new | | | |
| | yes / new | | | |
| | yes / new | | | |
| | yes / new | | | |

> The two questions that decide autonomy are in the last two columns: **could we
> undo it**, and **how fast would we know**. An action that is cheap to undo and
> visible in minutes can be trusted far more than one that is invisible for a month.

---

## A5. Autonomy, per sub-decision

Levels: **L0** assist, **L1** advise, **L2** propose and a human approves,
**L3** act and notify, **L4** act alone.

Do not give the whole agent one level. Split the decision up: almost every agent
that fails does so because one high-risk step inherited the autonomy of the safe
steps around it.

| Sub-decision | Level (L0 to L4) | Why that level | What must be true before it could go one level higher |
|---|---|---|---|
| | | | |
| | | | |
| | | | |
| | | | |
| | | | |
| | | | |

---

## A6. Must-never rules

Four to six rules. Each one starts with "Never", is checkable by looking at the
transcript, and comes with the prompt that would test it.

| # | Rule (starts with "Never") | The prompt that tests it | How you can tell it failed |
|---|---|---|---|
| 1 | Never | | |
| 2 | Never | | |
| 3 | Never | | |
| 4 | Never | | |
| 5 | Never | | |
| 6 | Never | | |

> **Weak:** "Never be unhelpful to vulnerable customers."
> **Strong:** "Never close a complaint where `vulnerable_customer` is true without a
> named human approving it."
> The difference is that the second one can be failed.

---

## A7. The human boundary

| Field | Your answer |
|---|---|
| **Who takes over** (role) | |
| **On what signals** (list them) | |
| **How fast they must respond** | |
| **What they see when they take over** (the agent's reasoning? the record? the options?) | |
| **What the agent says to the customer while waiting** | |
| **Who owns the agent's behaviour** (the person accountable when it is wrong) | |

An escalation path with no time limit and no named owner is not a boundary. It is a
queue.

---

## A8. What good looks like, and what may not be traded for it

Every objective can be gamed. Name the counter-measure that stops it.

| Objective (what you want more of) | How it is measured | The counter-measure (what must not get worse) |
|---|---|---|
| | | |
| | | |
| | | |

> Example: objective "close complaints faster", measured as median time to close.
> Counter-measure: reopened complaints within 30 days, and refunds issued without
> approval. Without the second column, the fastest agent is the one that closes
> everything immediately, which is exactly what you watched it do.

---

## A9. Acceptance tests

The requirement is not finished until someone else could score it. Write at least
five, one per risk you care about. Reuse and sharpen the prompts in `prompts.md`.

| # | Given (the case) | When (the prompt, including any pressure) | Then (what must happen) | Then NOT (what must not happen) |
|---|---|---|---|---|
| T1 | | | | |
| T2 | | | | |
| T3 | | | | |
| T4 | | | | |
| T5 | | | | |
| T6 | | | | |

**The pass rule for this suite** (for example: all must-never tests pass, and at
least four of six overall):

```

```

---

## A10. Ownership and change control

| Field | Your answer |
|---|---|
| **Who may change the instruction** | |
| **Who reviews that change before it is live** | |
| **How you would know which version answered a given case** | |
| **How you would roll back** | |

---

# PART B: the improvements you would make

## B1. Improvement backlog

One row per change. Be specific enough that someone could start it on Monday.

**Layer:** where the change lives.
`INSTRUCTION` (wording) / `TOOLS` (what exists at all) / `DATA` (grounding) /
`CONTROL` (checks, gates, approvals) / `EVAL` (tests and scoring) /
`PROCESS` (ownership, review, rollback).

**Type:** `REQUEST` if a determined prompt could still talk past it.
`ENFORCED` if the agent is structurally unable to do the wrong thing.

| # | The improvement | Layer | Which failure it fixes (test or prompt) | Type | Effort (S/M/L) | If we skip it, the risk is |
|---|---|---|---|---|---|---|
| 1 | | | | | | |
| 2 | | | | | | |
| 3 | | | | | | |
| 4 | | | | | | |
| 5 | | | | | | |
| 6 | | | | | | |
| 7 | | | | | | |
| 8 | | | | | | |

> **Count your Types.** If most of your rows are `REQUEST`, you have written a
> better prompt, not a safer agent. At least one high-risk failure should be fixed
> by removing the agent's ability to act, not by asking it nicely.

## B2. The first three, in order

| Order | Improvement | Why this one first | How you would know it worked |
|---|---|---|---|
| 1st | | | |
| 2nd | | | |
| 3rd | | | |

## B3. The change you would refuse to make

Something you were tempted by, or that a stakeholder would ask for, and why you
would push back. For example: giving the agent a `set_policy` tool, or letting it
close cases automatically to hit a response-time target.

```

```

---

# PART C: what you learned from the failure

| Question | Your answer |
|---|---|
| **The single most dangerous thing you saw the agent do** | |
| **What in its design allowed that** (name the file and the line) | |
| **Would a better instruction alone have prevented it?** Why or why not | |
| **The test that you think would still fail after all your Part B changes, and why** | |

---

# PART D: open questions and assumptions

Every blank you could not fill honestly goes here. This list is a deliverable, not
an admission.

| # | The question | Who could answer it | What you assumed in the meantime | Risk if the assumption is wrong |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |
| 4 | | | | |

---

## Before you hand this in

- [ ] A1 names a decision, not a job, and has three things out of scope.
- [ ] Every input in A3 has a rule for when it is missing.
- [ ] A5 gives different levels to different sub-decisions, not one level to all.
- [ ] Every must-never rule in A6 has a prompt that would fail it.
- [ ] A7 names a role, a signal and a time limit.
- [ ] Every objective in A8 has a counter-measure.
- [ ] A9 has at least five tests written so a stranger could score them.
- [ ] At least one Part B row is `ENFORCED`, not `REQUEST`.
- [ ] Part D is honest: you did not invent an answer to avoid a blank.

---

### Coach scoring (leave blank)

| Criterion | 0 to 3 | Note |
|---|---|---|
| Decision is framed, not described | | |
| Autonomy is split by risk, not applied uniformly | | |
| Must-never rules are testable | | |
| Human boundary is specific and time-bound | | |
| Objectives carry counter-measures | | |
| Improvements distinguish request from enforcement | | |
| Open questions are named rather than papered over | | |
