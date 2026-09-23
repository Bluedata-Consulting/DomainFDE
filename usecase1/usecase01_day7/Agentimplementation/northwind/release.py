"""Releases: the model, the instructions and the policies, versioned as one (Day 7: Operate).

An agent's behaviour depends on more than its code. A new model, a one-line prompt
edit or an updated policy can change what it does with no code change at all. So all
of them are released together, as one numbered release:

    releases/
        CURRENT              the tag of the release the agents run, such as r1
        HISTORY.log          every promotion and rollback, with the time
        r1/
            release.yaml     tag, model, notes, status, tool settings, fingerprints
            instructions/    what each agent is told
            policies/        the documents the knowledge agent searches

Every trace span and every line of runs.jsonl carries the release tag, so any answer
can be traced back to exactly what produced it.

Fingerprints are content hashes of every file in the release, and of the code the
release was tested with. If a file changes after the release was made, the release
no longer matches its fingerprint: an edit was made outside a release.
"""
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parents[1]
RELEASES = KIT / "releases"
CODE_FILES = ["northwind/rules.py", "northwind/tools.py", "northwind/guardrail.py",
              "northwind/semantic_layer.yaml", "northwind/sql.py", "northwind/policy_search.py"]


def current_tag():
    return (RELEASES / "CURRENT").read_text(encoding="utf-8").strip()


def folder(tag=None):
    return RELEASES / (tag or current_tag())


def config(tag=None):
    return yaml.safe_load((folder(tag) / "release.yaml").read_text(encoding="utf-8"))


def instruction(name, tag=None):
    return (folder(tag) / "instructions" / f"{name}.txt").read_text(encoding="utf-8")


def policies_dir(tag=None):
    return folder(tag) / "policies"


def model(tag=None):
    return config(tag).get("model") or os.getenv("AGENT_MODEL", "gemini-2.5-flash")


def tool_setting(tool_name, tag=None):
    """A per-tool operating setting, such as 'timeout'. Read at call time, not at start."""
    return (config(tag).get("tool_settings") or {}).get(tool_name)


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def fingerprints(tag=None):
    f = folder(tag)
    prints = {str(p.relative_to(f)): _hash(p)
              for p in sorted(f.rglob("*")) if p.is_file() and p.name != "release.yaml"
              and not p.name.startswith(".")}
    for code in CODE_FILES:
        prints[f"code/{code}"] = _hash(KIT / code)
    return prints


def drift(tag=None):
    """Files whose content no longer matches the release's recorded fingerprints."""
    recorded = config(tag).get("fingerprints", {})
    now = fingerprints(tag)
    return sorted(k for k in set(recorded) | set(now) if recorded.get(k) != now.get(k))


def write_config(cfg, tag):
    (folder(tag) / "release.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")


def seal(tag):
    """Record the fingerprints of a release as it is now."""
    cfg = config(tag)
    cfg["fingerprints"] = fingerprints(tag)
    write_config(cfg, tag)


def log(line):
    time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(RELEASES / "HISTORY.log", "a", encoding="utf-8") as f:
        f.write(f"{time} | {line}\n")


def all_tags():
    return sorted((p.name for p in RELEASES.iterdir() if (p / "release.yaml").exists()),
                  key=lambda t: int("".join(ch for ch in t if ch.isdigit()) or 0))
