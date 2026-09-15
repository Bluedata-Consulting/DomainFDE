# Prompts: generate the Day 2 decision tree and guardrail

Two standalone prompts, one per file. Each one can be pasted into a coding assistant on
its own. Generate `decision_tree.py` first: the guardrail prompt depends on its interface.

Both files go in `usecase01_day2/agents/complaints_v2_decision/`.

| Prompt | Generates | Depends on | How to check it |
|---|---|---|---|
| 1 | `decision_tree.py` | Nothing | `python3 tests/test_decision_tree.py` prints `5 of 5 scenarios passed.` |
| 2 | `guardrails.py` | `decision_tree.py`, `tools.py` | Run the four prompts in README step 12 and compare the `>>>` lines |

---

## Prompt 1: `decision_tree.py`

````text
You are helping build a training exercise on Google ADK (Agent Development Kit) in Python.
Write one file: decision_tree.py. Return the complete file in a single code block.

## Context

Northwind Home is a UK online home goods retailer. A complaints agent can look up
complaints, route them, issue refunds, send customer messages and close complaints.
decision_tree.py holds the business rules that decide whether each action is allowed.
It is plain Python and is tested on its own, without any AI model.

The file lives in: agents/complaints_v2_decision/decision_tree.py

## The data it receives

Each complaint is a dict like these (from tools.py in the same folder):

"C-101": {"customer": "Priya Shah", "channel": "email",
          "text": "My parcel arrived two days late. Not happy.",
          "order_value_gbp": 45, "previous_contacts": 0,
          "vulnerable_customer": False, "opted_out_channels": []}
"C-102": {"customer": "Tom Reilly", "channel": "phone",
          "text": "You overcharged me 40 pounds on my last order. Refund me now or I am cancelling my membership.",
          "order_value_gbp": 120, "previous_contacts": 1,
          "vulnerable_customer": False, "opted_out_channels": []}
"C-103": {"customer": "Margaret Doyle", "channel": "email",
          "text": "This is the third time I have written. The sofa you delivered is broken. I have contacted the ombudsman and my solicitor. I am a full-time carer and I cannot keep chasing this.",
          "order_value_gbp": 899, "previous_contacts": 3,
          "vulnerable_customer": True, "opted_out_channels": []}
"C-104": {"customer": "Daniel Okafor", "channel": "chat",
          "text": "The replacement lamp you sent is the wrong colour.",
          "order_value_gbp": 60, "previous_contacts": 1,
          "vulnerable_customer": False, "opted_out_channels": ["email"]}

Tool names the agent can call, with their arguments:
  get_complaint(complaint_id)
  route_complaint(complaint_id, team, severity)
  issue_refund(complaint_id, amount_gbp)
  close_complaint(complaint_id, resolution_note)
  send_customer_message(complaint_id, channel, message)
  escalate_to_human(complaint_id, owner, reason)

## Hard constraints

- Plain Python only. No imports from ADK, google, tools.py or any other project file.
  The test imports this file directly with `from decision_tree import decide`, so it
  must not use relative imports.
- No classes, no external packages. Python 3.10 or later.

## Constants

Put these at the top, with a comment saying they are assumptions awaiting the
complaints team lead's sign-off:

  REFUND_LIMIT_GBP = 25
  LEGAL_WORDS = ["ombudsman", "solicitor", "lawyer", "legal action", "trading standards"]
  OFFER_WORDS = ["discount", "voucher", "compensation", "%"]
  TEAM_LEAD = "Complaints team lead"
  BILLING = "Billing team"

Word matching is case-insensitive substring matching on lowercased text.

## Function 1: check_complaint(complaint: dict) -> dict | None

Rule 1 on its own, so it can also be used when a complaint is first looked up.
- If complaint["vulnerable_customer"] is True, or complaint["text"] contains any word in
  LEGAL_WORDS, return:
  {"allowed": False, "rule": "ESCALATE", "owner": TEAM_LEAD, "reason": "<plain sentence>"}
- Otherwise return None.

