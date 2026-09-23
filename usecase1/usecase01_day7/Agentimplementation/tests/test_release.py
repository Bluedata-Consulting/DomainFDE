"""Component test: releases, rollback and the fire drill (Day 7). No AI model.

Run from the kit folder, with the ADK environment active:
    python3 tests/test_release.py

It works on a temporary copy of releases/, so the real releases are never changed.
"""
import contextlib
import io
import shutil
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
from northwind import release as rel  # noqa: E402
from ops import fire_drill, release as ops_release  # noqa: E402

failures = 0


def check(name, got, expected):
    global failures
    ok = got == expected
    failures += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<58} expected {str(expected)[:26]:<28} got {str(got)[:30]}")


def quiet(fn, *args):
    with contextlib.redirect_stdout(io.StringIO()):
        fn(*args)


real = rel.RELEASES
print("Part 1: the shipped release\n")
check("A current release exists", rel.current_tag(), "r1")
check("r1 matches its fingerprints (no drift)", rel.drift("r1"), [])
check("r1 carries no tool settings", rel.config("r1").get("tool_settings") or {}, {})
check("r1 has the five instructions", sorted(p.stem for p in (rel.folder("r1") / "instructions").glob("*.txt")),
      ["billing", "complaints", "coordinator", "operations_assistant", "returns"])

with tempfile.TemporaryDirectory() as tmp:
    rel.RELEASES = Path(tmp) / "releases"
    shutil.copytree(real, rel.RELEASES)

    print("\nPart 2: a normal release, and rollback\n")
    quiet(ops_release.cmd_new, "r2", "Wording change")
    check("A new release starts as a candidate", rel.config("r2")["status"], "candidate")
    check("Creating it does not change the current release", rel.current_tag(), "r1")
    (rel.folder("r2") / "instructions" / "complaints.txt").write_text("edited\n")
    check("Editing a released file shows as drift", rel.drift("r2"), ["instructions/complaints.txt"])
    rel.seal("r2")
    quiet(ops_release.cmd_promote, "r2")
    check("Promote makes it current", rel.current_tag(), "r2")
    check("The old release is kept as good", rel.config("r1")["status"], "good")
    quiet(ops_release.cmd_rollback)
    check("Rollback returns to the release it was based on", rel.current_tag(), "r1")
    check("The rolled-back release is marked", rel.config("r2")["status"], "rolled_back")

    print("\nPart 3: the fire drill\n")
    effects = {
        "tool": lambda t: rel.tool_setting("get_refunds", t) == "timeout",
        "prompt": lambda t: "Call billing_agent before" not in rel.instruction("coordinator", t),
        "model": lambda t: rel.model(t) == "gemini-2.5-flash-lite",
        "policy": lambda t: "up to 50 pounds" in (rel.policies_dir(t) / "refunds.md").read_text(),
    }
    for kind, effect in effects.items():
        quiet(fire_drill.inject, kind)
        tag = rel.current_tag()
        check(f"'{kind}' deploys a new current release with its fault", effect(tag), True)
        check(f"'{kind}' release is sealed, so it shows no drift", rel.drift(tag), [])
        quiet(ops_release.cmd_rollback)
        check(f"Rolling back '{kind}' returns to a release without it", effect(rel.current_tag()), False)
    check("History records every deploy and rollback", sum(
        1 for line in (rel.RELEASES / "HISTORY.log").read_text().splitlines() if "ROLLBACK" in line), 5)

rel.RELEASES = real
check("\nThe real releases are untouched", rel.current_tag(), "r1")

total = 23
print(f"\n{total - failures} of {total} checks passed.")
sys.exit(1 if failures else 0)
