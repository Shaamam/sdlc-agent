#!/usr/bin/env python3
"""PreToolUse guardrail for /ship runs.

Does nothing unless a /ship run is active for the repo containing the tool
call's cwd (see active.json). While active it blocks, via exit code 2:
  - edits to .github/workflows/
  - adding test-skip markers, deleting test files
  - --no-verify / git commit -n
  - pushing to the base branch, main or master, and any force push
  - gh pr merge, gh pr review --approve, merges through gh api, gh workflow disable

Fails open: an internal error never blocks the developer's tool call.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ALWAYS_PROTECTED = {"main", "master"}

SKIP_MARKERS = [
    r"\b(?:it|test|describe|context|suite)\.skip\s*\(",
    r"\bx(?:it|test|describe|context)\s*\(",
    r"@pytest\.mark\.skip",
    r"\bpytest\.skip\s*\(",
    r"@unittest\.skip",
    r"\bself\.skipTest\s*\(",
    r"@Disabled\b",
    r"@Ignore\b",
    r"\bt\.Skip(?:Now|f)?\s*\(",
    r"#\[ignore\]",
    r"\[Ignore\]",
    r"\[(?:Fact|Theory)\s*\(\s*Skip\s*=",
]
SKIP_RE = re.compile("|".join(SKIP_MARKERS))

TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|specs?)/"
    r"|(^|/)test_[^/]+$"
    r"|_test\.[^/]+$"
    r"|\.(test|spec)\.[^/]+$"
    r"|(Test|Tests|IT)\.(java|kt|cs|scala)$"
    r"|_spec\.rb$"
)

WRITE_TOOLS = {"rm", "unlink", "mv", "cp", "tee", "truncate", "touch", "dd", "install", "ln", "chmod"}
SEGMENT_SPLIT = re.compile(r"\|\||&&|;|\||\n|&")


class Block(Exception):
    pass


def agent_home() -> Path:
    env = os.environ.get("SDLC_AGENT_HOME")
    return Path(env).expanduser() if env else Path.home() / ".config" / "sdlc-agent"


def norm(p: str) -> str:
    return p.replace("\\", "/")


def find_active_run(cwd: str):
    try:
        with open(agent_home() / "active.json", encoding="utf-8") as f:
            active = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    try:
        here = Path(cwd).resolve()
    except OSError:
        return None
    for repo_path, run in (active or {}).items():
        try:
            root = Path(repo_path).resolve()
        except OSError:
            continue
        if here == root or root in here.parents:
            return dict(run, repo_path=str(root))
    return None


def is_workflow_path(p: str) -> bool:
    p = norm(p)
    return "/.github/workflows/" in p or p.startswith(".github/workflows/") or p.endswith("/.github/workflows")


def is_test_path(p: str) -> bool:
    return bool(TEST_PATH_RE.search(norm(p)))


def count_skips(text: str) -> int:
    return len(SKIP_RE.findall(text or ""))


# ---------------------------------------------------------------- file tools

def check_file_tool(tool: str, ti: dict) -> None:
    path = ti.get("file_path") or ti.get("notebook_path") or ""
    if path and is_workflow_path(path):
        raise Block(f"editing CI workflow files ({path}) is not allowed during /ship; ask the developer")

    if tool == "Edit":
        pairs = [(ti.get("old_string", ""), ti.get("new_string", ""))]
    elif tool == "MultiEdit":
        pairs = [(e.get("old_string", ""), e.get("new_string", "")) for e in ti.get("edits", [])]
    elif tool == "Write":
        old = ""
        try:
            old = Path(path).read_text(encoding="utf-8", errors="ignore") if path else ""
        except OSError:
            pass
        pairs = [(old, ti.get("content", ""))]
    elif tool == "NotebookEdit":
        pairs = [("", ti.get("new_source", ""))]
    else:
        return
    for old, new in pairs:
        if count_skips(new) > count_skips(old):
            raise Block("adding a test-skip marker is not allowed during /ship; fix the test or code, or ask the developer")


# ---------------------------------------------------------------- bash

def split_segments(command: str) -> list[list[str]]:
    segments = []
    for raw in SEGMENT_SPLIT.split(command):
        raw = raw.strip()
        if not raw:
            continue
        try:
            toks = shlex.split(raw, posix=True)
        except ValueError:
            toks = raw.split()
        while toks and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]) or toks[0] in {"sudo", "command", "env", "exec", "time"}):
            toks = toks[1:]
        if toks:
            toks[0] = os.path.basename(toks[0])
            if toks[0].lower().endswith(".exe"):
                toks[0] = toks[0][:-4]
            segments.append(toks)
    return segments


def git_subcommand(toks: list[str]):
    i = 1
    while i < len(toks):
        t = toks[i]
        if t in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}:
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return t, toks[i + 1:]
    return None, []


def current_branch(cwd: str) -> str:
    try:
        res = subprocess.run(["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return res.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def short_flag_has(arg: str, letter: str) -> bool:
    return arg.startswith("-") and not arg.startswith("--") and letter in arg[1:]


def check_git(toks: list[str], run: dict, cwd: str) -> None:
    sub, rest = git_subcommand(toks)
    if "--no-verify" in rest:
        raise Block("--no-verify is not allowed during /ship; hooks must run")
    if sub == "commit" and any(a == "-n" or (short_flag_has(a, "n") and len(a) <= 4) for a in rest):
        raise Block("git commit -n skips hooks and is not allowed during /ship")
    if sub == "push":
        protected = ALWAYS_PROTECTED | {run.get("base_branch") or "main"}
        positional = []
        for a in rest:
            if a in {"--all", "--mirror", "--delete", "-d"}:
                raise Block(f"git push {a} is not allowed during /ship")
            if a.startswith("--force") or short_flag_has(a, "f"):
                raise Block("force push is not allowed during /ship")
            if a.startswith("-"):
                continue
            positional.append(a)
        refspecs = positional[1:]
        for spec in refspecs:
            if spec.startswith("+"):
                raise Block("force push (+refspec) is not allowed during /ship")
            dst = spec.split(":", 1)[1] if ":" in spec else spec
            dst = re.sub(r"^refs/heads/", "", dst)
            if dst in protected:
                raise Block(f"pushing to '{dst}' is not allowed during /ship; push the feature branch only")
            if dst == "HEAD" and current_branch(cwd) in protected:
                raise Block("pushing HEAD while on a protected branch is not allowed during /ship")
        if not refspecs and current_branch(cwd) in protected:
            raise Block("you are on a protected branch; /ship pushes only its feature branch")
    if sub in {"rm", "mv"}:
        for a in rest:
            if a.startswith("-"):
                continue
            if is_workflow_path(a):
                raise Block("changing CI workflow files is not allowed during /ship")
            if sub == "rm" and is_test_path(a):
                raise Block(f"deleting test file '{a}' is not allowed during /ship; ask the developer")


def check_gh(toks: list[str]) -> None:
    args = toks[1:]
    words, skip_next = [], False
    for a in args:
        if skip_next:
            skip_next = False
        elif a in {"-R", "--repo", "--hostname"}:
            skip_next = True
        elif not a.startswith("-"):
            words.append(a)
    if words[:2] == ["pr", "merge"]:
        raise Block("the agent never merges; a human reviewer merges")
    if words[:2] == ["pr", "review"] and any(a in {"--approve", "-a"} for a in args):
        raise Block("the agent never approves PRs")
    if words[:2] == ["workflow", "disable"]:
        raise Block("disabling workflows is not allowed during /ship")
    if words[:1] == ["api"] and any(re.search(r"/pulls/\d+/merge\b|/merges\b", a) for a in args):
        raise Block("merging through gh api is not allowed during /ship")


def check_bash(command: str, run: dict, cwd: str) -> None:
    if re.search(r">>?\s*['\"]?[^\s'\"]*\.github/workflows", norm(command)):
        raise Block("writing to CI workflow files is not allowed during /ship")
    for toks in split_segments(command):
        exe = toks[0]
        if exe == "git":
            check_git(toks, run, cwd)
        elif exe == "gh":
            check_gh(toks)
        elif exe in WRITE_TOOLS:
            targets = [t for t in toks[1:] if not t.startswith("-")]
            if exe in {"cp", "install", "ln"}:
                targets = targets[-1:]
            if any(is_workflow_path(t) for t in targets):
                raise Block("changing CI workflow files is not allowed during /ship")
            if exe in {"rm", "unlink"} and any(is_test_path(t) for t in targets):
                raise Block("deleting test files is not allowed during /ship; ask the developer")
        elif exe in {"sed", "perl"} and any(a.startswith("-i") or a == "--in-place" for a in toks[1:]):
            if any(is_workflow_path(t) for t in toks[1:]):
                raise Block("editing CI workflow files is not allowed during /ship")


# ---------------------------------------------------------------- entry

def evaluate(payload: dict):
    """Return a block reason, or None to allow."""
    cwd = payload.get("cwd") or os.getcwd()
    run = find_active_run(cwd)
    if not run:
        return None
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}
    try:
        if tool == "Bash":
            check_bash(ti.get("command", ""), run, cwd)
        elif tool in {"Edit", "MultiEdit", "Write", "NotebookEdit"}:
            check_file_tool(tool, ti)
    except Block as b:
        return f"sdlc-agent guardrail ({run.get('ticket', '?')}): {b}"
    return None


def log_error(err: Exception) -> None:
    try:
        path = agent_home() / "guard-errors.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {type(err).__name__}: {err}\n")
    except OSError:
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        reason = evaluate(payload)
    except Exception as e:
        log_error(e)
        return 0
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
