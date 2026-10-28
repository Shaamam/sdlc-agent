#!/usr/bin/env python3
"""State store for /ship runs.

Layout (huddle-style: append-only raw events + a synthesized bookmark):

    {home}/
        userconfig.json
        active.json                      {repo_path: {ticket, repo, branch, base_branch}}
        {owner}/{repo}/config.json       per-repo memory
        {owner}/{repo}/{TICKET}/state.json
        {owner}/{repo}/{TICKET}/raw/{ts_ms}_{event}.json

{home} is $SDLC_AGENT_HOME or ~/.config/sdlc-agent. Stdlib only.
Every command prints JSON on stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1

PHASES = [
    "preflight", "intake", "clarify", "spec", "tests",
    "build", "review", "pr", "ci", "awaiting_review", "feedback", "merged",
]
STATUSES = {"in_progress", "waiting_user", "blocked", "awaiting_review", "done", "abandoned"}
GUARD_OFF_STATUSES = {"awaiting_review", "done", "abandoned"}
FINISHED_STATUSES = {"done", "abandoned"}

DEFAULT_REPO_CONFIG = {
    "base_branch": "main",
    "branch_prefix": "feature/",
    "commands": {"test": "", "lint": "", "build": ""},
    "jira": {"in_progress_status": "In Progress", "in_review_status": "In Review", "done_status": ""},
    "ci": {"max_fix_attempts": 3, "timeout_minutes": 45},
    "confirmed": False,
}

TICKET_RE = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")


class StateError(Exception):
    pass


def home() -> Path:
    env = os.environ.get("SDLC_AGENT_HOME")
    return Path(env).expanduser() if env else Path.home() / ".config" / "sdlc-agent"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, path)


def deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def set_path(data: dict, dotted: str, value) -> None:
    keys = dotted.split(".")
    cur = data
    for k in keys[:-1]:
        if not isinstance(cur.get(k), dict):
            cur[k] = {}
        cur = cur[k]
    cur[keys[-1]] = value


# ---------------------------------------------------------------- repo identity

def git(cwd: Path, *args: str) -> str:
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise StateError(res.stderr.strip() or f"git {' '.join(args)} failed")
    return res.stdout.strip()


def parse_remote(url: str):
    url = url.strip()
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", url)
    if not m:
        return None
    return m.group(1), m.group(2)


def safe_segment(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", s) or "_"


def repo_info(cwd: Path) -> dict:
    top = Path(git(cwd, "rev-parse", "--show-toplevel")).resolve()
    owner, repo = "local", top.name
    try:
        parsed = parse_remote(git(top, "remote", "get-url", "origin"))
        if parsed:
            owner, repo = parsed
    except StateError:
        pass
    try:
        branch = git(top, "rev-parse", "--abbrev-ref", "HEAD")
    except StateError:
        branch = ""
    return {
        "repo_path": str(top),
        "owner": owner,
        "repo": repo,
        "slug": f"{owner}/{repo}",
        "branch": branch,
        "repo_dir": str(home() / safe_segment(owner) / safe_segment(repo)),
    }


# ---------------------------------------------------------------- tickets

def norm_ticket(ticket: str) -> str:
    t = ticket.strip().upper()
    if not TICKET_RE.match(t):
        raise StateError(f"'{ticket}' is not a Jira key like PROJ-123")
    return t


def ticket_dir(info: dict, ticket: str) -> Path:
    return Path(info["repo_dir"]) / ticket


def state_path(info: dict, ticket: str) -> Path:
    return ticket_dir(info, ticket) / "state.json"


def load_state(info: dict, ticket: str) -> dict:
    st = read_json(state_path(info, ticket))
    if st is None:
        raise StateError(f"no run for {ticket} in {info['slug']}; start one with init")
    return st


def save_state(info: dict, st: dict) -> dict:
    st["updated_at"] = now_iso()
    write_json(state_path(info, st["ticket"]), st)
    return st


def add_event(info: dict, ticket: str, etype: str, data: dict | None = None) -> Path:
    raw = ticket_dir(info, ticket) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    etype = safe_segment(etype)
    ts = int(time.time() * 1000)
    path = raw / f"{ts}_{etype}.json"
    n = 1
    while path.exists():
        path = raw / f"{ts}-{n}_{etype}.json"
        n += 1
    write_json(path, {"type": etype, "ts": ts, "at": now_iso(), "ticket": ticket, "data": data or {}})
    return path


def new_state(info: dict, ticket: str, base_branch: str) -> dict:
    ts = now_iso()
    return {
        "schema": SCHEMA,
        "ticket": ticket,
        "repo": info["slug"],
        "repo_path": info["repo_path"],
        "summary": "",
        "branch": "",
        "base_branch": base_branch,
        "phase": "preflight",
        "status": "in_progress",
        "phases": {"preflight": {"status": "in_progress", "started_at": ts}},
        "approvals": {},
        "pr": {"number": None, "url": None},
        "review_loops": 0,
        "ci": {"fix_attempts": 0, "reruns": {}, "last_result": None},
        "review": {"rounds": 0, "handled_ids": []},
        "created_at": ts,
        "updated_at": ts,
    }


# ---------------------------------------------------------------- active runs

def active_path() -> Path:
    return home() / "active.json"


def activate(info: dict, st: dict) -> None:
    active = read_json(active_path(), {}) or {}
    active[st["repo_path"]] = {
        "ticket": st["ticket"],
        "repo": st["repo"],
        "branch": st.get("branch", ""),
        "base_branch": st.get("base_branch", "main"),
        "since": now_iso(),
    }
    write_json(active_path(), active)


def deactivate(info: dict, ticket: str) -> None:
    active = read_json(active_path(), {}) or {}
    rp = info["repo_path"]
    if rp in active and active[rp].get("ticket") == ticket:
        del active[rp]
        write_json(active_path(), active)


# ---------------------------------------------------------------- repo config

def config_path(info: dict) -> Path:
    return Path(info["repo_dir"]) / "config.json"


def load_config(info: dict) -> dict:
    return deep_merge(DEFAULT_REPO_CONFIG, read_json(config_path(info), {}) or {})


# ---------------------------------------------------------------- commands

def cmd_repo_info(info, args):
    return info


def cmd_init(info, args):
    ticket = norm_ticket(args.ticket)
    existing = read_json(state_path(info, ticket))
    if existing:
        if existing.get("status") in FINISHED_STATUSES:
            return {"resumed": False, "finished": True, "state": existing, "dir": str(ticket_dir(info, ticket))}
        add_event(info, ticket, "run_resumed", {"phase": existing.get("phase")})
        if existing.get("status") not in GUARD_OFF_STATUSES:
            activate(info, existing)
        return {"resumed": True, "state": existing, "dir": str(ticket_dir(info, ticket))}
    cfg = load_config(info)
    st = new_state(info, ticket, cfg["base_branch"])
    save_state(info, st)
    add_event(info, ticket, "run_started", {"repo": info["slug"]})
    activate(info, st)
    return {"resumed": False, "state": st, "dir": str(ticket_dir(info, ticket)), "config": cfg}


def cmd_get(info, args):
    ticket = norm_ticket(args.ticket)
    return {"state": load_state(info, ticket), "dir": str(ticket_dir(info, ticket))}


def cmd_phase(info, args):
    ticket = norm_ticket(args.ticket)
    if args.phase not in PHASES:
        raise StateError(f"unknown phase '{args.phase}'; expected one of {', '.join(PHASES)}")
    st = load_state(info, ticket)
    ts = now_iso()
    prev = st.get("phase")
    if prev and prev != args.phase and prev in st["phases"]:
        if st["phases"][prev].get("status") != "done":
            st["phases"][prev]["status"] = "done"
            st["phases"][prev]["ended_at"] = ts
            add_event(info, ticket, "phase_done", {"phase": prev})
    st["phase"] = args.phase
    entry = st["phases"].setdefault(args.phase, {})
    entry["status"] = "in_progress"
    entry.setdefault("started_at", ts)
    entry["entered"] = entry.get("entered", 0) + 1
    if args.phase in {"awaiting_review", "merged"}:
        entry["status"] = "done" if args.phase == "merged" else "in_progress"
        if args.phase == "merged":
            entry["ended_at"] = ts
        st["status"] = "done" if args.phase == "merged" else "awaiting_review"
        deactivate(info, ticket)
        add_event(info, ticket, args.phase, {"pr": st.get("pr")})
    else:
        if args.phase == "feedback":
            review = st.setdefault("review", {"rounds": 0, "handled_ids": []})
            review["rounds"] = review.get("rounds", 0) + 1
            st["review_loops"] = 0
            st["ci"]["fix_attempts"] = 0
            st["ci"]["reruns"] = {}
        st["status"] = "in_progress"
        activate(info, st)
        add_event(info, ticket, "phase_started", {"phase": args.phase})
    save_state(info, st)
    return {"state": st}


def cmd_status(info, args):
    ticket = norm_ticket(args.ticket)
    if args.status not in STATUSES:
        raise StateError(f"unknown status '{args.status}'; expected one of {', '.join(sorted(STATUSES))}")
    st = load_state(info, ticket)
    st["status"] = args.status
    if args.reason:
        st["status_reason"] = args.reason
    else:
        st.pop("status_reason", None)
    if args.status in GUARD_OFF_STATUSES:
        deactivate(info, ticket)
    else:
        activate(info, st)
    add_event(info, ticket, args.status if args.status in {"blocked", "done", "abandoned"} else "status_changed",
              {"status": args.status, "reason": args.reason or ""})
    save_state(info, st)
    return {"state": st}


def cmd_set(info, args):
    ticket = norm_ticket(args.ticket)
    st = load_state(info, ticket)
    changed = {}
    for pair in args.pairs:
        if "=" not in pair:
            raise StateError(f"expected key=value, got '{pair}'")
        key, raw = pair.split("=", 1)
        if key.split(".")[0] in {"ticket", "schema", "repo_path"}:
            raise StateError(f"'{key}' is read-only")
        val = parse_value(raw)
        set_path(st, key, val)
        changed[key] = val
    save_state(info, st)
    if any(k in changed for k in ("branch", "base_branch")) and st.get("status") not in GUARD_OFF_STATUSES:
        activate(info, st)
    return {"state": st, "changed": changed}


def cmd_event(info, args):
    ticket = norm_ticket(args.ticket)
    load_state(info, ticket)
    data = parse_value(args.data) if args.data else {}
    if not isinstance(data, dict):
        data = {"value": data}
    path = add_event(info, ticket, args.type, data)
    return {"event": str(path)}


def cmd_approve(info, args):
    ticket = norm_ticket(args.ticket)
    st = load_state(info, ticket)
    st.setdefault("approvals", {})[args.what] = now_iso()
    save_state(info, st)
    add_event(info, ticket, f"{args.what}_approved", {})
    return {"state": st}


def cmd_ci_attempt(info, args):
    ticket = norm_ticket(args.ticket)
    st = load_state(info, ticket)
    cfg = load_config(info)
    max_attempts = int(cfg["ci"].get("max_fix_attempts", 3))
    attempts = int(st["ci"].get("fix_attempts", 0))
    if attempts >= max_attempts:
        return {"allowed": False, "attempts": attempts, "max": max_attempts}
    st["ci"]["fix_attempts"] = attempts + 1
    save_state(info, st)
    add_event(info, ticket, "ci_fix_attempt", {"attempt": attempts + 1})
    return {"allowed": True, "attempts": attempts + 1, "max": max_attempts}


def cmd_ci_rerun(info, args):
    ticket = norm_ticket(args.ticket)
    st = load_state(info, ticket)
    reruns = st["ci"].setdefault("reruns", {})
    if reruns.get(args.check, 0) >= 1:
        return {"allowed": False, "check": args.check, "reruns": reruns[args.check]}
    reruns[args.check] = reruns.get(args.check, 0) + 1
    save_state(info, st)
    add_event(info, ticket, "ci_rerun", {"check": args.check})
    return {"allowed": True, "check": args.check, "reruns": reruns[args.check]}


def cmd_handled(info, args):
    ticket = norm_ticket(args.ticket)
    st = load_state(info, ticket)
    review = st.setdefault("review", {"rounds": 0, "handled_ids": []})
    ids = review.setdefault("handled_ids", [])
    added = [i for i in args.ids if i not in ids]
    ids.extend(added)
    save_state(info, st)
    if added:
        add_event(info, ticket, "feedback_handled", {"ids": added})
    return {"handled": added, "total": len(ids)}


def cmd_list(info, args):
    root = Path(info["repo_dir"])
    runs = []
    if root.is_dir():
        for d in sorted(root.iterdir()):
            st = read_json(d / "state.json") if d.is_dir() else None
            if not st:
                continue
            if not args.all and st.get("status") in {"done", "abandoned"}:
                continue
            runs.append({
                "ticket": st["ticket"], "summary": st.get("summary", ""), "phase": st.get("phase"),
                "status": st.get("status"), "pr": (st.get("pr") or {}).get("url"),
                "updated_at": st.get("updated_at"),
            })
    return {"repo": info["slug"], "runs": runs}


def cmd_config(info, args):
    cfg = load_config(info)
    if args.action == "get":
        return {"config": cfg, "exists": config_path(info).exists(), "path": str(config_path(info))}
    stored = read_json(config_path(info), {}) or {}
    for pair in args.pairs or []:
        if "=" not in pair:
            raise StateError(f"expected key=value, got '{pair}'")
        key, raw = pair.split("=", 1)
        set_path(stored, key, parse_value(raw))
    write_json(config_path(info), stored)
    return {"config": load_config(info), "path": str(config_path(info))}


def cmd_paths(info, args):
    ticket = norm_ticket(args.ticket)
    d = ticket_dir(info, ticket)
    return {
        "dir": str(d), "state": str(d / "state.json"), "spec": str(d / "spec.md"),
        "ticket_json": str(d / "ticket.json"), "clarifications": str(d / "clarifications.md"),
        "review": str(d / "review.md"), "raw": str(d / "raw"),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sdlc_state", description=__doc__.splitlines()[0])
    p.add_argument("--cwd", default=".", help="path inside the target git repo")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("repo-info").set_defaults(fn=cmd_repo_info)

    s = sub.add_parser("init"); s.add_argument("ticket"); s.set_defaults(fn=cmd_init)
    s = sub.add_parser("get"); s.add_argument("ticket"); s.set_defaults(fn=cmd_get)
    s = sub.add_parser("paths"); s.add_argument("ticket"); s.set_defaults(fn=cmd_paths)

    s = sub.add_parser("phase"); s.add_argument("ticket"); s.add_argument("phase"); s.set_defaults(fn=cmd_phase)

    s = sub.add_parser("status"); s.add_argument("ticket"); s.add_argument("status")
    s.add_argument("--reason", default=""); s.set_defaults(fn=cmd_status)

    s = sub.add_parser("set"); s.add_argument("ticket"); s.add_argument("pairs", nargs="+"); s.set_defaults(fn=cmd_set)

    s = sub.add_parser("event"); s.add_argument("ticket"); s.add_argument("type")
    s.add_argument("--data", default=""); s.set_defaults(fn=cmd_event)

    s = sub.add_parser("approve"); s.add_argument("ticket")
    s.add_argument("what", choices=["clarifications", "spec"]); s.set_defaults(fn=cmd_approve)

    s = sub.add_parser("ci-attempt"); s.add_argument("ticket"); s.set_defaults(fn=cmd_ci_attempt)
    s = sub.add_parser("ci-rerun"); s.add_argument("ticket"); s.add_argument("check"); s.set_defaults(fn=cmd_ci_rerun)

    s = sub.add_parser("handled"); s.add_argument("ticket"); s.add_argument("ids", nargs="+"); s.set_defaults(fn=cmd_handled)

    s = sub.add_parser("list"); s.add_argument("--all", action="store_true"); s.set_defaults(fn=cmd_list)

    s = sub.add_parser("config"); s.add_argument("action", choices=["get", "set"])
    s.add_argument("pairs", nargs="*"); s.set_defaults(fn=cmd_config)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        info = repo_info(Path(args.cwd).resolve())
        out = args.fn(info, args)
    except StateError as e:
        print(json.dumps({"error": str(e)}))
        return 1
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
