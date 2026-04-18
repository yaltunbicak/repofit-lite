# RepoFit Lite — Technical Design & Implementation Plan

## 1. Product Summary

RepoFit Lite is a **single-command Python CLI tool** that accepts a project document (PRD, architecture doc, or free-text description), automatically discovers relevant open-source repositories from GitHub and GitLab, fetches real metadata for each candidate, performs LLM-powered fit analysis, and outputs a structured Markdown report ranking the best matches.

```
repofit analyze --input ./my_prd.md --profile dataguess --output ./report.md
```

### 1.1 What It Is NOT

- NOT a web application — no UI, no database, no Docker
- NOT a monitoring system — runs on demand, not continuously
- NOT a data platform — no PostgreSQL, no Redis, no message queues
- NOT Augur — no dependency on any third-party analytics platform

### 1.2 Core Value Proposition

User gives a document → tool returns a ranked, evidence-based shortlist of open-source projects with fit scores, pros/cons, and actionable recommendations.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     repofit-lite CLI                        │
├─────────────┬─────────────┬──────────────┬─────────────────┤
│  1. Parser  │  2. Search  │  3. Enrich   │  4. Analyze     │
│  (LLM)      │  (API)      │  (API)       │  (LLM)          │
│             │             │              │                 │
│ PRD → JSON  │ GitHub API  │ Per-repo     │ Fit scoring     │
│ extract:    │ GitLab API  │ metadata:    │ Pros/cons       │
│ - keywords  │ ecosyste.ms │ - README     │ Comparison      │
│ - languages │             │ - Languages  │ Recommendation  │
│ - domains   │             │ - License    │ Report gen      │
│ - criteria  │             │ - Activity   │                 │
│ - antipattn │             │ - OpenSSF    │                 │
└─────────────┴─────────────┴──────────────┴─────────────────┘
         │              │             │              │
         ▼              ▼             ▼              ▼
    requirements.json  candidates[]  enriched[]    report.md
```

**A four-stage, one-way pipeline. Each stage builds upon the output of the previous one.**

---

## 3. Folder Structure

```
repofit-lite/
├── README.md
├── pyproject.toml
├── .env.example
├── profiles/
│   ├── dataguess.yaml          # Company-specific default profile
│   └── examples/
│       ├── ai_agent_platform.yaml
│       ├── rag_stack.yaml
│       ├── cv_inspection.yaml
│       ├── mlops_platform.yaml
│       ├── industrial_iot.yaml
│       └── workflow_automation.yaml
├── src/
│   └── repofit/
│       ├── __init__.py
│       ├── cli.py              # Typer CLI entry point
│       ├── config.py           # Settings, env vars, defaults
│       ├── pipeline.py         # Orchestrates 4 stages
│       ├── parser.py           # Stage 1: LLM document parsing
│       ├── search.py           # Stage 2: GitHub/GitLab/ecosyste.ms search
│       ├── enrichment.py       # Stage 3: Per-repo metadata fetching
│       ├── analyzer.py         # Stage 4: LLM fit analysis + scoring
│       ├── report.py           # Markdown report generator
│       ├── models.py           # Pydantic data models
│       ├── github_client.py    # GitHub REST/GraphQL client
│       ├── gitlab_client.py    # GitLab REST client
│       ├── ecosystems_client.py # ecosyste.ms API client
│       ├── scorecard_client.py # OpenSSF Scorecard API client
│       ├── llm_client.py       # Multi-provider LLM abstraction (Gemini, Anthropic, OpenAI)
│       └── utils.py            # Rate limiting, retry, logging
├── tests/
│   ├── test_parser.py
│   ├── test_search.py
│   ├── test_enrichment.py
│   ├── test_analyzer.py
│   ├── test_report.py
│   └── fixtures/
│       ├── sample_prd.md
│       └── sample_repos.json
└── cache/                      # Auto-created, gitignored
    └── repos/                  # Cached API responses (24h TTL)
