#!/usr/bin/env python3
"""Print which calls in a list the project's kortix.yaml would hold.

Kortix is the open-source AI Operating System; this script is a reading
aid for reviewers, not the enforcement point. The platform evaluates the
same rules at call time, and its decision is the one that counts.

What it does: loads the policy-relevant keys from a kortix.yaml (project
`policy.default_mode`, `approvals.ttl` and project-wide `policies`), then
resolves each call in a JSON fixture against them with the documented
order: project-wide rules first, first match wins, default_mode as the
fallback. Output is one table row per call.

Usage:
    python3 check_policy.py                       # kortix.yaml + the fixture
    python3 check_policy.py --policy kortix.yaml --calls examples/support-calls.json
    python3 check_policy.py --json                # the same rows as JSON

Limits, stated so nobody trusts it further than it goes:
  * stdlib only, and the parser understands only the keys above. Any other
    top-level key is ignored, which is safe because rules live under
    `policies:`.
  * Connector-level `policies:` blocks are not read. This manifest keeps
    every rule project-wide.
  * `default_mode: risk` needs a read/write split. The split here is a verb
    heuristic over the action after the dot (get/list/search/read/find/... are
    reads). The platform classifies each action from the connector's own
    tool list; if the two disagree, the platform is right.
  * A condition's `match` is a glob (fnmatch) against one argument, so it
    cannot express a range. Amount thresholds belong in a separate rule,
    not in a glob.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

READ_VERBS = {
    "get", "list", "search", "read", "lookup", "look", "retrieve", "find",
    "fetch", "describe", "inspect", "query", "count", "check",
}
DECISIONS = {"always_run": "run", "require_approval": "hold", "block": "block"}


def strip_comment(line: str) -> str:
    """Drop a trailing comment. No quoted '#', which is true of every key
    this parser reads; a '#' inside an argument cannot reach these lines."""
    if "#" in line:
        return line[: line.index("#")]
    return line


def parse_policy(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    default_mode, ttl, rules = "allow_all", "24h", []
    block = None          # "policy" | "approvals" | "policies"
    rule = None           # the policy row being built
    cond = None           # the condition row being built
    for raw in lines:
        line = strip_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        body = line.strip()
        if indent == 0:
            block, rule, cond = None, None, None
            if body.startswith("policy:"):
                block = "policy"
            elif body.startswith("approvals:"):
                block = "approvals"
            elif body.startswith("policies:"):
                block = "policies"
            continue
        if block == "policy" and body.startswith("default_mode:"):
            default_mode = body.split(":", 1)[1].strip()
        elif block == "approvals" and body.startswith("ttl:"):
            ttl = body.split(":", 1)[1].strip()
        elif block == "policies":
            # A rule starts at the list's own indent (2); deeper bullets are
            # a rule's conditions.
            if body.startswith("- ") and indent <= 2:
                if rule:
                    rules.append(rule)
                rule = {"match": "", "action": "", "conditions": []}
                cond = None
                body = body[2:].strip()
            if rule is None:
                continue
            if body.startswith("match:") and not cond and indent <= 4:
                rule["match"] = body.split(":", 1)[1].strip().strip('"\'')
            elif body.startswith("action:"):
                rule["action"] = body.split(":", 1)[1].strip().strip('"\'')
            elif body.startswith("conditions:"):
                cond = None
            elif body.startswith("- ") or (cond and body.startswith("arg:")):
                if body.startswith("- "):
                    cond = {}
                    rule["conditions"].append(cond)
                    body = body[2:].strip()
                if cond is not None and body.startswith("arg:"):
                    cond["arg"] = body.split(":", 1)[1].strip().strip('"\'')
            elif body.startswith("match:") and cond is not None:
                cond["match"] = body.split(":", 1)[1].strip().strip('"\'')
    if rule:
        rules.append(rule)
    return {"default_mode": default_mode, "approvals_ttl": ttl, "rules": rules}


def matches(call: dict, rule: dict) -> bool:
    if not fnmatch.fnmatchcase(call["tool"], rule["match"]):
        return False
    for c in rule.get("conditions") or []:
        value = (call.get("args") or {}).get(c.get("arg", ""))
        if value is None or not fnmatch.fnmatchcase(str(value), c.get("match", "")):
            return False
    return True


def looks_like_write(tool: str) -> bool:
    verb = tool.rsplit(".", 1)[-1].split("_")[0]
    return verb not in READ_VERBS


def resolve(call: dict, policy: dict) -> tuple[str, str]:
    for rule in policy["rules"]:
        if matches(call, rule):
            return DECISIONS[rule["action"]], f"rule {rule['match']}" + (
                " + condition" if rule.get("conditions") else "")
    if policy["default_mode"] == "risk" and looks_like_write(call["tool"]):
        return "hold", "default_mode: risk (write)"
    return "run", "default_mode: risk (read)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--policy", default="kortix.yaml")
    ap.add_argument("--calls", default="examples/support-calls.json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    policy = parse_policy(Path(a.policy))
    calls = json.loads(Path(a.calls).read_text(encoding="utf-8"))
    rows = []
    for call in calls:
        decision, why = resolve(call, policy)
        rows.append({"call": call["tool"], "decision": decision, "because": why})
    if a.json:
        print(json.dumps({"policy": policy, "rows": rows}, indent=2))
        return 0
    width = max(len(r["call"]) for r in rows)
    print(f"default_mode: {policy['default_mode']}   "
          f"approvals.ttl: {policy['approvals_ttl']}")
    print(f"{'call'.ljust(width)}  {'decision':<8}  because")
    for r in rows:
        print(f"{r['call'].ljust(width)}  {r['decision']:<8}  {r['because']}")
    counts = {d: sum(1 for r in rows if r["decision"] == d)
              for d in ("run", "hold", "block")}
    print(f"\n{len(rows)} calls: {counts['run']} run without a person, "
          f"{counts['hold']} wait for one, {counts['block']} blocked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
