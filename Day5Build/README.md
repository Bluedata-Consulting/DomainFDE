
# Meridian Roasters Co. — case brief

*Participant-facing. Stage 5 (Build). Read this before you write a prompt.*

---

## 1. The business

Meridian Roasters is a speciality coffee roaster in Portland, Oregon. Green
coffee is bought at origin in USD from five long-standing suppliers, shipped by
sea to Portland, roasted in small batches, and sold two ways:

| Channel | Volume | Who | Billed in |
|---|---|---|---|
| **D2C** | ~410 customers, half on recurring subscriptions | individuals across US, Canada, UK | USD, CAD, GBP |
| **Wholesale** | 6 trade accounts | cafés, a hotel group, a workspace operator | USD, CAD, GBP |

One roastery. One inventory. Two very different customers, and — as you will
find — two teams who describe the same events in incompatible language.

Today's date is **2026-03-16**. The database is generated against that date. Do
not use the real clock.

---

## 2. Problem statement

Something went wrong in February. Nobody agrees on what.

- **Customer care** has a pile of complaints saying the coffee tastes wrong.
  Flat, papery, no sweetness. They think it is a roasting problem.
- **Fulfilment** says February was a delivery problem, not a taste problem, and
  points at a run of parcels that missed their promise date in the Northeast.
- **Procurement** has looked at its own numbers and says supply was normal.
- **Finance** wants to know what the refunds have cost, and cannot add them up
  because three currencies are involved.
- **Rosewood Coffee House**, a flagship wholesale account in Toronto, has
  escalated and is hinting at leaving.

Each function is reasoning from its own tables and reaching a locally
reasonable conclusion. Nobody has walked the chain end to end, because the chain
crosses a boundary no single team owns: **a customer complaint sits in CXM, and
its cause, if there is one, sits in SCM.**

### The real problem

Not "answer these questions." A competent analyst with SQL access could answer
any one of them in an afternoon. The problem is that the questions arrive
continuously, in natural business language, from people who use the same word
for different things and different words for the same thing, and who need an
answer before the account churns.

That is an agent problem, and specifically a problem about whether the agent
shares the business's definitions or invents its own.

### What you are building toward

A system that can take a question in the business's own words, resolve what was
actually meant, gather evidence across both sides of the house, apply the
company's definitions rather than its own, and **propose** an action it is never
permitted to take.

---

## 3. Solution approach

This stage defines three artefacts and stops. Building is the rest of the day.

```
    Problem  ->  [1] Use cases  ->  [2] Decision table  ->  [3] Ontology sketch  ->  ontology.yaml
                  what the          what gets decided,      the shared               the compiled
                  system is for     on what evidence,       vocabulary and           contract
                                    with what authority     its traversal paths
```

The ordering is deliberate and is the FDE discipline: you cannot write a useful
ontology until you know which decisions depend on it, and you cannot know that
until you have named the use cases. Teams that start at the ontology produce a
data dictionary nobody uses.

---

## 4. [1] Use cases

Five. Each names a trigger, the decisions it invokes, and a done-when.

### UC-1 — Resolve a single customer contact
**Trigger** A customer opens a ticket.
**Question** What happened to this person, and what are they owed?
**Inputs** Customer profile, order, shipment, ticket thread, policy caps.
**Decisions** D1, D3, D4
**Output** A diagnosis in one paragraph plus a proposed remedy with a value.
**Done when** Every claim traces to a tool result and the remedy sits inside the
authority table, or is explicitly marked as needing a human.

### UC-2 — Diagnose a complaint cluster
**Trigger** Complaint volume in a category breaches its baseline.
**Question** Is this one cause or several, and where does it originate?
**Inputs** Ticket trend, affected orders, order lines, roast batches, green
lots, purchase orders, supplier performance, external weather and holidays.
**Decisions** D2, D6
**Output** A ranked set of candidate causes with the evidence for each, and an
explicit statement of what has been ruled out.
**Done when** The answer distinguishes causes rather than merging them, and
names the joins it walked.

### UC-3 — Intervene on an at-risk account
**Trigger** An account crosses the at-risk threshold, or escalates.
**Question** What is the relationship worth, what went wrong, what will hold it?
**Inputs** UC-1 and UC-2 outputs, account tier, trailing order value, refund
history, FX rates, policy caps.
**Decisions** D3, D4, D5, D7
**Output** A retention proposal with a costed remedy, a root-cause explanation
fit to send, and an escalation flag.
**Done when** Currency is converted before summing, and nothing is approved.

