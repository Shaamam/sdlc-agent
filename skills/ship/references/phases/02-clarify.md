# Phase 2 — Clarify (Analyst) · developer gate 1

Goal: ask only what the code cannot answer, once, in one batch.

1. Take the `needs-human` doubts from `{TDIR}/intake.md`. Drop any you can answer by reading more code. Merge overlapping ones. Keep the ones that would change behavior, scope or acceptance; drop cosmetic ones (decide those yourself and note the choice in the spec).

2. **If none remain**: record `{STATE} event {KEY} no_questions`, write `{TDIR}/clarifications.md` stating "No open questions; assumptions listed in spec", skip to step 6.

3. Otherwise set `{STATE} status {KEY} waiting_user` and ask the developer, **max 7 questions**, each with your proposed default so they can answer "ok":
   ```
   PROJ-123 needs a few answers before I write the spec:

   1. Should an expired coupon return 400 or 422?
      → Proposed: 422, matching OrderController's validation errors (src/orders/controller.ts:88)
   2. ...

   Reply with numbers, e.g. "1 ok, 2: only admins".
   ```
   If phase 1 flagged suspicious instructions in the ticket, mention them here too.

4. When the developer answers: `{STATE} status {KEY} in_progress`, then for each one `{STATE} event {KEY} question_answered --data '{"q": "...", "a": "..."}'`.

5. Write `{TDIR}/clarifications.md` from `{SKILL_DIR}/references/templates/clarifications.md` and post it on the story:
   ```
   acli jira workitem comment create --key {KEY} --body-file "{TDIR}/clarifications.md"
   ```
   If posting fails, tell the developer and continue; the local copy is the source of truth.

6. `{STATE} approve {KEY} clarifications`

7. If `jira.in_progress_status` is set in the repo config:
   `acli jira workitem transition --key {KEY} --status "<in_progress_status>" --yes`
   If the transition isn't available from the current status, note it and continue.

8. Next: `{STATE} phase {KEY} spec` and read `03-spec.md`.
