# 05 — Multi-Agent Supervisor

**One agent owns the question. Three specialists own the facts. The supervisor has
no data tools of its own.**

Use case: Aurora's supply chain control tower. "The festive promotion starts on 2 March
— can we supply the diffuser?" is not a demand question, an inventory question or a
logistics question. It is all three, and the answer only exists once someone compares
the date stock runs out against the date stock arrives. No specialist can make that
comparison. That is the supervisor's job.

## Run it

```bash
python ex05_multi_agent_supervisor/main.py           # five scenarios
python ex05_multi_agent_supervisor/main.py --chat
```

## Architecture

```
                       planner's question
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │  supply_chain_control_tower  (gemini-2.5-pro)│
        │  thinking_budget 4096 · NO data tools        │
        │  decompose → sequence → reconcile → cost     │
        └───────┬──────────────┬───────────────┬───────┘
                │ AgentTool    │ AgentTool     │ AgentTool
                ▼              ▼               ▼
      ┌─────────────────┐ ┌──────────────┐ ┌────────────────────┐
      │ demand_analyst  │ │ inventory_   │ │ logistics_         │
      │ (Flash, 512)    │ │ planner      │ │ coordinator        │
      ├─────────────────┤ ├──────────────┤ ├────────────────────┤
      │ get_sales_      │ │ get_stock_   │ │ get_open_shipments │
      │   velocity      │ │   position   │ │ get_supplier_      │
      │ get_promotions  │ │ compute_     │ │   performance      │
      │                 │ │   stock_cover│ │                    │
      └─────────────────┘ └──────────────┘ └────────────────────┘
                │                │                   │
                └────────────────┴───────────────────┘
                          data/*.json

  dependency: demand rate ──▶ inventory cover        (order matters)
  synthesis:  runs-out date vs arrives date          (only the supervisor can)
```

## What to study here

### AgentTool vs sub_agents — the decision that defines the pattern

ADK offers two delegation mechanisms and they are not interchangeable:

| | `sub_agents=[...]` | `AgentTool(agent=...)` |
|---|---|---|
| What moves | **Control** transfers to the sub-agent | Only a **call** — control never leaves |
| Who talks to the user | The sub-agent, in its own voice | Always the supervisor |
| Result goes to | The user | The supervisor, as a tool response |
| Good for | Triage routing — billing question → billing agent | Synthesis — combine several partial views |

This example uses `AgentTool` because the answer is a synthesis. Under transfer, the
demand analyst would answer the user directly and the conversation would end with two
thirds of the picture missing. Under AgentTool, the supervisor collects three partial
answers and does what none of them can.

**Rule of thumb: if the answer is a synthesis, AgentTool. If the answer belongs to
whichever specialist you routed to, sub_agents.**

### `description` is routing metadata, not documentation

The supervisor picks a specialist by reading its `description`. So each one states what
it does *and what it does not*:

> "Demand specialist. Answers questions about sales velocity, demand trends, seasonality
> and planned promotions for a SKU. **Does NOT know stock levels, shipment status or
> supplier performance.**"

Without the negative half, the supervisor asks the demand analyst about stock, gets a
polite refusal, and burns a round trip — or worse, gets a guess.

### Specialists report; only the supervisor recommends

Every specialist instruction ends with a version of "never recommend a purchase order,
an expedite, or a promotion change". This is not politeness. A specialist that
recommends is optimising its own domain in isolation: the logistics coordinator will
always say air-freight it, because from where it sits the premium has no downside. Cost
and trade-off live at the supervisor, because that is the only place both sides of the
trade are visible.

### Ordering under a dependency

`compute_stock_cover` needs a daily demand rate. The supervisor must therefore ask the
demand analyst *first* and pass the resulting rate into its request to the planner.
Get the order wrong and you compute cover against baseline demand — which for the
diffuser is 41.5 units/day instead of the promotional 150, turning 0.7 days of cover
into 2.4 and hiding the entire problem.

This ordering is stated in the supervisor's instruction and is the main thing to watch
in scenario 3's trace.

### Specialists cannot see each other, or the user

Each `AgentTool` call carries only the text the supervisor writes. The specialist cannot
read the user's original message or another specialist's answer. That is why the
supervisor is told to write specific, self-contained requests: *"Compute cover for
AUR-DIFF-CER-01 at 150 units per day, the promotional rate"* works; *"check the stock"*
produces a useless answer.

### Model tiering pays for itself here