```

---

## 4. Data Models (Pydantic)

### 4.1 Stage 1 Output: ParsedRequirements

```python
class ParsedRequirements(BaseModel):
    """LLM-extracted requirements from the input document."""

    project_name: str
    project_summary: str  # 2-3 sentence summary

    # Search signals
    primary_keywords: list[str]       # max 10, most specific terms
    secondary_keywords: list[str]     # max 15, broader related terms
    negative_keywords: list[str]      # terms to exclude

    # Technical constraints
    preferred_languages: list[str]    # e.g. ["Python", "TypeScript", "Go"]
    preferred_frameworks: list[str]   # e.g. ["FastAPI", "NestJS", "React"]
    deployment_model: str | None      # "on-premise", "cloud", "hybrid", "any"

    # Domain classification
    domains: list[str]                # e.g. ["AI Agents", "Workflow Automation"]

    # Evaluation criteria (what matters most for THIS project)
    must_have: list[str]              # e.g. ["REST API", "Docker support", "MIT or Apache license"]
    nice_to_have: list[str]           # e.g. ["Plugin system", "Multi-tenant"]
    deal_breakers: list[str]          # e.g. ["GPL license", "No activity in 12 months"]

    # Scale expectations
    maturity_preference: str          # "production-ready", "growing", "any"
    community_size_preference: str    # "large", "medium", "small-ok", "any"
```

### 4.2 Stage 2 Output: RepoCandidate

```python
class RepoCandidate(BaseModel):
    """Raw search result before enrichment."""

    source: str                       # "github", "gitlab", "ecosystems"
    full_name: str                    # "owner/repo"
    url: str
    description: str | None
    stars: int | None
    forks: int | None
    language: str | None
    topics: list[str]
    updated_at: str | None
    search_query: str                 # which query found this repo
    search_rank: int                  # position in search results
```

### 4.3 Stage 3 Output: EnrichedRepo

```python
class EnrichedRepo(BaseModel):
    """Fully enriched repository data."""

    # Identity
    source: str
    full_name: str
    url: str
    description: str | None
    homepage: str | None

    # Popularity
    stars: int
    forks: int
    watchers: int
    open_issues: int

    # Activity
    created_at: str
    updated_at: str
    pushed_at: str
    last_commit_date: str | None
    commits_last_90d: int | None
    releases_last_180d: int | None
    latest_release: str | None
    latest_release_date: str | None

    # Community
    contributors_total: int | None
    contributors_last_90d: int | None

    # Technical
    primary_language: str | None
    languages: dict[str, int]         # language -> bytes
    topics: list[str]
    license: str | None
    license_spdx: str | None

    # Quality signals
    has_readme: bool
    readme_length: int | None
    readme_excerpt: str | None        # first 2000 chars
    has_ci: bool                      # .github/workflows or .gitlab-ci.yml detected
    has_tests: bool                   # test directory or config detected
    has_contributing: bool
    has_code_of_conduct: bool
    has_changelog: bool

    # OpenSSF Scorecard (optional, GitHub only)
    openssf_score: float | None       # 0-10
    openssf_checks: dict[str, float] | None

    # ecosyste.ms data (optional)
    dependent_repos_count: int | None
    dependent_packages_count: int | None
    download_count: int | None

    # Metadata
    search_queries: list[str]         # all queries that found this repo
    enriched_at: str
```

### 4.4 Stage 4 Output: AnalyzedRepo

```python
class FitDimension(BaseModel):
    name: str
    score: float                      # 0-100
    weight: float                     # 0.0-1.0
    evidence: list[str]               # bullet points explaining score

class AnalyzedRepo(BaseModel):
    """Final analysis result per repository."""

    repo: EnrichedRepo

    # Overall
    overall_score: float              # 0-100 weighted
    recommendation: str               # "Strong Candidate" | "Review Further" | "Low Priority" | "Not Suitable"

    # Dimension scores
    fit_score: FitDimension           # 35% - relevance to requirements
    activity_score: FitDimension      # 20% - project liveliness
    community_score: FitDimension     # 15% - contributor health
    popularity_score: FitDimension    # 15% - adoption signals
    quality_score: FitDimension       # 15% - maintainability

    # LLM analysis
    summary: str                      # 2-3 sentence what this repo does
    pros: list[str]                   # max 5
    cons: list[str]                   # max 5
    fit_explanation: str              # Why it matches or doesn't match the requirements
    risk_factors: list[str]           # max 3

    # Comparison helpers
    similar_to: list[str]             # other repos in this batch it's similar to
    differentiator: str               # what makes it unique vs alternatives
