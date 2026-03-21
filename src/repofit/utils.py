"""Rate limiting, token rotation, caching, and retry utilities."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from aiolimiter import AsyncLimiter
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger = logging.getLogger("repofit")


# ---------------------------------------------------------------------------
# Retryable error classification
# ---------------------------------------------------------------------------

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    """Return True only for transient errors that warrant a retry."""
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS_CODES
    return False


api_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=30, jitter=2),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)


# ---------------------------------------------------------------------------
# Rate Limiter Registry (aiolimiter-based, per-bucket)
# ---------------------------------------------------------------------------

# Rates match GitHub/GitLab/ecosyste.ms documented limits
_DEFAULT_RATES: dict[str, tuple[float, float]] = {
    "github_search": (30, 60),       # 30 req/min
    "github_core": (5000, 3600),     # 5000 req/hr
    "gitlab_search": (10, 60),       # 10 req/min
    "gitlab_api": (400, 60),         # 400 req/min
    "ecosystems": (5000, 3600),      # 5000 req/hr
    "scorecard": (100, 60),          # 100 req/min
    "llm": (30, 60),                 # 30 req/min
}


class RateLimiterRegistry:
    """Thread-safe async rate limiters keyed by bucket name."""

    def __init__(self) -> None:
        self._limiters: dict[str, AsyncLimiter] = {}

    def _get(self, bucket: str) -> AsyncLimiter:
        if bucket not in self._limiters:
            rate, period = _DEFAULT_RATES.get(bucket, (100, 60))
            self._limiters[bucket] = AsyncLimiter(rate, period)
        return self._limiters[bucket]

    async def acquire(self, bucket: str) -> None:
        """Wait until a request slot is available."""
        limiter = self._get(bucket)
        await limiter.acquire()


# Backward-compatible alias
RateLimiter = RateLimiterRegistry


# ---------------------------------------------------------------------------
# Token Rotator
# ---------------------------------------------------------------------------

class TokenRotator:
    """Rotate multiple tokens when rate-limited."""

    def __init__(self, tokens: list[str]) -> None:
        valid = [t for t in (tokens or []) if t and t.strip()]
        if not valid:
            raise ValueError(
                "TokenRotator requires at least one non-empty token. "
                "Set GITHUB_TOKEN or GITHUB_TOKENS in your .env file."
            )
        self.tokens = valid
        self._current = 0

    def current(self) -> str:
        return self.tokens[self._current]

    def next(self) -> str:
        self._current = (self._current + 1) % len(self.tokens)
        return self.tokens[self._current]

    @property
    def count(self) -> int:
        return len(self.tokens)


# ---------------------------------------------------------------------------
# File Cache (UTC-aware, atomic writes, robust error handling)
# ---------------------------------------------------------------------------

class FileCache:
    """Simple JSON file cache with TTL."""

    def __init__(self, cache_dir: Path, ttl_hours: int = 24) -> None:
        self.cache_dir = cache_dir
        self.ttl = timedelta(hours=ttl_hours)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:32]

    def get(self, url: str) -> dict | None:
        path = self.cache_dir / f"{self._key(url)}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cached_at_str = data["_cached_at"]
            # Handle both UTC-aware and naive (legacy) timestamps
            cached_at = datetime.fromisoformat(cached_at_str)
            if cached_at.tzinfo is None:
                # Legacy naive timestamp — treat as expired
                return None
            if datetime.now(timezone.utc) - cached_at < self.ttl:
                return data["payload"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError,
                ValueError, UnicodeDecodeError, OSError):
            pass
        return None

    def set(self, url: str, payload: dict) -> None:
        path = self.cache_dir / f"{self._key(url)}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(
            {
                "_cached_at": datetime.now(timezone.utc).isoformat(),
                "_url": url,
                "payload": payload,
            },
            ensure_ascii=False,
            indent=2,
        )
        # Atomic write: temp file + os.replace
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            os.replace(tmp_path, str(path))
        except Exception:
            os.close(fd) if not os.get_inheritable(fd) else None
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def clear(self) -> int:
        count = 0
        for f in self.cache_dir.glob("*.json"):
            f.unlink(missing_ok=True)
            count += 1
        return count

    def stats(self) -> dict[str, int]:
        files = list(self.cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in files if f.exists())
        return {"entries": len(files), "total_size_bytes": total_size}


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------

def extract_owner_repo(url: str) -> tuple[str, str] | None:
    """Extract (owner, repo) from a GitHub/GitLab URL. Returns None on failure."""
    from urllib.parse import urlsplit
    parsed = urlsplit(url.strip())
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None


def normalize_repo_url(url: str) -> str:
    """Normalize a repo URL for deduplication."""
    url = url.strip().rstrip("/").lower()
    if url.endswith(".git"):
        url = url[:-4]
    # Strip query params and fragments
    from urllib.parse import urlsplit, urlunsplit
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
