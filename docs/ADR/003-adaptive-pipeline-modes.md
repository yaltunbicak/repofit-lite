# ADR-003: Adaptive Pipeline Modes (quick/normal/thorough)

## Status
Accepted

## Context
`--max 10` previously ran the full pipeline on 100 repos (15-20 min). Users wanting a quick scan shouldn't wait for exhaustive analysis.

## Decision
Introduce three pipeline modes that control the budget at every stage:

| Mode | Search Queries | Enrichment | LLM Budget | Time (10 repos) |
|------|---------------|------------|------------|-----------------|
| `--quick` | 10 | 20 | 15 | ~2 min |
| `--normal` | 16 | 30 | 20 | ~3-5 min |
| `--thorough` | 24 | 50 | 30 | ~8-15 min |

Each stage budget = `max(floor, round(max_repos * multiplier))`.

## Consequences
- **Pro:** `--quick --max 10` completes in ~2 min (was 15-20 min)
- **Pro:** Users choose their quality/speed tradeoff explicitly
- **Pro:** `--normal` is the default, matching typical use case
- **Con:** Quick mode may miss niche repos with low stars but high fit
- **Con:** Three modes add configuration complexity

## Alternatives Considered
- **Single mode with `--max` only**: Rejected — `--max` controls report size, not pipeline depth
- **Automatic mode selection based on --max**: Rejected — users should control the tradeoff
