# Phase 6 — Review (sdlc-reviewer subagent)

Goal: an independent review with fresh context before anything leaves the machine.

1. Launch the `sdlc-reviewer` subagent (Agent tool, `subagent_type: "sdlc-reviewer"`) with this prompt, filling in the values:
   ```
   Review the change for {KEY}.
   Repo: <repo_path>   Base: origin/<base_branch>   Branch: <branch>
   Spec: {TDIR}/spec.md
   Clarifications: {TDIR}/clarifications.md
   Test command: <commands.test>
   Write your review to {TDIR}/review.md and return the verdict line.
   ```
   If the subagent type isn't available, read `~/.claude/agents/sdlc-reviewer.md` and do the review yourself by its checklist, but tell the developer it wasn't independent.

2. Read `{TDIR}/review.md`. Record:
   `{STATE} event {KEY} review_verdict --data '{"verdict": "APPROVE|CHANGES", "blocking": <n>}'`

3. **APPROVE** (no blocking findings): go to step 5.

4. **CHANGES**: check `review_loops` in `{STATE} get {KEY}`.
   - Below 2: `{STATE} set {KEY} review_loops=<n+1>`, then `{STATE} phase {KEY} build` and fix the blocking findings (`05-build.md`), then come back here.
   - At 2: show the developer the remaining blocking findings and ask whether to fix them, open the PR anyway with the findings listed, or stop. Follow their call.

5. Non-blocking findings go into the PR body under "Reviewer notes". Don't act on them now.

6. Next:
   - If `pr.number` is already set, you're in a review-feedback round: go back to `10-feedback.md` step 8 (push and reply).
   - Otherwise: `{STATE} phase {KEY} pr` and read `07-pr.md`.
