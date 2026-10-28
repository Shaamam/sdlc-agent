# Phase 9 — Awaiting review (you own the PR until it merges)

Goal: keep the PR moving until a human merges it. React to review feedback, conflicts and a stale branch. **Never merge, approve or enable auto-merge.**

1. `{STATE} phase {KEY} awaiting_review`. This releases the guard while you're idle; any phase that changes code re-arms it.

2. **Re-request review** if the last feedback round left names in `review.rerequest` (from `{STATE} get {KEY}`):
   ```
   gh api -X POST repos/{owner}/{repo}/pulls/<n>/requested_reviewers -f "reviewers[]=<login>"
   ```
   One `-f` per login. Then `{STATE} set {KEY} 'review.rerequest=[]'`.

3. Tell the developer where things stand:
   - **First time** (`review.rounds` is 0):
     ```
     ✅ {KEY}: CI green, PR ready for review: <pr url>
        tests: <n> new · fix attempts: <n>
        I'll keep watching it: review comments get fixed (and the spec updated), conflicts resolved,
        until a reviewer merges it. You can keep working; if you close this session, /ship {KEY} picks the watch back up.
     ```
   - **After a feedback round:** `▸ {KEY} · review round <N> pushed, CI green, review re-requested from <names>`

4. **Watch** in the background (Bash with `run_in_background: true`) and wait for the completion notification. Don't poll it:
   ```
   "{PY}" "{SKILL_DIR}/scripts/review_watch.py" --pr <n> --ticket {KEY}
   ```

5. Act on the JSON `result`:

| result | Do |
|---|---|
| `merged` | `{STATE} phase {KEY} merged`. If `jira.done_status` is set: `acli jira workitem transition --key {KEY} --status "<done_status>" --yes`. Comment on Jira: `acli jira workitem comment create --key {KEY} --body "Merged: <pr url>"`. Tell the developer: `🎉 {KEY} merged · review rounds: <n> · spec: {TDIR}/spec.md`. Offer (don't run) `git switch <base> && git pull`. **The run is done.** |
| `closed` | Ask the developer whether it was abandoned or will be reopened. Abandoned → `{STATE} status {KEY} abandoned --reason "PR closed"`. Reopened → back to step 4. |
| `feedback` | Read `10-feedback.md` and handle `items`. |
| `conflict` | **Update the branch** (below). |
| `behind` | Approved, but the branch is behind base and that blocks the merge. **Update the branch** (below). Tell the developer that if the repo dismisses stale approvals, the reviewer will need to approve again. |
| `timeout` | Nothing happened. Go back to step 4 without saying anything. |
| `error` | Show `detail`, then `{STATE} status {KEY} blocked --reason "review watch: <detail>"` and stop. |

`bot_items`: mention them to the developer once (e.g. "codecov says coverage dropped 0.4%"), then `{STATE} handled {KEY} <ids>`. Address them only if the developer asks.

## Update the branch

1. `{STATE} phase {KEY} build` (re-arms the guard).
2. `git fetch origin <base>` then `git merge --no-edit origin/<base>`. Never rebase or force-push.
3. Resolve conflicts in line with `{TDIR}/spec.md`. If a conflict is in code whose intent you can't tell, ask the developer.
4. Run the full test and lint commands. Commit: `chore({KEY}): merge <base>`.
5. `git push`, then `{STATE} phase {KEY} ci` and follow `08-ci.md`. It brings you back here when green.
