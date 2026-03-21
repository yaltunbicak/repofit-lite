# ADR-002: Hybrid Scoring System (Rule-based + LLM)

## Status
Accepted

## Context
Repositories need to be scored on multiple dimensions. Some dimensions (stars, commit frequency) are objective and computable. Others (fit to requirements) require semantic understanding.

## Decision
Use a hybrid scoring system:
- **4 rule-based dimensions** (Activity, Community, Popularity, Quality): Deterministic, reproducible, fast, free
- **1 LLM dimension** (Fit): Semantic analysis of how well a repo matches the PRD requirements

Weighted sum with configurable weights from profiles (default: Fit 35%, Activity 20%, Community/Popularity/Quality 15% each).

## Consequences
- **Pro:** 65% of scoring is deterministic and free
- **Pro:** LLM is used only where it adds unique value (semantic fit)
- **Pro:** Weights are profile-configurable for different use cases
- **Con:** LLM fit scores have ~5-10 point variance across runs (mitigated by temperature=0, seed, caching)
- **Con:** Batch composition can influence LLM scores (anchoring bias)

## Alternatives Considered
- **Pure LLM scoring**: Rejected — expensive, slow, non-reproducible
- **Pure rule-based scoring**: Rejected — cannot assess semantic fit to requirements
- **Ensemble LLM (3 calls, median)**: Tested and rejected — 3x cost for marginal improvement
