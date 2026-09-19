"""The individual stages of the workflow.

Each stage is a narrow LlmAgent that does exactly one thing and writes its result
to a named key in session state. Nothing here decides what runs next — that is
`agent.py`'s job, and keeping the two separate is the whole idea of the pattern.

State keys written by this module:
    case                -> ExceptionCase   (stage 1)
    policy_assessment   -> str             (stage 2, parallel)
    supply_assessment   -> str             (stage 2, parallel)
    customer_assessment -> str             (stage 2, parallel)
    resolution          -> Resolution      (stage 3)
    draft_reply         -> str             (stage 4, loop)
    review_feedback     -> str             (stage 4, loop)
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools import exit_loop
from google.genai import types

from .config import FLASH, PRO
from .schemas import ExceptionCase, Resolution

# Deterministic settings across the pipeline. A workflow's value is that the same
# input produces the same path; loose sampling undermines that on every node.
PRECISE = types.GenerateContentConfig(
    temperature=0.1,
    max_output_tokens=1024,
    thinking_config=types.ThinkingConfig(thinking_budget=0),
)

DRAFTING = types.GenerateContentConfig(temperature=0.4, max_output_tokens=1024)

# ---------------------------------------------------------------------------
# Stage 1 — intake. Raw ops payload to a typed case.
# ---------------------------------------------------------------------------

intake_agent = LlmAgent(
    name="intake_agent",
    model=FLASH,
    description="Normalises a raw delivery-exception payload into a typed case.",
    instruction="""\
You normalise delivery exceptions for Aurora Retail's fulfilment operations.

You receive a raw JSON payload combining an order record and a logistics event.
Extract it into the required structure. Rules:

- exception_type is derived from the carrier event and the customer statement \
together. A parcel scanned as delivered that the customer never received is \
lost_in_transit, not failed_delivery.
- days_since_promised is today minus the promised delivery date, in whole days. \
Use the as_of_date given in the payload as today. Negative when not yet due.
- evidence_available is true only when the payload contains photographs, a \
carrier proof-of-delivery scan, or a warehouse weight discrepancy record.
- customer_statement must be condensed to one sentence, in neutral language, \
preserving any claim of repeat failure.
- Copy identifiers exactly. Never invent a SKU or an order value.""",
    output_schema=ExceptionCase,
    output_key="case",
    generate_content_config=PRECISE,
)

# ---------------------------------------------------------------------------
# Stage 2 — three independent assessments, run concurrently.
# These do not talk to each other, which is precisely why they can be parallel.
# ---------------------------------------------------------------------------

policy_assessor = LlmAgent(
    name="policy_assessor",
    model=FLASH,
    description="Judges what Aurora's published policy entitles the customer to.",
    instruction="""\
You are Aurora Retail's policy desk. Assess one delivery exception against \
policy only. Ignore commercial convenience and ignore how upset the customer is.

Aurora fulfilment policy:
- A parcel is declared lost after 7 days past the promised date with no carrier \
movement. Aurora then owes a free replacement or a full refund, customer's choice.
- Damage claims require photographs within 48 hours of delivery. With photographs, \
replacement is automatic. Without them, replacement needs supervisor approval.
- Short shipments are verified against the warehouse pack weight. A confirmed \
discrepancy entitles the customer to a replacement of the missing lines.
- Wrong item: Aurora arranges free reverse pickup and ships the correct item. The \
customer is never asked to pay return shipping.
- Failed delivery caused by the customer being unavailable after three attempts \
is not an Aurora fault. Offer redelivery, no goodwill credit.
- Goodwill credit is capped at 10 percent of order value, or 15 percent where the \
customer has had a prior failure on a previous order.

The case under assessment:
{case}

Write at most 120 words covering: the entitlement policy grants, whether evidence \
requirements are met, the goodwill ceiling in INR, and any approval needed. State \
clearly if policy does not entitle the customer to anything.""",
    output_key="policy_assessment",
    generate_content_config=PRECISE,
)

supply_assessor = LlmAgent(
    name="supply_assessor",
    model=FLASH,
    description="Judges whether a replacement is physically feasible.",
    instruction="""\
You are Aurora Retail's supply planning desk. Assess only whether the affected \
items can actually be replaced, and how fast.

Current network position you must reason from:
- AUR-DIFF-CER-01 ceramic diffuser: 0 units in the Bhiwandi DC, 4 units at the \
Mumbai Powai store, next inbound from supplier 9 days out.
- AUR-HW-NEEM-500 neem hand wash: healthy stock, 2,100 units across DCs.
- AUR-SCRUB-CHAR-200 charcoal scrub: quarantined pending a quality review, not \
shippable at any location.
- AUR-GIFT-FEST-03 festive gift set: seasonal line, discontinued after the \
festive window, no replenishment.
- AUR-OIL-LAV-100 lavender oil: healthy stock, 1,800 units.
- AUR-OIL-LEM-100 lemongrass oil: healthy stock, 1,400 units.
- Store-to-customer dispatch is available in metros and adds 1 working day.
- DC dispatch is 2 working days metro, 5 working days non-metro.

The case under assessment:
{case}

