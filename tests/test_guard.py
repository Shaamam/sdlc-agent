import json
import subprocess
import sys
import unittest

from helpers import GUARD, TempEnvCase, git

sys.path.insert(0, str(GUARD.parent))
import guard  # noqa: E402


class GuardTest(TempEnvCase):
    def setUp(self):
        super().setUp()
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "active.json").write_text(json.dumps({
            str(self.repo): {"ticket": "PROJ-1", "repo": "acme/widgets", "branch": "feature/PROJ-1-x", "base_branch": "develop"}
        }))
        git(self.repo, "switch", "-q", "-c", "feature/PROJ-1-x")

    def decide(self, tool, cwd=None, **tool_input):
        return guard.evaluate({"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd or self.repo)})

    def bash(self, command, cwd=None):
        return self.decide("Bash", cwd=cwd, command=command)

    def assertBlocked(self, reason):
        self.assertIsNotNone(reason)
        self.assertIn("sdlc-agent guardrail", reason)

    # --- scope

    def test_inactive_repo_allows_everything(self):
        other = self.tmp / "elsewhere"
        other.mkdir()
        self.assertIsNone(self.bash("git push --force origin main", cwd=other))

    def test_no_active_file_allows(self):
        (self.home / "active.json").unlink()
        self.assertIsNone(self.bash("gh pr merge 1"))

    def test_subdirectory_of_active_repo_is_guarded(self):
        sub = self.repo / "src"
        sub.mkdir()
        self.assertBlocked(self.bash("gh pr merge 1 --squash", cwd=sub))

    # --- pushes

    def test_feature_push_allowed(self):
        self.assertIsNone(self.bash("git push -u origin feature/PROJ-1-x"))
        self.assertIsNone(self.bash("git push"))

    def test_push_to_protected_blocked(self):
        for cmd in ("git push origin main", "git push origin HEAD:master", "git push origin develop",
                    "git push origin feature/PROJ-1-x:refs/heads/main", "git -C . push origin main"):
            self.assertBlocked(self.bash(cmd))

    def test_force_push_blocked(self):
        for cmd in ("git push -f", "git push --force origin feature/PROJ-1-x",
                    "git push --force-with-lease", "git push origin +feature/PROJ-1-x", "git push -uf origin x"):
            self.assertBlocked(self.bash(cmd))

    def test_push_while_on_protected_branch_blocked(self):
        git(self.repo, "switch", "-q", "main")
        self.assertBlocked(self.bash("git push"))
        self.assertBlocked(self.bash("git push origin HEAD"))

    def test_no_verify_blocked(self):
        self.assertBlocked(self.bash('git commit --no-verify -m "x"'))
        self.assertBlocked(self.bash('git commit -n -m "x"'))
        self.assertBlocked(self.bash("git push --no-verify"))
        self.assertIsNone(self.bash('git commit -m "feat(PROJ-1): add thing"'))

    def test_chained_commands_checked(self):
        self.assertBlocked(self.bash("npm test && git push origin main"))
        self.assertBlocked(self.bash("FOO=1 git push --force"))

    # --- gh

    def test_merge_and_approve_blocked(self):
        self.assertBlocked(self.bash("gh pr merge 12 --squash"))
        self.assertBlocked(self.bash("gh -R acme/widgets pr merge 12"))
        self.assertBlocked(self.bash("gh pr review 12 --approve"))
        self.assertBlocked(self.bash("gh api -X PUT repos/acme/widgets/pulls/12/merge"))
        self.assertBlocked(self.bash("gh workflow disable ci.yml"))

    def test_normal_gh_allowed(self):
        for cmd in ("gh pr create --title x --body-file b.md", "gh pr checks 12 --json name,bucket",
                    "gh run view 99 --log-failed", "gh run rerun 99 --failed", "gh pr view 12 --json state",
                    "gh api -X POST repos/acme/widgets/pulls/12/comments/555/replies -F body=@/tmp/r.md",
                    "gh api -X POST repos/acme/widgets/pulls/12/requested_reviewers -f reviewers[]=alice",
                    "gh pr comment 12 --body-file /tmp/r.md", "gh pr edit 12 --body-file /tmp/b.md"):
            self.assertIsNone(self.bash(cmd), cmd)

    # --- workflows

    def test_workflow_file_edits_blocked(self):
        wf = str(self.repo / ".github" / "workflows" / "ci.yml")
        self.assertBlocked(self.decide("Edit", file_path=wf, old_string="a", new_string="b"))
        self.assertBlocked(self.decide("Write", file_path=wf, content="x"))
        self.assertBlocked(self.decide("Edit", file_path=".github\\workflows\\ci.yml", old_string="a", new_string="b"))

    def test_workflow_bash_writes_blocked(self):
        for cmd in ("echo x > .github/workflows/ci.yml", "sed -i '' s/a/b/ .github/workflows/ci.yml",
                    "rm .github/workflows/ci.yml", "git rm .github/workflows/ci.yml",
                    "cp /tmp/x.yml .github/workflows/ci.yml", "tee -a .github/workflows/ci.yml"):
            self.assertBlocked(self.bash(cmd))

    def test_workflow_reads_allowed(self):
        for cmd in ("cat .github/workflows/ci.yml", "grep -r node .github/workflows", "ls .github/workflows"):
            self.assertIsNone(self.bash(cmd), cmd)

    # --- tests

    def test_adding_skip_marker_blocked(self):
        f = str(self.repo / "tests" / "a.test.ts")
        self.assertBlocked(self.decide("Edit", file_path=f, old_string="it('works'", new_string="it.skip('works'"))
        self.assertBlocked(self.decide("Edit", file_path="t.py", old_string="def test_x", new_string="@pytest.mark.skip\ndef test_x"))
        self.assertBlocked(self.decide("MultiEdit", file_path="T.java", edits=[{"old_string": "@Test", "new_string": "@Disabled @Test"}]))
        self.assertBlocked(self.decide("Write", file_path=str(self.repo / "x_test.go"), content="func TestX(t *testing.T) { t.Skip(\"later\") }"))

    def test_existing_skip_marker_untouched_is_fine(self):
        self.assertIsNone(self.decide("Edit", file_path="a.test.ts", old_string="it.skip('a', () => { x })", new_string="it.skip('a', () => { y })"))
        self.assertIsNone(self.decide("Edit", file_path="src/app.ts", old_string="a", new_string="b"))

    def test_existing_file_with_skip_rewritten_is_fine(self):
        f = self.repo / "old_test.py"
        f.write_text("@pytest.mark.skip\ndef test_a(): pass\n")
        self.assertIsNone(self.decide("Write", file_path=str(f), content="@pytest.mark.skip\ndef test_a(): assert True\n"))

    def test_deleting_tests_blocked(self):
        for cmd in ("rm tests/test_orders.py", "git rm src/orders.test.ts", "rm -f pkg/orders_test.go",
                    "rm src/test/java/OrderTest.java"):
            self.assertBlocked(self.bash(cmd))
        self.assertIsNone(self.bash("rm -rf build/"))

    # --- process wiring

    def test_exit_code_2_and_stderr_when_blocked(self):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "gh pr merge 1"}, "cwd": str(self.repo)})
        res = subprocess.run([sys.executable, str(GUARD)], input=payload, capture_output=True, text=True,
                             env={**__import__("os").environ})
        self.assertEqual(res.returncode, 2)
        self.assertIn("never merges", res.stderr)

    def test_bad_input_fails_open(self):
        res = subprocess.run([sys.executable, str(GUARD)], input="not json", capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)


if __name__ == "__main__":
    unittest.main()
