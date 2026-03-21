"""Deterministic scoring functions — no LLM, pure rule-based."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from repofit.models import EnrichedRepo, FitDimension


def compute_activity_score(repo: EnrichedRepo) -> FitDimension:
    """100% rule-based activity scoring."""
    score = 0
    evidence: list[str] = []

    # Recency (0-30 points)
    if repo.pushed_at:
        try:
            pushed = datetime.fromisoformat(repo.pushed_at.replace("Z", "+00:00"))
            days = (datetime.now(timezone.utc) - pushed).days
            if days <= 7:
                score += 30
                evidence.append("Active in last week")
            elif days <= 30:
                score += 25
                evidence.append(f"Active {days} days ago")
            elif days <= 90:
                score += 15
                evidence.append(f"Last activity {days} days ago")
            elif days <= 365:
                score += 5
                evidence.append(f"Inactive for {days} days")
            else:
                evidence.append(f"No activity for {days} days")
        except ValueError:
            evidence.append("Could not parse push date")

    # Commit velocity (0-25 points)
    if repo.commits_last_90d:
        if repo.commits_last_90d > 100:
            score += 25
            evidence.append(f"{repo.commits_last_90d} commits in 90d (very active)")
        elif repo.commits_last_90d > 30:
            score += 20
            evidence.append(f"{repo.commits_last_90d} commits in 90d (active)")
        elif repo.commits_last_90d > 10:
            score += 10
            evidence.append(f"{repo.commits_last_90d} commits in 90d (moderate)")
        elif repo.commits_last_90d > 0:
            score += 5
            evidence.append(f"{repo.commits_last_90d} commits in 90d (low)")

    # Releases (0-25 points)
    if repo.releases_last_180d:
        if repo.releases_last_180d >= 3:
            score += 25
            evidence.append(f"{repo.releases_last_180d} releases in 180d")
        elif repo.releases_last_180d >= 1:
            score += 15
            evidence.append(f"{repo.releases_last_180d} release(s) in 180d")

    # Issue/PR activity (0-20 points)
    if repo.open_issues > 0:
        score += 10
        evidence.append(f"{repo.open_issues} open issues (active usage)")
    if repo.open_issues < 500:
        score += 10
    else:
        evidence.append(f"{repo.open_issues} open issues (may be overwhelmed)")

    return FitDimension(name="Activity", score=min(score, 100), weight=0.20, evidence=evidence)


def compute_popularity_score(repo: EnrichedRepo) -> FitDimension:
    """Log-normalized popularity scoring."""
    score = 0
    evidence: list[str] = []

    if repo.stars > 0:
        star_score = min(50, int(math.log10(repo.stars + 1) * 15))
        score += star_score
        evidence.append(f"{repo.stars:,} stars")

    if repo.forks > 0:
        fork_score = min(25, int(math.log10(repo.forks + 1) * 10))
        score += fork_score
        evidence.append(f"{repo.forks:,} forks")

    if repo.dependent_repos_count and repo.dependent_repos_count > 0:
        if repo.dependent_repos_count > 1000:
            score += 15
        elif repo.dependent_repos_count > 100:
            score += 10
        elif repo.dependent_repos_count > 10:
            score += 5
        evidence.append(f"{repo.dependent_repos_count:,} dependent repos")

    if repo.watchers > 100:
        score += 10
    elif repo.watchers > 10:
        score += 5
    if repo.watchers > 0:
        evidence.append(f"{repo.watchers:,} watchers")

    return FitDimension(name="Popularity", score=min(score, 100), weight=0.15, evidence=evidence)


def compute_community_score(repo: EnrichedRepo) -> FitDimension:
    """Contributor count and health scoring."""
    score = 0
    evidence: list[str] = []

    tc = repo.contributors_total or 0
    if tc > 100:
        score += 50
        evidence.append(f"{tc} total contributors (large community)")
    elif tc > 30:
        score += 40
        evidence.append(f"{tc} total contributors (healthy)")
    elif tc > 10:
        score += 25
        evidence.append(f"{tc} total contributors (growing)")
    elif tc > 3:
        score += 15
        evidence.append(f"{tc} total contributors (small team)")
    elif tc > 0:
        score += 5
        evidence.append(f"{tc} contributor(s) (minimal)")

    rc = repo.contributors_last_90d or 0
    if rc > 20:
        score += 30
        evidence.append(f"{rc} active contributors (90d)")
    elif rc > 5:
        score += 20
        evidence.append(f"{rc} active contributors (90d)")
    elif rc > 0:
        score += 10
        evidence.append(f"{rc} active contributor(s) (90d)")

    if repo.has_contributing:
        score += 10
        evidence.append("Has contributing guide")
    if repo.has_code_of_conduct:
        score += 10
        evidence.append("Has code of conduct")

    return FitDimension(name="Community", score=min(score, 100), weight=0.15, evidence=evidence)


def compute_quality_score(repo: EnrichedRepo) -> FitDimension:
    """Code quality signals scoring."""
    score = 0
    evidence: list[str] = []

    if repo.license:
        score += 15
        evidence.append(f"License: {repo.license_spdx or repo.license}")
        if repo.license_spdx in ("MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"):
            score += 5
            evidence.append("Permissive license")
    else:
        evidence.append("No license detected")

    if repo.has_ci:
        score += 20
        evidence.append("Has CI/CD pipeline")

    if repo.has_tests:
        score += 20
        evidence.append("Has test suite")

    if repo.has_readme:
        score += 10
        if repo.readme_length and repo.readme_length > 1000:
            score += 5
            evidence.append("Detailed README")
        else:
            evidence.append("Has README")

    if repo.has_changelog:
        score += 10
        evidence.append("Has changelog")

    if repo.openssf_score is not None:
        ossf = min(15, int(repo.openssf_score * 1.5))
        score += ossf
        evidence.append(f"OpenSSF Score: {repo.openssf_score}/10")

    return FitDimension(name="Quality", score=min(score, 100), weight=0.15, evidence=evidence)
