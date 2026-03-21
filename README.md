# RepoFit Lite

**Find the best open-source repositories for your project -- automatically.**

RepoFit takes a project document (PRD, architecture doc, or description), discovers relevant repositories from GitHub and GitLab, enriches them with real metadata, scores them using a hybrid rule-based + LLM approach, and produces a ranked Markdown report.

```bash
repofit analyze -i my_prd.md -o report.md --max 10 --quick
```

## How It Works

```
PRD Document --> [Parse] --> [Search] --> [Enrich] --> [Analyze] --> Report
                  LLM        GitHub       API calls    LLM + Rules   Markdown
                             GitLab       (parallel)   (5 dimensions)
                             ecosyste.ms
```

1. **Parse** -- LLM extracts structured requirements from your document
2. **Search** -- Multi-query fan-out across GitHub, GitLab, ecosyste.ms
3. **Enrich** -- Parallel metadata fetching (stars, contributors, license, CI, tests, README, OpenSSF)
4. **Analyze** -- Deterministic scoring (Activity, Community, Popularity, Quality) + LLM fit scoring
5. **Report** -- Ranked results with scores, pros/cons, and comparison matrix

## Installation

```bash
pip install repofit-lite
```

Or from source:

```bash
git clone https://github.com/yaltunbicak/repofit-lite.git
cd repofit-lite
pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and add your API keys:

```bash
cp .env.example .env
```

**Required:**
- `LLM_PROVIDER` + corresponding API key (Gemini, Anthropic, or OpenAI)
- `GITHUB_TOKEN` -- GitHub personal access token (read-only scopes sufficient)

**Optional:**
- `GITLAB_TOKEN` -- for GitLab search
- `GITHUB_TOKENS` -- comma-separated tokens for rate limit rotation
- `ECOSYSTEMS_EMAIL` -- for ecosyste.ms polite pool

## Usage

```bash
# Quick scan (10 repos, ~2 min)
repofit analyze -i prd.md --max 10 --quick

# Standard analysis (default: 20 repos, ~3-5 min)
repofit analyze -i prd.md -o report.md

# Thorough analysis (50 repos, ~10-15 min)
repofit analyze -i prd.md --max 50 --thorough -o report.md

# Dry run (parse doc, show search queries, no API calls)
repofit analyze -i prd.md --dry-run

# JSON output for programmatic use
repofit analyze -i prd.md -f json -o results.json

# With specific profile
repofit analyze -i prd.md -p ai_agent_platform
```

## Pipeline Modes

| Mode | Search | Enrich | LLM | Time (10 repos) |
|------|--------|--------|-----|-----------------|
| `--quick` | 10 queries | 20 repos | 15 repos | ~2 min |
| `--normal` (default) | 16 queries | 30 repos | 20 repos | ~3-5 min |
| `--thorough` | 24 queries | 50 repos | 30 repos | ~8-15 min |

Budgets scale proportionally with `--max`.

## Scoring

| Dimension | Weight | Method |
|-----------|--------|--------|
| Fit | 35% | LLM-powered requirements matching |
| Activity | 20% | Rule-based (commits, releases, recency) |
| Community | 15% | Rule-based (contributors, guides) |
| Popularity | 15% | Rule-based (stars, forks, dependents) |
| Quality | 15% | Rule-based (license, CI, tests, docs, OpenSSF) |

Weights are configurable via profiles.

## Profiles

Profiles define evaluation preferences (languages, frameworks, license policy, scoring weights).

```bash
repofit profiles --list
repofit profiles --show dataguess
```

Built-in profiles:
- `dataguess` -- Default technology stack (Python, TypeScript, Go)
- `ai_agent_platform` -- AI agent orchestration focus
- `rag_stack` -- RAG components focus
- `mlops_platform` -- MLOps tools focus

## Cache

Enrichment and LLM fit results are cached for 24 hours.

```bash
repofit cache --stats    # View cache size
repofit cache --clear    # Clear all caches
repofit analyze ... --no-cache  # Bypass cache
```

## Supported LLM Providers

| Provider | Models | JSON Mode |
|----------|--------|-----------|
| Gemini | `gemini-2.5-flash` (default), `gemini-2.5-pro` | Native |
| Anthropic | `claude-sonnet-4-20250514`, `claude-haiku-4-5-20251001` | Native |
| OpenAI | `gpt-4o-mini`, `gpt-4o` | Native |

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full architecture documentation including:
- Pipeline design and data flow
- Scoring system details
- Rate limiting strategy
- Caching architecture

Architecture Decision Records: [docs/ADR/](docs/ADR/)

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
ruff check src/
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

## License

[MIT](LICENSE)
