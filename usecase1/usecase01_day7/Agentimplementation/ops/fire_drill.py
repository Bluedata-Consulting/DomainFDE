"""The fire drill (Day 7: Operate). The coach runs this; the learner does not look.

    python3 -m ops.fire_drill inject random    deploy a release with one hidden fault
    python3 -m ops.fire_drill inject tool      Billing's ledger stops responding
    python3 -m ops.fire_drill inject prompt    a line disappears from the coordinator's instruction
    python3 -m ops.fire_drill inject model     the release moves to a different model
    python3 -m ops.fire_drill inject policy    the refund policy says the limit is 50 pounds
    python3 -m ops.fire_drill reveal           say which fault the current release carries

Each fault is a realistic bad release, not a hack: a setting, an edited instruction,
a model change or an updated document, deployed through ops.release like any other.
The learner must find it from the traces and the health check, roll back, and write
a one-line incident note.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from northwind import release as rel  # noqa: E402
from ops.release import cmd_new, promote  # noqa: E402

PROMPT_LINES = [
    "3. Call billing_agent before anyone tells the customer about money.",
    "Never promise the customer anything a specialist did not confirm.",
]


def _fault_tool(tag):
    cfg = rel.config(tag)
    cfg["tool_settings"] = {**(cfg.get("tool_settings") or {}), "get_refunds": "timeout"}
    rel.write_config(cfg, tag)
    return "tool: get_refunds times out (Billing's ledger stops responding)"


def _fault_prompt(tag):
    path = rel.folder(tag) / "instructions" / "coordinator.txt"
    text = path.read_text(encoding="utf-8")
    for line in PROMPT_LINES:
        text = text.replace(line + "\n", "")
    path.write_text(text, encoding="utf-8")
    return "prompt: the coordinator no longer calls Billing first, or avoids unconfirmed promises"


def _fault_model(tag):
    cfg = rel.config(tag)
    cfg["model"] = "gemini-2.5-flash-lite"
    rel.write_config(cfg, tag)
    return "model: the release moved to gemini-2.5-flash-lite"


def _fault_policy(tag):
    path = rel.folder(tag) / "policies" / "refunds.md"
    text = path.read_text(encoding="utf-8").replace("up to 25 pounds", "up to 50 pounds").replace(
        "above 25 pounds", "above 50 pounds")
    path.write_text(text, encoding="utf-8")
    return "policy: refunds.md now says the limit is 50 pounds, while the rules still enforce 25"


FAULTS = {"tool": _fault_tool, "prompt": _fault_prompt, "model": _fault_model, "policy": _fault_policy}


def inject(kind):
    if kind == "random":
        kind = random.choice(list(FAULTS))
    current = rel.current_tag()
    tag = f"r{max(int(t[1:]) for t in rel.all_tags() if t[1:].isdigit()) + 1}"
    cmd_new(tag, "Routine update")
    description = FAULTS[kind](tag)
    rel.seal(tag)
    (rel.folder(tag) / ".drill").write_text(description + "\n", encoding="utf-8")
    promote(tag, reason="deployed")
    print(f"\nRelease {tag} is deployed (was {current}). Restart adk web.")
    print("Something in it may be wrong. Find it, roll back, and write the incident note.\n")


def reveal():
    marker = rel.folder() / ".drill"
    print(marker.read_text().strip() if marker.exists() else "The current release carries no drill fault.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "inject" and (args[1] in FAULTS or args[1] == "random"):
        inject(args[1])
    elif args[:1] == ["reveal"]:
        reveal()
    else:
        print(__doc__)
