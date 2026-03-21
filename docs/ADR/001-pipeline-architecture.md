# ADR-001: 4-Stage Pipeline Architecture

## Status
Accepted

## Context
RepoFit needs to discover, evaluate, and rank open-source repositories against project requirements. The process involves multiple data sources (GitHub, GitLab, ecosyste.ms, LLM providers) with different latencies, rate limits, and costs.

## Decision
Adopt a linear 4-stage pipeline: Parse -> Search -> Enrich -> Analyze.

Each stage:
- Has a single input and output type (Pydantic model)
- Is independently testable
- Can be cached at its output boundary
- Has a budget controlled by `PipelineConfig`

## Consequences
- **Pro:** Clear data contracts between stages
- **Pro:** Each stage can be optimized independently
- **Pro:** Cache boundaries are natural (enrichment cache, fit cache)
- **Con:** No streaming/interleaving between stages (search must complete before enrichment starts)
- **Con:** Linear execution means total time = sum of all stages

## Alternatives Considered
- **Streaming pipeline** (asyncio.Queue): Rejected — 10-20% theoretical speedup doesn't justify complexity for a CLI tool
- **Single LLM call** (send all data to LLM): Rejected — too expensive, no deterministic scoring
