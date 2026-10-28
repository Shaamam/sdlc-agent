import sys
import unittest

from helpers import SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import ci_watch  # noqa: E402

LINK = "https://github.com/acme/widgets/actions/runs/111/job/222"


def check(name, bucket, link=LINK):
    return {"name": name, "bucket": bucket, "state": bucket.upper(), "link": link, "workflow": "CI"}


class SummarizeTest(unittest.TestCase):
    def test_all_pass(self):
        out = ci_watch.summarize([check("unit", "pass"), check("lint", "skipping")])
        self.assertEqual(out["result"], "passed")
        self.assertEqual(out["failed"], [])

    def test_pending_wins_over_fail(self):
        out = ci_watch.summarize([check("unit", "fail"), check("e2e", "pending")])
        self.assertEqual(out["result"], "pending")
        self.assertEqual(len(out["failed"]), 1)

    def test_failure_extracts_run_and_job(self):
        out = ci_watch.summarize([check("unit", "fail"), check("lint", "pass")])
        self.assertEqual(out["result"], "failed")
        self.assertEqual(out["failed"][0]["run_id"], "111")
        self.assertEqual(out["failed"][0]["job_id"], "222")

    def test_cancel_counts_as_failure(self):
        self.assertEqual(ci_watch.summarize([check("unit", "cancel")])["result"], "failed")

    def test_external_status_without_run_link(self):
        out = ci_watch.summarize([check("codecov", "fail", link="https://codecov.io/x")])
        self.assertIsNone(out["failed"][0]["run_id"])


if __name__ == "__main__":
    unittest.main()