```

---

## 5. Stage Details

### 5.1 Stage 1: Document Parsing (parser.py)

**Input:** Raw document text (Markdown, plain text, or PDF text)
**Output:** `ParsedRequirements`
**Method:** Single LLM call

```python
PARSER_SYSTEM_PROMPT = """
You are a technical analyst. Given a project document (PRD, architecture doc,
or description), extract structured requirements for finding matching
open-source repositories.

Be specific with keywords. Prefer technical terms over generic ones.
For example: "LangGraph" over "AI", "FastAPI" over "web framework".

Extract both what the project NEEDS and what it should AVOID.

If the document mentions specific technologies, frameworks, or patterns,
include those as primary_keywords.

Output valid JSON matching the provided schema. Nothing else.
"""
```

**Profile merging:** If a `--profile` is specified, the profile's preferences are merged with the LLM-extracted requirements. Profile values act as defaults; document-extracted values override.

### 5.2 Stage 2: Repository Search (search.py)

**Input:** `ParsedRequirements`
**Output:** `list[RepoCandidate]` (deduplicated)

**Search strategy — multi-query fan-out:**

```python
def build_search_queries(reqs: ParsedRequirements) -> list[SearchQuery]:
    """Generate 8-15 targeted search queries from requirements."""
    queries = []

    # Strategy A: Direct keyword combinations (primary keywords, 2-3 at a time)
    for combo in itertools.combinations(reqs.primary_keywords[:8], 2):
        queries.append(SearchQuery(
            terms=" ".join(combo),
            language=reqs.preferred_languages[0] if reqs.preferred_languages else None,
            sort="stars",
            max_results=10
        ))

    # Strategy B: Domain + framework combos
    for domain in reqs.domains[:3]:
        for fw in reqs.preferred_frameworks[:3]:
            queries.append(SearchQuery(
                terms=f"{domain} {fw}",
                sort="stars",
                max_results=5
            ))

    # Strategy C: "awesome-list" mining
    for kw in reqs.primary_keywords[:5]:
        queries.append(SearchQuery(
            terms=f"awesome {kw}",
            sort="stars",
            max_results=3
        ))

    # Strategy D: ecosyste.ms topic search (broader discovery)
    for kw in reqs.primary_keywords[:5]:
        queries.append(EcosystemsQuery(topic=kw, max_results=10))

    return queries
```

**API endpoints:**

| Source | Endpoint | Rate Limit | Auth |
|--------|----------|------------|------|
| GitHub Search | `GET /search/repositories?q=...` | 30 req/min (authenticated) | PAT |
| GitLab Search | `GET /api/v4/search?scope=projects&search=...` | 10 req/sec | PAT |
| ecosyste.ms | `GET /api/v1/repositories/search?q=...` | 5000 req/hr | Email header |

**Deduplication:** By normalized URL. If same repo found by multiple queries, merge `search_queries` list.

**Target:** 50-100 unique candidates before enrichment.

### 5.3 Stage 3: Enrichment (enrichment.py)

**Input:** `list[RepoCandidate]`
**Output:** `list[EnrichedRepo]`

**Per-repo API calls (parallel with asyncio + semaphore):**

```python
async def enrich_repo(candidate: RepoCandidate) -> EnrichedRepo:
    """Fetch full metadata for a single repo. Uses cache if fresh."""

    if cached := cache.get(candidate.url, max_age_hours=24):
        return cached

    if candidate.source == "github":
        # 1. Repo metadata: GET /repos/{owner}/{repo}
        # 2. Languages: GET /repos/{owner}/{repo}/languages
        # 3. Contributors: GET /repos/{owner}/{repo}/contributors?per_page=1&anon=true
        #    (use Link header for total count)
        # 4. Releases: GET /repos/{owner}/{repo}/releases?per_page=5
        # 5. README: GET /repos/{owner}/{repo}/readme (Accept: application/vnd.github.raw)
        # 6. Community profile: GET /repos/{owner}/{repo}/community/profile
        # 7. Commit activity: GET /repos/{owner}/{repo}/stats/commit_activity
        # 8. Contents check: GET /repos/{owner}/{repo}/contents/ (root listing for CI/test detection)

    elif candidate.source == "gitlab":
        # 1. Project: GET /api/v4/projects/{id}
        # 2. Languages: GET /api/v4/projects/{id}/languages
        # 3. Members: GET /api/v4/projects/{id}/members/all
        # 4. Releases: GET /api/v4/projects/{id}/releases
        # 5. README: GET /api/v4/projects/{id}/repository/files/README.md/raw
        # 6. Repository tree: GET /api/v4/projects/{id}/repository/tree

    # Optional enrichments (non-blocking, fail silently)
    openssf = await scorecard_client.get_score(candidate.url)  # GitHub only
    ecosystems = await ecosystems_client.get_repo(candidate.url)

    return EnrichedRepo(...)
