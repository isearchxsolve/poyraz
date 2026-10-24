from __future__ import annotations

import unittest

from verifier import verify_record


def issue(
    *,
    title: str = "Implement cache eviction",
    body: str = "Bounty: $100 paid upon merge.",
    state: str = "open",
    association: str = "OWNER",
    comments: int = 0,
    assignees: list[dict] | None = None,
) -> dict:
    return {
        "title": title,
        "body": body,
        "state": state,
        "author_association": association,
        "comments": comments,
        "assignees": assignees or [],
        "locked": False,
    }


def repository(
    *,
    archived: bool = False,
    fork: bool = False,
    stars: int = 25,
) -> dict:
    return {
        "archived": archived,
        "fork": fork,
        "stargazers_count": stars,
    }


class VerificationTests(unittest.TestCase):
    def test_authoritative_numeric_bounty_with_payment_condition_is_verified(self) -> None:
        result = verify_record(issue=issue(), repository=repository())

        self.assertEqual("VERIFIED", result.status)
        self.assertGreaterEqual(result.score, 65)
        self.assertIn("explicit reward amount: USD 100.00", result.reasons)
        self.assertFalse(result.claim_signal)

    def test_generic_bounty_wording_cannot_be_verified(self) -> None:
        result = verify_record(
            issue=issue(body="Bounty available for a future contributor."),
            repository=repository(),
        )

        self.assertEqual("REVIEW", result.status)
        self.assertIn(
            "compensation wording has no explicit monetary amount",
            result.risks,
        )
        self.assertIn("no explicit payout or completion condition", result.risks)

    def test_numeric_reward_without_payment_condition_requires_review(self) -> None:
        result = verify_record(
            issue=issue(body="Reward: $500 for this task."),
            repository=repository(),
        )

        self.assertEqual("REVIEW", result.status)
        self.assertIn("no explicit payout or completion condition", result.risks)

    def test_proposed_reward_requires_review(self) -> None:
        result = verify_record(
            issue=issue(body="Proposed bounty: $100 paid upon merge."),
            repository=repository(),
        )

        self.assertEqual("REVIEW", result.status)
        self.assertIn("reward appears proposed/not final", result.risks)

    def test_claim_in_comments_requires_review(self) -> None:
        result = verify_record(
            issue=issue(),
            repository=repository(),
            comments=[{"body": "I am working on this now."}],
        )

        self.assertEqual("REVIEW", result.status)
        self.assertTrue(result.claim_signal)
        self.assertIn(
            "possible claim/work-in-progress signal in comments",
            result.risks,
        )

    def test_assigned_issue_requires_review(self) -> None:
        result = verify_record(
            issue=issue(assignees=[{"login": "already-working"}]),
            repository=repository(),
        )

        self.assertEqual("REVIEW", result.status)
        self.assertIn("issue already has assignee(s)", result.risks)

    def test_fork_repository_cannot_be_verified(self) -> None:
        result = verify_record(issue=issue(), repository=repository(fork=True))

        self.assertEqual("REVIEW", result.status)
        self.assertIn(
            "repository is a fork; payout authority is not established",
            result.risks,
        )

    def test_external_author_cannot_be_verified(self) -> None:
        result = verify_record(
            issue=issue(association="NONE"),
            repository=repository(),
        )

        self.assertEqual("REVIEW", result.status)
        self.assertIn("no repository-authority signal on issue author", result.risks)

    def test_repeated_bounty_title_requires_review(self) -> None:
        result = verify_record(
            issue=issue(
                title=(
                    "Bounty Seguro payment task "
                    "Bounty Seguro payment task now"
                )
            ),
            repository=repository(),
        )

        self.assertEqual("REVIEW", result.status)
        self.assertIn("title contains repeated multi-word content", result.risks)

    def test_closed_issue_is_rejected(self) -> None:
        result = verify_record(
            issue=issue(state="closed"),
            repository=repository(),
        )

        self.assertEqual("REJECT", result.status)
        self.assertIn("issue is not open", result.risks)

    def test_archived_repository_is_rejected(self) -> None:
        result = verify_record(
            issue=issue(),
            repository=repository(archived=True),
        )

        self.assertEqual("REJECT", result.status)
        self.assertIn("repository is archived", result.risks)

    def test_comma_delimited_usd_amount_is_supported(self) -> None:
        result = verify_record(
            issue=issue(body="Reward: USD 12,500 paid upon completion."),
            repository=repository(),
        )

        self.assertEqual("VERIFIED", result.status)
        self.assertIn("explicit reward amount: USD 12,500.00", result.reasons)


if __name__ == "__main__":
    unittest.main(verbosity=2)
