#!/usr/bin/env python3
"""Wait for a PR's CI checks to finish and summarize the result as JSON.

    ci_watch.py --pr 42 [--expect-sha SHA] [--ticket PROJ-123] [--cwd .]
                [--interval 30] [--grace-seconds 180] [--timeout-minutes 45] [--fail-fast]

result: passed | failed | no_checks | timeout | error
Exit code: 0 passed/no_checks, 1 failed, 2 timeout/error.
Run it in the background; it only polls `gh` and never changes anything except
recording a ci_result event when --ticket is given.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

FIELDS = "name,state,bucket,link,workflow,startedAt,completedAt"
RUN_RE = re.compile(r"/actions/runs/(\d+)(?:/job/(\d+))?")


def gh(cwd: str, *args: str):
    res = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr


def summarize(checks: list[dict]) -> dict:
    buckets = {"pass": [], "fail": [], "pending": [], "skipping": [], "cancel": []}
    for c in checks:
        buckets.setdefault(c.get("bucket") or "pending", []).append(c)
    failed = []
    for c in buckets["fail"] + buckets["cancel"]:
        m = RUN_RE.search(c.get("link") or "")
        failed.append({
            "name": c.get("name"),
            "workflow": c.get("workflow"),
            "bucket": c.get("bucket"),
            "link": c.get("link"),
            "run_id": m.group(1) if m else None,
            "job_id": m.group(2) if m and m.group(2) else None,
        })
    if buckets["pending"]:
        result = "pending"
    elif failed:
        result = "failed"
    else:
        result = "passed"
    return {
        "result": result,
        "counts": {k: len(v) for k, v in buckets.items()},
        "failed": failed,
        "pending": [c.get("name") for c in buckets["pending"]],
    }


def head_sha(cwd: str, pr: str):
    code, out, _ = gh(cwd, "pr", "view", pr, "--json", "headRefOid", "-q", ".headRefOid")
    return out.strip() if code == 0 else None


def fetch_checks(cwd: str, pr: str):
    code, out, err = gh(cwd, "pr", "checks", pr, "--json", FIELDS)
    text = (out or "").strip()
    if text.startswith("["):
        return json.loads(text), None
    if "no checks reported" in (err + out).lower():
        return [], None
    if code != 0:
        return None, (err or out).strip()
    return [], None


def watch(args) -> dict:
    deadline = time.monotonic() + args.timeout_minutes * 60
    started = time.monotonic()

    if args.expect_sha:
        while True:
            sha = head_sha(args.cwd, args.pr)
            if sha and sha.startswith(args.expect_sha):
                break
            if time.monotonic() - started > args.grace_seconds:
                return {"result": "error", "detail": f"PR head is {sha}, expected {args.expect_sha}; was the push received?"}
            time.sleep(min(args.interval, 10))

    errors = 0
    while True:
        checks, err = fetch_checks(args.cwd, args.pr)
        if checks is None:
            errors += 1
            if errors >= 5:
                return {"result": "error", "detail": err}
        else:
            errors = 0
            if not checks:
                if time.monotonic() - started > args.grace_seconds:
                    return {"result": "no_checks", "counts": {}, "failed": [], "pending": []}
            else:
                summary = summarize(checks)
                if summary["result"] != "pending":
                    return summary
                if args.fail_fast and summary["failed"]:
                    summary["result"] = "failed"
                    summary["note"] = "fail-fast: some checks still pending"
                    return summary
        if time.monotonic() > deadline:
            out = summarize(checks) if checks else {"counts": {}, "failed": [], "pending": []}
            out["result"] = "timeout"
            return out
        time.sleep(args.interval)


def record(args, out: dict) -> None:
    if not args.ticket:
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sdlc_state as s
    info = s.repo_info(Path(args.cwd).resolve())
    ticket = s.norm_ticket(args.ticket)
    st = s.load_state(info, ticket)
    st["ci"]["last_result"] = {"result": out["result"], "at": s.now_iso(), "failed": [f["name"] for f in out.get("failed", [])]}
    s.save_state(info, st)
    s.add_event(info, ticket, "ci_result", {"pr": args.pr, **out})


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pr", required=True)
    p.add_argument("--cwd", default=".")
    p.add_argument("--expect-sha", default="")
    p.add_argument("--ticket", default="")
    p.add_argument("--interval", type=int, default=30)
    p.add_argument("--grace-seconds", type=int, default=180)
    p.add_argument("--timeout-minutes", type=float, default=45)
    p.add_argument("--fail-fast", action="store_true")
    args = p.parse_args(argv)

    out = watch(args)
    out["pr"] = args.pr
    try:
        record(args, out)
    except Exception as e:  # state recording must never hide the CI result
        out["record_error"] = str(e)
    print(json.dumps(out, indent=2))
    return {"passed": 0, "no_checks": 0, "failed": 1}.get(out["result"], 2)


if __name__ == "__main__":
    sys.exit(main())