```

**Concurrency:** `asyncio.Semaphore(5)` — max 5 parallel requests per platform to stay within rate limits.

**Caching:** Simple JSON file cache in `./cache/repos/{url_hash}.json` with 24-hour TTL. Avoids re-fetching when re-running analysis.

**CI detection heuristic:**
```python
CI_INDICATORS = [
    ".github/workflows",    # GitHub Actions
    ".gitlab-ci.yml",       # GitLab CI
    "Jenkinsfile",          # Jenkins
    ".circleci",            # CircleCI
    ".travis.yml",          # Travis CI
    "azure-pipelines.yml",  # Azure DevOps
]
```

**Test detection heuristic:**
```python
TEST_INDICATORS = [
    "tests/", "test/", "spec/", "__tests__/",
    "pytest.ini", "setup.cfg[tool:pytest]",
    "jest.config", "vitest.config",
    "karma.conf", "cypress.config",
]
```

### 5.4 Stage 4: Analysis (analyzer.py)

**Input:** `ParsedRequirements` + `list[EnrichedRepo]`
**Output:** `list[AnalyzedRepo]`

**Two-phase analysis:**

#### Phase A: Deterministic scoring (no LLM)

```python
def compute_activity_score(repo: EnrichedRepo) -> FitDimension:
    """100% rule-based, no LLM needed."""
    score = 0
    evidence = []

    # Recency (0-30 points)
    days_since_push = (now - repo.pushed_at).days
    if days_since_push <= 7:
        score += 30; evidence.append("Active in last week")
    elif days_since_push <= 30:
        score += 25; evidence.append(f"Active {days_since_push} days ago")
    elif days_since_push <= 90:
        score += 15; evidence.append(f"Last activity {days_since_push} days ago")
    elif days_since_push <= 365:
        score += 5; evidence.append(f"Inactive for {days_since_push} days")
    else:
        evidence.append(f"⚠️ No activity for {days_since_push} days")

    # Commit velocity (0-25 points)
    if repo.commits_last_90d:
        if repo.commits_last_90d > 100: score += 25
        elif repo.commits_last_90d > 30: score += 20
        elif repo.commits_last_90d > 10: score += 10
        elif repo.commits_last_90d > 0: score += 5

    # Releases (0-25 points)
    if repo.releases_last_180d:
        if repo.releases_last_180d >= 3: score += 25
        elif repo.releases_last_180d >= 1: score += 15

    # Issue/PR activity (0-20 points)
    if repo.open_issues > 0: score += 10  # issues exist = people use it
    if repo.open_issues < 500: score += 10  # not overwhelmed

    return FitDimension(name="Activity", score=min(score, 100), weight=0.20, evidence=evidence)