The supervisor runs Pro with a 4,096-token thinking budget because it is doing genuine
planning — decompose, sequence under a dependency, reconcile, cost. The three
specialists run Flash at 512 because each is a two-tool lookup with a formatting rule.
Running Pro across all four would roughly quadruple the cost of every question for no
improvement on three quarters of the work.

## The scenarios, and what a good run looks like

**1. Flagship — all three domains.** Diffuser at 68/day and accelerating (64% above
average), locked promotion at 2.2x uplift → ~150/day. Against 98 usable units that is
**0.7 days of cover**. PO-55210 has slipped 14 days to 6 March — four days *after* the
promotion opens. Supplier is at 58% on-time with a 44-day real lead time against a
35-day contract. Air freight is available at INR 310/unit; on 900 units that is
INR 279,000. The promotion is locked with INR 1.85m already committed. A good answer
escalates rather than recommending, because the choice is between an unbudgeted expedite
and pulling a campaign that has already been paid for.

**2. Single domain.** "When is PO-55210 going to land?" should use **exactly one**
specialist. Over-delegation is the characteristic failure mode of this pattern — a
supervisor that reflexively asks all three triples latency and cost on a question with
one owner.

**3. Dependency ordering.** Demand first, rate passed through, inventory second. Watch
for the rate appearing inside the second request in the trace.

**4. Quarantine.** 910 units on hand, zero available. Any answer that plans volume on
that stock is wrong, and the tool returns `available_units: 0` specifically so the model
cannot get this one wrong by accident.

**5. Attach effect.** Lavender oil attaches at 0.8 per diffuser, is already running at
143/day against a 96/day average, and has **zero on order**. The strong answer catches
this second-order risk unprompted; the weak one answers only about the diffuser.

## Reading the trace

```
  [  2.14s] ASK demand_analyst
            "Sales velocity and promotional uplift for AUR-DIFF-CER-01..."
  [  2.31s]     demand_analyst -> get_sales_velocity({"sku": "AUR-DIFF-CER-01"})
  [  3.02s] GOT demand_analyst: Current rate 68 units/day, 64% above the 8-week...
  [  3.988s] ASK inventory_planner
            "Compute cover for AUR-DIFF-CER-01 at 150 units/day, promotional rate"
```

Judge the delegation, not the prose. A well-written recommendation built on two
specialists when it needed three is a worse outcome than a clumsy one built on all
three, because you cannot see the missing domain in the output.

## When this pattern is the right answer

- The question genuinely spans domains that need different tools and different framing.
- A single agent's tool list has grown past roughly 8–10 tools and quality is sliding.
- Different parts of the problem warrant different models or different owners.
- Teams need to own their specialist independently — this is as much an org boundary as
  a technical one.

## When NOT to use it

**Most of the time.** This is the most expensive, slowest and least predictable pattern
in the repo, and it is the one people reach for first. Each specialist call is a full
LLM round trip, so a three-specialist answer costs four calls minimum.

Specific anti-patterns:

- **A fixed sequence of specialists.** If you always ask demand, then inventory, then
  logistics, that is a `SequentialAgent` — build example 2 and keep the determinism.
- **Splitting by data source rather than by reasoning domain.** An "orders agent" and a
  "customers agent" that are always called together are one agent with two tools.
- **Fewer than ~8 tools total.** Below that, one agent with good docstrings beats a
  supervisor, and debugs far more easily.

The honest test: could one agent with all six tools answer these five questions? For
this corpus it very nearly could. The supervisor earns its place once tool count grows
and the domains need genuinely different instructions — which is the situation this
example is sized to demonstrate, not to prove.

## Production notes

- **Cap the delegation depth and breadth.** Specialists here have no sub-agents of their
  own, deliberately. Nested supervisors produce traces nobody can follow.
- **Log the delegation graph per request.** Which specialists, in what order, with what
  request text. That is your debugging surface and your cost model.
- **Watch for the supervisor answering from its own head.** It has no data tools, so any
  number in its output that no specialist returned is a hallucination. This is
  automatically checkable: extract figures from the final answer and diff them against
  the tool responses in the trace.
- **Specialists share session state.** They cannot see each other's answers, but they can
  read and write `tool_context.state`. Useful for shared context, and a source of
  action-at-a-distance bugs if you overuse it.
- **Timeouts and partial answers.** If one specialist fails, decide deliberately whether
  the supervisor answers with two thirds of the picture, clearly labelled, or refuses.
  Silent partial answers are the worst option and the default one.
