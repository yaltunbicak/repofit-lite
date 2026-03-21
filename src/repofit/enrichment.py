"""Stage 3: Per-repo metadata enrichment."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

from repofit.config import Settings
from repofit.ecosystems_client import EcosystemsClient
from repofit.github_client import GitHubClient
from repofit.gitlab_client import GitLabClient
from repofit.models import EnrichedRepo, RepoCandidate
from repofit.scorecard_client import ScorecardClient
from repofit.utils import FileCache

logger = logging.getLogger("repofit")

CI_INDICATORS = [
    ".github/workflows", ".gitlab-ci.yml",
    "Jenkinsfile", ".circleci", ".travis.yml", "azure-pipelines.yml",
]

TEST_INDICATORS = [
    "tests/", "test/", "spec/", "__tests__/",
    "pytest.ini", "jest.config", "vitest.config",
    "karma.conf", "cypress.config",
]


def _detect_ci(file_names: list[str]) -> bool:
    for name in file_names:
        for indicator in CI_INDICATORS:
            if name.lower().startswith(indicator.lower().rstrip("/")):
                return True
    return False


def _detect_tests(file_names: list[str]) -> bool:
    for name in file_names:
        for indicator in TEST_INDICATORS:
            if name.lower().startswith(indicator.lower().rstrip("/")):
                return True
    return False


_TEST_README_PATTERNS = [
    "pytest", "jest", "unittest", "test suite", "test coverage",
    "coverage report", "vitest", "mocha", "cypress", "playwright",
    "cargo test", "go test", "`npm test`", "`yarn test`",
    "ci/cd", "github actions", "running tests",
]


def _detect_tests_from_readme(readme: str | None) -> bool:
    """Detect test presence from README content (catches monorepos)."""
    if not readme:
        return False
    lower = readme.lower()
    return any(p in lower for p in _TEST_README_PATTERNS)


def _parse_releases(releases: list[dict], date_key: str = "published_at") -> tuple[int, str | None, str | None]:
    """Parse releases list. Returns (releases_180d, latest_tag, latest_date)."""
    now = datetime.now(timezone.utc)
    count_180d = 0
    latest_tag = None
    latest_date = None
    for rel in (releases or []):
        tag = rel.get("tag_name")
        if tag and not latest_tag:
            latest_tag = tag
            latest_date = rel.get(date_key)
        pub = rel.get(date_key)
        if pub:
            try:
                pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                if (now - pub_dt) < timedelta(days=180):
                    count_180d += 1
            except ValueError:
                pass
    return count_180d, latest_tag, latest_date


class EnrichmentEngine:
    """Async parallel enrichment with concurrency control and caching."""

    def __init__(
        self,
        github: GitHubClient | None,
        gitlab: GitLabClient | None,
        ecosystems: EcosystemsClient | None,
        scorecard: ScorecardClient | None,
        cache: FileCache | None,
        settings: Settings,
        concurrency: int = 5,
        per_repo_timeout: int = 60,
        skip_ecosystems_detail: bool = False,
    ) -> None:
        self.github = github
        self.gitlab = gitlab
        self.ecosystems = ecosystems
        self.scorecard = scorecard
        self.cache = cache
        self.semaphore = asyncio.Semaphore(concurrency)
        self.per_repo_timeout = per_repo_timeout
        self.skip_ecosystems_detail = skip_ecosystems_detail

    async def enrich_all(self, candidates: list[RepoCandidate]) -> list[EnrichedRepo]:
        """Enrich all candidates in parallel (semaphore-controlled)."""
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            transient=False,
        ) as progress:
            task = progress.add_task("Enriching repos...", total=len(candidates))
            results: list[EnrichedRepo | None] = []

            async def _enrich_one(c: RepoCandidate) -> EnrichedRepo | None:
                async with self.semaphore:
                    try:
                        async with asyncio.timeout(self.per_repo_timeout):
                            result = await self._enrich_repo(c)
                        return result
                    except TimeoutError:
                        logger.warning("Enrichment timed out for %s", c.full_name)
                        return None
                    except Exception as e:
                        logger.warning("Enrichment failed for %s: %s", c.full_name, e)
                        return None
                    finally:
                        progress.advance(task)

            tasks = [_enrich_one(c) for c in candidates]
            results = await asyncio.gather(*tasks)

        enriched = [r for r in results if r is not None]
        logger.info("Enriched %d/%d candidates", len(enriched), len(candidates))
        return enriched

    async def _enrich_repo(self, candidate: RepoCandidate) -> EnrichedRepo:
        """Enrich a single repo candidate."""
        # Check cache first
        if self.cache:
            cached = self.cache.get(candidate.url)
            if cached:
                logger.debug("Cache hit for %s", candidate.full_name)
                return EnrichedRepo.model_validate(cached)

        if candidate.source == "github" and self.github:
            enriched = await self._enrich_github(candidate)
        elif candidate.source == "gitlab" and self.gitlab:
            enriched = await self._enrich_gitlab(candidate)
        else:
            enriched = self._minimal_enriched(candidate)

        # Optional: OpenSSF Scorecard
        if self.scorecard and candidate.source == "github":
            try:
                sc = await self.scorecard.get_score(candidate.url)
                if sc:
                    enriched.openssf_score = sc.get("score")
                    enriched.openssf_checks = sc.get("checks")
            except Exception as e:
                logger.debug("Scorecard failed for %s: %s", candidate.full_name, e)

        # Optional: ecosyste.ms detail
        if self.ecosystems and not self.skip_ecosystems_detail:
            try:
                eco = await self.ecosystems.get_repo_detail(candidate.url)
                if eco:
                    enriched.dependent_repos_count = eco.get("dependent_repos_count")
                    enriched.dependent_packages_count = eco.get("dependent_packages_count")
                    enriched.download_count = eco.get("downloads") or eco.get("download_count")
            except Exception as e:
                logger.debug("ecosyste.ms detail failed for %s: %s", candidate.full_name, e)

        # Cache result
        if self.cache:
            self.cache.set(candidate.url, enriched.model_dump(mode="json"))

        return enriched

    async def _enrich_github(self, candidate: RepoCandidate) -> EnrichedRepo:
        """Fetch full metadata from GitHub."""
        parts = candidate.full_name.split("/")
        if len(parts) != 2:
            return self._minimal_enriched(candidate)
        owner, repo = parts

        # Parallel API calls
        detail, languages, contrib_count, releases, readme, community, activity, contents = (
            await asyncio.gather(
                self.github.get_repo_detail(owner, repo),
                self.github.get_languages(owner, repo),
                self.github.get_contributors_count(owner, repo),
                self.github.get_releases(owner, repo),
                self.github.get_readme(owner, repo),
                self._safe(self.github.get_community_profile(owner, repo), {}),
                self._safe(self.github.get_commit_activity(owner, repo), []),
                self._safe(self.github.get_contents_root(owner, repo), []),
                return_exceptions=False,
            )
        )

        # Compute commit activity
        commits_90d = 0
        active_weeks_90d = 0
        if isinstance(activity, list) and activity:
            for week in activity[-13:]:
                total = week.get("total", 0)
                commits_90d += total
                if total > 0:
                    active_weeks_90d += 1

        # Estimate recent contributors: heuristic based on commit spread
        # If many active weeks, likely multiple contributors
        contributors_90d_est = None
        if active_weeks_90d > 0 and contrib_count:
            ratio = min(active_weeks_90d / 13, 1.0)
            contributors_90d_est = max(1, int(contrib_count * ratio * 0.3))

        releases_180d, latest_release, latest_release_date = _parse_releases(releases or [])

        # File name list for CI/test detection
        file_names = [item.get("name", "") for item in (contents or []) if isinstance(item, dict)]

        # Community profile
        community_files = community.get("files", {}) if isinstance(community, dict) else {}

        # License
        license_info = detail.get("license") or {}
        license_name = license_info.get("name") if isinstance(license_info, dict) else None
        license_spdx = license_info.get("spdx_id") if isinstance(license_info, dict) else None

        readme_text = readme or ""

        return EnrichedRepo(
            source="github",
            full_name=candidate.full_name,
            url=candidate.url,
            description=detail.get("description"),
            homepage=detail.get("homepage"),
            stars=detail.get("stargazers_count", 0),
            forks=detail.get("forks_count", 0),
            watchers=detail.get("subscribers_count", 0),
            open_issues=detail.get("open_issues_count", 0),
            created_at=detail.get("created_at", ""),
            updated_at=detail.get("updated_at", ""),
            pushed_at=detail.get("pushed_at", ""),
            last_commit_date=detail.get("pushed_at"),
            commits_last_90d=commits_90d if commits_90d > 0 else None,
            releases_last_180d=releases_180d,
            latest_release=latest_release,
            latest_release_date=latest_release_date,
            contributors_total=contrib_count,
            contributors_last_90d=contributors_90d_est,
            primary_language=detail.get("language"),
            languages=languages if isinstance(languages, dict) else {},
            topics=detail.get("topics", []),
            license=license_name,
            license_spdx=license_spdx,
            has_readme=bool(readme),
            readme_length=len(readme_text) if readme else None,
            readme_excerpt=readme_text[:2000] if readme else None,
            has_ci=_detect_ci(file_names),
            has_tests=_detect_tests(file_names) or _detect_tests_from_readme(readme),
            has_contributing=bool(community_files.get("contributing")),
            has_code_of_conduct=bool(community_files.get("code_of_conduct")),
            has_changelog=any(n.lower().startswith("changelog") for n in file_names),
            search_queries=[candidate.search_query],
            enriched_at=datetime.now(timezone.utc).isoformat(),
        )

    async def _enrich_gitlab(self, candidate: RepoCandidate) -> EnrichedRepo:
        """Fetch full metadata from GitLab."""
        project_path = candidate.full_name

        detail, languages, contrib_count, releases, readme, tree, commits_90d = await asyncio.gather(
            self._safe(self.gitlab.get_project_detail(project_path), {}),
            self._safe(self.gitlab.get_languages(project_path), {}),
            self._safe(self.gitlab.get_contributors_count(project_path), 0),
            self._safe(self.gitlab.get_releases(project_path), []),
            self._safe(self.gitlab.get_readme(project_path), None),
            self._safe(self.gitlab.get_repository_tree(project_path), []),
            self._safe(self.gitlab.get_commit_count_90d(project_path), 0),
        )

        file_names = [item.get("name", "") for item in (tree or []) if isinstance(item, dict)]

        releases_180d, latest_release, latest_release_date = _parse_releases(releases or [], "released_at")
        readme_text = readme or ""

        # Derive primary language from languages dict
        primary_lang = None
        if isinstance(languages, dict) and languages:
            primary_lang = max(languages, key=languages.get)

        # Extract license from project detail (requires ?license=true)
        license_info = detail.get("license") or {}
        license_name = license_info.get("name") if isinstance(license_info, dict) else None
        license_key = license_info.get("key") if isinstance(license_info, dict) else None

        return EnrichedRepo(
            source="gitlab",
            full_name=candidate.full_name,
            url=candidate.url,
            description=detail.get("description"),
            homepage=detail.get("web_url"),
            stars=detail.get("star_count", 0),
            forks=detail.get("forks_count", 0),
            watchers=0,
            open_issues=detail.get("open_issues_count", 0),
            created_at=detail.get("created_at", ""),
            updated_at=detail.get("last_activity_at", ""),
            pushed_at=detail.get("last_activity_at", ""),
            commits_last_90d=commits_90d if commits_90d > 0 else None,
            contributors_total=contrib_count if isinstance(contrib_count, int) else 0,
            primary_language=primary_lang,
            languages={k: int(v) for k, v in languages.items()} if languages else {},
            topics=detail.get("topics", []) or detail.get("tag_list", []),
            license=license_name,
            license_spdx=license_key,
            has_readme=bool(readme),
            readme_length=len(readme_text) if readme else None,
            readme_excerpt=readme_text[:2000] if readme else None,
            has_ci=_detect_ci(file_names),
            has_tests=_detect_tests(file_names) or _detect_tests_from_readme(readme),
            has_contributing=any(n.lower().startswith("contributing") for n in file_names),
            has_code_of_conduct=any(n.lower().startswith("code_of_conduct") for n in file_names),
            has_changelog=any(n.lower().startswith("changelog") for n in file_names),
            releases_last_180d=releases_180d,
            latest_release=latest_release,
            latest_release_date=latest_release_date,
            search_queries=[candidate.search_query],
            enriched_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _minimal_enriched(candidate: RepoCandidate) -> EnrichedRepo:
        """Create a minimally enriched repo from search data only."""
        return EnrichedRepo(
            source=candidate.source,
            full_name=candidate.full_name,
            url=candidate.url,
            description=candidate.description,
            stars=candidate.stars or 0,
            forks=candidate.forks or 0,
            primary_language=candidate.language,
            topics=candidate.topics,
            updated_at=candidate.updated_at or "",
            pushed_at=candidate.updated_at or "",
            search_queries=[candidate.search_query],
            enriched_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    async def _safe(coro, default):
        """Execute coroutine, return default on error."""
        try:
            return await coro
        except Exception as e:
            logger.debug("Safe call failed: %s", e)
            return default