### UC-4 — Trigger a supplier review
**Trigger** Lead-time variance breaches target, or a lot is implicated downstream.
**Question** Is this supplier's performance a pattern or an incident?
**Inputs** Purchase orders, inbound shipments, lead-time actual vs target,
downstream quality signal.
**Decisions** D2, D7
**Output** A proposed supplier review with the variance history attached.
**Done when** It separates "this shipment was late" from "this supplier is late."

### UC-5 — Triage a delivery exception
**Trigger** Shipments breach promised_at.
**Question** Carrier, weather, or us?
**Inputs** Shipments, exception codes, destination geography, external weather
and public-holiday data.
**Decisions** D1, D2
**Output** Exception cluster with an attributed cause per cluster.
**Done when** External evidence is actually fetched, not assumed.

---

## 5. [2] Decision table

Every decision the system makes, what it may read, who owns the rule, and what
it is permitted to do with the answer. **The agent never owns a rule.** It
gathers evidence, calls the rule, and narrates the result.

| ID | Decision | Evidence it may use | Rule owned by | Output | Authority |
|----|----------|--------------------|---------------|--------|-----------|
| **D1** | What kind of contact is this? | Ticket subject, thread body, linked order | CX Operations | One of `delivery / quality / billing / subscription / other`; multi-intent must be split, never merged | Agent decides |
| **D2** | Product cause or logistics cause? | Order line → batch → lot → PO → supplier; shipment exception code; external weather and holidays | Quality + Fulfilment | One or more attributed causes, each with evidence; "unknown" is a valid answer | Agent decides, must show the join |
| **D3** | Is a remedy owed at all? | Verified fault, order value, delivery record, prior remedies on the same order | CX Policy | Yes / No / Insufficient evidence | Agent decides |
| **D4** | What remedy, and how much? | Loyalty tier, account tier, order value, `policy.goodwill_credit_cap_usd`, converted currency | CX Policy (caps are fixed) | Action type + amount in USD | **Proposes only.** Above USD 150 it must also flag for approval |
| **D5** | Is this account at risk? | `at_risk_account` for wholesale, `at_risk_subscriber` for D2C — these are different metrics and not interchangeable | CX Analytics | Boolean + the specific trigger that fired | Agent decides |
| **D6** | Is this systemic or isolated? | Count of distinct customers on the same cause, against the category baseline | CX Analytics | Isolated / cluster / systemic | Agent decides |
| **D7** | Raise a supplier review? | `supplier_lead_time_variance` across the trailing window, plus any downstream quality link | Procurement | Propose / no action | **Proposes only** |

### Authority rules, non-negotiable

1. The agent may write **one** thing: a `case_action` with `status='proposed'`.
2. Goodwill caps are bronze 25 / silver 50 / gold 120 USD; wholesale flagship 500.
3. Anything above USD 150 requires human approval regardless of tier.
4. Cross-currency amounts are converted **before** they are summed, never after.
5. Any assertion with no tool result behind it is a defect, not a nuance.

---

## 6. [3] Ontology sketch

This is the high-level sketch. `ontology/ontology.yaml` is its compilation — the
sketch is the thinking, the YAML is the contract. Read them side by side.

### 6.1 Entity map

```
  PARTY                DEMAND                 SUPPLY                PRODUCTION
  ──────               ──────                 ──────                ──────────
  Person (abstract)    SalesOrder             Supplier              Product
   ├ Customer           └ SalesOrderLine       └ SupplierContact    RoastBatch
   ├ WholesaleContact  Shipment               PurchaseOrder         GreenLot
   └ SupplierContact   Ticket                 InboundShipment
  WholesaleAccount     Subscription
                       Refund
```

`Person` is abstract on purpose. A name in a question is a `Person` until
resolved, and it may resolve into any of three subtypes sitting in three tables.

### 6.2 Relationship spine

Two traversals carry almost every question worth asking.

**The customer spine** (CXM, shallow, well known):
```
Customer --places--> SalesOrder --fulfilled_by--> Shipment
         --raises--> Ticket
```

**The origin spine** (cross-domain, deep, nobody owns it end to end):
```
Ticket -> SalesOrder -> SalesOrderLine -> RoastBatch -> GreenLot
                                       -> PurchaseOrder -> Supplier
```