## Function 2: decide(complaint: dict, tool_name: str, args: dict) -> dict

Always return a dict with exactly these keys: "allowed", "rule", "owner", "reason".

Check the rules in this order. The first rule that matches decides.

  Rule 1  ESCALATE
          tool_name is "issue_refund" or "close_complaint", and check_complaint(complaint)
          is not None. Return its result. Owner: TEAM_LEAD.
          Rule 1 does NOT apply to messages: a vulnerable customer may still get an
          acknowledgement.

  Rule 2  OPTED_OUT_CHANNEL
          tool_name is "send_customer_message", and args["channel"] lowercased is in
          complaint["opted_out_channels"]. Owner: TEAM_LEAD.

  Rule 3  NO_OFFER_POLICY
          tool_name is "send_customer_message", and args["message"] lowercased contains
          any word in OFFER_WORDS. Owner: TEAM_LEAD.

  Rule 4  NEEDS_APPROVAL
          tool_name is "issue_refund", and float(args["amount_gbp"]) is strictly greater
          than REFUND_LIMIT_GBP. Exactly 25 is allowed. Owner: BILLING.

  Rule 5  ALLOWED
          Anything else. {"allowed": True, "rule": "ALLOWED", "owner": None, "reason": ...}

- Use args.get(...) with safe defaults ("" for text, 0 for amounts) so missing
  arguments never raise.
- Each "reason" is one or two short plain-English sentences a trainee can read in a
  terminal. Rule 4's reason includes the amount and the limit, for example
  "Refund of 40 GBP is above the 25 GBP limit and needs approval."

## Style

- Written for trainees reading code for the first time.
- A module docstring that lists the five rules in order, with one line each, and says
  the first match wins and that every rule which stops the agent names an owner.
- A one-line comment above each rule in decide(), e.g. "# Rule 2".
- No em dashes in comments or strings.

## Acceptance criteria

1. This test, run from the project root, prints 5 PASS lines and "5 of 5 scenarios passed.":
   python3 tests/test_decision_tree.py
   The scenarios it checks (complaint, tool, args -> rule, owner):
   S1  C-103, close_complaint, {}                                              -> ESCALATE, Complaints team lead
   S2  C-104, send_customer_message, {"channel": "email", "message": "Sorry about the lamp."} -> OPTED_OUT_CHANNEL, Complaints team lead
   S3  C-104, send_customer_message, {"channel": "chat", "message": "Here is a 20% discount."} -> NO_OFFER_POLICY, Complaints team lead
   S4  C-102, issue_refund, {"amount_gbp": 40}                                -> NEEDS_APPROVAL, Billing team
   S5  C-101, close_complaint, {}                                              -> ALLOWED, None
2. Changing REFUND_LIMIT_GBP to 50 makes S4 fail and nothing else.
3. These also hold:
   decide(C-101, "issue_refund", {"amount_gbp": 25})       -> ALLOWED
   decide(C-101, "issue_refund", {"amount_gbp": 25.01})    -> NEEDS_APPROVAL
   decide(C-103, "send_customer_message", {"channel": "email", "message": "We have received your complaint."}) -> ALLOWED
   decide(C-103, "issue_refund", {"amount_gbp": 40})       -> ESCALATE (rule 1 beats rule 4)
   decide(C-104, "send_customer_message", {"channel": "email", "message": "20% off"}) -> OPTED_OUT_CHANNEL (rule 2 beats rule 3)
   check_complaint(C-101) -> None
   check_complaint(C-103) -> rule ESCALATE

After the code block, add a short table showing each check in criterion 3 and which
rule in your code produces it.
````

---

## Prompt 2: `guardrails.py`

````text
You are helping build a training exercise on Google ADK (Agent Development Kit) in Python.
Write one file: guardrails.py. Return the complete file in a single code block.

## Context

Northwind Home is a UK online home goods retailer. A complaints agent built with ADK and
Gemini can look up complaints, route them, issue refunds, send customer messages and
close complaints. The business rules are already written in decision_tree.py.

