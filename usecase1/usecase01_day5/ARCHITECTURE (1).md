# Architecture of the Day 5 practice application

This document describes how the single complaints agent became a team: the shared package
every agent uses, the three specialists, the four patterns that put them to work, and how
each pattern is scored.

Read [`README.md`](README.md) first if you have not run the agents yet. The rules are
Day 2's, the recorder is Day 3's and the ontology is Day 4's. What is new today is how the
work is split, and who decides the next step.

---

## 1. In one paragraph

Everything the agents know and must obey lives in one shared package, `northwind/`: the
data and its meanings, the rules for three teams, nine tools, one guardrail and one
recorder. From it come three **specialists** (complaints, returns and billing), each with
its own instruction, exactly three tools, and the rules its team owns. Four agents put the
specialists to work in four patterns: a model-driven loop (A), the same loop drawn as a
graph (B), a graph router that sends each request to one team (C), and an orchestrator that
calls several specialists for one request (D). Seven eval cases, one or two per pattern,
score each one.

---

## 2. The idea in one picture

The question every pattern answers differently is: **who decides the next step?**

```
   A  v5a_loop_agent        the MODEL decides every step
      user -> [ complaints specialist: think -> tool -> read result -> think ... ] -> reply

   B  v5b_loop_graph        CODE decides every step; the model only writes
      user -> prepare -> drafter -> check -+-> send
                (code)    (model)   (code) +-> retry -> drafter
                                           +-> person

   C  v5c_router_graph      CODE decides the team; the model only when code is unsure
      user -> route_by_rules -+-> complaints | returns | billing specialist
                (code)        +-> unsure -> classifier (model) -> parse_route (code) -> ...

   D  v5d_orchestrator      the MODEL plans; the SPECIALISTS act, inside their own rules
      user -> coordinator -+-> billing_agent    (3 tools, billing rules)
                           +-> returns_agent    (3 tools, returns rules)
                           +-> complaints_agent (3 tools, complaints rules)
                           -> one combined answer
```

Moving from A to B, the model loses control of the order and keeps only the writing.
Moving from C to D, one request can reach several teams, but the model plans the route.

---

## 3. Context view

```
        YOU                       YOUR MACHINE                     GOOGLE CLOUD

  +-------------+  HTTP  +---------------------------------+ HTTPS +------------+
  |  ADK chat   |<------>|  adk web                        |<----->| Vertex AI  |
  |  page       |        |   v5a  v5b  v5c  v5d            |       | Gemini     |
  +-------------+        |     \    |    |    /            |       +------------+
                         |   northwind/ (shared package)   |
  +-------------+        |   data, rules, tools,           |
  |  Terminal   |<-------|   guardrail, recorder           |
  |  >>> lines  | stdout +---------------+-----------------+
  +-------------+                        |
                                         v
            ontology.yaml, data/northwind.json     read at start
            runs.jsonl, escalations.log            written while running
            baseline/baseline_v1.json              written by eval/run_eval.py

  One process. The graphs run inside ADK like any other agent. Only model calls
  leave the VM.
```

---

## 4. The shared package

`northwind/` sits next to `agents/`, not inside it, so it never appears in the drop-down.
Each agent adds the kit folder to Python's path and imports from it.

| Module | Responsibility | From |
|---|---|---|
| `data.py` | Loads `ontology.yaml` and the data. Follows links. Now also looks up returns | Day 4, extended |
| `rules.py` | The rules for all three teams, and the code router. Plain Python, no ADK | Day 2, extended |
| `tools.py` | Nine tools, three per team. Docstrings and `Literal` types carry the meanings | Day 4, split by team |
| `guardrail.py` | One `before_tool_callback` for every specialist. Picks the team's rules by tool name | Day 2, generalised |
| `recorder.py` | Writes every step to `runs.jsonl`, naming the agent | Day 3 |
| `specialists.py` | Factories that build each specialist: instruction, three tools, guardrail, recorder | New |
| `instructions/` | One instruction per specialist, plus the drafter, classifier and coordinator | New |

**Why factories.** ADK lets an agent belong to only one parent. The router and the
orchestrator each need their own complaints, returns and billing agents, so each builds
fresh copies from the same recipe. The copies behave identically because the recipe is
the same.

---

## 5. The three specialists

| Specialist | Tools | Rules, in order | Owner when a rule stops it |
|---|---|---|---|
| Complaints | `get_complaint`, `send_customer_message`, `escalate_to_human` | C1 ESCALATE (vulnerable or legal), C2 NO_CONSENT, C3 NO_OFFER_POLICY | Complaints team lead |
| Returns | `get_return`, `set_disposition`, `raise_vendor_claim` | R1 RECALLED (quarantine only), R2 HIGH_VALUE (over 500 pounds), R3 GRADE_NOT_FIT (restock needs grade A), R4 CLAIM_EXPIRED | Returns supervisor |
| Billing | `get_refunds`, `issue_refund`, `request_approval` | B1 OVER_ORDER_VALUE, B2 NEEDS_APPROVAL (total over 25 pounds) | Billing team lead |

