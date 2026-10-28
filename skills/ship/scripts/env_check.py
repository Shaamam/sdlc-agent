#!/usr/bin/env python3
"""Check the tools /ship depends on and cache what was found in userconfig.json.

    env_check.py                 check tools + gh/acli auth, print JSON
    env_check.py --no-auth       skip auth probes (used by the installers)
    env_check.py --write-userconfig --repo-dir DIR --mode symlink|copy

Exit code 0 when everything required is usable, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sdlc_state import home, now_iso, read_json, write_json  # noqa: E402

MIN_VERSIONS = {"git": (2, 30), "gh": (2, 40), "acli": (1, 3)}
REQUIRED = ("git", "gh", "acli")
INSTALL_HINTS = {
    "gh": "https://cli.github.com  (then: gh auth login)",
    "acli": "https://developer.atlassian.com/cloud/acli/guides/install-acli/  (then: acli jira auth login)",
    "claude": "https://docs.claude.com/en/docs/claude-code/setup",
    "git": "https://git-scm.com/downloads",
}


def run(cmd: list[str], timeout: int = 20):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, (res.stdout or "") + (res.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def parse_version(text: str):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    return tuple(int(x) for x in m.groups() if x is not None) if m else None


def check_tool(name: str) -> dict:
    path = shutil.which(name)
    if not path:
        return {"path": None, "version": None, "ok": False, "problem": "not installed"}
    _, out = run([path, "--version"])
    line = next((l for l in out.splitlines() if re.search(r"\d+\.\d+", l)), "")
    ver = parse_version(line)
    info = {"path": path, "version": ".".join(map(str, ver)) if ver else None, "ok": True}
    minimum = MIN_VERSIONS.get(name)
    if minimum and ver and ver[: len(minimum)] < minimum:
        info["ok"] = False
        info["problem"] = f"version {info['version']} is older than {'.'.join(map(str, minimum))}"
    return info


def check_auth(tools: dict) -> dict:
    auth = {}
    if tools["gh"]["ok"]:
        code, out = run([tools["gh"]["path"], "auth", "status"])
        auth["gh"] = {"ok": code == 0, "detail": out.strip().splitlines()[0] if out.strip() else ""}
    if tools["acli"]["ok"]:
        code, out = run([tools["acli"]["path"], "jira", "auth", "status"])
        ok = code == 0 and "unauthorized" not in out.lower() and "not logged" not in out.lower()
        auth["jira"] = {"ok": ok, "detail": " ".join(out.split())[:200]}
    return auth


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--no-auth", action="store_true")
    p.add_argument("--write-userconfig", action="store_true")
    p.add_argument("--repo-dir", default="")
    p.add_argument("--mode", default="")
    p.add_argument("--python-bin", default="", help="interpreter path to record (installer passes a stable path)")
    p.add_argument("--text", action="store_true", help="print a short human summary instead of JSON")
    args = p.parse_args(argv)

    tools = {name: check_tool(name) for name in ("git", "gh", "acli", "claude")}
    errors, warnings = [], []
    for name in REQUIRED:
        if not tools[name]["ok"]:
            errors.append(f"{name}: {tools[name]['problem']}. Install: {INSTALL_HINTS[name]}")
    if not tools["claude"]["ok"]:
        warnings.append(f"claude: not found on PATH. Install: {INSTALL_HINTS['claude']}")

    auth = {} if args.no_auth else check_auth(tools)
    if auth.get("gh") and not auth["gh"]["ok"]:
        errors.append("gh is not logged in. Run: gh auth login")
    if auth.get("jira") and not auth["jira"]["ok"]:
        errors.append("acli is not logged in to Jira. Run: acli jira auth login")

    cfg_path = home() / "userconfig.json"
    cfg = read_json(cfg_path, {}) or {}
    if args.python_bin:
        cfg["python_bin"] = Path(args.python_bin).as_posix()
    elif not cfg.get("python_bin") or not Path(cfg["python_bin"]).exists():
        cfg["python_bin"] = Path(sys.executable).as_posix()
    cfg["tools"] = {k: {"path": v["path"], "version": v["version"]} for k, v in tools.items()}
    cfg["checked_at"] = now_iso()
    if args.write_userconfig:
        cfg["install"] = {"repo_dir": args.repo_dir, "mode": args.mode, "installed_at": now_iso()}
    write_json(cfg_path, cfg)

    out = {
        "ok": not errors,
        "python_bin": cfg["python_bin"],
        "agent_home": home().as_posix(),
        "tools": tools,
        "auth": auth,
        "errors": errors,
        "warnings": warnings,
    }
    if args.text:
        for name, t in tools.items():
            mark = "ok " if t["ok"] else "-- "
            print(f"  {mark}{name:<7} {t['version'] or t.get('problem', '')}")
        for name, a in auth.items():
            print(f"  {'ok ' if a['ok'] else '-- '}{name} auth")
        for e in errors:
            print(f"  ! {e}")
        for w in warnings:
            print(f"  ! {w}")
    else:
        print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
