#!/usr/bin/env python3
"""Add or remove the sdlc-agent PreToolUse hook in a Claude Code settings.json.

    settings_merge.py install   --settings PATH --python PY --hook GUARD_PY
    settings_merge.py uninstall --settings PATH

The hook command is built here (not by the installers) so Windows PowerShell 5.1
never has to pass an argument containing double quotes to a native program.

Our entries are recognised by MARKER in the hook command, so nothing else in
the file is touched. A timestamped backup is written before any change.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

MARKER = "hooks/sdlc-agent/guard.py"
MATCHER = "Bash|Edit|Write|MultiEdit|NotebookEdit"


def hook_command(python: str, hook: str) -> str:
    def fwd(p: str) -> str:
        return p.replace("\\", "/")
    return f'"{fwd(python)}" "{fwd(hook)}"'


def is_ours(hook: dict) -> bool:
    return MARKER in str(hook.get("command", "")).replace("\\", "/")


def strip_ours(settings: dict) -> dict:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return settings
    groups = hooks.get("PreToolUse")
    if isinstance(groups, list):
        kept = []
        for g in groups:
            if not isinstance(g, dict):
                kept.append(g)
                continue
            inner = [h for h in g.get("hooks", []) if not (isinstance(h, dict) and is_ours(h))]
            if inner:
                kept.append(dict(g, hooks=inner))
            elif not g.get("hooks"):
                kept.append(g)
        if kept:
            hooks["PreToolUse"] = kept
        else:
            hooks.pop("PreToolUse", None)
    if not hooks:
        settings.pop("hooks", None)
    return settings


def add_ours(settings: dict, command: str) -> dict:
    settings = strip_ours(settings)
    hooks = settings.setdefault("hooks", {})
    hooks.setdefault("PreToolUse", []).append({
        "matcher": MATCHER,
        "hooks": [{"type": "command", "command": command, "timeout": 15}],
    })
    return settings


def load(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.sdlc-agent.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def backup(path: Path):
    if not path.exists():
        return None
    dest = path.with_name(f"{path.name}.sdlc-agent-backup-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    shutil.copy2(path, dest)
    return dest


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["install", "uninstall"])
    p.add_argument("--settings", required=True)
    p.add_argument("--python", default="")
    p.add_argument("--hook", default="")
    args = p.parse_args(argv)

    path = Path(args.settings).expanduser()
    try:
        data = load(path)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"error: cannot parse {path}: {e}. Fix it by hand; nothing was changed.", file=sys.stderr)
        return 1

    if args.action == "install":
        if not args.python or not args.hook:
            print("error: --python and --hook are required for install", file=sys.stderr)
            return 1
        new = add_ours(json.loads(json.dumps(data)), hook_command(args.python, args.hook))
    else:
        new = strip_ours(json.loads(json.dumps(data)))

    if new == data:
        print(f"settings unchanged: {path}")
        return 0
    if args.action == "uninstall" and not path.exists():
        return 0
    bak = backup(path)
    if new or path.exists():
        save(path, new)
    print(f"settings updated: {path}" + (f" (backup: {bak})" if bak else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
