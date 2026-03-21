"""Tests for report generation — verify structure."""

from datetime import datetime, timedelta, timezone

from repofit.models import AnalyzedRepo, EnrichedRepo, FitDimension, ParsedRequirements
from repofit.report import generate_csv, generate_json, generate_markdown


def _make_analyzed_repos() -> list[AnalyzedRepo]:
    now = datetime.now(timezone.utc)
    repo1 = EnrichedRepo(
        source="github",
        full_name="owner/strong-repo",
        url="https://github.com/owner/strong-repo",
        stars=10000,
        forks=500,
        watchers=200,
        open_issues=30,
        primary_language="Python",
        license="MIT License",
        license_spdx="MIT",
        pushed_at=(now - timedelta(days=2)).isoformat(),
        created_at=(now - timedelta(days=365)).isoformat(),
        updated_at=(now - timedelta(days=2)).isoformat(),
        has_readme=True,
        has_ci=True,
        has_tests=True,
        topics=["ai", "agents"],
    )
    repo2 = EnrichedRepo(
        source="github",
        full_name="owner/weak-repo",
        url="https://github.com/owner/weak-repo",
        stars=50,
        forks=5,
        primary_language="JavaScript",
        license_spdx="Apache-2.0",
        pushed_at=(now - timedelta(days=200)).isoformat(),
        created_at=(now - timedelta(days=500)).isoformat(),
        updated_at=(now - timedelta(days=200)).isoformat(),
        topics=["web"],
    )
    return [
        AnalyzedRepo(
            repo=repo1,
            overall_score=85,
            recommendation="Strong Candidate",
            fit_score=FitDimension(name="Fit", score=90, weight=0.35, evidence=["Great match"]),
            activity_score=FitDimension(name="Activity", score=80, weight=0.20, evidence=["Active"]),
            community_score=FitDimension(name="Community", score=70, weight=0.15),
            popularity_score=FitDimension(name="Popularity", score=85, weight=0.15),
            quality_score=FitDimension(name="Quality", score=90, weight=0.15),
            summary="A strong AI agent framework.",
            pros=["Active development", "Large community"],
            cons=["Complex setup"],
            fit_explanation="Matches AI agent requirements well.",
            risk_factors=["Rapid API changes"],
        ),
        AnalyzedRepo(
            repo=repo2,
            overall_score=35,
            recommendation="Low Priority",
            fit_score=FitDimension(name="Fit", score=30, weight=0.35),
            activity_score=FitDimension(name="Activity", score=20, weight=0.20),
            community_score=FitDimension(name="Community", score=10, weight=0.15),
            popularity_score=FitDimension(name="Popularity", score=15, weight=0.15),
            quality_score=FitDimension(name="Quality", score=25, weight=0.15),
            summary="A small web project.",
        ),
    ]


def _make_reqs() -> ParsedRequirements:
    return ParsedRequirements(
        project_name="Test AI Platform",
        project_summary="An AI agent orchestration platform.",
        domains=["AI Agents"],
        primary_keywords=["AI", "agents"],
    )


def test_markdown_has_required_sections():
    """Markdown report should contain all required sections."""
    analyzed = _make_analyzed_repos()
    reqs = _make_reqs()
    md = generate_markdown(analyzed, reqs)

    assert "# RepoFit Analysis Report" in md
    assert "## Executive Summary" in md
    assert "## Top Recommendations" in md
    assert "## Comparison Matrix" in md
    assert "## Methodology" in md


def test_markdown_profile_name_in_header():
    """Profile name should appear in header when provided."""
    analyzed = _make_analyzed_repos()
    reqs = _make_reqs()
    md = generate_markdown(analyzed, reqs, profile_name="Dataguess Default")
    assert "**Profile:** Dataguess Default" in md


def test_markdown_first_place_trophy():
    """First repo should have trophy emoji."""
    analyzed = _make_analyzed_repos()
    reqs = _make_reqs()
    md = generate_markdown(analyzed, reqs)
    # First repo gets trophy
    assert "### \U0001f3c6 1." in md  # 🏆


def test_markdown_methodology_detailed():
    """Methodology should include threshold details."""
    analyzed = _make_analyzed_repos()
    reqs = _make_reqs()
    md = generate_markdown(analyzed, reqs)
    assert "Strong Candidate >= 75" in md
    assert "Hard gates" in md


def test_markdown_contains_repo_names():
    """Report should mention all analyzed repos."""
    analyzed = _make_analyzed_repos()
    reqs = _make_reqs()
    md = generate_markdown(analyzed, reqs)

    assert "owner/strong-repo" in md
    assert "owner/weak-repo" in md


def test_markdown_comparison_table():
    """Comparison matrix should have table headers."""
    analyzed = _make_analyzed_repos()
    reqs = _make_reqs()
    md = generate_markdown(analyzed, reqs)

    assert "| Repository |" in md
    assert "| Score |" in md or "Score" in md


def test_markdown_score_breakdown():
    """Report should include score breakdown for repos."""
    analyzed = _make_analyzed_repos()
    reqs = _make_reqs()
    md = generate_markdown(analyzed, reqs)

    assert "Fit:" in md
    assert "Activity:" in md
    assert "Quality:" in md


def test_csv_output():
    """CSV should have headers and data rows."""
    analyzed = _make_analyzed_repos()
    csv_output = generate_csv(analyzed)
    lines = csv_output.strip().split("\n")

    assert len(lines) == 3  # header + 2 repos
    assert "Repository" in lines[0]
    assert "owner/strong-repo" in lines[1]


def test_json_output():
    """JSON should be valid and contain repos."""
    import json
    analyzed = _make_analyzed_repos()
    json_output = generate_json(analyzed)
    data = json.loads(json_output)

    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["repo"]["full_name"] == "owner/strong-repo"
    assert data[0]["overall_score"] == 85
