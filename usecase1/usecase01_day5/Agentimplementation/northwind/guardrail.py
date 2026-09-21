"""The guardrail, for every agent (Day 2 pattern, Day 5 composition).

ADK runs before_tool_callback before every tool call.
  - Return None   -> the tool runs.
  - Return a dict -> the tool does NOT run, and the dict goes back to the model.

Whenever a rule stops an action, the guardrail hands the case to the rule's owner
itself. It does not depend on the model remembering to escalate.

The same guardrail is attached to the complaints, returns and billing agents. It
looks at which tool is being called, and asks that team's rules.
"""
from . import rules
from .data import complaint_view, return_view
from .tools import hand_to_person

LOOKUPS = {"get_complaint", "get_return", "get_refunds"}
ALWAYS_ALLOWED = {"escalate_to_human", "request_approval"}
HOLD_BLOCKS = {"issue_refund", "set_disposition", "raise_vendor_claim"}


def _subject(args):
    return str(args.get("complaint_id") or args.get("return_id") or "").strip().upper()


def _escalate(tool_context, subject, owner, rule, reason, attempted):
    """Hand over once per subject and rule, and put the subject on hold."""
    state = tool_context.state
    if not state.get(f"escalated:{subject}:{rule}"):
        hand_to_person(subject, owner, f"[{rule}] {reason} Attempted: {attempted}")
        state[f"escalated:{subject}:{rule}"] = True
    if not state.get(f"with_human:{subject}"):
        state[f"with_human:{subject}"] = owner
    return owner


def _blocked(tool, subject, rule, reason, owner):
    print(f"\n>>> BLOCKED BY GUARDRAIL: {tool} | {subject} | {rule} | {reason}\n", flush=True)
    return {
        "status": "blocked", "rule": rule, "reason": reason, "escalated_to": owner,
        "next_step": (f"This has already been handed to {owner}. Do not retry and do not "
                      f"escalate again. Say what was not done, why, and that {owner} has it."),
    }


def _decide(tool, args):
    """Returns (view, result). result is None when the subject does not exist."""
    if tool == "send_customer_message":
        view = complaint_view(args.get("complaint_id", ""))
        return view, view and rules.decide_message(view, str(args.get("channel", "")).lower(),
                                                   str(args.get("purpose", "")).lower(),
                                                   str(args.get("message", "")))
    if tool == "issue_refund":
        view = complaint_view(args.get("complaint_id", ""))
        return view, view and rules.decide_refund(view, args.get("amount_gbp", 0))
    if tool == "set_disposition":
        view = return_view(args.get("return_id", ""))
        return view, view and rules.decide_disposition(view, str(args.get("disposition", "")))
    if tool == "raise_vendor_claim":
        view = return_view(args.get("return_id", ""))
        return view, view and rules.decide_claim(view)
    return None, rules.ALLOWED


def before_tool_callback(tool, args, tool_context):
    subject = _subject(args)
    with_human = tool_context.state.get(f"with_human:{subject}")

    # 1. A complaint lookup: hand over at once if rule C1 applies
    if tool.name == "get_complaint":
        view = complaint_view(subject)
        result = rules.check_complaint(view) if view else None
        if result:
            owner = _escalate(tool_context, subject, result["owner"], result["rule"],
                              result["reason"], "looked up the complaint")
            return {"status": "found", **view, "escalated_to": owner,
                    "note": f"{result['reason']} Already handed to {owner}. You may send a "
                            f"short service acknowledgement, nothing else."}
        return None

    # 2. Other lookups, and the tools that hand over to a person, always run
    if tool.name in LOOKUPS:
        return None
    if tool.name in ALWAYS_ALLOWED:
        if with_human and tool.name == "escalate_to_human":
            return {"status": "already_escalated", "owner": with_human}
        tool_context.state[f"with_human:{subject}"] = with_human or args.get("owner", "Billing team lead")
        return None

    # 3. Already with a person: no more decisions by the agent
    if with_human and tool.name in HOLD_BLOCKS:
        return _blocked(tool.name, subject, "WITH_HUMAN", "This is already with a person.", with_human)

    # 4. Ask the team's rules
    view, result = _decide(tool.name, args)
    if result is None:
        print(f"\n>>> BLOCKED BY GUARDRAIL: {tool.name} | {subject} | UNKNOWN\n", flush=True)
        return {"status": "blocked", "rule": "UNKNOWN", "next_step": "Ask the user for a valid ID."}
    if result["allowed"]:
        return None
    owner = _escalate(tool_context, subject, result["owner"], result["rule"], result["reason"],
                      f"{tool.name} {args}"[:120])
    return _blocked(tool.name, subject, result["rule"], result["reason"], owner)
