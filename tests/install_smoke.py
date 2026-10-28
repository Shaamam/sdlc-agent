#!/usr/bin/env python3
"""End-to-end installer check in a sandboxed home. Runs install.sh on macOS/Linux
and install.ps1 on Windows: install, re-install, conflict refusal, uninstall.
Set SMOKE_INSTALLER=ps1 to exercise install.ps1 with pwsh on macOS/Linux."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = os.name == "nt"
USE_PS1 = WINDOWS or os.environ.get("SMOKE_INSTALLER") == "ps1"
MARKER = "hooks/sdlc-agent/guard.py"

ORIGINAL_SETTINGS = {
    "model": "opus",
    "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo existing"}]}]},
}


def run_installer(env, *flags, expect_ok=True):
    if USE_PS1:
        shell = (shutil.which("powershell") if WINDOWS else None) or shutil.which("pwsh")
        ps_flags = {"--uninstall": "-Uninstall", "--force": "-Force", "--purge": "-Purge"}
        cmd = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "install.ps1"),
               *[ps_flags[f] for f in flags]]
    else:
        cmd = ["bash", str(ROOT / "install.sh"), *flags]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    print(f"$ {' '.join(cmd[-2:])} -> {res.returncode}\n{res.stdout}{res.stderr}")
    if expect_ok and res.returncode != 0:
        sys.exit(f"installer failed: {flags}")
    if not expect_ok and res.returncode == 0:
        sys.exit(f"installer should have failed: {flags}")
    return res


def our_hooks(settings_path):
    data = json.loads(settings_path.read_text())
    return [h for g in data.get("hooks", {}).get("PreToolUse", []) for h in g.get("hooks", [])
            if MARKER in h.get("command", "").replace("\\", "/")]


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print(f"ok: {msg}")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="sdlc-install-"))
    claude = tmp / "claude"
    agent_home = tmp / "agent-home"
    claude.mkdir()
    settings = claude / "settings.json"
    settings.write_text(json.dumps(ORIGINAL_SETTINGS, indent=2))
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(claude), "SDLC_AGENT_HOME": str(agent_home)}

    try:
        run_installer(env)
        check((claude / "skills" / "ship" / "SKILL.md").is_file(), "skill installed")
        check((claude / "skills" / "ship" / "references" / "phases" / "08-ci.md").is_file(), "phase files installed")
        check((claude / "agents" / "sdlc-reviewer.md").is_file(), "reviewer subagent installed")
        check((claude / "hooks" / "sdlc-agent" / "guard.py").is_file(), "guard hook installed")
        check(len(our_hooks(settings)) == 1, "hook registered once")
        check(json.loads(settings.read_text())["model"] == "opus", "other settings preserved")
        cfg = json.loads((agent_home / "userconfig.json").read_text())
        check(Path(cfg["python_bin"]).exists(), "userconfig records a real python")

        hook_cmd = our_hooks(settings)[0]["command"]
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(tmp)})
        res = subprocess.run(hook_cmd, shell=True, input=payload, capture_output=True, text=True, env=env)
        check(res.returncode == 0, f"registered hook command runs ({hook_cmd})")

        run_installer(env)
        check(len(our_hooks(settings)) == 1, "re-install is idempotent")

        run_installer(env, "--uninstall")
        check(not (claude / "skills" / "ship").exists(), "skill removed")
        check(not (claude / "agents" / "sdlc-reviewer.md").exists(), "agent removed")
        check(json.loads(settings.read_text()) == ORIGINAL_SETTINGS, "settings restored to original")
        check((agent_home / "userconfig.json").exists(), "state kept without --purge")

        foreign = claude / "skills" / "ship"
        foreign.mkdir(parents=True)
        (foreign / "SKILL.md").write_text("someone else's skill")
        run_installer(env, expect_ok=False)
        check((foreign / "SKILL.md").read_text() == "someone else's skill", "foreign skill not overwritten")
        run_installer(env, "--force")
        check("name: ship" in (foreign / "SKILL.md").read_text(), "--force replaces it")

        run_installer(env, "--uninstall", "--purge")
        check(not agent_home.exists(), "--purge removes state")

        if not USE_PS1:
            run_installer(env, "--copy")
            skill = claude / "skills" / "ship"
            check(skill.is_dir() and not skill.is_symlink(), "--copy installs real files")
            run_installer(env)
            check(skill.is_symlink(), "switching back to symlink mode replaces the copy")
            run_installer(env, "--uninstall")
            check(not skill.exists() and json.loads(settings.read_text()) == ORIGINAL_SETTINGS, "copy/symlink round trip cleans up")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("install smoke test passed")


if __name__ == "__main__":
    main()
