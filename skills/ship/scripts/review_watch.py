#!/usr/bin/env python3
"""Watch an open PR until something needs the agent, then report it as JSON.

    review_watch.py --pr 42 --ticket PROJ-123 [--cwd .] [--interval 120] [--timeout-minutes 480]

result:
  merged     the PR was merged (run is done)
  closed     the PR was closed without merging
  feedback   new review feedback not yet handled (see "items")
  conflict   the PR conflicts with its base branch
  behind     approved but the branch is behind its base, which blocks the merge
  timeout    nothing happened; start the watcher again
  error      gh kept failing (see "detail")

Feedback already handled is listed in state.json review.handled_ids. Replies the
agent posts carry AGENT_MARKER and are never treated as feedback. Read-only:
it never changes the PR.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sdlc_state as s  # noqa: E402

AGENT_MARKER = "<!-- sdlc-agent -->"
PR_FIELDS = "state,mergedAt,mergeable,mergeStateStatus,reviewDecision,headRefOid,url,author"


class GhError(Exception):
    pass


def gh_json(cwd: str, *args: str):
    res = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True)
    if res.returncode != 0:
        raise GhError((res.stderr or res.stdout).strip())
    return json.loads(res.stdout or "null")


def gh_pages(cwd: str, path: str) -> list:
    items, page = [], 1
    while True:
        sep = "&" if "?" in path else "?"
        batch = gh_json(cwd, "api", f"{path}{sep}per_page=100&page={page}")
        if not batch:
            return items
        items.extend(batch)
        if len(batch) < 100:
            return items
        page += 1


def is_bot(user: dict) -> bool:
    return (user or {}).get("type") == "Bot" or (user or {}).get("login", "").endswith("[bot]")


def collect_feedback(reviews: list, inline: list, conversation: list, handled: set) -> dict:
    """Pure: turn raw GitHub payloads into unhandled, actionable feedback items."""
    items, bots = [], []

    def consider(kind: str, raw: dict, body: str, **extra):
        key = f"{kind}:{raw.get('id')}"
        if key in handled or AGENT_MARKER in (body or ""):
            return
        user = raw.get("user") or {}
        entry = {"id": key, "kind": kind, "author": user.get("login", ""), "body": (body or "").strip(),
                 "url": raw.get("html_url", ""), **extra}
        (bots if is_bot(user) else items).append(entry)

    for r in reviews:
        state = r.get("state")
        if state in {"APPROVED", "DISMISSED", "PENDING"} or not (r.get("body") or "").strip():
            continue
        consider("review", r, r.get("body"), review_state=state)
    for c in inline:
        consider("inline", c, c.get("body"), path=c.get("path"), line=c.get("line") or c.get("original_line"),
                 in_reply_to=c.get("in_reply_to_id"), review_id=c.get("pull_request_review_id"))
    for c in conversation:
        consider("conversation", c, c.get("body"))

    changes_requested_by = sorted({(r.get("user") or {}).get("login", "") for r in reviews
                                   if r.get("state") == "CHANGES_REQUESTED"} - {""})
    return {"items": items, "bot_items": bots, "changes_requested_by": changes_requested_by}


def decide(pr: dict, feedback: dict):
    """Pure: what should wake the agent, or None to keep waiting."""
    if pr.get("state") == "MERGED" or pr.get("mergedAt"):
        return "merged"
    if pr.get("state") == "CLOSED":
        return "closed"
    if feedback["items"]:
        return "feedback"
    if pr.get("mergeable") == "CONFLICTING" or pr.get("mergeStateStatus") == "DIRTY":
        return "conflict"
    if pr.get("reviewDecision") == "APPROVED" and pr.get("mergeStateStatus") == "BEHIND":
        return "behind"
    return None


def poll_once(cwd: str, slug: str, number: str, handled: set):
    pr = gh_json(cwd, "pr", "view", number, "--json", PR_FIELDS)
    base = f"repos/{slug}"
    feedback = collect_feedback(
        gh_pages(cwd, f"{base}/pulls/{number}/reviews"),
        gh_pages(cwd, f"{base}/pulls/{number}/comments"),
        gh_pages(cwd, f"{base}/issues/{number}/comments"),
        handled,
    )
    return pr, feedback


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pr", required=True)
    p.add_argument("--ticket", required=True)
    p.add_argument("--cwd", default=".")
    p.add_argument("--interval", type=int, default=120)
    p.add_argument("--timeout-minutes", type=float, default=480)
    p.add_argument("--once", action="store_true", help="poll once and report, even if nothing happened")
    args = p.parse_args(argv)

    info = s.repo_info(Path(args.cwd).resolve())
    ticket = s.norm_ticket(args.ticket)
    deadline = time.monotonic() + args.timeout_minutes * 60
    errors = 0
    out = {"result": "timeout"}

    while True:
        st = s.load_state(info, ticket)
        handled = set((st.get("review") or {}).get("handled_ids", []))
        try:
            pr, feedback = poll_once(args.cwd, info["slug"], args.pr, handled)
            errors = 0
        except (GhError, json.JSONDecodeError) as e:
            errors += 1
            if errors >= 5:
                out = {"result": "error", "detail": str(e)}
                break
        else:
            result = decide(pr, feedback)
            out = {"result": result or ("waiting" if args.once else "timeout"), "pr": pr, **feedback}
            if result or args.once:
                break
        if time.monotonic() > deadline:
            out["result"] = "timeout"
            break
        time.sleep(args.interval)

    if out["result"] not in {"timeout", "waiting"}:
        s.add_event(info, ticket, "review_watch", {"result": out["result"],
                                                    "items": [i["id"] for i in out.get("items", [])]})
    print(json.dumps(out, indent=2))
    return 0 if out["result"] != "error" else 2


if __name__ == "__main__":
    sys.exit(main())
