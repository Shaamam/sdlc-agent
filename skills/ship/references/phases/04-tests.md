# Phase 4 — Tests first (Tester)

Read `{SKILL_DIR}/references/personas/tester.md`.

Goal: failing tests that prove the acceptance criteria aren't met yet.

1. Check the spec is approved: `{STATE} get {KEY}` → `approvals.spec` must be set. If not, go back to `03-spec.md`.

2. Write every test case from the spec's AC → tests table, in the files it names, in the repo's existing test style and helpers. Each test name should read as the behavior it checks.

3. Run only the new tests (narrowest command the test runner allows), then confirm:
   - they **fail**, and
   - they fail **for the right reason**: an assertion about the missing behavior, not an import error, typo, missing fixture or syntax error.
   Fix any test that fails for the wrong reason and run it again.

4. A test that already passes means the behavior exists or the test is wrong. Look into it. Either fix the test or tell the developer the criterion may already be met.

5. Commit the tests only:
   ```
   git add <test files>
   git commit -m "test({KEY}): <what the tests cover>"
   ```
   `{STATE} event {KEY} tests_red --data '{"tests": <n>, "files": [...]}'`

6. Next: `{STATE} phase {KEY} build` and read `05-build.md`.
