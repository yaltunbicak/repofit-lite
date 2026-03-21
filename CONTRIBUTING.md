# Contributing to RepoFit Lite

Thank you for your interest in contributing! This guide will help you get started.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/yaltunbicak/repofit-lite.git
cd repofit-lite

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install in dev mode with all dependencies
pip install -e ".[dev]"

# Verify installation
repofit --help
pytest tests/ -v
```

## Project Structure

```
src/repofit/
  cli.py           # Typer CLI entry point
  config.py         # pydantic-settings configuration
  models.py         # Pydantic data models + PipelineConfig
  pipeline.py       # 4-stage pipeline orchestrator
  parser.py         # Stage 1: LLM document parsing
  search.py         # Stage 2: Multi-source repo search
  enrichment.py     # Stage 3: Async metadata enrichment
  analyzer.py       # Stage 4: Scoring + LLM fit analysis
  scoring.py        # Deterministic scoring functions
  report.py         # Markdown/CSV/JSON report generation
  llm_client.py     # Multi-provider LLM abstraction
  github_client.py  # GitHub REST API client
  gitlab_client.py  # GitLab REST API client
  ecosystems_client.py  # ecosyste.ms API client
  scorecard_client.py   # OpenSSF Scorecard client
  utils.py          # Rate limiting, caching, URL normalization
```

## Making Changes

1. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/your-feature
   ```

2. **Follow existing patterns**:
   - All HTTP calls go through centralized `_request()` methods
   - Use `@api_retry` only for httpx calls, not LLM calls
   - All API clients must be async
   - Use `pydantic` models for data contracts
   - Keep files under 300 lines

3. **Run tests** before committing:
   ```bash
   pytest tests/ -v
   ruff check src/
   ```

4. **Submit a PR** with a clear description of what changed and why.

## Code Style

- Python 3.11+
- Type hints on all function signatures
- `ruff` for linting (config in `pyproject.toml`)
- No `print()` for debug — use `logging.getLogger("repofit")`
- Use `rich.console` for user-facing terminal output

## Testing

- Mock all external APIs — never make real API calls in tests
- Use `respx` for httpx mocking
- Use `freezegun` for time-dependent tests
- Test deterministic scoring with exact assertions
- Test report structure (section headers, table format)

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=repofit --cov-report=term-missing
```

## Adding a New Profile

1. Create a YAML file in `profiles/examples/`
2. Follow the schema in `profiles/dataguess.yaml`
3. Ensure `scoring_weights` sum to 1.0
4. Add the profile name to `README.md`

## Reporting Issues

- Use the issue templates in `.github/ISSUE_TEMPLATE/`
- Include the RepoFit version (`repofit --help`)
- Include your Python version and OS
- For bugs: include the command you ran and the error output
