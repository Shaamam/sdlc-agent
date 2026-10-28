# Phase 0 — Preflight

Goal: the tools work, the repo is configured, and you are on the feature branch.

1. **Tools.** Run `"{PY}" "{SKILL_DIR}/scripts/env_check.py"`. If `ok` is false, show the `errors` list with its fix commands, run `{STATE} status {KEY} blocked --reason "preflight: <first error>"` and stop.

2. **Repo config.** Run `{STATE} config get`.
   - If `exists` is false, or `config.confirmed` is false, detect the commands. Look at, in order: the repo's `CLAUDE.md`/`AGENTS.md`, `package.json` scripts, `Makefile`, `pyproject.toml`/`tox.ini`, `pom.xml`/`build.gradle`, `go.mod`, `Cargo.toml`, `.github/workflows/*` (read only, to see what CI runs). Detect the base branch with `gh repo view --json defaultBranchRef -q .defaultBranchRef.name`.
   - Show the developer one compact block and ask them to confirm or correct it:
     ```
     base branch      main
     branch prefix    feature/
     test             npm test
     lint             npm run lint
     build            (none)
     Jira on start    In Progress
     Jira on PR       In Review
     Jira on merge    (none, e.g. if the Jira GitHub app already moves it)
     CI fix attempts  3
     ```
   - Save: `{STATE} config set base_branch=main branch_prefix=feature/ commands.test="npm test" commands.lint="npm run lint" commands.build="" jira.in_progress_status="In Progress" jira.in_review_status="In Review" jira.done_status="" confirmed=true`
   - This is asked once per repo. Later runs reuse it silently.

3. **Clean tree.** `git status --porcelain`. If anything is uncommitted, show it and ask the developer to commit or stash. Don't stash for them. Stop until it's clean.

4. **Branch.** Fetch the summary first so the branch name is readable: `acli jira workitem view {KEY} --fields summary --json`. Slug it to lowercase words, max 40 chars.
   ```
   git fetch origin {base}
   git switch -c {prefix}{KEY}-{slug} origin/{base}
   ```
   If the branch already exists locally or on origin, switch to it instead. Record:
   `{STATE} set {KEY} branch="{prefix}{KEY}-{slug}" base_branch="{base}" summary="<summary>"`

5. Next: `{STATE} phase {KEY} intake` and read `01-intake.md`.
