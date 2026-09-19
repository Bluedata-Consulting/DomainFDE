# 02 — Static Workflow (Sequential + Parallel + Loop)

**The control flow is code. The model fills in the steps; it does not choose them.**

Use case: a delivery exception lands in Aurora Retail's fulfilment queue — a parcel
lost in transit, a damaged carton, a short shipment. Resolving one correctly means
checking policy, checking whether a replacement is physically possible, weighing the
customer relationship, deciding, then writing to the customer. Four stages, always the
same four, in the same order.

## Run it

```bash
python ex02_workflow_pipeline/main.py
python ex02_workflow_pipeline/main.py --case EXC-7704
```

## Architecture

```
raw ops payload
      │
      ▼
┌─ SequentialAgent: exception_resolution_pipeline ──────────────────────────┐
│                                                                           │
│  1. intake_agent (Flash)              payload ──▶ ExceptionCase           │
│                                                    state["case"]          │
│                                                                           │
│  2. ParallelAgent: assessment_fan_out      ← all three read state["case"] │
│       ├── policy_assessor    (Flash) ──▶ state["policy_assessment"]       │
│       ├── supply_assessor    (Flash) ──▶ state["supply_assessment"]       │
│       └── customer_assessor  (Flash) ──▶ state["customer_assessment"]     │
│                                                                           │
│  3. resolution_agent (Pro)   3 assessments ──▶ Resolution                 │
│                                                 state["resolution"]       │
│                                                                           │
│  4. LoopAgent: drafting_loop (max 3)                                      │
│       ├── comms_drafter  (Flash) ──▶ state["draft_reply"]                 │
│       └── comms_reviewer (Flash) ──▶ exit_loop() or state["review_feedback"]│
└───────────────────────────────────────────────────────────────────────────┘
      │
      ▼
audited resolution + approved customer message
```

## What to study here

**State is the wiring.** `output_key` writes an agent's result into session state;
`{key}` in the next agent's instruction reads it back. That is the whole mechanism.
Trace the key `case` from `intake_agent`'s `output_key` into the three assessors'
instructions and the pattern is obvious — and it is the same mechanism you will use in
every ADK workflow you build.

**`{review_feedback?}` — the optional-injection gotcha.** On the loop's first pass that
key does not exist yet. A bare `{review_feedback}` raises `KeyError` and kills the run.
The trailing `?` makes ADK substitute an empty string instead. Every loop that feeds
critique backwards needs this, and it is the single most common cause of a
first-iteration crash in ADK pipelines.

**Why those three assessors are parallel.** They are independent: none reads another's
output. That is the test for `ParallelAgent`, not "these feel unrelated". They share one
session state, so distinct `output_key`s are mandatory — two parallel children writing
the same key is a race you will lose intermittently.

**Why the loop is bounded.** `max_iterations=3`. A reviewer with strict rules and a
drafter with a 130-word ceiling can disagree forever. The loop exits on `exit_loop()`
or on the third pass, whichever comes first, and `main.py` prints the reviewer's last
objection when the loop ran out — so a persistent failure is visible instead of silent.

**Model tiering.** Four of the six LLM nodes run Flash with thinking disabled. Only
`resolution_agent` runs Pro with a 2,048-token thinking budget, because it is the one
node trading off three competing inputs under a rule hierarchy. Running Pro on all six
would cost roughly ten times as much for no better answer on five of them.

**Separation of judgement from voice.** Stage 3 decides; stage 4 writes. Keeping them
apart means the reviewer can check the message against the decision as an independent
artefact. An agent that decides and writes in one breath has nothing to check against.

## Deliberate test cases

- `EXC-7701` — diffuser lost in transit, but the supply desk has zero DC stock and only
  four units in one Mumbai store. The resolution must not promise a DC replacement.
  Customer is Platinum with a prior failure, so goodwill should land at the higher tier.
- `EXC-7702` — damaged on arrival with photographs inside 48 hours. Clean path: policy
  entitles replacement, stock is healthy. This is the boring case, and it should be
  boring.
- `EXC-7703` — Malaysian order returned for an incomplete address, seasonal SKU with no
  replenishment. Replacement is impossible, so the action has to be a refund.
- `EXC-7704` — allergic reaction, quarantined SKU, public complaint. Rule 5 should force
  `escalate_to_human` regardless of what the other desks say.

## When this pattern is the right answer

- The steps are known in advance and do not vary by input.
- You need the same audit trail on every run — regulated processes, financial decisions,
  anything a person might later have to justify.
- You want to evaluate and improve stages independently.
- Latency and cost need to be predictable.

**This is the pattern most enterprise use cases actually need.** A large share of
"we need an agent" requirements are a fixed process where the LLM's job is judgement
inside each step, not choosing the steps. Reaching for pattern 4 or 5 here buys
non-determinism you did not need and cannot debug.

## When to move on

- To pattern 3, when a stage needs knowledge too large or too fast-changing for a prompt.
- To pattern 4, when the steps genuinely vary by input and you cannot enumerate the paths.

## Production notes

- `ParallelAgent` reduces wall-clock time but not token spend — you still pay for three
  calls. Parallelise for latency, not cost.
- Persist the full state dict per case. `case`, the three assessments and `resolution`
  together are your audit record, and regulators ask for reasoning, not just outcomes.
- Add `before_agent_callback` on `resolution_agent` to hard-block automation above a
  value threshold. Prompt rule 5 is a strong instruction, not a guarantee; a callback is.
- Evaluate stage by stage. Label 50 cases with the correct `action` and score stage 3 in
  isolation, feeding it known-good assessments. Otherwise a stage-1 extraction bug looks
  like a stage-3 reasoning failure.