```

Similar deterministic functions for `popularity_score`, `community_score`, `quality_score`.

#### Phase B: LLM-powered fit analysis (fit_score + pros/cons/summary)

**Batched LLM calls — 5 repos per call to minimize API costs:**

```python
ANALYZER_SYSTEM_PROMPT = """
You are a senior software architect evaluating open-source projects for
adoption. You will receive:
1. Project requirements extracted from a PRD
2. Metadata for up to 5 candidate repositories

For each repository, provide:
- fit_score (0-100): How well does this repo match the requirements?
- summary: 2-3 sentences describing what this repo does
- pros: Up to 5 specific advantages for THIS project's needs
- cons: Up to 5 specific disadvantages or gaps
- fit_explanation: Why it matches or doesn't (reference specific requirements)
- risk_factors: Up to 3 risks of adopting this repo
- similar_to: Which other repos in this batch serve the same purpose
- differentiator: What makes this repo unique vs the alternatives

Be specific. Reference actual data (stars, last commit, license, languages).
Don't be generic. Tailor every assessment to the requirements.

Output valid JSON array. Nothing else.
"""
```

#### Phase C: Recommendation assignment

```python
def assign_recommendation(repo: AnalyzedRepo) -> str:
    """Rule-based gates + score thresholds."""

    # Hard gates — cannot be Strong Candidate if:
    if not repo.repo.license:
        return "Not Suitable"  # No license = legal risk
    if repo.repo.license_spdx in ["GPL-3.0", "AGPL-3.0"] and profile.requires_permissive:
        return "Not Suitable"
    days_inactive = (now - repo.repo.pushed_at).days
    if days_inactive > 365:
        return "Not Suitable"  # Dead project

    # Score-based thresholds
    if repo.overall_score >= 75:
        return "Strong Candidate"
    elif repo.overall_score >= 50:
        return "Review Further"
    elif repo.overall_score >= 30:
        return "Low Priority"
    else:
        return "Not Suitable"
```

---

## 6. Report Generation (report.py)

### 6.1 Output: Markdown Report

```markdown
# RepoFit Analysis Report

**Project:** {project_name}
**Generated:** {datetime}
**Candidates evaluated:** {count}
**Profile:** {profile_name}

## Executive Summary

{LLM-generated 3-5 sentence summary of findings}

## Top Recommendations

### 🏆 1. {repo_name} — Score: {score}/100 — ✅ Strong Candidate

> {summary}

| Metric | Value |
|--------|-------|
| Stars | {stars} |
| Last Activity | {pushed_at} |
| License | {license} |
| Language | {language} |
| Contributors (90d) | {contributors_last_90d} |
| OpenSSF Score | {openssf_score}/10 |

**Fit Score:** {fit_score}/100 — {fit_explanation}

**Pros:**
- {pro_1}
- {pro_2}

**Cons:**
- {con_1}
- {con_2}

**Risk Factors:**
- {risk_1}

**Score Breakdown:**
- Fit: {fit}/100 (35%)
- Activity: {activity}/100 (20%)
- Community: {community}/100 (15%)
- Popularity: {popularity}/100 (15%)
- Quality: {quality}/100 (15%)

---

### 2. {next_repo}...

## Comparison Matrix

| Repository | Score | Fit | Activity | License | Language | Stars | Recommendation |
|------------|-------|-----|----------|---------|----------|-------|----------------|
| repo1      | 85    | 90  | 80       | MIT     | Python   | 12.3k | ✅ Strong       |
| repo2      | 72    | 85  | 60       | Apache  | Go       | 8.1k  | 🔍 Review       |

## Domain Grouping

### AI Agents & Orchestration
1. {repo} — {score} — {one-liner}

### Backend & API Frameworks
1. {repo} — {score} — {one-liner}

## Methodology

Scoring weights: Fit 35%, Activity 20%, Community 15%, Popularity 15%, Quality 15%.
{details about how scores were calculated}
```

### 6.2 Additional Output Formats

- `--format csv` → Same data as flat CSV (for spreadsheet analysis)
- `--format json` → Full `list[AnalyzedRepo]` as JSON (for programmatic use)
- Default is `md` (Markdown)

---

## 7. Profile System (profiles/*.yaml)

```yaml
# profiles/dataguess.yaml
name: "Dataguess Default"
description: "Default evaluation profile for Dataguess technology stack"

# These are merged as DEFAULTS with document-extracted requirements.
# Document values override profile values.

preferred_languages:
  - Python
  - TypeScript
  - Go

preferred_frameworks:
  - NestJS
  - FastAPI
  - React

deployment_preference: "on-premise"  # on-premise | cloud | hybrid | any

license_policy:
  allowed:
    - MIT
    - Apache-2.0
    - BSD-2-Clause
    - BSD-3-Clause
    - ISC
  forbidden:
    - AGPL-3.0-only
    - AGPL-3.0-or-later
    - SSPL-1.0
  warn:
    - GPL-3.0-only
    - GPL-3.0-or-later
    - LGPL-3.0-only

