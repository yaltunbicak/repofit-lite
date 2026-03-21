# RepoFit Lite -- Architecture

## Overview

RepoFit Lite is a single-command Python CLI tool that takes a project document (PRD, architecture doc) and produces a ranked report of matching open-source repositories.

```
Input: PRD document (.md, .txt)
  |
  v
[4-Stage Pipeline]
  |
  v
Output: Ranked report (.md, .csv, .json)
```

## System Context (C4 Level 1)

```
+-------------------+
|   User (Developer)|
|   Gives PRD doc   |
+--------+----------+
         |
         v
+--------+----------+        +------------------+
|   RepoFit CLI     |------->| LLM Provider     |
|   (Python CLI)    |        | (Gemini/Claude/   |
|                   |        |  OpenAI)          |
|                   |        +------------------+
|                   |
|                   |------->| GitHub API        |
|                   |------->| GitLab API        |
|                   |------->| ecosyste.ms API   |
|                   |------->| OpenSSF Scorecard |
+-------------------+
```

## Pipeline Architecture (C4 Level 2)

```
 PRD Document
      |
      v
+-----------+    +-----------+    +------------+    +------------+    +--------+
| Stage 1   |--->| Stage 2   |--->| Stage 3    |--->| Stage 4    |--->| Report |
| PARSE     |    | SEARCH    |    | ENRICH     |    | ANALYZE    |    | GEN    |
| (LLM)     |    | (API)     |    | (API)      |    | (LLM+Rule) |    | (MD)   |
+-----------+    +-----------+    +------------+    +------------+    +--------+
      |                |                |                 |
      v                v                v                 v
 Parsed           Repo            Enriched           Analyzed
 Requirements     Candidates      Repos              Repos
```

### Stage 1: Document Parsing
- **Input:** Raw document text
- **Process:** Single LLM call extracts structured requirements
- **Output:** `ParsedRequirements` (keywords, languages, frameworks, domains, criteria)
- **File:** `parser.py`, `llm_client.py`

### Stage 2: Repository Search
- **Input:** `ParsedRequirements`
- **Process:** Multi-query fan-out across GitHub, GitLab, ecosyste.ms
- **Output:** `list[RepoCandidate]` (deduplicated)
- **File:** `search.py`, `github_client.py`, `gitlab_client.py`, `ecosystems_client.py`
- **Budget:** Controlled by `PipelineConfig.query_budget`

### Stage 3: Metadata Enrichment
- **Input:** `list[RepoCandidate]`
- **Process:** Parallel async API calls (8 per GitHub repo, 7 per GitLab repo)
- **Output:** `list[EnrichedRepo]` (full metadata: stars, contributors, license, CI, tests, README)
- **File:** `enrichment.py`
- **Budget:** Controlled by `PipelineConfig.enrichment_budget`

### Stage 4: Analysis & Scoring
- **Input:** `list[EnrichedRepo]` + `ParsedRequirements`
- **Process:**
  1. Deterministic scoring (Activity, Popularity, Community, Quality)
  2. Early elimination (skip bottom 50% for LLM)
  3. LLM fit analysis (batched, 5-10 repos per call)
  4. Weighted overall score + recommendation assignment
- **Output:** `list[AnalyzedRepo]` (scored, ranked, with pros/cons)
- **File:** `analyzer.py`, `scoring.py`
- **Budget:** Controlled by `PipelineConfig.llm_budget`

## Data Models

```
ParsedRequirements     RepoCandidate     EnrichedRepo     AnalyzedRepo
  project_name           source            stars            overall_score
  primary_keywords       full_name         contributors     recommendation
  preferred_languages    url               license          fit_score
  domains                stars             has_ci           activity_score
  must_have              language          has_tests        community_score
  deal_breakers          topics            readme_excerpt   popularity_score
                                           openssf_score    quality_score
                                                            pros/cons
```

All models are Pydantic v2 `BaseModel` subclasses defined in `models.py`.

## Scoring System

### Dimensions (default weights)

| Dimension | Weight | Method | Source |
|-----------|--------|--------|--------|
| Fit | 35% | LLM-powered | Requirements vs repo metadata |
| Activity | 20% | Rule-based | Push date, commits, releases, issues |
| Community | 15% | Rule-based | Contributors, guides, code of conduct |
| Popularity | 15% | Rule-based | Stars (log), forks, dependents |
| Quality | 15% | Rule-based | License, CI, tests, README, OpenSSF |

Weights are configurable via profiles.

### Recommendation Thresholds

| Overall Score | Recommendation |
|---------------|----------------|
| >= 75 | Strong Candidate |
| >= 50 | Review Further |
| >= 30 | Low Priority |
| < 30 | Not Suitable |

Hard gates (override score): no license, forbidden license (SPDX), inactive > 1 year.

## Pipeline Modes

| Mode | Search | Enrich | LLM | Time (10 repos) |
|------|--------|--------|-----|-----------------|
| `--quick` | 10 queries | 20 repos | 15 repos | ~2 min |
| `--normal` | 16 queries | 30 repos | 20 repos | ~3-5 min |
| `--thorough` | 24 queries | 50 repos | 30 repos | ~8-15 min |

Budgets scale proportionally with `--max` parameter.

## Caching

```
cache/
  repos/     # Enrichment cache (24h TTL, atomic writes)
  fit/       # LLM fit score cache (24h TTL, per repo+PRD hash)
```

- UTC timestamps for timezone-safe TTL
- Atomic writes via tempfile + os.replace
- `--no-cache` bypasses both caches
- `repofit cache --clear` clears both

## Rate Limiting

Uses `aiolimiter.AsyncLimiter` (leaky bucket, no race conditions):

| Platform | Limit | Bucket |
|----------|-------|--------|
| GitHub Search | 30/min | `github_search` |
| GitHub Core | 5000/hr | `github_core` |
| GitLab Search | 10/min | `gitlab_search` |
| GitLab API | 400/min | `gitlab_api` |
| ecosyste.ms | 5000/hr | `ecosystems` |
| Scorecard | 100/min | `scorecard` |

Token rotation on 403/429 for GitHub multi-token setups.

## Error Handling

- **Retry:** `tenacity` with custom `_is_retryable()` predicate (429, 5xx, timeouts only)
- **Per-repo timeout:** `asyncio.timeout()` in enrichment (30-60s per mode)
- **Graceful degradation:** Failed enrichment = skip repo, log warning, continue
- **Pipeline error boundary:** User-friendly message + full traceback in verbose mode

## License Compliance

Uses `license-expression` library for SPDX normalization:
- Exact matching after normalization (no prefix hacks)
- Three-tier policy from profiles: `forbidden`, `warn`, `allowed`
- GitHub's deprecated SPDX IDs auto-normalized (e.g., `AGPL-3.0` -> `AGPL-3.0-only`)

## Configuration

```
.env                  # API keys and settings (pydantic-settings)
profiles/*.yaml       # Evaluation profiles (weights, license policy, pinned orgs)
PipelineConfig        # Runtime config from --max + --mode
```

All environment variables documented in `.env.example`.
