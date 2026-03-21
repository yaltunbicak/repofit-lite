# ADR-004: aiolimiter-based Rate Limiting

## Status
Accepted

## Context
The custom `RateLimiter` had a race condition under concurrent asyncio coroutines (no `asyncio.Lock`). Multiple coroutines could pass the capacity check simultaneously.

## Decision
Replace custom RateLimiter with `aiolimiter.AsyncLimiter`:
- Lock-free leaky bucket algorithm
- Native asyncio futures (no manual Lock needed)
- O(1) memory per bucket
- Per-platform rate limit buckets

## Consequences
- **Pro:** Race condition eliminated by design
- **Pro:** Zero complexity for async safety
- **Pro:** Lightweight dependency (~15KB, zero transitive deps)
- **Con:** New runtime dependency
- **Con:** Cannot read server response headers for adaptive limiting (future enhancement)

## Alternatives Considered
- **asyncio.Lock on custom RateLimiter**: Rejected — still has timing edge cases
- **pyrate-limiter**: Rejected — wrapped async, multi-backend complexity overkill
- **httpx transport middleware**: Rejected — pre-alpha, complex token rotation interaction
