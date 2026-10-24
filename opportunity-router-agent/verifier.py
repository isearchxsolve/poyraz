from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

CLAIM_PATTERNS = (
    r"\bclaimed\b",
    r"\bassigned\b",
    r"\bworking on this\b",
    r"\bi(?:'| a)?m working on (?:this|it)\b",
    r"\bi(?:'| wi)?ll take (?:this|it)\b",
    r"\bi can take this\b",
    r"\bopened (?:a )?pr\b",
    r"\bpull request (?:is )?open\b",
)

TENTATIVE_TERMS = (
    "proposed",
    "proposal",
    "suggested bounty",
    "potential bounty",
    "candidate bounty",
)

COMPENSATION_TERMS = (
    "bounty",
    "reward",
    "paid",
    "payment",
    "payout",
    "prize",
)

PAYMENT_TRIGGER_TERMS = (
    "upon merge",
    "after merge",
    "paid on merge",
    "payment after",
    "payout after",
    "rewarded after",
    "on completion",
    "after completion",
    "upon completion",
    "paid upon completion",
)

AMOUNT_RE = re.compile(
    r"(?:(?:USD|US\$|\$)\s*(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?))"
    r"|(?:(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:USD|dollars?))",
    re.IGNORECASE,
)

MAX_REWARD_USD = 1_000_000.0
MIN_REPOSITORY_STARS = 5
AUTHORITY_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


@dataclass(frozen=True)
class Verification:
    score: int
    status: str
    reasons: list[str]
    risks: list[str]
    claim_signal: bool


def _money_amount(text: str) -> float | None:
    """Return the largest valid USD-denominated amount in text."""
    amounts: list[float] = []

    for match in AMOUNT_RE.finditer(text):
        raw = match.group(1) or match.group(2)
        if raw is None:
            continue
        try:
            amount = float(raw.replace(",", ""))
        except ValueError:
            continue
        if 1.0 <= amount <= MAX_REWARD_USD:
            amounts.append(amount)

    return max(amounts) if amounts else None


def _has_repeated_title(title: str) -> bool:
    """
    Identify obvious copy-pasted title duplication without rejecting ordinary
    repeated words such as "test test".
    """
    words = re.findall(r"[a-z0-9]+", title.lower())
    if len(words) < 6:
        return False

    midpoint = len(words) // 2
    for width in range(3, midpoint + 1):
        prefix = words[:width]
        for offset in range(width, len(words) - width + 1):
            if words[offset : offset + width] == prefix:
                return True
    return False


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def verify_record(
    issue: dict[str, Any],
    repository: dict[str, Any],
    comments: list[dict[str, Any]] | None = None,
) -> Verification:
    """
    Verify public evidence only.

    VERIFIED means a repository-associated author published an open,
    non-fork opportunity with a numeric reward and explicit payment condition.
    It never guarantees payment and never authorizes external action.
    """
    comments = comments or []
    score = 0
    reasons: list[str] = []
    risks: list[str] = []

    title = str(issue.get("title") or "").strip()
    body = str(issue.get("body") or "").strip()
    text = f"{title}\n{body}"
    lowered = text.lower()

    issue_open = issue.get("state") == "open"
    repository_archived = bool(repository.get("archived", False))
    repository_fork = bool(repository.get("fork", False))
    association = str(issue.get("author_association") or "NONE").upper()
    reward = _money_amount(text)
    compensation_present = _contains_any(lowered, COMPENSATION_TERMS)
    payment_condition_present = _contains_any(lowered, PAYMENT_TRIGGER_TERMS)
    tentative_reward = _contains_any(lowered, TENTATIVE_TERMS)
    repeated_title = _has_repeated_title(title)
    assignees = issue.get("assignees") or []
    claim_text = "\n".join(str(comment.get("body") or "") for comment in comments)
    claim_signal = any(
        re.search(pattern, claim_text, re.IGNORECASE)
        for pattern in CLAIM_PATTERNS
    )

    if issue_open:
        score += 15
        reasons.append("issue is open")
    else:
        risks.append("issue is not open")

    if repository_archived:
        risks.append("repository is archived")
    else:
        score += 10
        reasons.append("repository is not archived")

    if repository_fork:
        risks.append("repository is a fork; payout authority is not established")
    else:
        reasons.append("repository is not a fork")

    if association in AUTHORITY_ASSOCIATIONS:
        score += 25
        reasons.append(f"posted by repository {association.lower()}")
    elif association == "CONTRIBUTOR":
        score += 10
        risks.append("issue author is a contributor, not a repository authority")
    else:
        risks.append("no repository-authority signal on issue author")

    if reward is not None:
        score += 15
        reasons.append(f"explicit reward amount: USD {reward:,.2f}")
    elif compensation_present:
        risks.append("compensation wording has no explicit monetary amount")
    else:
        risks.append("no explicit compensation wording")

    if payment_condition_present:
        score += 10
        reasons.append("payment/completion trigger described")
    else:
        risks.append("no explicit payout or completion condition")

    stars = int(repository.get("stargazers_count") or 0)
    if stars >= MIN_REPOSITORY_STARS:
        score += 10
        reasons.append(f"repository maturity signal ({stars} stars)")
    else:
        risks.append(
            f"limited repository maturity signal ({stars} stars; "
            f"{MIN_REPOSITORY_STARS} required for maturity credit)"
        )

    if tentative_reward:
        score -= 18
        risks.append("reward appears proposed/not final")

    if repeated_title:
        score -= 20
        risks.append("title contains repeated multi-word content")

    if assignees:
        score -= 20
        risks.append("issue already has assignee(s)")

    if issue.get("locked"):
        score -= 8
        risks.append("issue conversation is locked")

    total_comments = int(issue.get("comments") or 0)
    if total_comments >= 200:
        score -= 35
        risks.append(f"extreme competition signal ({total_comments} comments)")
    elif total_comments >= 100:
        score -= 30
        risks.append(f"very high competition signal ({total_comments} comments)")
    elif total_comments >= 50:
        score -= 22
        risks.append(f"high competition signal ({total_comments} comments)")
    elif total_comments >= 20:
        score -= 14
        risks.append(f"elevated competition signal ({total_comments} comments)")
    elif total_comments >= 10:
        score -= 7
        risks.append(f"moderate competition signal ({total_comments} comments)")

    if claim_signal:
        score -= 25
        risks.append("possible claim/work-in-progress signal in comments")

    score = max(0, min(100, int(score)))

    verified_gates_pass = (
        issue_open
        and not repository_archived
        and not repository_fork
        and association in AUTHORITY_ASSOCIATIONS
        and reward is not None
        and payment_condition_present
        and not tentative_reward
        and not repeated_title
        and not assignees
        and not claim_signal
    )

    if verified_gates_pass and score >= 65:
        status = "VERIFIED"
    elif issue_open and not repository_archived:
        status = "REVIEW"
    else:
        status = "REJECT"

    return Verification(
        score=score,
        status=status,
        reasons=reasons,
        risks=risks,
        claim_signal=claim_signal,
    )