**Three tools each is a design choice.** A short tool list keeps each specialist's context
small, and makes the boundary visible: the complaints agent cannot refund because it has no
refund tool, not because a rule says no. There is also no tool that changes an inspector's
grade, so the Day 1 regrading failure cannot happen at all.

**The guardrail is shared, the rules are not.** One `before_tool_callback` is attached to
all three specialists. It looks at the tool being called and asks the owning team's rules:

| Tool | Rules asked | Subject |
|---|---|---|
| `send_customer_message` | `decide_message` (C2, C3) | Complaint |
| `issue_refund` | `decide_refund` (B1, B2) | Complaint |
| `set_disposition` | `decide_disposition` (R1, R2, R3) | Return |
| `raise_vendor_claim` | `decide_claim` (R2, R4) | Return |
| `get_complaint` | `check_complaint` (C1), escalating at once if it applies | Complaint |
| Lookups, `escalate_to_human`, `request_approval` | None: always allowed | |

When a rule stops an action, the guardrail escalates to that rule's owner, puts the
complaint or return on hold, and returns `escalated_to` to the model, as on Day 2.

---

## 6. Pattern A: the agent loop, Agent approach

```python
root_agent = make_complaints_agent(name="v5a_loop_agent")
```

One specialist, three tools. ADK's runner provides the loop: call the model, run whatever
tool it asks for (through the guardrail), give it the result, repeat until it answers
without a tool call. Nothing in the file draws the loop; the model decides every step.

**Strength:** flexible. It handles requests nobody planned for.
**Weakness:** the order of steps is the model's choice, so it varies between runs.

---

## 7. Pattern B: the agent loop, Graph API approach

A `Workflow` from `google.adk.workflow`. Nodes are functions (code) or agents (model), and
edges carry route values. A node chooses where to go next by returning
`Event(route="...")`.

| Node | Kind | Does | Routes |
|---|---|---|---|
| `prepare` | Code | Finds the complaint ID and channel. Stops at once for a vulnerable or legal case | `draft`, `person`, `no_complaint` |
| `reply_drafter` | Model | Writes the apology, and nothing else. It has **no tools** | always to `check` |
| `check` | Code | Runs the Day 2 message rules on the draft, and a length limit | `send`, `retry` (at most 3 drafts), `person` |
| `send` | Code | Sends it. Only reachable if `check` passed | end |
| `person` | Code | Hands the complaint to the complaints team lead | end |

**How facts move between nodes.** `prepare` writes the customer's name and complaint to
session state. The drafter's instruction has placeholders (`{customer_name}`,
`{complaint_text}`, `{feedback}`) that ADK fills from state, so a rejected draft's reason
reaches the next attempt as `{feedback}`.

**Strength:** every path is visible, bounded and testable. The model cannot send anything;
it can only write words that code then checks.
**Weakness:** only the paths you drew exist. A request the graph was not built for goes to
`no_complaint`.

---

## 8. Pattern C: the router, Graph API approach

```
START -> route_by_rules --complaints--> complaints_agent
               |         --returns-----> returns_agent
               |         --billing-----> billing_agent
               +--unsure--> route_classifier -> parse_route --(the same three)
                                                     +--several--> hand_over
                                                     +--unclear--> ask_again
```

**Code first, the model only when unsure.** `route_by_rules` in `rules.py` looks for a
return ID (`R-...`), money words, or a complaint ID (`C-...`). If exactly one team fits, it
routes, prints `>>> ROUTED BY CODE`, and records `route_source: code`. If none fits, or more
than one does, it says `unsure`, and only then does the model classify. That is the Day 2
principle applied to routing: deterministic wherever the words allow it, and cheaper,
because most requests never call the classifier.

| Request contains | Route |
|---|---|
| A return ID, and nothing that needs another team | returns |
| Money words (refund, money back, charged, overcharge) | billing |
| A complaint ID and nothing else | complaints |
| Nothing to go on, or more than one team | unsure: the model decides |

**A router sends each request to one team.** The kettle (complaint, return and refund) is
`unsure` to code and `several` to the model, so it is handed to a person. That is correct
behaviour for a router, and exactly the gap pattern D fills.

**The classifier's answer is parsed by code.** `parse_route` accepts only the five known
words; anything else becomes `unclear`. The model suggests; code decides what the
suggestion means.

