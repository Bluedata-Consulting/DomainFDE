# 01 — Prompt-based GenAI Assistant

**One model call. No tools. No retrieval. Everything the agent knows is in the prompt.**

Use case: Aurora Retail's care desk receives a few thousand tickets a day. Each one
needs to be classified, prioritised, and answered. This agent turns a messy inbound
message into a validated `TicketTriage` object with a draft reply attached, which a
human agent reviews and sends.

## Run it

```bash
python ex01_prompt_assistant/main.py
python ex01_prompt_assistant/main.py --ticket TKT-40122
python ex01_prompt_assistant/main.py --text "where is my refund, returned it 12 days ago"
```

## Architecture

```
ticket text ──▶ LlmAgent (gemini-2.5-flash)
                  ├─ instruction: role, policy, constraints, field rules, few-shot
                  ├─ output_schema: TicketTriage  (constrained decoding)
                  └─ generate_content_config: temp 0.2, thinking off
                              │
                              ▼
                  validated TicketTriage object ──▶ human review
```

## What to study here

**`schemas.py` — the output contract.** This is the highest-leverage file in the
folder. Passing a Pydantic model as `output_schema` makes ADK hand Gemini a response
schema, so the model is constrained while decoding rather than merely instructed. The
practical effect: no "Sure! Here's the JSON:" preamble, no missing fields, no invented
enum values, and `model_validate_json` in `main.py` essentially always succeeds.

**`prompts.py` — prompt structure.** Six blocks in a fixed order: role, task, domain
knowledge, hard constraints, field rules, few-shot examples. The domain-knowledge block
exists because the model cannot know Aurora's returns window; the constraints block
exists because the expensive failure here is not misclassification, it is a confident
draft reply promising a refund date that turns out to be wrong.

**Grounding by prohibition.** With no tools, the agent cannot look anything up, so the
prompt forbids it from asserting anything it would need a lookup for. `policy_dependent`
makes that boundary explicit in the output, and `internal_note` tells the human exactly
what to verify. That is how you ship a useful assistant with zero system integration.

**Cost control.** `thinking_budget=0` turns off Flash's default reasoning pass. On a
rubric-driven classification task it changes nothing about accuracy and meaningfully
cuts latency and token spend — which matters when the thing runs on every ticket.

## Deliberate test cases in the sample data

- `TKT-40122` — allergic reaction plus a public complaint. Should come back P1 with a
  supervisor escalation in the internal note.
- `TKT-40124` — a prompt-injection attempt asking for card data. Constraint 5 should
  catch it; the draft should ask the customer to confirm the order ID and nothing else.
- `TKT-40125` — two issues in one message. Should push confidence down.
- `TKT-40119` — mentions a 14-year-old. Watch whether the draft stays factual about
  ingredients rather than giving medical advice.

## When this pattern is the right answer

- The task is a transform: input in, structured output out.
- All the knowledge needed fits in a prompt and changes slowly.
- A human reviews the output, or the downstream action is low-risk.
- You want a latency and cost floor.

## When to move to pattern 2

The moment you need more than one thing to happen in a fixed order — classify, then
check, then draft, then review. Cramming a four-stage process into one prompt is the
most common way these systems go bad: quality degrades on every stage at once and you
cannot tell which stage failed.

## Production notes

- Version prompts like code. `prompts.py` is a module, not a string in a notebook, so
  it diffs in review and you can pin which version produced which output.
- Log `confidence` and route anything below 0.6 to a human queue.
- Build a golden set of 50-100 labelled tickets before touching the prompt. Otherwise
  "improving" the prompt is unfalsifiable.
- Swap `InMemorySessionService` for `DatabaseSessionService` when you want turn history
  to survive a restart. Not needed here — this is stateless by design.