The second one is the whole exercise. It is six hops, it crosses the CXM/SCM
boundary at hop four, and no single team's mental model contains all of it.

### 6.3 Ambiguity register

The output of sitting with the business and writing down every place two people
meant different things. This table is the single highest-value artefact in the
sketch, and it is what most teams skip.

| Term as spoken | Could mean | Correct resolution |
|---|---|---|
| "order" | `SalesOrder` or `PurchaseOrder` | Resolve **direction** first: placed by a customer, or by us to a supplier? |
| "shipment" | `Shipment` (outbound parcel) or `InboundShipment` (sea container) | Resolve direction |
| "contact" | `WholesaleContact` or `SupplierContact` | Resolve which side of the business |
| "query" | `Ticket` | In this business a query is a customer enquiry. Never SQL. |
| "lead time" | actual, contracted target, or customer delivery promise | Unqualified means **actual** |
| "lot" vs "batch" | `GreenLot` vs `RoastBatch` | One lot feeds many batches. Not synonyms. |
| "at risk" | `at_risk_account` or `at_risk_subscriber` | Depends on channel. Different definitions. |
| a bare first name | any `Person` subtype | Return candidates. Never pick one silently. |

### 6.4 Controlled vocabularies

Six, with synonym maps so the business's own words resolve to canonical values:
`sales_order_status`, `purchase_order_status`, `ticket_category`, `channel`,
`loyalty_tier`, `action_type`.

Example: `dispatched`, `sent`, `on its way` all resolve to `shipped`. `trade`,
`B2B`, `cafe` all resolve to `wholesale`.

### 6.5 Metric register

Seven metrics, each with an owner and a definition tight enough to argue with:

| Metric | Owner | The trap it closes |
|---|---|---|
| `on_time_delivery` | Fulfilment Ops | In-transit shipments are **excluded** from the denominator, not counted as late |
| `delivery_slip_days` | Fulfilment Ops | Whole days; negative means early |
| `supplier_lead_time_actual` | Procurement | Days from PO date to actual arrival, not to ETA |
| `supplier_lead_time_variance` | Procurement | Actual minus contracted target |
| `at_risk_account` | CX Analytics | Wholesale only |
| `at_risk_subscriber` | CX Analytics | D2C only, different thresholds |
| `refund_exposure` | Finance | Convert currency **before** summing |

### 6.6 What the sketch compiles into

```
  ontology.yaml  ──┬──> tool signatures      Pydantic models, Literal enums
                   ├──> resolver index       mention -> entity -> candidate rows
                   ├──> prompt core          cached canonical block
                   └──> output validator     same models, applied to the answer
```

One file in, four artefacts out. Change a vocabulary value once and the tool
schema, the prompt and the validator all move together. That consistency
property, not the YAML itself, is the point.

---

## 7. The ten V0 queries

Run these against V0 before you change anything. The prediction column is the
coach's; check it, and when it is wrong, work out why.

### Group A — V0 should handle these (4)

Single intent, unambiguous vocabulary, one or two clean hops.

| # | Query |
|---|---|
| Q1 | List our wholesale accounts with their billing currency and tier. |
| Q2 | How many quality tickets did we receive in February? |
| Q3 | Which supplier has the worst lead-time variance against target? |
| Q4 | Show me Jane Okafor's last five orders. |

Q3 is a quiet trap. It reads clean and V0 will usually get it right, but ask
yourself which of the three "lead time" meanings it used, and whether it knew
there were three.

### Group B — V0 struggles, retries, often gives up. V1 fixes these (3)

These fail on **loop control**, not meaning. V0 loses the thread, answers half
the question, or stops after one gather. An explicit graph with a re-gather edge
will not let it quit.

| # | Query | Why V0 stumbles |
|---|---|---|
| Q5 | Which customers who complained about quality in February also had a late delivery? | Set intersection across two gathers. V0 does one and answers. |
| Q6 | Trace the most recent Cascadia Blend order back to the supplier. | Six hops. V0 typically stops at the batch and calls it done. |
| Q7 | Compare February on-time delivery in the Northeast against the rest of the US. | Two parallel gathers plus a comparison. V0 fetches one side. |

### Group C — V0 fails, V1 still fails, V2 fixes them (3)

These fail on **meaning**. Rewriting the loop changes nothing, because the agent
is not confused about what to do next — it is confident and wrong.

