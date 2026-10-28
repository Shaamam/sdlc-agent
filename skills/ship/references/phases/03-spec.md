# Phase 3 — Spec (Architect) · developer gate 2

Read `{SKILL_DIR}/references/personas/architect.md`.

Goal: a spec the developer approves, where every acceptance criterion maps to at least one test.

1. Write `{TDIR}/spec.md` from `{SKILL_DIR}/references/templates/spec.md`, using `ticket.json`, `intake.md` and `clarifications.md`.
   - Acceptance criteria: the story's own, sharpened by the clarifications. If the story had none, derive them and mark them **derived**.
   - AC → tests table: each criterion gets one or more named test cases at the right level (unit / integration / e2e), naming the test file each lands in.
   - Files to touch: real paths from the code map. New files must follow the repo's layout.
   - Approach: the smallest change that satisfies the criteria and matches local conventions. No refactors the story didn't ask for.
   - Assumptions: every decision you made without asking.
   - Out of scope: what you deliberately won't do.

2. Set `{STATE} status {KEY} waiting_user`. Show the developer the spec (the full file, or a tight summary plus its path if it's long) and ask:
   > Approve this spec, or tell me what to change.

3. Loop on edits until they approve. Each revision: update the file, `{STATE} event {KEY} spec_revised --data '{"change": "..."}'`.

4. On approval: `{STATE} status {KEY} in_progress`, then `{STATE} approve {KEY} spec`.

5. Next: `{STATE} phase {KEY} tests` and read `04-tests.md`.
