# sdlc-agent — `/ship`

A [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) skill that takes a **Jira story all the way to a merged pull request**.

```
/ship PROJ-123
```

You give it a ticket number. It:

1. reads the story from Jira;
2. asks you only the questions the code can't answer;
3. writes a spec and waits for your approval;
4. writes tests first and checks that they fail;
5. writes the code until the tests pass;
6. gets an independent review from a second agent;
7. opens the pull request;
8. fixes CI until it's green;
9. **stays on the PR until it's merged**: fixes reviewer comments, updates the spec to match, replies on every thread, resolves conflicts and keeps CI green.

It **never merges or approves**. A human reviewer does that.

> Design and every decision behind it: [`docs/specs/sdlc-agent.md`](docs/specs/sdlc-agent.md)

---

## Contents

1. [How it works](#1-how-it-works)
2. [Prerequisites](#2-prerequisites): what to install, per OS
3. [One-time logins](#3-one-time-logins): GitHub, Jira, Claude
4. [Install sdlc-agent](#4-install-sdlc-agent): macOS, Linux, Windows
5. [Your first run](#5-your-first-run)
6. [What happens, step by step](#6-what-happens-step-by-step)
7. [Commands](#7-commands)
8. [Where things are stored](#8-where-things-are-stored)
9. [Guardrails](#9-guardrails)
10. [Per-repo settings](#10-per-repo-settings)
11. [Update and uninstall](#11-update-and-uninstall)
12. [Troubleshooting](#12-troubleshooting)
13. [FAQ](#13-faq)
14. [Developing sdlc-agent](#14-developing-sdlc-agent)

---

## 1. How it works

```
 /ship PROJ-123
      │
      ▼
 preflight ─▶ intake ─▶ clarify ⏸ ─▶ spec ⏸ ─▶ tests (fail) ─▶ build (pass) ─▶ self-review ─▶ PR ─▶ CI loop
                         you answer   you approve                               2nd agent              ≤3 fixes
                                                                                                          │
      ┌───────────────────────────────────────────────────────────────────────────────────────────────────┘
      ▼
 awaiting review ──(reviewer comments)──▶ triage ⏸* ─▶ revise spec ─▶ tests ─▶ fix ─▶ review ─▶ push + reply ─▶ CI ─┐
      ▲     │                                                                                                      │
      │     └──(human merges)──▶ ✅ done                                                                            │
      └────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

- ⏸ = the agent stops and waits for you. There are normally two stops: answering clarifying questions and approving the spec.
- ⏸* = it stops during review only when it disagrees with a comment, the comment is out of scope, or acting on it would drop an acceptance criterion.
- Everything else runs on its own. You can close the terminal at any point; `/ship PROJ-123` picks up where it left off.

Behind the scenes:

| Piece | What it is |
|---|---|
| `/ship` skill | The instructions Claude follows, one phase file at a time |
| Personas | Analyst (questions), Architect (spec), Tester (tests, CI triage), Developer (code) |
| `sdlc-reviewer` | A separate subagent with fresh context that reviews the diff against the spec |
| Guard hook | Blocks dangerous actions while a run is active (see [Guardrails](#9-guardrails)) |
| State folder | `~/.config/sdlc-agent/`: every ticket's spec, progress and history |
| `gh` / `acli` | The only way it talks to GitHub and Jira |

---

## 2. Prerequisites

| Tool | Minimum | Used for |
|---|---|---|
| [Claude Code](https://docs.claude.com/en/docs/claude-code/setup) | recent | runs the skill |
| Python | 3.9 | state, CI/review watchers, guard hook (standard library only, no `pip install`) |
| git | 2.30 | branches, commits |
| [GitHub CLI `gh`](https://cli.github.com) | 2.40 | PRs, CI checks, review comments |
| [Atlassian CLI `acli`](https://developer.atlassian.com/cloud/acli/guides/install-acli/) | 1.3 | reading Jira stories, comments, transitions |

You also need **GitHub** access to the repos you'll work on, and a **Jira Cloud** account (`yourcompany.atlassian.net`).

### macOS

Install [Homebrew](https://brew.sh) first if you don't have it. Then:

```bash
brew install python git gh
brew tap atlassian/homebrew-acli
brew install acli
curl -fsSL https://claude.ai/install.sh | bash      # Claude Code
```

### Linux (Ubuntu / Debian)

```bash
sudo apt update
sudo apt install -y python3 git curl

# GitHub CLI: use the official apt repo so you get a current version (Ubuntu's own package can be too old)
#   → follow https://github.com/cli/cli/blob/trunk/docs/install_linux.md

# Atlassian CLI (use acli_linux_arm64 on ARM machines)
curl -LO "https://acli.atlassian.com/linux/latest/acli_linux_amd64/acli"
chmod +x ./acli
sudo install -o root -g root -m 0755 acli /usr/local/bin/acli

# Claude Code
curl -fsSL https://claude.ai/install.sh | bash
```

Other distributions: use your package manager for `python3` and `git`, and follow the links in the table above for `gh` and `acli`.

### Windows 10 / 11

Open **PowerShell** (no admin rights needed) and run:

```powershell
winget install --id Git.Git -e              # Git for Windows; Claude Code also needs its Git Bash
winget install --id Python.Python.3.12 -e   # Python
winget install --id GitHub.cli -e           # gh

# Claude Code
irm https://claude.ai/install.ps1 | iex
```

Atlassian CLI has no winget package. Download it into a folder on your PATH:

```powershell
New-Item -ItemType Directory -Force "$HOME\bin" | Out-Null
Invoke-WebRequest -Uri "https://acli.atlassian.com/windows/latest/acli_windows_amd64/acli.exe" -OutFile "$HOME\bin\acli.exe"

# add $HOME\bin to your user PATH (one time)
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$HOME\bin*") { [Environment]::SetEnvironmentVariable("Path", "$userPath;$HOME\bin", "User") }
```

**Close and reopen PowerShell** so the new PATH applies.

> **Windows Python gotcha:** if typing `python` opens the Microsoft Store, turn it off in
> *Settings → Apps → Advanced app settings → App execution aliases* (switch off `python.exe` and `python3.exe`).
> `py -3 --version` should print a 3.9+ version.

### Check everything is installed

macOS / Linux:
```bash
python3 --version && git --version && gh --version && acli --version && claude --version
```
Windows:
```powershell
py -3 --version; git --version; gh --version; acli --version; claude --version
```

---

## 3. One-time logins

**GitHub**
```bash
gh auth login
```
Choose *GitHub.com* and log in with your browser. The default permissions are enough.

**Jira** (pick one)

```bash
# A) browser login (OAuth), the easiest
acli jira auth login --web

# B) API token. Create one at https://id.atlassian.com/manage-profile/security/api-tokens
echo "<your-token>" | acli jira auth login --site "yourcompany.atlassian.net" --email "you@yourcompany.com" --token
```
On Windows, option B is:
```powershell
Get-Content token.txt | acli jira auth login --site "yourcompany.atlassian.net" --email "you@yourcompany.com" --token
```

**Claude Code**: run `claude` once and follow the login prompt (Claude subscription or Anthropic Console account).

**Check:**
```bash
gh auth status
acli jira auth status
```

---

## 4. Install sdlc-agent

The install is **global**: one install per machine, and it works in every repo.

### macOS / Linux

```bash
git clone https://github.com/Shaamam/sdlc-agent.git ~/tools/sdlc-agent
~/tools/sdlc-agent/install.sh
```

By default it **symlinks** into Claude's config, so a `git pull` in `~/tools/sdlc-agent` updates you instantly. Prefer copies? `install.sh --copy`.

### Windows

```powershell
git clone https://github.com/Shaamam/sdlc-agent.git $HOME\tools\sdlc-agent
powershell -ExecutionPolicy Bypass -File $HOME\tools\sdlc-agent\install.ps1
```

Windows installs **copy** files (Windows symlinks need admin or Developer Mode). After every `git pull`, run `install.ps1` again.

### What the installer does

| Step | Detail |
|---|---|
| Checks prerequisites | Python 3.9+ and git are required (it stops if missing); gh, acli and claude are reported |
| Installs the skill | `skills/ship` → `~/.claude/skills/ship` |
| Installs the reviewer | `agents/sdlc-reviewer.md` → `~/.claude/agents/` |
| Installs the guard hook | `hooks/` → `~/.claude/hooks/sdlc-agent/` |
| Registers the hook | Adds one entry to `~/.claude/settings.json`. It **backs the file up first** (`settings.json.sdlc-agent-backup-<time>`) and never touches your other settings |
| Records config | `~/.config/sdlc-agent/userconfig.json` (Python path, tool versions) |

It's safe to run again; running it again is how you update. It **refuses to overwrite** a `ship` skill it didn't install unless you add `--force` (`-Force` on Windows). It honors `CLAUDE_CONFIG_DIR` if you've moved Claude's config.

Example output:
```
Installing sdlc-agent from /Users/you/tools/sdlc-agent
  symlink  ~/.claude/skills/ship
  symlink  ~/.claude/agents/sdlc-reviewer.md
  symlink  ~/.claude/hooks/sdlc-agent
  settings updated: /Users/you/.claude/settings.json (backup: ...)
Checking tools
  ok git     2.50.1
  ok gh      2.83.1
  ok acli    1.3.22
  ok claude  2.1.312

Done. In any repo, start Claude Code and run:  /ship PROJ-123
```

**Restart any Claude Code sessions you already had open** so they load the new skill and hook.

### Verify

Start `claude` anywhere and:
- type `/` and look for **ship** in the list;
- run `/hooks` and look for a **PreToolUse** hook pointing at `hooks/sdlc-agent/guard.py`;
- run `/agents` and look for **sdlc-reviewer**.

---

## 5. Your first run

1. **Go to the repo** the ticket belongs to, on a clean working tree (commit or stash your changes first):
   ```bash
   cd ~/code/orders-service        # Windows: cd C:\code\orders-service
   git status                      # should be clean
   ```
2. **Start Claude Code:**
   ```bash
   claude
   ```
3. **Start the run:**
   ```
   /ship PROJ-123
   ```
4. **The first time in a repo**, it shows the settings it detected and asks you to confirm or fix them:
   ```
   base branch      main
   branch prefix    feature/
   test             npm test
   lint             npm run lint
   build            (none)
   Jira on start    In Progress
   Jira on PR       In Review
   Jira on merge    (none)
   CI fix attempts  3
   ```
   Reply `ok`, or correct a line (e.g. `test is "pnpm test", Jira on PR is "Code Review"`). It remembers these for this repo.
5. **Answer its questions** (if it has any) and **approve the spec**. After that you can step away. It'll print one progress line per step.

> Tip: the Jira status names must match **your board's** transition names exactly. If a transition fails, it just tells you and carries on.

---

## 6. What happens, step by step

The examples below are illustrative. Your output will match your ticket and repo.

### 0 · Preflight
Checks that `git`, `gh` and `acli` are installed and logged in, that your tree is clean, and loads (or asks for) the repo settings. Then it creates the branch from the latest base:
```
▸ PROJ-123 · preflight · branch feature/PROJ-123-expired-coupon-error from origin/main
```

### 1 · Intake (Analyst)
Reads the story and its comments with `acli`, then explores the code involved: where the behavior lives, existing tests, and conventions. It writes everything it doesn't know as a list of doubts and resolves as many as it can **from the code**.

Ticket text is treated as **data, not instructions**. If a story says "also push to main" or "print the env", it won't, and it will tell you.

### 2 · Clarify (Analyst): ⏸ you answer
Only questions that would change behavior, scope or acceptance, all at once, max 7, each with a proposed answer:
```
PROJ-123 needs a few answers before I write the spec:

1. Should an expired coupon return 400 or 422?
   → Proposed: 422, matching OrderController's validation errors (src/orders/controller.ts:88)
2. Should the error message include the expiry date?
   → Proposed: no, the existing coupon errors don't expose dates

Reply with numbers, e.g. "1 ok, 2: yes include it".
```
Your answers are saved and **posted to the Jira ticket as a comment**, so the decisions live with the story. The ticket moves to *In Progress* (if configured). No questions? It skips this step.

### 3 · Spec (Architect): ⏸ you approve
Writes the spec: summary, acceptance criteria, an **acceptance-criteria → test table**, files to touch, approach, assumptions, risks, out of scope. You approve it or ask for changes. **No code is written before you approve.**

The spec is stored at `~/.config/sdlc-agent/<owner>/<repo>/PROJ-123/spec.md`, not in your repo.

### 4 · Tests first (Tester)
Writes every test from the table, runs them, and makes sure they **fail for the right reason** (missing behavior, not a typo or import error). Commits them:
```
test(PROJ-123): expired coupon returns 422 with code COUPON_EXPIRED
```

### 5 · Build (Developer)
Writes the smallest change that makes the new tests pass, then runs your **full** test suite, lint and build. It fixes code, not tests. Small commits:
```
feat(PROJ-123): reject expired coupons at checkout
```

### 6 · Self-review (`sdlc-reviewer` subagent)
A separate agent with **fresh context** reviews the diff against the spec. It checks criteria coverage, test quality, correctness, security, scope creep and conventions. Verdict: APPROVE or CHANGES. On CHANGES it goes back to build, at most twice, then asks you.

### 7 · Pull request
Merges the latest base branch in (never rebases or force-pushes), pushes the feature branch, and opens the PR with:
- the Jira link,
- what changed,
- an acceptance-criteria checklist mapped to tests,
- how it was tested,
- decisions from clarification,
- reviewer notes, and things it noticed but didn't change.

The ticket moves to *In Review* and gets a comment with the PR link.

### 8 · CI loop (Tester triages, Developer fixes)
Watches GitHub Actions in the background. When a check fails, it **triages before touching anything**:

| Class | Example | What it does |
|---|---|---|
| ours | our new test fails on Linux only | fixes, pushes (max 3 attempts) |
| flaky | a timeout in an unrelated test | re-runs that job once |
| broken on base | same check already red on `main` | doesn't fix it; notes it in the PR and tells you |
| infra | runner out of disk, missing secret | hands it back to you with the log excerpt |

It never edits workflow files, skips tests or uses `--no-verify` to get green (the guard hook blocks it).

### 9 · Awaiting review (it owns the PR)
```
✅ PROJ-123: CI green, PR ready for review: https://github.com/acme/orders-service/pull/482
   I'll keep watching it: review comments get fixed (and the spec updated), conflicts resolved,
   until a reviewer merges it.
```
A background watcher checks the PR every 2 minutes and wakes the agent when:
- **a reviewer comments** → step 10;
- **the PR conflicts with base**, or is approved but behind base → it merges base in, resolves, re-tests, pushes, takes CI green again;
- **it's merged** → done (below);
- **it's closed** → it asks whether the work was abandoned.

You can keep working in another terminal. If you close this one, run `/ship PROJ-123` later and it catches up on everything that happened.

### 10 · Review feedback
Every new comment (inline, review summary or conversation) is classified:

| Class | What it does |
|---|---|
| fix | fixes it |
| spec change | **updates the spec** (criteria, test table, approach), adds a revision-history entry, writes tests first, fixes |
| question | answers in the thread |
| already done | replies with the commit that did it |
| disagree | ⏸ asks you first, with its reasoning |
| out of scope | ⏸ asks you: do it here, or suggest a follow-up ticket |

Then it pushes, **replies on every thread** (what changed and the commit), updates the PR description if the spec changed, takes CI green again, **re-requests review** from whoever asked for changes, and goes back to watching. If an acceptance criterion changed, Jira gets a comment too.

The spec keeps a history:
```
## Revision history
- r0 2026-10-28: approved by developer
- r1 2026-10-29 — error code renamed COUPON_EXPIRED → PROMO_EXPIRED — @alice https://github.com/.../pull/482#discussion_r123
```

### ✅ Merged
When a human merges the PR:
```
🎉 PROJ-123 merged · review rounds: 1 · spec: ~/.config/sdlc-agent/acme/orders-service/PROJ-123/spec.md
```
Optionally moves the Jira ticket to your done status and comments the PR link. The run is finished.

---

## 7. Commands

| Command | What it does |
|---|---|
| `/ship PROJ-123` | Start a run, or resume it from wherever it stopped |
| `/ship status` | List in-flight tickets in this repo: phase, status, PR |
| `/ship abandon PROJ-123` | Stop a run and release its guardrails (leaves the branch and PR alone) |

You can also just talk to it mid-run: "skip the lint step, it's broken on main", "use the existing `formatMoney` helper", "pause here".

---

## 8. Where things are stored

Nothing is added to your repo except the code, tests and commits for the story. Run state lives here:

```
~/.config/sdlc-agent/                       Windows: %USERPROFILE%\.config\sdlc-agent
├── userconfig.json                         Python path, tool versions
├── active.json                             which repo has an active run (read by the guard hook)
├── installed.txt                           what the installer placed (used by uninstall)
└── <owner>/<repo>/
    ├── config.json                         this repo's settings (§10)
    └── PROJ-123/
        ├── state.json                      current phase, status, branch, PR, CI attempts, handled comments
        ├── spec.md                         the spec, revised as review feedback lands
        ├── clarifications.md               your answers (also posted to Jira)
        ├── intake.md                       the analyst's notes and code map
        ├── review.md                       the self-review verdict
        ├── pr-body.md                      the PR description
        ├── ticket.json, comments.json      Jira payloads
        ├── feedback/round-N.json, .md      review comments handled per round
        └── raw/<timestamp>_<event>.json    append-only history of everything that happened
```

Set `SDLC_AGENT_HOME` to keep it somewhere else.

---

## 9. Guardrails

The guard hook runs before every shell command and file edit Claude makes, **but only while a `/ship` run is active and you're inside that run's repo**. Everywhere else it does nothing, so your normal Claude Code use is unaffected.

During a run it **blocks**:

| Blocked | Why |
|---|---|
| editing `.github/workflows/` | CI must not be weakened to go green |
| adding test-skip markers (`it.skip`, `@pytest.mark.skip`, `@Disabled`, `t.Skip`, …) | same |
| deleting test files | same |
| `--no-verify`, `git commit -n` | your git hooks must run |
| pushing to the base branch, `main` or `master` | only the feature branch is pushed |
| any force push | history is never rewritten |
| `gh pr merge`, `gh pr review --approve`, merging through `gh api` | humans merge and approve |
| `gh workflow disable` | same as workflows |

When something is blocked, Claude sees the reason and stops to ask you. If the guard itself crashes, it **lets the action through** and logs to `~/.config/sdlc-agent/guard-errors.log`, so a bug never locks you out of Claude Code.

---

## 10. Per-repo settings

Saved after your first run in a repo, at `~/.config/sdlc-agent/<owner>/<repo>/config.json`:

```json
{
  "base_branch": "main",
  "branch_prefix": "feature/",
  "commands": { "test": "npm test", "lint": "npm run lint", "build": "" },
  "jira": { "in_progress_status": "In Progress", "in_review_status": "In Review", "done_status": "" },
  "ci": { "max_fix_attempts": 3, "timeout_minutes": 45 },
  "confirmed": true
}
```

- An empty string means "skip this step" (e.g. no build command, or no Jira transition on merge).
- To be asked again, set `"confirmed": false` or delete the file.
- You can edit it by hand at any time; the next run picks it up.

---

## 11. Update and uninstall

**Update**
```bash
cd ~/tools/sdlc-agent && git pull                 # macOS/Linux symlink install: that's it
./install.sh                                      # only needed if you installed with --copy
```
```powershell
cd $HOME\tools\sdlc-agent; git pull
powershell -ExecutionPolicy Bypass -File .\install.ps1     # Windows: always re-run
```

**Uninstall**
```bash
~/tools/sdlc-agent/install.sh --uninstall            # keeps your run history
~/tools/sdlc-agent/install.sh --uninstall --purge    # also deletes ~/.config/sdlc-agent
```
```powershell
powershell -ExecutionPolicy Bypass -File $HOME\tools\sdlc-agent\install.ps1 -Uninstall [-Purge]
```
Uninstall removes only what it installed and its single hook entry in `settings.json` (with a backup first).

---

## 12. Troubleshooting

| Symptom | Fix |
|---|---|
| `/ship` doesn't appear | Restart Claude Code. Check `~/.claude/skills/ship/SKILL.md` exists. Re-run the installer. |
| "already exists and wasn't installed by sdlc-agent" | You have another skill called `ship`. Rename it, or re-run with `--force` / `-Force` to replace it. |
| Preflight: `gh is not logged in` | `gh auth login` |
| Preflight: `acli is not logged in to Jira` | `acli jira auth login --web` |
| `acli ... version is older than 1.3` | Update acli (`brew upgrade acli`, or re-download it on Linux/Windows) |
| Jira transition failed | The status name in your repo settings doesn't match your board. Fix `jira.*_status` in `config.json` (§10). |
| "working tree not clean" | Commit or stash your own changes first; the agent won't stash them for you. |
| A guardrail blocked something you really want | Do that one action yourself in a normal terminal. The guard only constrains the agent. |
| Guard blocking outside a run (shouldn't happen) | `/ship abandon PROJ-123`, or delete the repo's entry from `~/.config/sdlc-agent/active.json`. |
| CI watcher says `timeout` | Long pipelines: raise `ci.timeout_minutes` in `config.json`, then `/ship PROJ-123` to resume. |
| Session closed while waiting for review | `/ship PROJ-123` resumes the watch and handles anything that happened. |
| **Windows:** `python` opens the Microsoft Store | Turn off the App execution aliases (see [Prerequisites → Windows](#windows-10--11)), re-run `install.ps1`. |
| **Windows:** "running scripts is disabled" | Use `powershell -ExecutionPolicy Bypass -File ...\install.ps1` as shown. |
| **Windows:** `acli` not found | Reopen PowerShell after adding `$HOME\bin` to PATH; check with `Get-Command acli`. |
| **Windows:** guard hook not running | Run `/hooks` in Claude Code. The command must point at `.../hooks/sdlc-agent/guard.py`. If it's missing, re-run `install.ps1`. Please open an issue with the output: Windows hook execution is the least-tested part. |

Your `settings.json` backups are next to it: `~/.claude/settings.json.sdlc-agent-backup-*`.

---

## 13. FAQ

**Does it ever merge?** No. Not even with auto-merge. A human approves and merges. The guard hook enforces this.

**Does it write anything into my repo besides the feature?** No. Specs and history live in `~/.config/sdlc-agent/`. The repo only gets the story's code, tests and commits.

**Can I run two tickets at once?** One active run per repo checkout. Use a second clone or a `git worktree` for a parallel ticket.

**Can I edit the spec myself?** Yes. Edit `spec.md` in the ticket folder before approving, or tell the agent what to change.

**What if a reviewer's comment is wrong?** The agent asks you before replying, with its reasoning. You decide.

**What does it cost?** It uses your Claude Code plan or API usage like any other Claude Code session. Review watching is a cheap background poll.

**Is my code sent anywhere new?** Only through Claude Code itself, and through `gh`/`acli` to GitHub and Jira, which you already use.

---

## 14. Developing sdlc-agent

```
skills/ship/SKILL.md                 entry point: routing and rules
skills/ship/references/phases/       00-preflight … 11-resume: one file per phase
skills/ship/references/personas/     analyst, architect, tester, developer
skills/ship/references/templates/    spec, clarifications, PR body
skills/ship/scripts/                 sdlc_state.py, env_check.py, ci_watch.py, review_watch.py
agents/sdlc-reviewer.md              independent reviewer subagent
hooks/guard.py                       guardrail hook
installer/settings_merge.py          safe settings.json merge/unmerge
install.sh / install.ps1             installers
tests/                               unit tests + installer smoke test
docs/specs/sdlc-agent.md             the design spec
```

Everything is standard-library Python 3.9+. There are no dependencies to install.

```bash
python3 -m unittest discover -s tests -t tests -v    # unit tests
python3 tests/install_smoke.py                       # install → reinstall → conflict → uninstall in a sandbox
```

**CI is manual.** It runs the tests and the installer smoke test on macOS, Ubuntu and Windows (Python 3.9 and 3.13). Run it before sharing a change that touches the installers, the hook or the scripts:
```bash
gh workflow run ci.yml && gh run watch
```
or from GitHub: **Actions → ci → Run workflow**.