domains_of_interest:
  - "AI Agents and Orchestration"
  - "LLM Apps and RAG"
  - "Computer Vision"
  - "MLOps and ML Platform"
  - "Industrial IoT and Edge"
  - "Workflow Automation"
  - "Backend and API Frameworks"
  - "DevOps and Observability"
  - "QA and Test Automation"

maturity_preference: "production-ready"  # production-ready | growing | any

scoring_weights:
  fit: 0.35
  activity: 0.20
  community: 0.15
  popularity: 0.15
  quality: 0.15

# Score thresholds for recommendation status
thresholds:
  strong_candidate: 75
  review_further: 50
  low_priority: 30

# GitHub/GitLab organizations to always include in search
pinned_orgs:
  github:
    - langchain-ai
    - langgenius
    - microsoft
    - anthropics
  gitlab: []

# ecosyste.ms topics to always include
pinned_topics:
  - llm
  - agents
  - rag
  - computer-vision
  - fastapi
```

---

## 8. CLI Interface (cli.py)

```python
import typer

app = typer.Typer(name="repofit", help="Find the best open-source repos for your project.")

@app.command()
def analyze(
    input: Path = typer.Option(..., "--input", "-i", help="Path to PRD, architecture doc, or text file"),
    profile: str = typer.Option("dataguess", "--profile", "-p", help="Evaluation profile name"),
    output: Path = typer.Option(None, "--output", "-o", help="Output file path (default: stdout)"),
    format: str = typer.Option("md", "--format", "-f", help="Output format: md, csv, json"),
    max_repos: int = typer.Option(20, "--max", help="Max repos in final report"),
    platforms: str = typer.Option("github,gitlab", "--platforms", help="Comma-separated: github,gitlab"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Ignore cached API responses"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show progress and debug info"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse doc + show search queries, don't execute"),
):
    """Analyze a project document and find matching open-source repositories."""
    ...

@app.command()
def profiles(
    list: bool = typer.Option(False, "--list", help="List available profiles"),
    show: str = typer.Option(None, "--show", help="Show profile details"),
):
    """Manage evaluation profiles."""
    ...

@app.command()
def cache(
    clear: bool = typer.Option(False, "--clear", help="Clear all cached data"),
    stats: bool = typer.Option(False, "--stats", help="Show cache statistics"),
):
    """Manage API response cache."""
    ...
```

**Example usage:**

```bash
# Basic: analyze a PRD
repofit analyze -i ./PROJECT_REQUIREMENTS.md

# With specific profile and output file
repofit analyze -i ./prd.md -p ai_agent_platform -o ./report.md

# Dry run to see what queries will be generated
repofit analyze -i ./prd.md --dry-run

# JSON output for programmatic processing
repofit analyze -i ./prd.md -f json -o ./results.json

# Only GitHub, skip cache
repofit analyze -i ./prd.md --platforms github --no-cache

# Verbose to see progress
repofit analyze -i ./prd.md -v
```

---

## 9. Configuration & Environment (.env)

```bash
# .env.example

# LLM Provider — pick one: gemini | anthropic | openai
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.5-flash

# Provider API Keys — only the selected provider's key is required
GEMINI_API_KEY=AIza...
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# LLM settings
LLM_MAX_TOKENS=8192

# Required: At least one platform token
GITHUB_TOKEN=ghp_...
# Optional: Additional GitHub tokens for higher rate limits (comma-separated)
GITHUB_TOKENS=ghp_token1,ghp_token2,ghp_token3

# Optional: GitLab
GITLAB_TOKEN=glpat-...
GITLAB_URL=https://gitlab.com   # Default. Change for self-hosted.

# Optional: ecosyste.ms (just an email for polite pool)
ECOSYSTEMS_EMAIL=abc@xyz.com

# Cache
CACHE_DIR=./cache
CACHE_TTL_HOURS=24
```

**Supported provider/model combinations:**

| Provider | Recommended Models | JSON Mode |
|----------|-------------------|-----------|
| `gemini` | `gemini-2.5-flash` (default, cheapest), `gemini-2.5-pro` | Native `response_mime_type="application/json"` |
| `anthropic` | `claude-sonnet-4-20250514`, `claude-haiku-4-5-20251001` | Prompt-based JSON instruction |
| `openai` | `gpt-4o-mini`, `gpt-4o` | Native `response_format={"type": "json_object"}` |

---

## 10. Dependencies (pyproject.toml)

```toml
[project]
name = "repofit-lite"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "typer[all]>=0.12",      # CLI framework
    "httpx>=0.27",           # Async HTTP client
    "pydantic>=2.7",         # Data models
    "pyyaml>=6.0",           # Profile configs
    "google-genai>=1.0",     # Google Gemini API
    "anthropic>=0.40",       # Anthropic Claude API
    "openai>=1.40",          # OpenAI API
    "rich>=13.7",            # Terminal output formatting
    "tenacity>=9.0",         # Retry logic
    "python-dotenv>=1.0",    # Env file loading
]