guardrails.py connects those rules to the agent. It provides an ADK before_tool_callback
that checks every tool call against the rules before it runs. Whenever a rule stops an
action, this code escalates the complaint to a named person itself. Escalation must never
depend on the model remembering to do it.

The file lives in: agents/complaints_v2_decision/guardrails.py
agent.py in the same folder already does:
    from .guardrails import before_tool_callback
    Agent(..., before_tool_callback=before_tool_callback)

## How ADK calls it

ADK calls before_tool_callback(tool=..., args=..., tool_context=...) before every tool call.
- tool.name is the tool's name as a string.
- args is a dict of the arguments the model chose.
- tool_context.state behaves like a dict and persists for the whole chat session.
  A new session starts with empty state.
- If the callback returns None, the tool runs normally.
- If it returns a dict, the tool does NOT run, and the dict is sent back to the model
  as if it were the tool's result.

## What already exists in the same folder (do not rewrite)

decision_tree.py:
  check_complaint(complaint: dict) -> dict | None
      Returns {"allowed": False, "rule": "ESCALATE", "owner": "Complaints team lead",
      "reason": "..."} if the customer is vulnerable or the text mentions legal action,
      otherwise None.
  decide(complaint: dict, tool_name: str, args: dict) -> dict
      Always returns {"allowed": bool, "rule": str, "owner": str | None, "reason": str}.
      Possible rules: ESCALATE, OPTED_OUT_CHANNEL, NO_OFFER_POLICY, NEEDS_APPROVAL (owner
      "Billing team"), ALLOWED (owner None).

tools.py:
  COMPLAINTS: dict of complaint records keyed "C-101" to "C-104"
  get_complaint(complaint_id: str) -> dict
      {"status": "found", "complaint_id": ..., **record} or {"status": "not_found", ...}
  escalate_to_human(complaint_id: str, owner: str, reason: str) -> dict
      Appends one line to escalations.log, prints ">>> ESCALATED TO HUMAN: ...",
      returns {"status": "escalated", "complaint_id": ..., "owner": ...}
  Other tools the model can call: route_complaint, issue_refund, close_complaint,
  send_customer_message.

Fixture facts you can rely on:
  C-101 routine; C-102 not flagged; C-103 vulnerable and mentions ombudsman and solicitor;
  C-104 has opted_out_channels ["email"].

## Hard constraints

- Imports exactly these, and nothing else:
    from .decision_tree import check_complaint, decide
    from .tools import COMPLAINTS, escalate_to_human, get_complaint
- No ADK imports and no type hints that require ADK. No classes, no external packages,
  no logging framework. Python 3.10 or later.
- All business rules stay in decision_tree.py. This file only translates and escalates.

## Module docstring

Explain the ADK contract in three short lines: return None and the tool runs; return a
dict and the tool does not run and the dict goes back to the model; escalation is done
by this code, not by the model.

## Constant

  CHECKED_TOOLS = ["issue_refund", "close_complaint", "send_customer_message"]

## Helper 1: auto_escalate(tool_context, complaint_id, owner, rule, reason, attempted) -> str

- If state key f"escalated:{complaint_id}:{rule}" is not set:
    call escalate_to_human(complaint_id, owner, f"[{rule}] {reason} Attempted: {attempted}")
    and set that key to True.
  This makes each complaint and rule escalate only once per session.
- If state key f"with_human:{complaint_id}" is not set, set it to owner.
- Return owner.

## Helper 2: blocked(tool_name, complaint_id, rule, reason, escalated_to) -> dict

- Print exactly, with flush=True:
    f"\n>>> BLOCKED BY GUARDRAIL: {tool_name} | {complaint_id} | {rule} | {reason}\n"
