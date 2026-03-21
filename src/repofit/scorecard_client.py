"""OpenSSF Scorecard API client."""

from __future__ import annotations

import logging

import httpx

from repofit.utils import RateLimiterRegistry, api_retry, extract_owner_repo

logger = logging.getLogger("repofit")

SCORECARD_API = "https://api.securityscorecards.dev"


class ScorecardClient:
    """Async OpenSSF Scorecard client. GitHub-only, fails silently."""

    def __init__(self, rate_limiter: RateLimiterRegistry) -> None:
        self.limiter = rate_limiter
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> ScorecardClient:
        self._client = httpx.AsyncClient(
            base_url=SCORECARD_API,
            timeout=15.0,
            limits=httpx.Limits(max_connections=5),
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()

    async def get_score(self, repo_url: str) -> dict | None:
        """Get OpenSSF Scorecard for a GitHub repo. Returns None on failure."""
        if "github.com" not in repo_url:
            return None

        parsed = extract_owner_repo(repo_url)
        if not parsed:
            return None
        owner, repo = parsed

        try:
            await self.limiter.acquire("scorecard")
            r = await self._client.get(f"/projects/github.com/{owner}/{repo}")
            if r.status_code != 200:
                logger.debug("Scorecard not available for %s/%s (status %d)", owner, repo, r.status_code)
                return None

            data = r.json()
            score = data.get("score")
            checks = {}
            for check in data.get("checks", []):
                if isinstance(check, dict) and "name" in check:
                    checks[check["name"]] = check.get("score", 0)

            return {"score": score, "checks": checks}
        except Exception as e:
            logger.debug("Scorecard lookup failed for %s: %s", repo_url, e)
            return None