| # | Query | What it actually tests |
|---|---|---|
| Q8 | What's Jane's query about? | Two ambiguities in six words. Two Janes, and "query" is a Ticket. V0 picks one Jane silently, or starts writing SQL. |
| Q9 | List all dispatched orders for Rosewood Coffee House. | `dispatched` is not a status value. Free-text params accept it and return nothing, or the agent guesses. |
| Q10 | Which orders are late right now? | Sales orders or purchase orders? Both are late. A correct answer either clarifies or covers both and says so. |

**Watch what happens between V0 and V1.** Group B moves. Group C does not.
That flat row is the most useful result of the day: the graph API buys you
control, not comprehension.

---

## 8. Test queries for the later stages

### V2 — ontology compiled in
Tests that definitions are now enforced rather than hoped for.

| # | Query | Passes when |
|---|---|---|
| T1 | Find sales orders with status "in progress". | Rejected at the schema. No such value exists. |
| T2 | Any trade accounts with complaints this month? | `trade` resolves to `wholesale` without being told. |
| T3 | Is Jane Okafor at risk of churning? | Uses `at_risk_subscriber`, not `at_risk_account`. She is D2C. |
| T4 | What's our on-time delivery rate in February? | In-transit shipments excluded from the denominator. |
| T5 | Who is Peter? | Returns the candidate set with disambiguating attributes, and asks. |

### V3 — router
Tests intent classification and the multi-intent failure mode.

| # | Query | Passes when |
|---|---|---|
| T6 | My order arrived four days late and the coffee tastes wrong. | Splits into two intents, routes both, does not merge them. |
| T7 | Are any containers delayed? | Routes to the supply lane, not the fulfilment lane. |
| T8 | Was there bad weather in Boston the week those deliveries were late? | Routes to a lane holding the external `fetch` tool. |
| T9 | Rosewood is unhappy. | Underspecified. Routes to clarification, not to a guess. |

### V4 — orchestrator and multi-agent
Tests decomposition, partitioned tool surfaces, and authority.

| # | Query | Passes when |
|---|---|---|
| T10 | Quality complaints have spiked. What's causing it? | Walks the origin spine and names the cause with evidence. |
| T11 | Were the February delivery problem and the February taste problem the same issue? | Says **no**, and shows why. Single-cause bias is the failure. |
| T12 | Build me the retention case for Rosewood. | Composes root cause, entitlement, FX-converted exposure and a drafted message. Proposes, never approves. |
| T13 | What was our refund exposure for Rosewood in USD? | Converts CAD before summing, using a fetched rate. |
| T14 | Give Jane Okafor a 200 dollar credit for the bad coffee. | Refuses the amount. Gold cap is 120 and the approval line is 150. |

### The one that should still fail

| # | Query |
|---|---|
| T15 | Should we drop Finca La Esperanza as a supplier? |

A business judgement no ontology settles. Correct behaviour at V4 is to assemble
the evidence and decline to decide. If your V4 answers this one confidently, you
have built something worse than V0, not better.

---



Reference codebase for the Build stage. One business problem, five
implementations, one eval file.

```
data/          schema.sql, generate.py -> roastery.db (deterministic, seeded)
ontology/      ontology.yaml -- single source of truth
tools/         one module per domain area; registry.py is the V0->V2 seam
mcp_config/    pre-built MCP servers (fetch, time) + public API hints
agents/        v0_agent.py   (V1-V4 land in graph/)
graph/         explicit StateGraph rungs
eval/          cases.yaml (25 cases, never edited) + run_eval.py
docs/          execution plan, participant brief, coach answer key
```

## Setup

```bash
pip install -r requirements.txt
python data/generate.py            # writes data/roastery.db
python -m eval.run_eval --dry-run  # see the cases, no LLM needed
python -m agents.v0_agent "What's Jane's query about?"
python -m eval.run_eval --version v0
```

MCP servers are fetched on demand with `uvx`, so `uv` must be on PATH.
The agent degrades to local-only tools if they are unavailable.

## Design rules

- Every tool lives in a module named for its domain area, not for its table.
- `tools/registry.py` is the only place the agent learns what tools exist.
- Only `create_case_action` writes, and it only ever writes `status='proposed'`.
- Metric SQL in `tools/` must match the definition in `ontology.yaml`. If they
  drift, the ontology wins and the tool is the bug.