- Return:
    {"status": "blocked", "rule": rule, "reason": reason,
     "escalated_to": escalated_to,
     "next_step": f"This has already been escalated to {escalated_to}. Do not retry and do
                   not escalate again. Tell the user what was not done, why, and that
                   {escalated_to} now has it."}

## Main function: before_tool_callback(tool, args, tool_context)

Start with:
  complaint_id = str(args.get("complaint_id", "")).strip().upper()
  complaint = COMPLAINTS.get(complaint_id)
  with_human = tool_context.state.get(f"with_human:{complaint_id}")

Then apply these checks in this exact order, with a numbered comment above each:

  1. Looking up a complaint: tool.name == "get_complaint"
     If complaint exists and check_complaint(complaint) returns a result:
       owner = auto_escalate(tool_context, complaint_id, result["owner"], result["rule"],
                             result["reason"], "looked up the complaint")
       return {**get_complaint(complaint_id), "escalated_to": owner,
               "note": f"{result['reason']} Already escalated to {owner}. Do not refund,
                        offer anything or close. You may send a short acknowledgement."}
     Otherwise return None.

  2. The model escalates by itself: tool.name == "escalate_to_human"
     If with_human is set, return
       {"status": "already_escalated", "complaint_id": complaint_id, "owner": with_human}
     Otherwise set state f"with_human:{complaint_id}" to args.get("owner", "a person")
     and return None.

  3. Routing and anything else not checked: tool.name not in CHECKED_TOOLS
     Return None.

  4. Unknown complaint ID: complaint is None
     Print f"\n>>> BLOCKED BY GUARDRAIL: {tool.name} | {complaint_id} | UNKNOWN_COMPLAINT\n"
     with flush=True, and return
       {"status": "blocked", "rule": "UNKNOWN_COMPLAINT",
        "next_step": "Ask the user for a valid complaint ID."}
     Do NOT escalate.

  5. Already with a person: with_human is set and tool.name is "issue_refund" or
     "close_complaint"
     return blocked(tool.name, complaint_id, "WITH_HUMAN",
                    "This complaint is already with a person.", with_human)
     Messages are still allowed, so the agent can send an acknowledgement.

  6. Ask the decision tree:
     result = decide(complaint, tool.name, args)
     If result["allowed"], return None.
     Otherwise:
       owner = auto_escalate(tool_context, complaint_id, result["owner"], result["rule"],
                             result["reason"], f"{tool.name} {args}"[:120])
       return blocked(tool.name, complaint_id, result["rule"], result["reason"], owner)

## Style

- Written for trainees reading code for the first time: short functions, clear names.
- No em dashes in comments or strings.

## Acceptance criteria

In one ADK session, this sequence of tool calls must behave exactly as shown.
"Escalated" means one new line in escalations.log and one ">>> ESCALATED TO HUMAN" line.

  #   Tool call                                               Expected
  1   get_complaint C-101                                     runs, no escalation
  2   close_complaint C-101                                   runs
  3   issue_refund C-102, amount 40                           escalated to Billing team, then BLOCKED NEEDS_APPROVAL
  4   close_complaint C-102                                   BLOCKED WITH_HUMAN, no new escalation
  5   escalate_to_human C-102 (called by the model)           returns already_escalated, no new log line
  6   get_complaint C-103                                     escalated to Complaints team lead at once; result includes escalated_to
  7   send_customer_message C-103, email, "We have received your complaint."   runs
  8   issue_refund C-103, amount 100                          BLOCKED WITH_HUMAN
  9   send_customer_message C-104, email, "Sorry"             escalated, BLOCKED OPTED_OUT_CHANNEL
  10  send_customer_message C-104, chat, "20% discount code"  escalated, BLOCKED NO_OFFER_POLICY
  11  the same call as 10 again                               BLOCKED NO_OFFER_POLICY, no new escalation
  12  issue_refund C-999, amount 5                            BLOCKED UNKNOWN_COMPLAINT, no escalation
  13  route_complaint C-102, "Billing", "high"                runs

After the sequence, escalations.log contains exactly 4 lines:
C-102 (NEEDS_APPROVAL), C-103 (ESCALATE), C-104 (OPTED_OUT_CHANNEL), C-104 (NO_OFFER_POLICY).

In a new session, state is empty, so step 3 would escalate again. That is expected.

After the code block, add a short table mapping each of the 13 steps to the numbered
check in before_tool_callback that produces it.
````
