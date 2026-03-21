"""Tests for deterministic scoring + recommendation gates."""

from datetime import datetime, timedelta, timezone

from repofit.analyzer import assign_recommendation
from repofit.scoring import (
    compute_activity_score,
    compute_community_score,
    compute_popularity_score,
    compute_quality_score,
)
from repofit.models import AnalyzedRepo, EnrichedRepo, FitDimension


def _make_repo(**overrides) -> EnrichedRepo:
    """Create a test EnrichedRepo with sensible defaults."""
    now = datetime.now(timezone.utc)
    defaults = {
        "source": "github",
        "full_name": "test/repo",
        "url": "https://github.com/test/repo",
        "stars": 1000,
        "forks": 100,
        "watchers": 50,
        "open_issues": 30,
        "pushed_at": (now - timedelta(days=3)).isoformat(),
        "created_at": (now - timedelta(days=365)).isoformat(),
        "updated_at": (now - timedelta(days=3)).isoformat(),
        "commits_last_90d": 50,
        "releases_last_180d": 2,
        "contributors_total": 25,
        "primary_language": "Python",
        "license": "MIT License",
        "license_spdx": "MIT",
        "has_readme": True,
        "readme_length": 5000,
        "has_ci": True,
        "has_tests": True,
        "has_contributing": True,
        "has_code_of_conduct": True,
        "has_changelog": True,
    }
    defaults.update(overrides)
    return EnrichedRepo(**defaults)


def test_activity_score_recent_active_repo():
    """Active repo should score high on activity."""
    repo = _make_repo(
        pushed_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        commits_last_90d=120,
        releases_last_180d=4,
        open_issues=50,
    )
    result = compute_activity_score(repo)
    assert result.score == 100
    assert result.weight == 0.20


def test_activity_score_dead_repo():
    """Dead repo should score low on activity."""
    repo = _make_repo(
        pushed_at=(datetime.now(timezone.utc) - timedelta(days=500)).isoformat(),
        commits_last_90d=0,
        releases_last_180d=0,
        open_issues=0,
    )
    result = compute_activity_score(repo)
    assert result.score == 10


def test_popularity_score_popular_repo():
    repo = _make_repo(stars=50000, forks=5000, watchers=500, dependent_repos_count=5000)
    result = compute_popularity_score(repo)
    assert result.score >= 80


def test_popularity_score_unknown_repo():
    repo = _make_repo(stars=5, forks=1, watchers=1)
    result = compute_popularity_score(repo)
    assert result.score < 30


def test_community_score_healthy():
    repo = _make_repo(
        contributors_total=50, contributors_last_90d=10,
        has_contributing=True, has_code_of_conduct=True,
    )
    result = compute_community_score(repo)
    assert result.score == 80


def test_community_score_solo():
    repo = _make_repo(
        contributors_total=1, contributors_last_90d=0,
        has_contributing=False, has_code_of_conduct=False,
    )
    result = compute_community_score(repo)
    assert result.score <= 10


def test_quality_score_high_quality():
    repo = _make_repo(
        license="MIT License", license_spdx="MIT",
        has_ci=True, has_tests=True, has_readme=True,
        readme_length=5000, has_changelog=True, openssf_score=8.0,
    )
    result = compute_quality_score(repo)
    assert result.score >= 90


def test_quality_score_no_license():
    repo = _make_repo(license=None, license_spdx=None, has_ci=False, has_tests=False)
    result = compute_quality_score(repo)
    assert result.score < 30


# --- Recommendation gate tests ---

def test_recommendation_strong_candidate():
    repo = _make_repo()
    analyzed = AnalyzedRepo(repo=repo, overall_score=80, fit_score=FitDimension(name="Fit", score=90, weight=0.35))
    assert assign_recommendation(analyzed) == "Strong Candidate"


def test_recommendation_no_license():
    repo = _make_repo(license=None, license_spdx=None)
    analyzed = AnalyzedRepo(repo=repo, overall_score=85, fit_score=FitDimension(name="Fit", score=90, weight=0.35))
    assert assign_recommendation(analyzed) == "Not Suitable"


def test_recommendation_noassertion_license():
    """NOASSERTION license should be treated as no license."""
    repo = _make_repo(license="NOASSERTION", license_spdx="NOASSERTION")
    analyzed = AnalyzedRepo(repo=repo, overall_score=85, fit_score=FitDimension(name="Fit", score=90, weight=0.35))
    assert assign_recommendation(analyzed) == "Not Suitable"


def test_recommendation_forbidden_license():
    """Profile-forbidden license (AGPL) should be Not Suitable."""
    repo = _make_repo(license="AGPL-3.0", license_spdx="AGPL-3.0-only")
    analyzed = AnalyzedRepo(repo=repo, overall_score=80, fit_score=FitDimension(name="Fit", score=90, weight=0.35))
    profile = {"license_policy": {"forbidden": ["AGPL-3.0-only", "SSPL-1.0"]}}
    assert assign_recommendation(analyzed, profile) == "Not Suitable"


def test_recommendation_allowed_license_with_profile():
    """Allowed license should pass even with profile."""
    repo = _make_repo()
    analyzed = AnalyzedRepo(repo=repo, overall_score=80, fit_score=FitDimension(name="Fit", score=90, weight=0.35))
    profile = {"license_policy": {"forbidden": ["AGPL-3.0-only"], "allowed": ["MIT"]}}
    assert assign_recommendation(analyzed, profile) == "Strong Candidate"


def test_recommendation_agpl_short_spdx():
    """AGPL-3.0 (without -only suffix) should also match forbidden AGPL-3.0-only."""
    repo = _make_repo(license="AGPL-3.0", license_spdx="AGPL-3.0")
    analyzed = AnalyzedRepo(repo=repo, overall_score=80, fit_score=FitDimension(name="Fit", score=90, weight=0.35))
    profile = {"license_policy": {"forbidden": ["AGPL-3.0-only", "AGPL-3.0-or-later"]}}
    assert assign_recommendation(analyzed, profile) == "Not Suitable"


def test_recommendation_dead_project():
    repo = _make_repo(pushed_at=(datetime.now(timezone.utc) - timedelta(days=400)).isoformat())
    analyzed = AnalyzedRepo(repo=repo, overall_score=60, fit_score=FitDimension(name="Fit", score=70, weight=0.35))
    assert assign_recommendation(analyzed) == "Not Suitable"


def test_recommendation_no_profile():
    """Without profile, only generic gates apply."""
    repo = _make_repo(license="AGPL-3.0", license_spdx="AGPL-3.0-only")
    analyzed = AnalyzedRepo(repo=repo, overall_score=80, fit_score=FitDimension(name="Fit", score=90, weight=0.35))
    assert assign_recommendation(analyzed) == "Strong Candidate"  # No profile = no forbidden list
