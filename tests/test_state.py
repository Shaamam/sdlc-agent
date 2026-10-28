import contextlib
import io
import json
import sys
import unittest

from helpers import SCRIPTS, TempEnvCase

sys.path.insert(0, str(SCRIPTS))
import sdlc_state  # noqa: E402


class StateTest(TempEnvCase):
    def run_cmd(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = sdlc_state.main(["--cwd", str(self.repo), *argv])
        return code, json.loads(buf.getvalue())

    def active(self):
        path = self.home / "active.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def test_repo_identity_from_origin(self):
        code, out = self.run_cmd("repo-info")
        self.assertEqual(code, 0)
        self.assertEqual(out["slug"], "acme/widgets")
        self.assertEqual(out["branch"], "main")

    def test_parse_remote_forms(self):
        for url in ("git@github.com:acme/widgets.git", "https://github.com/acme/widgets",
                    "https://github.com/acme/widgets.git/", "ssh://git@github.com/acme/widgets.git"):
            self.assertEqual(sdlc_state.parse_remote(url), ("acme", "widgets"), url)

    def test_init_creates_state_events_and_activates(self):
        code, out = self.run_cmd("init", "proj-12")
        self.assertEqual(code, 0)
        self.assertFalse(out["resumed"])
        st = out["state"]
        self.assertEqual(st["ticket"], "PROJ-12")
        self.assertEqual(st["phase"], "preflight")
        tdir = self.home / "acme" / "widgets" / "PROJ-12"
        self.assertTrue((tdir / "state.json").exists())
        self.assertTrue(any(p.name.endswith("_run_started.json") for p in (tdir / "raw").iterdir()))
        self.assertEqual(self.active()[str(self.repo)]["ticket"], "PROJ-12")

    def test_init_twice_resumes(self):
        self.run_cmd("init", "PROJ-12")
        self.run_cmd("phase", "PROJ-12", "spec")
        _, out = self.run_cmd("init", "PROJ-12")
        self.assertTrue(out["resumed"])
        self.assertEqual(out["state"]["phase"], "spec")

    def test_rejects_bad_ticket(self):
        code, out = self.run_cmd("init", "not a ticket")
        self.assertEqual(code, 1)
        self.assertIn("Jira key", out["error"])

    def test_phase_transitions_close_previous(self):
        self.run_cmd("init", "PROJ-1")
        self.run_cmd("phase", "PROJ-1", "intake")
        _, out = self.run_cmd("phase", "PROJ-1", "clarify")
        phases = out["state"]["phases"]
        self.assertEqual(phases["preflight"]["status"], "done")
        self.assertEqual(phases["intake"]["status"], "done")
        self.assertEqual(phases["clarify"]["status"], "in_progress")

    def test_unknown_phase(self):
        self.run_cmd("init", "PROJ-1")
        code, out = self.run_cmd("phase", "PROJ-1", "deploy")
        self.assertEqual(code, 1)

    def test_awaiting_review_releases_guard_but_run_continues(self):
        self.run_cmd("init", "PROJ-1")
        self.assertIn(str(self.repo), self.active())
        _, out = self.run_cmd("phase", "PROJ-1", "awaiting_review")
        self.assertEqual(out["state"]["status"], "awaiting_review")
        self.assertNotIn(str(self.repo), self.active())
        _, out = self.run_cmd("init", "PROJ-1")
        self.assertTrue(out["resumed"])
        self.assertFalse(out.get("finished", False))
        self.assertNotIn(str(self.repo), self.active())

    def test_feedback_round_reactivates_and_resets_budgets(self):
        self.run_cmd("init", "PROJ-1")
        self.run_cmd("ci-attempt", "PROJ-1")
        self.run_cmd("set", "PROJ-1", "review_loops=2")
        self.run_cmd("ci-rerun", "PROJ-1", "unit")
        self.run_cmd("phase", "PROJ-1", "awaiting_review")
        _, out = self.run_cmd("phase", "PROJ-1", "feedback")
        st = out["state"]
        self.assertEqual(st["status"], "in_progress")
        self.assertEqual(st["review"]["rounds"], 1)
        self.assertEqual(st["ci"]["fix_attempts"], 0)
        self.assertEqual(st["ci"]["reruns"], {})
        self.assertEqual(st["review_loops"], 0)
        self.assertIn(str(self.repo), self.active())
        self.run_cmd("phase", "PROJ-1", "awaiting_review")
        _, out = self.run_cmd("phase", "PROJ-1", "feedback")
        self.assertEqual(out["state"]["review"]["rounds"], 2)

    def test_merged_finishes_run(self):
        self.run_cmd("init", "PROJ-1")
        self.run_cmd("phase", "PROJ-1", "awaiting_review")
        _, out = self.run_cmd("phase", "PROJ-1", "merged")
        self.assertEqual(out["state"]["status"], "done")
        self.assertNotIn(str(self.repo), self.active())
        _, out = self.run_cmd("init", "PROJ-1")
        self.assertTrue(out.get("finished"))

    def test_handled_ids_are_deduplicated(self):
        self.run_cmd("init", "PROJ-1")
        _, out = self.run_cmd("handled", "PROJ-1", "inline:1", "review:2")
        self.assertEqual(out["handled"], ["inline:1", "review:2"])
        _, out = self.run_cmd("handled", "PROJ-1", "inline:1", "conversation:3")
        self.assertEqual(out["handled"], ["conversation:3"])
        _, out = self.run_cmd("get", "PROJ-1")
        self.assertEqual(out["state"]["review"]["handled_ids"], ["inline:1", "review:2", "conversation:3"])

    def test_done_is_finished(self):
        self.run_cmd("init", "PROJ-1")
        self.run_cmd("status", "PROJ-1", "done")
        _, out = self.run_cmd("init", "PROJ-1")
        self.assertTrue(out.get("finished"))

    def test_set_dotted_and_readonly(self):
        self.run_cmd("init", "PROJ-1")
        _, out = self.run_cmd("set", "PROJ-1", "pr.number=42", 'pr.url="https://x/42"', "branch=feature/PROJ-1-x")
        self.assertEqual(out["state"]["pr"], {"number": 42, "url": "https://x/42"})
        self.assertEqual(self.active()[str(self.repo)]["branch"], "feature/PROJ-1-x")
        code, _ = self.run_cmd("set", "PROJ-1", "ticket=OTHER-1")
        self.assertEqual(code, 1)

    def test_ci_attempts_capped_by_config(self):
        self.run_cmd("config", "set", "ci.max_fix_attempts=2")
        self.run_cmd("init", "PROJ-1")
        results = [self.run_cmd("ci-attempt", "PROJ-1")[1]["allowed"] for _ in range(3)]
        self.assertEqual(results, [True, True, False])

    def test_ci_rerun_once_per_check(self):
        self.run_cmd("init", "PROJ-1")
        self.assertTrue(self.run_cmd("ci-rerun", "PROJ-1", "unit")[1]["allowed"])
        self.assertFalse(self.run_cmd("ci-rerun", "PROJ-1", "unit")[1]["allowed"])
        self.assertTrue(self.run_cmd("ci-rerun", "PROJ-1", "lint")[1]["allowed"])

    def test_config_defaults_and_merge(self):
        _, out = self.run_cmd("config", "get")
        self.assertFalse(out["exists"])
        self.assertEqual(out["config"]["ci"]["max_fix_attempts"], 3)
        _, out = self.run_cmd("config", "set", 'commands.test="npm test"', "confirmed=true")
        self.assertEqual(out["config"]["commands"]["test"], "npm test")
        self.assertEqual(out["config"]["commands"]["lint"], "")
        self.assertTrue(out["config"]["confirmed"])

    def test_list_hides_finished_unless_all(self):
        self.run_cmd("init", "PROJ-1")
        self.run_cmd("init", "PROJ-2")
        self.run_cmd("status", "PROJ-2", "abandoned")
        _, out = self.run_cmd("list")
        self.assertEqual([r["ticket"] for r in out["runs"]], ["PROJ-1"])
        _, out = self.run_cmd("list", "--all")
        self.assertEqual(len(out["runs"]), 2)

    def test_event_and_approve(self):
        self.run_cmd("init", "PROJ-1")
        self.run_cmd("event", "PROJ-1", "question_answered", "--data", '{"q": "a", "a": "b"}')
        _, out = self.run_cmd("approve", "PROJ-1", "spec")
        self.assertIn("spec", out["state"]["approvals"])
        raw = sorted(p.name for p in (self.home / "acme" / "widgets" / "PROJ-1" / "raw").iterdir())
        self.assertTrue(any("question_answered" in n for n in raw))
        self.assertTrue(any("spec_approved" in n for n in raw))


if __name__ == "__main__":
    unittest.main()
