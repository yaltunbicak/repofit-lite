"""Pipeline orchestrator -- budget-controlled 4-stage funnel."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console
from rich.table import Table

from repofit.analyzer import analyze_all
from repofit.config import Settings
from repofit.enrichment import EnrichmentEngine
from repofit.llm_client import LLMClient
from repofit.models import ParsedRequirements, PipelineConfig
from repofit.search import SearchOrchestrator
from repofit.utils import FileCache, RateLimiterRegistry

logger = logging.getLogger("repofit")

RECOMMENDATION_STYLE = {
    "Strong Candidate": "[bold green]Strong Candidate[/bold green]",
    "Review Further": "[yellow]Review Further[/yellow]",
    "Low Priority": "[dim]Low Priority[/dim]",
    "Not Suitable": "[red]Not Suitable[/red]",
}


async def run_pipeline(
    reqs: ParsedRequirements,
    settings: Settings,
    llm: LLMClient,
    platforms: list[str],
    pipe_cfg: PipelineConfig,
    no_cache: bool,
    output_path: Path | None,
    output_format: str,
    console: Console,
    profile: dict | None = None,
) -> None:
    """Run the budget-controlled analysis pipeline."""

    rate_limiter = RateLimiterRegistry()
    cache = None if no_cache else FileCache(settings.cache_dir / "repos", settings.cache_ttl_hours)

    from repofit.ecosystems_client import EcosystemsClient
    from repofit.github_client import GitHubClient
    from repofit.gitlab_client import GitLabClient
    from repofit.scorecard_client import ScorecardClient

    github = GitHubClient(settings.github_tokens, rate_limiter) if settings.github_tokens else None
    gitlab = GitLabClient(settings.gitlab_token, settings.gitlab_url, rate_limiter) if settings.gitlab_token else None
    ecosystems = EcosystemsClient(settings.ecosystems_email, rate_limiter)
    scorecard = ScorecardClient(rate_limiter)

    async with _managed(github), _managed(gitlab), _managed(ecosystems), _managed(scorecard):
      try:
        # Stage 2: Search (budget-controlled)
        console.print("\n[bold]Stage 2:[/bold] Searching repositories...")
        orchestrator = SearchOrchestrator(github, gitlab, ecosystems, rate_limiter)
        candidates = await orchestrator.search(
            reqs, platforms, profile,
            query_budget=pipe_cfg.query_budget,
            search_target=pipe_cfg.search_target,
            per_query_results=pipe_cfg.per_query_results,
        )
        console.print(f"  Found [cyan]{len(candidates)}[/cyan] unique candidates\n")

        if not candidates:
            console.print("[red]No candidates found. Try adjusting your search terms or platforms.[/red]")
            return

        # Pre-filter: quality gate + budget enforcement
        before = len(candidates)
        candidates = _pre_filter(candidates, max_candidates=pipe_cfg.enrichment_budget)
        if before != len(candidates):
            console.print(f"  Pre-filtered: {before} -> [cyan]{len(candidates)}[/cyan] candidates\n")

        # Stage 3: Enrichment (budget-controlled)
        console.print("[bold]Stage 3:[/bold] Enriching repository metadata...")
        engine = EnrichmentEngine(
            github, gitlab, ecosystems,
            scorecard if not pipe_cfg.skip_scorecard else None,
            cache, settings,
            concurrency=pipe_cfg.enrichment_concurrency,
            per_repo_timeout=pipe_cfg.per_repo_timeout,
            skip_ecosystems_detail=pipe_cfg.skip_ecosystems_detail,
        )
        enriched = await engine.enrich_all(candidates)
        console.print(f"  Enriched [cyan]{len(enriched)}[/cyan] repositories\n")

        if not enriched:
            console.print("[red]No repositories could be enriched.[/red]")
            return

        # Stage 4: Analysis (budget-controlled)
        console.print("[bold]Stage 4:[/bold] Analyzing and scoring...")
        analyzed = await analyze_all(
            enriched, reqs, llm, profile,
            cache_dir=None if no_cache else settings.cache_dir,
            llm_budget=pipe_cfg.llm_budget,
            batch_size=pipe_cfg.llm_batch_size,
            readme_chars=pipe_cfg.readme_chars,
        )

        # Limit to max_repos for report
        analyzed = analyzed[:pipe_cfg.max_repos]

        # Show summary table
        _display_summary(analyzed, console)

        # Generate report
        from repofit.report import generate_csv, generate_json, generate_markdown

        profile_name = profile.get("name") if profile else None
        if output_format == "md":
            report = generate_markdown(analyzed, reqs, profile_name=profile_name, llm=llm)
        elif output_format == "csv":
            report = generate_csv(analyzed)
        elif output_format == "json":
            report = generate_json(analyzed)
        else:
            report = generate_markdown(analyzed, reqs, profile_name=profile_name, llm=llm)

        if output_path:
            output_path.write_text(report, encoding="utf-8")
            console.print(f"\n[green]Report saved to {output_path}[/green]")
        else:
            console.print("\n" + report)
      except Exception as e:
        console.print(f"\n[red]Pipeline error:[/red] {type(e).__name__}: {e}")
        console.print("[dim]Use --verbose for details. Check API keys and network.[/dim]")
        logger.exception("Pipeline failed")
        raise


def _display_summary(analyzed: list, console: Console) -> None:
    table = Table(title="Analysis Results")
    table.add_column("#", style="dim", width=3)
    table.add_column("Repository", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Fit", justify="right")
    table.add_column("Activity", justify="right")
    table.add_column("Stars", justify="right")
    table.add_column("License")
    table.add_column("Recommendation")

    for i, a in enumerate(analyzed[:20], 1):
        rec_style = RECOMMENDATION_STYLE.get(a.recommendation, a.recommendation)
        table.add_row(
            str(i), a.repo.full_name,
            f"{a.overall_score:.0f}", f"{a.fit_score.score:.0f}",
            f"{a.activity_score.score:.0f}", f"{a.repo.stars:,}",
            a.repo.license_spdx or a.repo.license or "--",
            rec_style,
        )
    console.print(table)


def _pre_filter(candidates: list, min_stars: int = 10, max_candidates: int = 100) -> list:
    """Quality gate + budget enforcement."""
    filtered = [
        c for c in candidates
        if c.full_name and c.url and c.stars is not None and c.stars >= min_stars
    ]
    filtered.sort(key=lambda c: c.stars or 0, reverse=True)
    return filtered[:max_candidates]


class _managed:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        if self.client and hasattr(self.client, "__aenter__"):
            await self.client.__aenter__()
        return self.client

    async def __aexit__(self, *args):
        if self.client and hasattr(self.client, "__aexit__"):
            await self.client.__aexit__(*args)