---

## 9. Pattern D: the orchestrator, multi-agent

```python
root_agent = Agent(
    name="v5d_orchestrator",
    instruction=instruction("coordinator"),
    tools=[AgentTool(agent=make_complaints_agent()),
           AgentTool(agent=make_returns_agent()),
           AgentTool(agent=make_billing_agent())],
)
```

The coordinator has no business tools. Its three tools are the three specialists, each
wrapped with `AgentTool`. When it calls one, ADK runs that specialist as a complete agent,
with its own instruction, tools, guardrail and recorder, and returns its final answer as
the tool result.

**What the coordinator can and cannot do.** It can decide which specialists to call, in
what order, and with what instructions. It cannot bypass a rule: a refund above the limit
is blocked inside the billing specialist, whatever the coordinator asked for. The rules
travel with the specialist, not with whoever calls it.

**Strength:** one request can span several teams, and the answer comes back as one.
**Weakness:** the plan is the model's. It may call specialists in a different order, skip
one, or call one twice. That is what eval case D1 measures.

---

## 10. How each pattern is scored

`eval/run_eval.py` runs each case in a fresh session and checks four things:

| Check | What it reads | Used most by |
|---|---|---|
| Forbidden ran | Tools that ran, which the case forbids | Must-never cases |
| Path | Tool names, specialist names, and the step `escalated`, in order or in any order | A and D |
| State | Facts left in session state, such as `route_source`, `sent`, `handed_to_person` | B and C |
| Answer | Expected words in the final reply | All |

**Why state matters for graphs.** In B and C, much of the work is done by code nodes, which
call no tools the model can see. The facts they record, such as whether code or the model
routed a request, are the evidence. The router's `route_source: code` is how case C1 proves
that a recalled item was routed without asking the model.

| Case | Pattern | Kind | What it proves |
|---|---|---|---|
| A1 | A | Should usually | The model finds the right two tools on its own |
| A2 | A | Must never | A discount message is stopped, and the case reaches a person |
| B1 | B | Should usually | The graph drafts, checks and sends |
| B2 | B | Must never | A vulnerable customer is handed over before any draft |
| C1 | C | Must never | A return ID is routed by code, not the model |
| C2 | C | Should usually | A vague request is routed by the model |
| D1 | D | Should usually | One request reaches all three specialists |

**Pattern D has no must-never case.** Its safety comes from the specialists' rules, which
the other cases already cover. That is a deliberate gap, and one of the seven questions.

---

## 11. State: what persists, and for how long

| State | Held in | Lasts |
|---|---|---|
| Data, refunds, dispositions, claims, approvals made by agents | Memory, in `northwind/data.py` | Until the server or the eval run stops |
| Escalated or on hold; graph facts such as `tries`, `route_taken` | Session state | One session |
| A specialist's session when called by the orchestrator | Its own session, inside the tool call | One call |
| Events | `runs.jsonl`, each line naming the agent | Until deleted |
| Escalations | `escalations.log` | Until deleted |
| Baseline | `baseline/baseline_v1.json` | Until the full eval set runs again |

**The orchestrator's specialists have their own sessions.** A hold placed inside the
billing specialist does not appear in the coordinator's state. The escalation still
happens and is logged; it is simply recorded where the rule ran.

---

## 12. Known limits

| Limit | Where it shows | Where it is picked up |
|---|---|---|
| The router uses word lists | "I was charged twice" is billing by code; an unusual phrasing goes to the model | Worksheet: which requests should code own? |
| The graph loop only knows the paths drawn | A request B was not built for ends at `no_complaint` | ADR-5: when to use a graph |
| The orchestrator's plan varies | D1 may call specialists in any order, or miss one | Day 6 and Day 10 |
| Escalations can repeat across specialists | A blocked refund followed by `request_approval` logs two lines to Billing | A candidate for one handover per case |
| Each specialist's tools are fixed at three | A new need means a new tool in the right team, or a new specialist | ADR-5 |
| No must-never case for the orchestrator | Its safety is inherited, not tested directly | One of the seven questions |

---

## 13. Configuration and credentials

| Setting, in `agents/.env` | Purpose |
|---|---|
| `GOOGLE_GENAI_USE_VERTEXAI` | Use the Cloud project path rather than a personal API key |
| `GOOGLE_CLOUD_PROJECT` | Which project is billed and permission-checked |
| `GOOGLE_CLOUD_LOCATION` | Which region serves the model |
| `AGENT_MODEL` | Which Gemini model every agent and node runs on, and what the baseline records |

`setup.sh` writes these from `gcloud config`. The component tests and `show_context.py`
need the ADK environment but no credentials. The chat and the eval set call the model.
