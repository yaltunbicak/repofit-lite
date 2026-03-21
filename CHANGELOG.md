# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-03-21

### Added
- Initial release of RepoFit Lite
- 4-stage pipeline: Parse -> Search -> Enrich -> Analyze
- Multi-provider LLM support (Gemini, Anthropic, OpenAI)
- GitHub and GitLab repository search
- ecosyste.ms integration for broader discovery
- OpenSSF Scorecard integration
- 5-dimension scoring: Fit (LLM), Activity, Community, Popularity, Quality
- Profile system with customizable weights and license policies
- SPDX license compliance with `license-expression` library
- Three pipeline modes: `--quick`, `--normal`, `--thorough`
- Adaptive pipeline sizing based on `--max` parameter
- Markdown, CSV, and JSON report output
- LLM-generated executive summaries
- Per-repo LLM fit score caching for deterministic reruns
- Enrichment caching with 24h TTL and atomic writes
- Rate limiting via `aiolimiter` with per-platform budgets
- Token rotation for GitHub API
- Pre-filter with Closed-World Assumption (unknown stars = reject)
- Early elimination: skip LLM for low-scoring candidates
- CI/CD detection heuristics (GitHub Actions, GitLab CI, Jenkins, etc.)
- Test detection from file structure and README content
- Windows cp1252 encoding compatibility
- File safety checks: size limit (512KB), binary detection, extension whitelist
