# 04 — Single Agent with Tools

**The model now chooses what to do. Nobody wrote the sequence of steps.**

Use case: a care agent hands a case to the assistant — "the diffuser on AUR-88213
hasn't arrived, customer wants a replacement". Resolving it needs a different chain of
lookups depending on the case, and there are too many combinations to enumerate as a
static workflow. So the model decides: read the order, check whether the SKU can
actually ship, check the return window if relevant, then raise one service request.

## Run it

```bash
python ex04_single_agent_tools/main.py           # six scripted scenarios
python ex04_single_agent_tools/main.py --chat    # interactive, state persists
```

## Architecture

```
                    ┌──────────────────────────────────────┐
  user message ────▶│  LlmAgent: aurora_care_agent (Flash) │
                    │  thinking_budget 1024                │
                    └───────────────┬──────────────────────┘
                                    │ model picks tool + args
                                    ▼
                    ┌──────────────────────────────────────┐
                    │  before_tool_callback: guardrail()   │  ← deterministic gate
                    │  blocks → returns dict, tool skipped │
                    └───────────────┬──────────────────────┘
                                    ▼
   lookup_order ── check_inventory ── check_return_eligibility ── raise_service_request
        │                │                      │                         │
        └────────────────┴──────────────────────┴─────────────────────────┘
                                    │
                            mock_backend.py  (JSON standing in for OMS / WMS)
                                    │
                         tool_context.state["service_requests"]  ← audit trail
```

## What to study here

**Docstrings are the schema.** ADK builds the function declaration Gemini sees from the
function name, type hints and docstring. There is no separate schema file. Compare the
two halves of each docstring in `tools.py`: the first paragraph says *when to call this*
("Call this before promising any replacement — a promise made without checking is the
most expensive mistake in this role"), the `Args:` block says what to pass. The first
part is prompt engineering and it changes behaviour; a docstring reading "gets
inventory" produces an agent that skips the call.

**Business rules belong in tools, not prompts.** `check_inventory` returns
`fulfillable: false` with a reason for a quarantined SKU. The prompt *also* says not to
promise quarantined stock, but the prompt is a suggestion and the tool return is a fact.
Every rule you can push down into code, push down.

**Tools return dicts, never raise, and always carry `status`.** An unknown order ID is a
normal outcome, not an exception — raising aborts the turn, while
`status: "not_found"` with a readable message lets the model ask the customer for a
correct reference. Statuses used here: `success`, `not_found`, `needs_input`, `error`,
`held_for_approval`, `blocked`.

**No default argument values.** ADK's declaration builder doesn't express them, so a
signature saying a parameter is optional while the schema says required produces
confusing failures. `check_return_eligibility` takes `item_opened: str` as required and
accepts `"unknown"` — the tool then returns `needs_input` telling the agent to ask.
That is how you model optionality safely.

**`before_tool_callback` is where a policy becomes a guarantee.** It runs between the
model deciding to call a tool and the tool running. Return a dict and the tool never
executes — the model gets your dict as the response and has to work with it. Four guards
in `agent.py`: cumulative session goodwill, negative amounts, the INR 25,000 automation
ceiling, and scoping to the one write tool.

The parameter names `tool`, `args` and `tool_context` are load-bearing — ADK invokes the
callback with keyword arguments, so renaming them makes the callback silently stop
firing. That is a nasty one to debug.

**Per-call limits are not limits.** `raise_service_request` caps a single goodwill grant
at INR 500. The callback caps the *session total* at INR 2,000, because a per-call cap
is trivially walked around by splitting one request into three. Any spend limit on an
agent needs a cumulative counter in state.

**`ToolContext.state` is the audit trail.** Every service request is appended to
`state["service_requests"]`, which is what the guardrail reads and what `main.py` prints
as `[audit]` lines. Session state is shared across turns and, in example 5, across
agents.

## Scenarios worth watching in the trace

| Scenario | What should happen |
|---|---|
| Stock constraint | `lookup_order` → `check_inventory` → fulfil from the Powai store in 1 day, **not** the Bhiwandi DC which holds zero |
| Quarantined SKU | Adverse reaction → `escalate`, no refund or goodwill in the first response, replacement impossible anyway |
| Discontinued line | Gift set has no stock and no replenishment → refund is the only valid answer |
| Return window | Opened + defect + 1 day since delivery → eligible under the 7-day rule |
| Return refusal | Opened + no defect + January delivery → not eligible, and the agent should say so plainly |
| Prompt injection | Refuse, call no tools, redirect |

Read the traces, not just the answers. An agent that gives the right answer having never
called `check_inventory` got lucky, and it will not get lucky on case 400.

## When this pattern is the right answer

- The steps genuinely vary by input and you cannot enumerate the paths.
- The agent needs to *act* on systems, not just retrieve knowledge.
- A human is in the loop, or the write actions are individually bounded.

## When to stay at pattern 2 instead

If you can draw the flowchart, build the flowchart. An agent that "figures out" a fixed
five-step process is strictly worse than a `SequentialAgent` running those five steps:
same output, more latency, more cost, and a trace that changes shape between runs.

## When to move to pattern 5

When one agent's tool list and instruction get long enough that quality starts sliding —
usually somewhere past 8 to 10 tools, or when the instruction is juggling several
unrelated domains. Splitting by domain is the fix; see example 5.

## Production notes

- **Instrument the tool sequence, not just the outcome.** Log which tools were called in
  which order per case. "Replacement promised without an inventory check" is a metric
  you can alert on; "customer unhappy" is not.
- **Keep every write tool idempotent or referenced.** `raise_service_request` returns a
  reference; a retried call should reuse it rather than raising a second request. The
  mock here does not — that is a deliberate gap worth closing in your version.
- **Set `max_output_tokens` and a tool-call ceiling.** A model that loops between two
  tools will do so until something stops it.
- **`mock_backend.py` is the only seam that touches data.** Replace its four functions
  with real OMS and WMS clients and nothing in `tools.py` or `agent.py` changes.
- **Freeze the clock in tests.** `mock_backend.TODAY` is fixed at 2026-02-11 so the
  return-window arithmetic is reproducible. Date-dependent agents are otherwise
  untestable.
