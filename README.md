# sdlc-agent — `/ship`

A Claude Code skill that takes a Jira story all the way to a merged pull request.

```
/ship PROJ-123
```

It reads the story with `acli`, asks only what the code can't answer, writes a spec you approve, writes failing tests, implements until they pass, gets an independent review from a subagent, opens the PR with `gh`, and fixes CI failures until CI is green. **Then it stays on the PR until it is merged.** It fixes review feedback, updates the spec to match, replies on every thread, re-requests review, resolves conflicts and keeps CI green. **It never merges or approves.** A human reviewer does that.

Design and decisions: [`docs/specs/sdlc-agent.md`](docs/specs/sdlc-agent.md).

## Flow

```
preflight → intake → clarify ⏸ → spec ⏸ → tests (red) → build (green) → review → PR → CI loop ─┐
                       you answer   you approve                          subagent       ≤3 fixes  │
   ┌──────────────────────────────────────────────────────────────────────────────────────────────┘
   └→ awaiting review ──feedback──→ triage ⏸* → revise spec → tests → build → review → push + reply → CI ─┐
            ▲   │                                                                                       │
            │   └──merged──→ done                                                                       │
            └───────────────────────────────────────────────────────────────────────────────────────────┘
```

⏸ = you're interrupted. ⏸* only when the agent disagrees with a comment, a comment is out of scope, or it would drop an acceptance criterion.
Close the terminal any time; `/ship PROJ-123` resumes, including the PR watch.

## Prerequisites

| Tool | Why | Setup |
|---|---|---|
| Claude Code | runs the skill | https://docs.claude.com/en/docs/claude-code/setup |
| Python ≥ 3.9 | state, CI watcher, guard hook | python.org / brew / apt |
| git | | |
| gh ≥ 2.40 | PRs and CI | `gh auth login` |
| acli ≥ 1.3 | Jira | `acli jira auth login` |

## Install (global)

macOS / Linux:
```bash
git clone <this repo> ~/tools/sdlc-agent
~/tools/sdlc-agent/install.sh            # symlinks, so `git pull` updates you
~/tools/sdlc-agent/install.sh --copy     # or copy files instead
```

Windows (PowerShell 5.1 or 7):
```powershell
git clone <this repo> $HOME\tools\sdlc-agent
powershell -ExecutionPolicy Bypass -File $HOME\tools\sdlc-agent\install.ps1
# after `git pull`, run install.ps1 again (Windows installs copy files)
```

What gets installed, into `~/.claude` (or `$CLAUDE_CONFIG_DIR`):

| From repo | To |
|---|---|
| `skills/ship/` | `~/.claude/skills/ship/` |
| `agents/sdlc-reviewer.md` | `~/.claude/agents/` |
| `hooks/` | `~/.claude/hooks/sdlc-agent/` |
| guard hook entry | merged into `~/.claude/settings.json` (backup written first; other entries untouched) |

The installer is safe to re-run, and it refuses to overwrite a `ship` skill it didn't install unless you pass `--force` / `-Force`. Restart open Claude Code sessions after installing.

Uninstall: `install.sh --uninstall` / `install.ps1 -Uninstall`. This removes only what was installed and our hook entry. Run state is kept unless you add `--purge` / `-Purge`.

## Usage

```
/ship PROJ-123          start, or resume
/ship status            in-flight tickets in this repo
/ship abandon PROJ-123  stop a run (leaves branch and PR alone)
```

The first run in a repo asks you to confirm the base branch, test/lint/build commands and Jira status names, then remembers them.

After CI is green, `/ship` keeps watching the PR in the background. Review comments are triaged, fixed, and reflected in the ticket's spec (with a revision history), and each thread gets a reply. CI goes green again and review is re-requested. When a human merges, the run ends (optionally moving the Jira ticket to your done status). If you closed the session, `/ship PROJ-123` catches up on everything that happened.

## State

Kept outside your repos, huddle-style (append-only events plus a bookmark file):

```
~/.config/sdlc-agent/                 ($SDLC_AGENT_HOME to override)
├── userconfig.json                   python path, tool versions
├── active.json                       runs the guard hook is protecting
└── {owner}/{repo}/
    ├── config.json                   per-repo commands and Jira statuses
    └── PROJ-123/
        ├── state.json                phase, status, branch, PR, CI attempts, handled comments
        ├── spec.md                   the approved spec, revised as review feedback lands
        ├── feedback/round-N.*        review comments handled per round
        ├── clarifications.md · review.md · ticket.json · pr-body.md
        └── raw/{ts}_{event}.json
```

## Guardrails

`hooks/guard.py` runs before every Bash/Edit/Write call, but only while a `/ship` run is active **and** you're inside that run's repo. Everywhere else it does nothing. During a run it blocks:

- edits to `.github/workflows/`
- adding test-skip markers or deleting test files
- `--no-verify` and `git commit -n`
- pushes to the base branch, `main` or `master`, and any force push
- `gh pr merge`, `gh pr review --approve`, merges via `gh api`, `gh workflow disable`

If the guard itself errors, it lets the tool call through and logs to `~/.config/sdlc-agent/guard-errors.log`.

## Develop

```
python -m unittest discover -s tests -t tests -v   # unit tests
python tests/install_smoke.py                      # install/uninstall in a sandboxed home
```

CI runs both on macOS, Ubuntu and Windows with Python 3.9 and 3.13.

```
skills/ship/SKILL.md                 entry point and routing
skills/ship/references/phases/       one file per phase, loaded one at a time
skills/ship/references/personas/     analyst, architect, tester, developer
skills/ship/references/templates/    spec, clarifications, PR body
skills/ship/scripts/                 sdlc_state.py, env_check.py, ci_watch.py, review_watch.py
agents/sdlc-reviewer.md              independent reviewer subagent
hooks/guard.py                       guardrail hook
installer/settings_merge.py          safe settings.json merge/unmerge
```