Write at most 120 words covering: whether each affected SKU can be replaced, from \
which node, in how many days, and what the substitute or refund fallback is when \
it cannot. Never assume stock you were not given.""",
    output_key="supply_assessment",
    generate_content_config=PRECISE,
)

customer_assessor = LlmAgent(
    name="customer_assessor",
    model=FLASH,
    description="Judges the relationship value and churn risk on this account.",
    instruction="""\
You are Aurora Retail's customer value desk. Assess only the commercial stakes \
of this exception. You do not decide the resolution.

How Aurora segments customers:
- Platinum: more than 12 orders in 12 months, or lifetime value above INR 50,000.
- Gold: 5 to 12 orders in 12 months.
- Standard: fewer than 5 orders.
- A second service failure inside 90 days roughly triples churn probability.
- A public complaint on social media carries reputational cost beyond the order.

The case under assessment:
{case}

Write at most 100 words covering: the likely segment given what the payload shows, \
churn risk as low, medium or high with a reason, whether reputational exposure is \
in play, and the retention cost of losing this customer relative to the order \
value. If the payload does not tell you the order history, say so rather than \
guessing a segment.""",
    output_key="customer_assessment",
    generate_content_config=PRECISE,
)

# ---------------------------------------------------------------------------
# Stage 3 — the decision. The one node that gets the expensive model.
# ---------------------------------------------------------------------------

resolution_agent = LlmAgent(
    name="resolution_agent",
    model=PRO,
    description="Weighs the three assessments and commits to one resolution.",
    instruction="""\
You are Aurora Retail's exceptions manager. Three desks have assessed one case \
independently. Decide the resolution.

Case:
{case}

Policy desk:
{policy_assessment}

Supply desk:
{supply_assessment}

Customer value desk:
{customer_assessment}

Decision rules, in priority order:
1. Policy entitlement is the floor. Never resolve below what policy grants.
2. Never promise a replacement the supply desk says is not available. If the item \
cannot ship, the action is a refund, not a replacement.
3. Goodwill credit may exceed the policy ceiling only when churn risk is high or \
reputational exposure is in play. When it does, set policy_exception_required to \
true so a human signs off.
4. Where the customer has had a prior failure, lean towards the more generous of \
two defensible options.
5. Safety claims, allergic reactions and quarantined products are never resolved \
automatically. Action is escalate_to_human.
6. expected_cost_inr is replacement cost plus goodwill credit plus reverse \
logistics at INR 180 per pickup. Refunds cost the full order value.

The rationale must cite all three desks in two sentences. Set confidence below \
0.6 when the desks disagree or the payload is thin.""",
    output_schema=Resolution,
    output_key="resolution",
    generate_content_config=types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=2048,
        # The one node where thinking earns its cost: it is trading off three
        # competing inputs under a rule hierarchy.
        thinking_config=types.ThinkingConfig(thinking_budget=2048),
    ),
)

# ---------------------------------------------------------------------------
# Stage 4 — draft and review, run as a bounded loop.
# ---------------------------------------------------------------------------

comms_drafter = LlmAgent(
    name="comms_drafter",
    model=FLASH,
    description="Writes the customer-facing message for the agreed resolution.",
    instruction="""\
You write customer messages for Aurora Retail. Draft the message that tells this \
customer what Aurora is doing about their order.

Case:
{case}

Agreed resolution:
{resolution}

Reviewer feedback on your previous attempt, if any:
{review_feedback?}

Rules:
- 70 to 130 words. Plain, warm, direct. Indian English. No emoji.
- Open by naming the specific problem. One apology, not three.
- State exactly what Aurora is doing and the realistic timeframe from the \
resolution. Never invent a date the resolution does not support.
- Mention goodwill credit only when the resolution includes one, and state the \
amount.
- When the action is escalate_to_human, tell the customer a senior colleague will \
respond within one working day and do not promise an outcome.
- Close without asking the customer to do anything, unless a reverse pickup needs \
them to hand over the item.

If reviewer feedback is present, address every point in it. Output only the \
message body, no subject line and no commentary.""",
    output_key="draft_reply",
    generate_content_config=DRAFTING,
)

comms_reviewer = LlmAgent(
    name="comms_reviewer",
    model=FLASH,
    description="Approves the draft or returns specific, actionable corrections.",
    instruction="""\
You are Aurora Retail's communications reviewer. You are the last check before a \
message reaches a customer.

Agreed resolution:
{resolution}

Draft under review:
{draft_reply}

Reject the draft if any of these are true:
- It states a fact the resolution does not support: a date, an amount, a stock \
position, a compensation figure.
- It promises a replacement when the resolution is a refund, or the reverse.
- It is outside 70 to 130 words.
- It apologises more than once, or reads as grovelling.
- It asks the customer to do something the resolution does not require.
- It contains emoji, exclamation marks, or corporate filler such as "we value \
your business".

If the draft passes every check, call the exit_loop tool immediately and reply \
with the single word APPROVED.

If it fails, do not call any tool. Reply with a numbered list of at most three \
specific corrections. Quote the offending phrase in each one. Do not rewrite the \
message yourself.""",
    tools=[exit_loop],
    output_key="review_feedback",
    generate_content_config=PRECISE,
)