[project.scripts]
repofit = "repofit.cli:app"

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "ruff>=0.5"]
```

---

## 11. Rate Limiting & Resilience (utils.py)

```python
class RateLimiter:
    """Token bucket rate limiter per platform."""

    LIMITS = {
        "github_search": {"calls": 30, "period": 60},    # 30/min
        "github_core":   {"calls": 5000, "period": 3600}, # 5000/hr with token
        "gitlab":        {"calls": 600, "period": 60},    # 10/sec
        "ecosystems":    {"calls": 5000, "period": 3600},
        "scorecard":     {"calls": 100, "period": 60},
        "llm":        {"calls": 30, "period": 60},     # LLM API (any provider)
    }

class TokenRotator:
    """Rotate multiple GitHub tokens when rate limited."""

    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.current = 0

    def next(self) -> str:
        token = self.tokens[self.current]
        self.current = (self.current + 1) % len(self.tokens)
        return token
```

**Retry strategy:** Use `tenacity` with exponential backoff for all API calls. Max 3 retries. On 403 (rate limited), switch to next token or wait.

---

## 12. Caching Strategy

```python
class FileCache:
    """Simple JSON file cache with TTL."""

    def __init__(self, cache_dir: Path, ttl_hours: int = 24):
        self.cache_dir = cache_dir
        self.ttl = timedelta(hours=ttl_hours)

    def _key(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def get(self, url: str) -> dict | None:
        path = self.cache_dir / f"{self._key(url)}.json"
        if path.exists():
            data = json.loads(path.read_text())
            cached_at = datetime.fromisoformat(data["_cached_at"])
            if datetime.now() - cached_at < self.ttl:
                return data["payload"]
        return None

    def set(self, url: str, payload: dict):
        path = self.cache_dir / f"{self._key(url)}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "_cached_at": datetime.now().isoformat(),
            "_url": url,
            "payload": payload
        }, ensure_ascii=False, indent=2))
