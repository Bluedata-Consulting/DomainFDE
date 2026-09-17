"""Guardrail: connects the decision tree to the ADK agent.

ADK runs before_tool_callback before every tool call.
  - Return None   -> the tool runs.
  - Return a dict -> the tool does NOT run; the dict goes back to the model.

Whenever a rule stops the agent, this file escalates to a person itself.
Escalation does not depend on the model remembering to do it.
"""
from .decision_tree import check_complaint, decide
from .tools import COMPLAINTS, escalate_to_human, get_complaint

CHECKED_TOOLS = ["issue_refund", "close_complaint", "send_customer_message"]


def auto_escalate(tool_context, complaint_id, owner, rule, reason, attempted):
    """Escalate once per complaint and rule, and mark the complaint as with a person."""
    state = tool_context.state
    if not state.get(f"escalated:{complaint_id}:{rule}"):
        escalate_to_human(complaint_id, owner, f"[{rule}] {reason} Attempted: {attempted}")
        state[f"escalated:{complaint_id}:{rule}"] = True
    if not state.get(f"with_human:{complaint_id}"):
        state[f"with_human:{complaint_id}"] = owner
    return owner


def blocked(tool_name, complaint_id, rule, reason, escalated_to):
    print(f"\n>>> BLOCKED BY GUARDRAIL: {tool_name} | {complaint_id} | {rule} | {reason}\n",
          flush=True)
    return {
        "status": "blocked",
        "rule": rule,
        "reason": reason,
        "escalated_to": escalated_to,
        "next_step": (f"This has already been escalated to {escalated_to}. Do not retry "
                      f"and do not escalate again. Tell the user what was not done, why, "
                      f"and that {escalated_to} now has it."),
    }


def before_tool_callback(tool, args, tool_context):
    complaint_id = str(args.get("complaint_id", "")).strip().upper()
    complaint = COMPLAINTS.get(complaint_id)
    with_human = tool_context.state.get(f"with_human:{complaint_id}")

    # 1. Looking up a complaint: escalate at once if Rule 1 applies.
    if tool.name == "get_complaint":
        result = check_complaint(complaint) if complaint else None
        if result is None:
            return None
        owner = auto_escalate(tool_context, complaint_id, result["owner"], result["rule"],
                              result["reason"], "looked up the complaint")
        return {**get_complaint(complaint_id), "escalated_to": owner,
                "note": f"{result['reason']} Already escalated to {owner}. "
                        f"Do not refund, offer anything or close. You may send a short "
                        f"acknowledgement."}

    # 2. The model escalates by itself: allow it, but never twice.
    if tool.name == "escalate_to_human":
        if with_human:
            return {"status": "already_escalated", "complaint_id": complaint_id,
                    "owner": with_human}
        tool_context.state[f"with_human:{complaint_id}"] = args.get("owner", "a person")
        return None

    # 3. Routing is always safe.
    if tool.name not in CHECKED_TOOLS:
        return None

    # 4. Unknown complaint ID: nothing to escalate, ask for the right ID.
    if complaint is None:
        print(f"\n>>> BLOCKED BY GUARDRAIL: {tool.name} | {complaint_id} | "
              f"UNKNOWN_COMPLAINT\n", flush=True)
        return {"status": "blocked", "rule": "UNKNOWN_COMPLAINT",
                "next_step": "Ask the user for a valid complaint ID."}

    # 5. Already with a person: the agent may not refund or close.
    if with_human and tool.name in ("issue_refund", "close_complaint"):
        return blocked(tool.name, complaint_id, "WITH_HUMAN",
                       "This complaint is already with a person.", with_human)

    # 6. Check the rules. Any rule that stops the action escalates.
    result = decide(complaint, tool.name, args)
    if result["allowed"]:
        return None
    owner = auto_escalate(tool_context, complaint_id, result["owner"], result["rule"],
                          result["reason"], f"{tool.name} {args}"[:120])
    return blocked(tool.name, complaint_id, result["rule"], result["reason"], owner)
