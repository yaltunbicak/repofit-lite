# CLAUDE.md — RepoFit Lite

## Project Identity

RepoFit Lite is a single-command Python CLI tool. User gives a project document (PRD, architecture doc) → tool discovers, enriches, scores and ranks open-source repositories → outputs a Markdown report.

**No web UI. No database. No Docker. No microservices.**

## Authoritative Source

All architecture decisions, data models, stage definitions, API details, scoring logic, and implementation order are defined in:

```
docs/REPOFIT_LITE_TECHNICAL_DESIGN.md
```

**Read this file FIRST before writing any code. Re-read the relevant section before implementing each phase.**

## Tech Stack

- Python 3.11+
- `typer` — CLI framework
- `httpx` — async HTTP client (NOT requests)
- `pydantic` v2 — data models
- `google-genai` — Google Gemini API
- `anthropic` — Anthropic Claude API
- `openai` — OpenAI API
- Provider selected via `LLM_PROVIDER` env var: `gemini` | `anthropic` | `openai`
- `rich` — terminal output (progress, tables, colors)
- `tenacity` — retry/backoff
- `pyyaml` — profile config
- `python-dotenv` — env loading

## Project Structure

```
RepoFit/
├── CLAUDE.md                          ← you are here
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── docs/
│   └── REPOFIT_LITE_TECHNICAL_DESIGN.md
├── profiles/
│   ├── dataguess.yaml
│   └── examples/
├── src/
│   └── repofit/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── pipeline.py
│       ├── parser.py
│       ├── search.py
│       ├── enrichment.py
│       ├── analyzer.py
│       ├── report.py
│       ├── models.py
│       ├── github_client.py
│       ├── gitlab_client.py
│       ├── ecosystems_client.py
│       ├── scorecard_client.py
│       ├── llm_client.py
│       └── utils.py
├── tests/
│   ├── test_parser.py
│   ├── test_search.py
│   ├── test_enrichment.py
│   ├── test_analyzer.py
│   ├── test_report.py
│   └── fixtures/
│       ├── sample_prd.md
│       └── sample_repos.json
└── cache/                             ← gitignored, auto-created
```

## Implementation Rules

### Architecture

1. **4-stage pipeline, single direction:** Parse → Search → Enrich → Analyze → Report. Each stage consumes the previous stage's output. No backtracking.
2. **Pydantic models are the contract.** Every stage input/output is a Pydantic model defined in `models.py`. All models are defined in the technical design doc — copy them exactly.
3. **All HTTP is async.** Use `httpx.AsyncClient` everywhere. The pipeline runs with `asyncio.run()`.
4. **Every external API call must have retry + rate limiting.** Use `tenacity` with exponential backoff. Max 3 retries. Switch token on 403.
5. **Fail gracefully.** If one repo enrichment fails → log warning → skip → continue. Never crash the pipeline for a single API failure.

### Code Style

6. **Keep files under 300 lines.** Split if approaching limit.
7. **No classes where functions suffice.** API clients can be classes (they hold state/tokens). Scoring functions should be plain functions.
8. **Type hints on every function signature.** No `Any` unless truly unavoidable.
9. **Use `rich.console` for all terminal output.** Progress bars for enrichment, tables for results, colored status indicators.
10. **Logging at DEBUG level via `logging` module.** `--verbose` flag activates it. Never `print()` for debug info.

### LLM Usage

11. **LLM prompts must request JSON output explicitly.** System prompt must say "Output valid JSON matching the schema. Nothing else."
12. **Parse LLM responses with `json.loads()`.** Never regex. If parse fails, retry once with a stricter prompt.
13. **Batch LLM analysis calls.** 5 repos per call to minimize cost. Never 1 LLM call per repo.
14. **Default model: `gemini-2.5-flash`.** Configurable via `LLM_PROVIDER` + `LLM_MODEL` env vars. `llm_client.py` must abstract all three providers behind a single `complete(system, user) -> str` interface. Provider-specific JSON mode: Gemini uses `response_mime_type="application/json"`, OpenAI uses `response_format={"type": "json_object"}`, Anthropic uses prompt instruction. Only the selected provider's SDK is initialized.

### API Clients

15. **GitHub: use both REST and Search API.** Search for discovery, REST for enrichment. Respect 30 req/min search limit.
16. **Token rotation:** Support multiple GitHub tokens via `GITHUB_TOKENS` env var (comma-separated). Rotate on rate limit.
17. **Cache enrichment results.** JSON file cache in `./cache/repos/`, 24h TTL. Search results are never cached.
18. **ecosyste.ms and OpenSSF Scorecard are optional enrichments.** If they fail or timeout, continue without them. Set fields to None.

### Testing

19. **Mock all external APIs in tests.** Never make real API calls in tests.
20. **Test deterministic scoring with known inputs.** Verify exact scores for specific repo metadata.
21. **Test report output structure.** Verify Markdown sections exist and data is populated.

### What NOT To Do

- Do NOT add a database (SQLite, PostgreSQL, or otherwise)
- Do NOT add a web framework (Flask, FastAPI, Streamlit)
- Do NOT add Docker or docker-compose
- Do NOT add background job processing (Celery, APScheduler)
- Do NOT add vector databases or embedding storage
- Do NOT implement any "nice-to-have" features listed in section 15 of the design doc
- Do NOT use `requests` library — only `httpx`
- Do NOT hardcode API URLs — use constants in config
- Do NOT make LLM calls where deterministic logic suffices (activity, popularity, community, quality scores are rule-based)

## Phase Execution

Implement in this exact order. Each phase must work and be manually testable before starting the next.

```
Phase 1: Skeleton + Config       → repofit --help works
Phase 2: Document Parser          → repofit analyze -i sample.md --dry-run shows parsed requirements
Phase 3: Search                   → real run shows candidate list from GitHub/GitLab
Phase 4: Enrichment               → candidates are enriched with full metadata
Phase 5: Analysis + Scoring       → full pipeline produces scored results
Phase 6: Report Generation        → repofit analyze -i sample.md -o report.md produces report
Phase 7: Profiles + Polish        → profile loading, cache commands, README
Phase 8: Tests                    → pytest passes
```

## Quick Commands

```bash
# Install in dev mode
pip install -e ".[dev]"

# Run analysis
repofit analyze -i docs/sample_prd.md -v

# Dry run (parse only, show queries)
repofit analyze -i docs/sample_prd.md --dry-run

# Run tests
pytest tests/ -v

# Lint
ruff check src/
```
