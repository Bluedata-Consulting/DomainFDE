"""Manage releases (Day 7: Operate). Run from the kit folder.

    python3 -m ops.release list                 every release, and which is current
    python3 -m ops.release show [TAG]           what is in a release, and whether it drifted
    python3 -m ops.release diff A B             what changed between two releases
    python3 -m ops.release new TAG "notes"      copy the current release into a new one
    python3 -m ops.release promote TAG          make a release current (after the gate)
    python3 -m ops.release rollback             go back to the last good release

After promote or rollback, restart adk web: the agents read their release at start.
"""
import difflib
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from northwind import release as rel  # noqa: E402


def cmd_list():
    current = rel.current_tag()
    print(f"\n  {'':<3}{'Release':<10}{'Status':<14}{'Model':<24}Notes")
    for tag in rel.all_tags():
        cfg = rel.config(tag)
        mark = "->" if tag == current else ""
        print(f"  {mark:<3}{tag:<10}{cfg.get('status', ''):<14}{rel.model(tag):<24}{cfg.get('notes', '')[:50]}")
    print(f"\n  Current: {current}\n")


def cmd_show(tag=None):
    tag = tag or rel.current_tag()
    cfg = rel.config(tag)
    print(f"\n  Release {tag}  ({cfg.get('status')})  created {cfg.get('created')}")
    print(f"  Based on: {cfg.get('based_on') or 'nothing'}   Model: {rel.model(tag)}")
    print(f"  Notes: {cfg.get('notes', '')}")
    if cfg.get("tool_settings"):
        print(f"  Tool settings: {cfg['tool_settings']}")
    print(f"  {len(cfg.get('fingerprints', {}))} files fingerprinted")
    changed = rel.drift(tag)
    print("  Drift: none. The release matches its fingerprints.\n" if not changed else
          "  DRIFT: changed since the release was made, outside any release:\n" +
          "".join(f"    {c}\n" for c in changed))


def cmd_diff(a, b):
    ca, cb = rel.config(a), rel.config(b)
    print(f"\n  {a} -> {b}")
    if rel.model(a) != rel.model(b):
        print(f"  model: {rel.model(a)} -> {rel.model(b)}")
    if (ca.get("tool_settings") or {}) != (cb.get("tool_settings") or {}):
        print(f"  tool settings: {ca.get('tool_settings') or {}} -> {cb.get('tool_settings') or {}}")
    fa, fb = ca.get("fingerprints", {}), cb.get("fingerprints", {})
    for key in sorted(set(fa) | set(fb)):
        if fa.get(key) == fb.get(key):
            continue
        print(f"  changed: {key}")
        pa, pb = rel.folder(a) / key, rel.folder(b) / key
        if key.startswith("code/") or not pa.exists() or not pb.exists():
            continue
        lines = difflib.unified_diff(pa.read_text().splitlines(), pb.read_text().splitlines(),
                                     a, b, lineterm="", n=0)
        for line in list(lines)[2:]:
            if not line.startswith("@@"):
                print(f"      {line}")
    print()


def cmd_new(tag, notes):
    source = rel.current_tag()
    if (rel.RELEASES / tag).exists():
        sys.exit(f"Release {tag} already exists.")
    drifted = rel.drift(source)
    if drifted:
        print(f"WARNING: {source} has been edited outside a release ({', '.join(drifted)}).")
        print(f"         {tag} will carry those unreleased edits. Undo them first if they were a mistake.")
    shutil.copytree(rel.folder(source), rel.RELEASES / tag)
    cfg = rel.config(tag)
    cfg.update(tag=tag, based_on=source, notes=notes, status="candidate",
               created=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    rel.write_config(cfg, tag)
    rel.seal(tag)
    rel.log(f"new {tag} from {source}: {notes}")
    print(f"Created {tag} from {source}. Edit it in releases/{tag}/, then: "
          f"python3 -m ops.release promote {tag}")


def promote(tag, reason="promoted"):
    old = rel.current_tag()
    cfg = rel.config(tag)
    cfg["status"] = "current"
    rel.write_config(cfg, tag)
    if old != tag:
        old_cfg = rel.config(old)
        if old_cfg.get("status") == "current":
            old_cfg["status"] = "good"
            rel.write_config(old_cfg, old)
    (rel.RELEASES / "CURRENT").write_text(tag + "\n", encoding="utf-8")
    rel.log(f"{reason}: {old} -> {tag}")


def cmd_promote(tag):
    promote(tag)
    print(f"Current release: {tag}. Restart adk web to run it.")


def cmd_rollback():
    current = rel.current_tag()
    base = rel.config(current).get("based_on")
    good = [t for t in reversed(rel.all_tags())
            if t != current and rel.config(t).get("status") in ("good", "current")]
    target = base if base and base in good else (good[0] if good else None)
    if not target:
        sys.exit("No good release to roll back to.")
    cfg = rel.config(current)
    cfg["status"] = "rolled_back"
    rel.write_config(cfg, current)
    promote(target, reason="ROLLBACK")
    print(f"Rolled back: {current} -> {target}. Restart adk web to run it.")


if __name__ == "__main__":
    args = sys.argv[1:]
    commands = {"list": cmd_list, "show": cmd_show, "diff": cmd_diff, "new": cmd_new,
                "promote": cmd_promote, "rollback": cmd_rollback}
    if not args or args[0] not in commands:
        print(__doc__)
        sys.exit(0)
    commands[args[0]](*args[1:])
