# Resume

`{STATE} init {KEY}` returned `resumed: true`. Pick up where the run stopped, without redoing finished work.

1. Tell the developer where things stand, in one line:
   `↺ {KEY} · resuming at <phase> (status <status>) · branch <branch> · PR <url or none> · review round <review.rounds>`
   If `status_reason` is set, include it.

2. Make sure you're on the run's branch: `git switch <branch>`. If the tree has uncommitted changes, show them and ask whether they belong to this run before going on.

3. Continue based on `status` and `phase`:

| State | Do |
|---|---|
| `awaiting_review` | `09-awaiting-review.md` from step 2. Re-request review if one is queued, then start the watcher. It reports merges, feedback and conflicts that happened while you were away. |
| `in_progress` in `feedback` | Open `{TDIR}/feedback/round-<N>.md` and continue `10-feedback.md` with the items whose ids aren't in `review.handled_ids`. Check `git log` to see which fixes are already committed. |
| `waiting_user` in `clarify` | Re-ask the unanswered questions (see `{TDIR}/intake.md` and the `question_answered` events in `{TDIR}/raw/`). |
| `waiting_user` in `spec` | Show `{TDIR}/spec.md` again and ask for approval. |
| `waiting_user` in `feedback` | Show the gated review items from `{TDIR}/feedback/round-<N>.md` again and ask. |
| `blocked` | Show the reason. Ask whether it's resolved. If yes, `{STATE} status {KEY} in_progress` and re-enter the phase. In `ci`, start again at **Watch**. |
| `in_progress` (any other phase) | Re-read that phase's file and continue from its first step that isn't already done (check state, events and git log). |

4. Never re-ask a question that has a `question_answered` event. Never re-request spec approval when `approvals.spec` is set, unless the spec changed since. Never reply twice to a feedback id already in `review.handled_ids`.
