import sys
import unittest

from helpers import SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import review_watch as rw  # noqa: E402

HUMAN = {"login": "alice", "type": "User"}
DEV = {"login": "dev", "type": "User"}
BOT = {"login": "codecov[bot]", "type": "Bot"}


def review(id, state, body="", user=HUMAN):
    return {"id": id, "state": state, "body": body, "user": user, "html_url": f"https://x/r{id}"}


def inline(id, body, user=HUMAN, reply_to=None):
    return {"id": id, "body": body, "user": user, "path": "src/a.ts", "line": 10,
            "in_reply_to_id": reply_to, "pull_request_review_id": 1, "html_url": f"https://x/c{id}"}


def convo(id, body, user=HUMAN):
    return {"id": id, "body": body, "user": user, "html_url": f"https://x/i{id}"}


OPEN = {"state": "OPEN", "mergedAt": None, "mergeable": "MERGEABLE", "mergeStateStatus": "BLOCKED",
        "reviewDecision": "REVIEW_REQUIRED"}


class CollectFeedbackTest(unittest.TestCase):
    def test_actionable_items_from_all_three_sources(self):
        fb = rw.collect_feedback(
            [review(1, "CHANGES_REQUESTED", "Please handle nulls")],
            [inline(2, "rename this")],
            [convo(3, "Also update the docs?")],
            set(),
        )
        self.assertEqual([i["id"] for i in fb["items"]], ["review:1", "inline:2", "conversation:3"])
        self.assertEqual(fb["changes_requested_by"], ["alice"])
        self.assertEqual(fb["items"][1]["path"], "src/a.ts")

    def test_skips_approvals_empty_reviews_handled_and_agent_replies(self):
        fb = rw.collect_feedback(
            [review(1, "APPROVED", "LGTM"), review(2, "COMMENTED", ""), review(3, "CHANGES_REQUESTED", "fix")],
            [inline(4, "done, renamed " + rw.AGENT_MARKER, user=DEV), inline(5, "nit")],
            [],
            {"review:3"},
        )
        self.assertEqual([i["id"] for i in fb["items"]], ["inline:5"])

    def test_developer_comments_count_as_feedback(self):
        fb = rw.collect_feedback([], [], [convo(9, "use the shared helper here", user=DEV)], set())
        self.assertEqual(len(fb["items"]), 1)

    def test_bots_are_separated(self):
        fb = rw.collect_feedback([], [], [convo(7, "coverage dropped", user=BOT)], set())
        self.assertEqual(fb["items"], [])
        self.assertEqual(len(fb["bot_items"]), 1)


class DecideTest(unittest.TestCase):
    def none(self):
        return {"items": [], "bot_items": [], "changes_requested_by": []}

    def test_waiting(self):
        self.assertIsNone(rw.decide(OPEN, self.none()))

    def test_merged_beats_everything(self):
        fb = {"items": [{"id": "inline:1"}], "bot_items": [], "changes_requested_by": []}
        self.assertEqual(rw.decide(dict(OPEN, state="MERGED", mergedAt="2026-10-28T00:00:00Z"), fb), "merged")

    def test_closed(self):
        self.assertEqual(rw.decide(dict(OPEN, state="CLOSED"), self.none()), "closed")

    def test_feedback_before_conflict(self):
        fb = {"items": [{"id": "inline:1"}], "bot_items": [], "changes_requested_by": []}
        self.assertEqual(rw.decide(dict(OPEN, mergeable="CONFLICTING"), fb), "feedback")
        self.assertEqual(rw.decide(dict(OPEN, mergeable="CONFLICTING"), self.none()), "conflict")

    def test_behind_only_matters_once_approved(self):
        self.assertIsNone(rw.decide(dict(OPEN, mergeStateStatus="BEHIND"), self.none()))
        self.assertEqual(rw.decide(dict(OPEN, mergeStateStatus="BEHIND", reviewDecision="APPROVED"), self.none()), "behind")


if __name__ == "__main__":
    unittest.main()
