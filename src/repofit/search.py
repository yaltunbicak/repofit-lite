"""Stage 2: Repository search orchestration."""

from __future__ import annotations

import asyncio
import itertools
import logging

from rich.progress import Progress, SpinnerColumn, TextColumn

from repofit.ecosystems_client import EcosystemsClient
from repofit.github_client import GitHubClient
from repofit.gitlab_client import GitLabClient
from repofit.models import EcosystemsQuery, ParsedRequirements, RepoCandidate, SearchQuery
from repofit.utils import RateLimiterRegistry, normalize_repo_url

logger = logging.getLogger("repofit")


_DOMAIN_BROAD_QUERIES: dict[str, list[str]] = {
    "ai agent": ["multi-agent framework", "AI agent platform", "agent orchestration framework"],
    "llm": ["LLM orchestration", "LLM application framework", "LLM gateway"],
    "rag": ["RAG framework", "retrieval augmented generation"],
    "workflow": ["workflow orchestration engine", "workflow automation platform"],
    "mlops": ["MLOps platform", "ML pipeline framework"],
    "computer vision": ["computer vision framework", "image recognition platform"],
    "iot": ["IoT platform", "edge computing framework"],
    "backend": ["backend framework API", "microservices framework"],
    "devops": ["DevOps platform", "observability platform"],
    "test": ["test automation framework", "QA automation platform"],
}


def build_search_queries(
    reqs: ParsedRequirements, profile: dict | None = None,
) -> list[SearchQuery | EcosystemsQuery]:
    """Generate targeted search queries from parsed requirements."""
    queries: list[SearchQuery | EcosystemsQuery] = []
    lang = reqs.preferred_languages[0] if reqs.preferred_languages else None

    # Strategy A: Direct keyword combinations (primary keywords, 2 at a time)
    for combo in itertools.combinations(reqs.primary_keywords[:8], 2):
        queries.append(SearchQuery(
            terms=" ".join(combo),
            language=lang,
            sort="stars",
            max_results=10,
            platform="github",
        ))

    # Strategy B: Domain + framework combos
    for domain in reqs.domains[:3]:
        for fw in reqs.preferred_frameworks[:3]:
            queries.append(SearchQuery(
                terms=f"{domain} {fw}",
                sort="stars",
                max_results=5,
                platform="github",
            ))

    # Strategy C: "awesome-list" mining
    for kw in reqs.primary_keywords[:5]:
        queries.append(SearchQuery(
            terms=f"awesome {kw}",
            sort="stars",
            max_results=3,
            platform="github",
        ))

    # Strategy D: ecosyste.ms topic search
    for kw in reqs.primary_keywords[:5]:
        queries.append(EcosystemsQuery(topic=kw, max_results=10))

    # Strategy E: Domain-generic broad queries (catches well-known repos)
    for domain in reqs.domains[:5]:
        domain_lower = domain.lower()
        for key, broad_terms in _DOMAIN_BROAD_QUERIES.items():
            if key in domain_lower:
                for term in broad_terms:
                    queries.append(SearchQuery(
                        terms=term,
                        sort="stars",
                        max_results=10,
                        platform="github",
                    ))
                break

    # Strategy F: Pinned org search (if profile provides orgs to always include)
    if profile:
        pinned_orgs = profile.get("pinned_orgs", {}).get("github", [])
        for org in pinned_orgs[:4]:
            kw = reqs.primary_keywords[0] if reqs.primary_keywords else reqs.domains[0] if reqs.domains else ""
            if kw:
                queries.append(SearchQuery(
                    terms=f"org:{org} {kw}",
                    sort="stars",
                    max_results=5,
                    platform="github",
                ))

    return queries


def _deduplicate(candidates: list[RepoCandidate]) -> list[RepoCandidate]:
    """Deduplicate candidates by normalized URL with survivorship rules."""
    seen: dict[str, RepoCandidate] = {}
    for c in candidates:
        key = normalize_repo_url(c.url)
        if key in seen:
            existing = seen[key]
            # Survivorship: max stars/forks, first non-null description
            merged = existing.model_copy()
            if c.stars and (not merged.stars or c.stars > merged.stars):
                merged.stars = c.stars
            if c.forks and (not merged.forks or c.forks > merged.forks):
                merged.forks = c.forks
            if not merged.description and c.description:
                merged.description = c.description
            seen[key] = merged
        else:
            seen[key] = c
    return list(seen.values())


class SearchOrchestrator:
    """Executes multi-query fan-out across GitHub, GitLab, and ecosyste.ms."""

    def __init__(
        self,
        github: GitHubClient | None,
        gitlab: GitLabClient | None,
        ecosystems: EcosystemsClient | None,
        rate_limiter: RateLimiterRegistry,
    ) -> None:
        self.github = github
        self.gitlab = gitlab
        self.ecosystems = ecosystems
        self.limiter = rate_limiter

    async def search(
        self, reqs: ParsedRequirements, platforms: list[str], profile: dict | None = None,
        query_budget: int = 60, search_target: int = 100, per_query_results: int = 15,
    ) -> list[RepoCandidate]:
        """Execute search queries within budget and return deduplicated candidates."""
        queries = build_search_queries(reqs, profile)
        # Apply query budget cap
        if len(queries) > query_budget:
            queries = queries[:query_budget]
            logger.info("Query budget: %d/%d queries selected", query_budget, len(queries) + (len(queries) - query_budget))
        all_candidates: list[RepoCandidate] = []

        github_queries = [q for q in queries if isinstance(q, SearchQuery)]
        eco_queries = [q for q in queries if isinstance(q, EcosystemsQuery)]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            # GitHub searches
            if "github" in platforms and self.github:
                task = progress.add_task("Searching GitHub...", total=len(github_queries))
                for q in github_queries:
                    try:
                        results = await self.github.search_repos(
                            query=q.terms, language=q.language,
                            sort=q.sort, max_results=q.max_results,
                        )
                        all_candidates.extend(results)
                    except Exception as e:
                        logger.warning("GitHub search failed for '%s': %s", q.terms, e)
                    progress.advance(task)

            # GitLab searches (limited to 5, independent from GitHub)
            if "gitlab" in platforms and self.gitlab:
                gitlab_queries = github_queries[:5]
                task = progress.add_task("Searching GitLab...", total=len(gitlab_queries))
                for q in gitlab_queries:
                    try:
                        results = await self.gitlab.search_projects(
                            query=q.terms, max_results=q.max_results,
                        )
                        all_candidates.extend(results)
                    except Exception as e:
                        logger.warning("GitLab search failed for '%s': %s", q.terms, e)
                    progress.advance(task)

            # ecosyste.ms searches
            if self.ecosystems:
                task = progress.add_task("Searching ecosyste.ms...", total=len(eco_queries))
                for q in eco_queries:
                    try:
                        results = await self.ecosystems.search_repos(
                            query=q.topic, max_results=q.max_results,
                        )
                        all_candidates.extend(results)
                    except Exception as e:
                        logger.warning("ecosyste.ms search failed for '%s': %s", q.topic, e)
                    progress.advance(task)

        # Deduplicate and cap at search_target
        unique = _deduplicate(all_candidates)
        unique.sort(key=lambda c: c.stars or 0, reverse=True)
        if len(unique) > search_target:
            unique = unique[:search_target]
        logger.info("Search complete: %d total -> %d unique -> %d target", len(all_candidates), len(unique), search_target)
        return unique
