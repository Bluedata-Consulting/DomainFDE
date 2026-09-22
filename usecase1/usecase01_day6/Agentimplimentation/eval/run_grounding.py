"""Before and after: the same ten questions on three agents (Day 6: Ground).

    python3 eval/run_grounding.py                       all three agents
    python3 eval/run_grounding.py raw semantic          only some agents
    python3 eval/run_grounding.py semantic G4 G9        some questions on one agent

For every question it records whether the answer was right, which tools were used,
and how many tokens the model read and wrote. The totals are the before and after
score; the per-question rows show where grounding, and then the data's shape, made
the difference.

Every failure gets a first guess at its cause, for you to confirm or correct:
    context     the answer was never in front of the model (no tool, or no useful rows)
    tool        a tool failed or was blocked, and the agent did not recover
    reasoning   the right data came back, but the answer was still wrong

This calls the real model. Thirty runs cost a few pence and take a few minutes.
"""
import asyncio
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT / "agents"))
sys.path.insert(0, str(KIT))

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from northwind.grounded import MODEL  # noqa: E402

AGENTS = {"ungrounded": "v6_ungrounded", "raw": "v6_grounded_raw", "semantic": "v6_grounded_semantic"}


def load():
    return yaml.safe_load((KIT / "eval" / "grounding_questions.yaml").read_text(encoding="utf-8"))


def judge(q, answer):
    text = f" {answer.lower()} "
    missing = [e for e in q.get("expect", []) if str(e).lower() not in text]
    any_ok = not q.get("any_of") or any(str(a).lower() in text for a in q["any_of"])
    return not missing and any_ok


async def ask(agent, question):
    runner = InMemoryRunner(agent=agent, app_name=agent.name)
    session = await runner.session_service.create_session(app_name=agent.name, user_id="eval")
    tools, outcomes, answer, tokens_in, tokens_out = [], [], "", 0, 0
    message = types.Content(role="user", parts=[types.Part(text=question)])
    async for event in runner.run_async(user_id="eval", session_id=session.id, new_message=message):
        usage = getattr(event, "usage_metadata", None)
        if usage:
            tokens_in += usage.prompt_token_count or 0
            tokens_out += (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
        for part in (event.content.parts if event.content else []):
            if part.function_call:
                tools.append(part.function_call.name)
            elif part.function_response:
                raw = json.dumps(part.function_response.response, default=str)
                outcomes.append("blocked" if '\\"blocked\\"' in raw or '"blocked"' in raw
                                else "error" if '\\"error\\"' in raw or '"isError": true' in raw
                                else "empty" if '\\"rows\\": []' in raw else "ok")
            elif part.text:
                answer = part.text
    return answer, tools, outcomes, tokens_in, tokens_out


def diagnose(tools, outcomes):
    if not tools or all(o == "empty" for o in outcomes):
        return "context"
    if outcomes and outcomes[-1] in ("blocked", "error"):
        return "tool"
    return "reasoning"


async def main():
    args = sys.argv[1:]
    if any(a in ("-h", "--help") for a in args):
        print(__doc__)
        return
    unknown = [a for a in args if a not in AGENTS and not a.upper().startswith("G")]
    if unknown:
        print(f"Unknown: {' '.join(unknown)}. Use agent names ({', '.join(AGENTS)}) and question IDs (G1 to G10).")
        return
    chosen = [a for a in args if a in AGENTS] or list(AGENTS)
    wanted = [a.upper() for a in args if a.upper().startswith("G")]
    questions = [q for q in load()["questions"] if not wanted or q["id"] in wanted]
    agents = {k: importlib.import_module(f"{AGENTS[k]}.agent").root_agent for k in chosen}

    print(f"\n{len(questions)} questions x {len(agents)} agents, on {MODEL}\n")
    header = "".join(f"{k:<24}" for k in agents)
    print(f"  {'#':<5}{'needs':<8}{header}")
    results = {k: [] for k in agents}
    for q in questions:
        cells = []
        for k, agent in agents.items():
            answer, tools, outcomes, tin, tout = await ask(agent, q["question"])
            ok = judge(q, answer)
            cause = None if ok else diagnose(tools, outcomes)
            results[k].append({"id": q["id"], "needs": q["needs"], "correct": ok, "cause": cause,
                               "tools": tools, "tool_outcomes": outcomes,
                               "tokens_in": tin, "tokens_out": tout, "answer": answer.strip()})
            cells.append(f"{('PASS' if ok else 'FAIL ' + cause):<14}{tin + tout:>7,} tok  ")
        print(f"  {q['id']:<5}{q['needs']:<8}{''.join(cells)}")

    print("\n  Totals")
    summary = {}
    for k, rows in results.items():
        right = sum(r["correct"] for r in rows)
        tokens = sum(r["tokens_in"] + r["tokens_out"] for r in rows)
        summary[k] = {"correct": f"{right} of {len(rows)}", "tokens": tokens}
        by_need = {n: f"{sum(r['correct'] for r in rows if r['needs'] == n)}/{sum(1 for r in rows if r['needs'] == n)}"
                   for n in ("sql", "policy", "both") if any(r["needs"] == n for r in rows)}
        print(f"    {k:<12} {right:>2} of {len(rows)} correct   {tokens:>8,} tokens   by source: {by_including(by_need)}")
    if "raw" in results and "semantic" in results:
        flipped = [r["id"] for r, s in zip(results["raw"], results["semantic"]) if s["correct"] and not r["correct"]]
        print(f"\n  Fixed by the semantic layer: {', '.join(flipped) or 'none'}")

    if not wanted and len(agents) == len(AGENTS):
        out = KIT / "baseline" / "grounding_v1.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({
            "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "model": MODEL, "eval_set": load()["eval_set"], "summary": summary, "questions": results,
        }, indent=2), encoding="utf-8")
        print(f"\n  Results written to {out.relative_to(KIT)}\n")
    for agent in agents.values():
        for tool in agent.tools:
            await tool.close()


def by_including(d):
    return "  ".join(f"{k} {v}" for k, v in d.items())


if __name__ == "__main__":
    asyncio.run(main())