```

**What gets cached:**
- Individual repo metadata (24h)
- Search results are NOT cached (always fresh)
- LLM responses are NOT cached (input-dependent)

---

## 13. Implementation Order for Claude Code

### Phase 1: Skeleton + Config (30 min)

1. Create folder structure
2. `pyproject.toml` with dependencies
3. `.env.example`
4. `config.py` — load env vars, defaults
5. `models.py` — all Pydantic models
6. `cli.py` — Typer app skeleton (parse args, print, exit)
7. Verify: `repofit --help` works

### Phase 2: Document Parser (30 min)

1. `llm_client.py` — Multi-provider LLM client (Gemini, Anthropic, OpenAI). Single `complete(system, user)` method. Provider-specific JSON mode handling.
2. `parser.py` — read file, call LLM, return `ParsedRequirements`
3. Test with sample PRD
4. Verify: `repofit analyze -i sample.md --dry-run` shows parsed requirements

### Phase 3: Search (1 hour)

1. `github_client.py` — search repos, handle pagination
2. `gitlab_client.py` — search projects
3. `ecosystems_client.py` — topic/keyword search
4. `search.py` — orchestrate multi-query fan-out, deduplicate
5. `utils.py` — RateLimiter, TokenRotator, retry decorator
6. Test: verify search returns candidates
7. Verify: `--dry-run` shows search queries, real run shows candidate list

### Phase 4: Enrichment (1 hour)

1. Extend `github_client.py` — repo detail, languages, contributors, releases, README, contents
2. Extend `gitlab_client.py` — same endpoints
3. `scorecard_client.py` — OpenSSF Scorecard lookup
4. Extend `ecosystems_client.py` — repo detail (dependents, downloads)
5. `enrichment.py` — async parallel enrichment with semaphore
6. `FileCache` in `utils.py`
7. Test: verify enrichment fills all fields

### Phase 5: Analysis + Scoring (1 hour)

1. `analyzer.py` — deterministic scoring functions (activity, popularity, community, quality)
2. `analyzer.py` — LLM-powered fit analysis (batched, 5 repos per call)
3. `analyzer.py` — recommendation assignment with gates
4. `pipeline.py` — wire all 4 stages together
5. Test: full pipeline end-to-end

### Phase 6: Report Generation (30 min)

1. `report.py` — Markdown report generator
2. `report.py` — CSV export
3. `report.py` — JSON export
4. Verify: `repofit analyze -i sample.md -o report.md` produces valid report

### Phase 7: Profiles + Polish (30 min)

1. Create `profiles/dataguess.yaml`
2. Create 2-3 example profiles
3. Profile loading and merging logic in `config.py`
4. `cli.py` — `profiles` and `cache` subcommands
5. README.md with usage examples

### Phase 8: Tests (30 min)

1. `test_parser.py` — mock LLM, verify JSON extraction
2. `test_search.py` — mock API responses, verify dedup
3. `test_enrichment.py` — mock API, verify field mapping
4. `test_analyzer.py` — test deterministic scoring with known inputs
5. `test_report.py` — verify Markdown structure

**Total estimated implementation time: ~6 hours with Claude Code**

---

## 14. Cost Estimation per Run

| Component | Calls | Gemini Flash | Claude Sonnet | GPT-4o-mini |
|-----------|-------|-------------|---------------|-------------|
| LLM: Parse document | 1 call | ~$0.001 | ~$0.01 | ~$0.005 |
| GitHub Search API | 10-15 queries | Free | Free | Free |
| GitLab Search API | 5-10 queries | Free | Free | Free |
| ecosyste.ms API | 5-10 queries | Free | Free | Free |
| GitHub repo enrichment | 50-100 repos × 8 calls | Free | Free | Free |
| OpenSSF Scorecard | 50-100 lookups | Free | Free | Free |
| LLM: Fit analysis | 10-20 calls (batched) | ~$0.01-0.03 | ~$0.10-0.20 | ~$0.03-0.06 |
| LLM: Executive summary | 1 call | ~$0.002 | ~$0.02 | ~$0.005 |
| **Total per run** | | **~$0.01-0.04** | **~$0.15-0.25** | **~$0.04-0.08** |

---

## 15. Future Extensions (NOT in MVP)

Do not implement these now. Listed only for awareness:

1. **Web UI wrapper** — Streamlit or Gradio around the CLI
2. **Scheduled monitoring** — cron job to re-run analysis weekly
3. **Comparison mode** — `repofit compare repo1 repo2 repo3`
4. **Trend tracking** — store results in SQLite, show score changes over time
5. **Team sharing** — export to Notion/Confluence
6. **Embedding-based search** — use README embeddings for semantic matching
7. **Dependency analysis** — check if candidates conflict with existing stack
8. **LLM-generated README summaries** — for repos with poor documentation

---

## 16. CLAUDE.md Directives

When implementing this project with Claude Code, follow these rules:

1. **Implement phases in order.** Each phase must work before starting the next.
2. **Test each phase manually** before moving on. Print intermediate results.
3. **Use `httpx.AsyncClient`** for all HTTP calls. No `requests` library.
4. **All API clients must be async.** The pipeline runs with `asyncio`.
5. **Every API call must have retry + rate limit handling.** Use `tenacity`.
6. **Never hardcode API URLs.** Use constants or config.
7. **Pydantic models are the contract.** If a field is Optional, handle None everywhere.
8. **LLM prompts must request JSON output.** Parse with `json.loads`, not regex.
9. **Keep files under 300 lines.** Split if longer.
10. **Use `rich.console` for terminal output** — progress bars, tables, colored status.
11. **Cache is optional but recommended.** `--no-cache` must bypass it cleanly.
12. **Fail gracefully.** If one repo enrichment fails, skip it, log warning, continue.
13. **Log everything at DEBUG level.** Use `--verbose` to show it.
14. **The report is the product.** Spend extra care on report formatting.
