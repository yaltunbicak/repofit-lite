"""Tests for search orchestration — API mocked."""

from repofit.models import ParsedRequirements, RepoCandidate
from repofit.search import _deduplicate, build_search_queries
from repofit.utils import normalize_repo_url


def test_build_search_queries_generates_multiple_strategies():
    """build_search_queries should produce queries from all strategies."""
    reqs = ParsedRequirements(
        project_name="Test",
        project_summary="Test project",
        primary_keywords=["AI agents", "LangGraph", "multi-agent", "orchestration"],
        secondary_keywords=["LLM"],
        preferred_languages=["Python"],
        preferred_frameworks=["FastAPI", "React"],
        domains=["AI Agents"],
    )
    queries = build_search_queries(reqs)

    terms = [q.terms for q in queries if hasattr(q, "terms")]

    # Strategy A: keyword combos
    assert any("AI agents" in t and "LangGraph" in t for t in terms)

    # Strategy B: domain + framework
    assert any("AI Agents" in t and "FastAPI" in t for t in terms)

    # Strategy C: awesome lists
    assert any("awesome" in t for t in terms)

    # Strategy D: ecosyste.ms
    eco_queries = [q for q in queries if hasattr(q, "topic")]
    assert len(eco_queries) > 0

    # Strategy E: broad domain queries
    assert any("multi-agent framework" in t or "AI agent platform" in t for t in terms)


def test_build_queries_with_pinned_orgs():
    """Strategy F: profile pinned orgs should generate org-scoped queries."""
    reqs = ParsedRequirements(
        project_name="Test",
        project_summary="Test",
        primary_keywords=["AI agents"],
        domains=["AI Agents"],
    )
    profile = {"pinned_orgs": {"github": ["langchain-ai", "microsoft"]}}
    queries = build_search_queries(reqs, profile)
    terms = [q.terms for q in queries if hasattr(q, "terms")]
    assert any("org:langchain-ai" in t for t in terms)
    assert any("org:microsoft" in t for t in terms)


def test_normalize_url():
    assert normalize_repo_url("https://github.com/owner/repo/") == "https://github.com/owner/repo"
    assert normalize_repo_url("https://github.com/owner/repo.git") == "https://github.com/owner/repo"
    assert normalize_repo_url("HTTPS://GitHub.com/Owner/Repo") == "https://github.com/owner/repo"


def test_deduplicate_removes_duplicates():
    candidates = [
        RepoCandidate(source="github", full_name="owner/repo", url="https://github.com/owner/repo", stars=100, search_query="query1", search_rank=1),
        RepoCandidate(source="github", full_name="owner/repo", url="https://github.com/owner/repo/", stars=100, search_query="query2", search_rank=2),
        RepoCandidate(source="github", full_name="other/project", url="https://github.com/other/project", stars=50, search_query="query1", search_rank=3),
    ]
    result = _deduplicate(candidates)
    assert len(result) == 2


def test_deduplicate_keeps_higher_stars():
    candidates = [
        RepoCandidate(source="github", full_name="owner/repo", url="https://github.com/owner/repo", stars=50, search_query="q1", search_rank=1),
        RepoCandidate(source="github", full_name="owner/repo", url="https://github.com/owner/repo", stars=200, search_query="q2", search_rank=1),
    ]
    result = _deduplicate(candidates)
    assert len(result) == 1
    assert result[0].stars == 200


def test_build_queries_empty_keywords():
    reqs = ParsedRequirements(project_name="Test", project_summary="Minimal")
    queries = build_search_queries(reqs)
    assert isinstance(queries, list)
