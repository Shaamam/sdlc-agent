# Phase 5 — Build (Developer)

Read `{SKILL_DIR}/references/personas/developer.md`.

Goal: the smallest change that turns the new tests green without breaking anything else.

1. If you came here from self-review (phase 6), CI (phase 8) or PR feedback (phase 10), first read `{TDIR}/review.md`, the CI triage, or `{TDIR}/feedback/round-<N>.md`, and fix exactly those items.

2. Implement per the spec's "Files to touch" and "Approach". If the spec turns out to be wrong (the approach can't work, a file doesn't exist, a criterion conflicts with the code), **stop and tell the developer**. Propose the spec change, update `spec.md` once they agree, and record `{STATE} event {KEY} spec_revised`. Don't drift silently.

3. Loop until all of these pass, using the repo config commands (`{STATE} config get`):
   - the new tests;
   - the full test command (`commands.test`);
   - lint (`commands.lint`), if set;
   - build (`commands.build`), if set.
   An existing test that breaks has found a real regression. Fix the code, not the test, unless the spec explicitly changes that behavior. In that case update the test and say so in the commit message.

4. Commit in small, reviewable steps:
   `git commit -m "feat({KEY}): <change>"` (or `fix(...)` for bugs). Never `--no-verify`. If a pre-commit hook fails, fix what it reports.

5. `{STATE} event {KEY} tests_green --data '{"commits": <n>}'`

6. Next: `{STATE} phase {KEY} review` and read `06-review.md`.
