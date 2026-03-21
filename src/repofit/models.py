"""Pydantic data models — the contract between pipeline stages."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Stage 1 Output
# ---------------------------------------------------------------------------

class ParsedRequirements(BaseModel):
    """LLM-extracted requirements from the input document."""

    project_name: str
    project_summary: str

    # Search signals
    primary_keywords: list[str] = Field(default_factory=list)
    secondary_keywords: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)

    # Technical constraints
    preferred_languages: list[str] = Field(default_factory=list)
    preferred_frameworks: list[str] = Field(default_factory=list)
    deployment_model: str | None = None

    # Domain classification
    domains: list[str] = Field(default_factory=list)

    # Evaluation criteria
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    deal_breakers: list[str] = Field(default_factory=list)

    # Scale expectations
    maturity_preference: str = "any"
    community_size_preference: str = "any"


# ---------------------------------------------------------------------------
# Stage 2 Output
# ---------------------------------------------------------------------------

class RepoCandidate(BaseModel):
    """Raw search result before enrichment."""

    source: str
    full_name: str
    url: str
    description: str | None = None
    stars: int | None = None
    forks: int | None = None
    language: str | None = None
    topics: list[str] = Field(default_factory=list)
    updated_at: str | None = None
    search_query: str = ""
    search_rank: int = 0


# ---------------------------------------------------------------------------
# Stage 3 Output
# ---------------------------------------------------------------------------

class EnrichedRepo(BaseModel):
    """Fully enriched repository data."""

    # Identity
    source: str
    full_name: str
    url: str
    description: str | None = None
    homepage: str | None = None

    # Popularity
    stars: int = 0
    forks: int = 0
    watchers: int = 0
    open_issues: int = 0

    # Activity
    created_at: str = ""
    updated_at: str = ""
    pushed_at: str = ""
    last_commit_date: str | None = None
    commits_last_90d: int | None = None
    releases_last_180d: int | None = None
    latest_release: str | None = None
    latest_release_date: str | None = None

    # Community
    contributors_total: int | None = None
    contributors_last_90d: int | None = None

    # Technical
    primary_language: str | None = None
    languages: dict[str, int] = Field(default_factory=dict)
    topics: list[str] = Field(default_factory=list)
    license: str | None = None
    license_spdx: str | None = None

    # Quality signals
    has_readme: bool = False
    readme_length: int | None = None
    readme_excerpt: str | None = None
    has_ci: bool = False
    has_tests: bool = False
    has_contributing: bool = False
    has_code_of_conduct: bool = False
    has_changelog: bool = False

    # OpenSSF Scorecard (optional, GitHub only)
    openssf_score: float | None = None
    openssf_checks: dict[str, float] | None = None

    # ecosyste.ms data (optional)
    dependent_repos_count: int | None = None
    dependent_packages_count: int | None = None
    download_count: int | None = None

    # Metadata
    search_queries: list[str] = Field(default_factory=list)
    enriched_at: str = ""


# ---------------------------------------------------------------------------
# Stage 4 Output
# ---------------------------------------------------------------------------

class FitDimension(BaseModel):
    """A single scoring dimension with evidence."""

    name: str
    score: float = 0.0
    weight: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class AnalyzedRepo(BaseModel):
    """Final analysis result per repository."""

    repo: EnrichedRepo

    # Overall
    overall_score: float = 0.0
    recommendation: str = "Not Suitable"

    # Dimension scores
    fit_score: FitDimension = Field(default_factory=lambda: FitDimension(name="Fit", weight=0.35))
    activity_score: FitDimension = Field(default_factory=lambda: FitDimension(name="Activity", weight=0.20))
    community_score: FitDimension = Field(default_factory=lambda: FitDimension(name="Community", weight=0.15))
    popularity_score: FitDimension = Field(default_factory=lambda: FitDimension(name="Popularity", weight=0.15))
    quality_score: FitDimension = Field(default_factory=lambda: FitDimension(name="Quality", weight=0.15))

    # LLM analysis
    summary: str = ""
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    fit_explanation: str = ""
    risk_factors: list[str] = Field(default_factory=list)

    # Comparison helpers
    similar_to: list[str] = Field(default_factory=list)
    differentiator: str = ""


# ---------------------------------------------------------------------------
# Search helper
# ---------------------------------------------------------------------------

class SearchQuery(BaseModel):
    """A single search query to execute."""

    terms: str
    language: str | None = None
    sort: str = "stars"
    max_results: int = 10
    platform: str = "github"


class EcosystemsQuery(BaseModel):
    """An ecosyste.ms topic search query."""

    topic: str
    max_results: int = 10


# ---------------------------------------------------------------------------
# Pipeline Configuration
# ---------------------------------------------------------------------------

_MODE_RATIOS = {
    "quick": {
        "search_mult": 3.0, "search_floor": 10,
        "enrich_mult": 2.0, "enrich_floor": 5,
        "llm_mult": 1.5, "llm_floor": 3,
        "query_budget": 10, "per_query_results": 10,
        "concurrency": 8, "timeout": 30,
        "skip_scorecard": True, "skip_ecosystems": True,
        "skip_comparison": True,
        "batch_size": 10, "readme_chars": 200,
    },
    "normal": {
        "search_mult": 5.0, "search_floor": 20,
        "enrich_mult": 3.0, "enrich_floor": 10,
        "llm_mult": 2.0, "llm_floor": 5,
        "query_budget": 16, "per_query_results": 15,
        "concurrency": 5, "timeout": 45,
        "skip_scorecard": False, "skip_ecosystems": False,
        "skip_comparison": False,
        "batch_size": 5, "readme_chars": 500,
    },
    "thorough": {
        "search_mult": 8.0, "search_floor": 40,
        "enrich_mult": 5.0, "enrich_floor": 20,
        "llm_mult": 3.0, "llm_floor": 10,
        "query_budget": 24, "per_query_results": 20,
        "concurrency": 5, "timeout": 60,
        "skip_scorecard": False, "skip_ecosystems": False,
        "skip_comparison": False,
        "batch_size": 5, "readme_chars": 500,
    },
}


class PipelineConfig:
    """Derived pipeline parameters from --max and --mode."""

    def __init__(self, max_repos: int, mode: str = "normal") -> None:
        if mode not in _MODE_RATIOS:
            raise ValueError(f"Unknown mode: {mode}. Choose: quick, normal, thorough")
        r = _MODE_RATIOS[mode]
        self.max_repos = max_repos
        self.mode = mode

        # Search
        self.query_budget = r["query_budget"]
        self.search_target = max(r["search_floor"], round(max_repos * r["search_mult"]))
        self.per_query_results = r["per_query_results"]

        # Enrichment
        self.enrichment_budget = max(r["enrich_floor"], round(max_repos * r["enrich_mult"]))
        self.enrichment_concurrency = r["concurrency"]
        self.per_repo_timeout = r["timeout"]
        self.skip_scorecard = r["skip_scorecard"]
        self.skip_ecosystems_detail = r["skip_ecosystems"]

        # LLM Analysis
        self.llm_budget = max(r["llm_floor"], round(max_repos * r["llm_mult"]))
        self.llm_batch_size = r.get("batch_size", 5)
        self.readme_chars = r.get("readme_chars", 500)
        self.skip_comparison = r["skip_comparison"]

    def summary(self) -> str:
        return (
            f"Mode: {self.mode} | Max: {self.max_repos} | "
            f"Search: {self.query_budget} queries | "
            f"Enrich: {self.enrichment_budget} | LLM: {self.llm_budget}"
        )
