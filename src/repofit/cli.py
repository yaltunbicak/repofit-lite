"""Typer CLI entry point."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.table import Table

from repofit.config import get_settings, list_profiles, load_profile, merge_profile_with_requirements
from repofit.utils import FileCache, setup_logging

app = typer.Typer(name="repofit", help="Find the best open-source repos for your project.")
console = Console()
logger = logging.getLogger("repofit")


def _display_parsed_requirements(reqs) -> None:
    """Display parsed requirements as rich tables."""
    console.print(f"\n[bold green]Project:[/bold green] {reqs.project_name}")
    console.print(f"[bold]Summary:[/bold] {reqs.project_summary}\n")

    kw_table = Table(title="Extracted Keywords")
    kw_table.add_column("Type", style="cyan")
    kw_table.add_column("Keywords")
    kw_table.add_row("Primary", ", ".join(reqs.primary_keywords))
    kw_table.add_row("Secondary", ", ".join(reqs.secondary_keywords))
    kw_table.add_row("Negative", ", ".join(reqs.negative_keywords) or "—")
    console.print(kw_table)

    tech_table = Table(title="Technical Constraints")
    tech_table.add_column("Field", style="cyan")
    tech_table.add_column("Value")
    tech_table.add_row("Languages", ", ".join(reqs.preferred_languages) or "—")
    tech_table.add_row("Frameworks", ", ".join(reqs.preferred_frameworks) or "—")
    tech_table.add_row("Deployment", reqs.deployment_model or "any")
    tech_table.add_row("Domains", ", ".join(reqs.domains) or "—")
    tech_table.add_row("Maturity", reqs.maturity_preference)
    tech_table.add_row("Community Size", reqs.community_size_preference)
    console.print(tech_table)

    crit_table = Table(title="Evaluation Criteria")
    crit_table.add_column("Type", style="cyan")
    crit_table.add_column("Items")
    crit_table.add_row("Must Have", "\n".join(f"• {m}" for m in reqs.must_have) or "—")
    crit_table.add_row("Nice to Have", "\n".join(f"• {n}" for n in reqs.nice_to_have) or "—")
    crit_table.add_row("Deal Breakers", "\n".join(f"• {d}" for d in reqs.deal_breakers) or "—")
    console.print(crit_table)


@app.command()
def analyze(
    input_file: Path = typer.Option(..., "--input", "-i", help="Path to PRD, architecture doc, or text file"),
    profile: str = typer.Option("dataguess", "--profile", "-p", help="Evaluation profile name"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output file path (default: stdout)"),
    format: str = typer.Option("md", "--format", "-f", help="Output format: md, csv, json"),
    max_repos: int = typer.Option(20, "--max", help="Max repos in final report"),
    mode: str = typer.Option("normal", "--mode", "-m", help="Pipeline mode: quick, normal, thorough"),
    quick: bool = typer.Option(False, "--quick", help="Fast screening mode (shortcut for --mode quick)"),
    thorough: bool = typer.Option(False, "--thorough", help="Deep analysis mode (shortcut for --mode thorough)"),
    platforms: str = typer.Option("github,gitlab", "--platforms", help="Comma-separated: github,gitlab"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Ignore cached API responses"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show progress and debug info"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse doc + show search queries, don't execute"),
) -> None:
    """Analyze a project document and find matching open-source repositories."""
    setup_logging(verbose)
    settings = get_settings()

    # Resolve mode from shortcut flags
    if quick:
        mode = "quick"
    elif thorough:
        mode = "thorough"

    # Create pipeline config
    from repofit.models import PipelineConfig
    pipe_cfg = PipelineConfig(max_repos=max_repos, mode=mode)

    if not input_file.exists():
        console.print(f"[red]Error:[/red] File not found: {input_file}")
        raise typer.Exit(1)

    console.print(f"[bold]RepoFit Lite[/bold] -- analyzing [cyan]{input_file}[/cyan]")
    console.print(f"[dim]{pipe_cfg.summary()}[/dim]")

    # Load profile
    try:
        profile_data = load_profile(profile)
        console.print(f"[dim]Profile: {profile_data.get('name', profile)}[/dim]\n")
    except FileNotFoundError:
        console.print(f"[yellow]Warning:[/yellow] Profile '{profile}' not found, using defaults\n")
        profile_data = {}

    # Stage 1: Parse document
    from repofit.llm_client import LLMClient
    from repofit.parser import parse_document

    with console.status("[bold green]Parsing document with LLM..."):
        llm = LLMClient(settings)
        reqs = parse_document(input_file, llm)

    # Merge profile with parsed requirements
    if profile_data:
        merge_profile_with_requirements(profile_data, reqs)

    _display_parsed_requirements(reqs)

    if dry_run:
        from repofit.search import build_search_queries
        queries = build_search_queries(reqs, profile_data)
        if len(queries) > pipe_cfg.query_budget:
            queries = queries[:pipe_cfg.query_budget]
        console.print(f"\n[bold yellow]Dry run:[/bold yellow] Would execute {len(queries)} search queries:")
        q_table = Table(title="Search Queries")
        q_table.add_column("#", style="dim")
        q_table.add_column("Platform", style="cyan")
        q_table.add_column("Query")
        q_table.add_column("Sort")
        q_table.add_column("Max")
        for i, q in enumerate(queries, 1):
            if hasattr(q, "terms"):
                q_table.add_row(str(i), q.platform, q.terms, q.sort, str(q.max_results))
            else:
                q_table.add_row(str(i), "ecosystems", q.topic, "relevance", str(q.max_results))
        console.print(q_table)
        raise typer.Exit(0)

    # Full pipeline
    from repofit.pipeline import run_pipeline
    asyncio.run(run_pipeline(
        reqs=reqs,
        settings=settings,
        llm=llm,
        platforms=platforms.split(","),
        pipe_cfg=pipe_cfg,
        no_cache=no_cache,
        output_path=output,
        output_format=format,
        console=console,
        profile=profile_data,
    ))


@app.command()
def profiles(
    list_profiles: bool = typer.Option(False, "--list", help="List available profiles"),
    show: str | None = typer.Option(None, "--show", help="Show profile details"),
) -> None:
    """Manage evaluation profiles."""
    if list_profiles:
        all_profiles = list_profiles_func()
        table = Table(title="Available Profiles")
        table.add_column("Name", style="cyan")
        table.add_column("File")
        table.add_column("Description")
        for p in all_profiles:
            table.add_row(p["name"], p["file"], p["description"])
        console.print(table)
        return

    if show:
        try:
            data = load_profile(show)
            console.print(f"\n[bold]{data.get('name', show)}[/bold]")
            console.print(f"[dim]{data.get('description', '')}[/dim]\n")
            console.print(yaml.dump(data, default_flow_style=False, allow_unicode=True))
        except FileNotFoundError:
            console.print(f"[red]Profile '{show}' not found[/red]")
        return

    console.print("Use --list to list profiles or --show <name> to view one.")


# Alias to avoid name collision with the `list_profiles` parameter
list_profiles_func = list_profiles_module = None


def _init_profiles_alias():
    global list_profiles_func
    from repofit.config import list_profiles as _lp
    list_profiles_func = _lp


_init_profiles_alias()


@app.command()
def cache(
    clear: bool = typer.Option(False, "--clear", help="Clear all cached data"),
    stats: bool = typer.Option(False, "--stats", help="Show cache statistics"),
) -> None:
    """Manage API response cache."""
    settings = get_settings()
    repo_cache = FileCache(settings.cache_dir / "repos", settings.cache_ttl_hours)
    fit_cache = FileCache(settings.cache_dir / "fit", settings.cache_ttl_hours)

    if clear:
        repo_count = repo_cache.clear()
        fit_count = fit_cache.clear()
        console.print(f"[green]Cleared {repo_count} enrichment + {fit_count} fit cache entries[/green]")
        return

    if stats:
        rs = repo_cache.stats()
        fs = fit_cache.stats()
        total_entries = rs["entries"] + fs["entries"]
        total_size = rs["total_size_bytes"] + fs["total_size_bytes"]
        console.print(f"Enrichment cache: [cyan]{rs['entries']}[/cyan] entries")
        console.print(f"Fit cache: [cyan]{fs['entries']}[/cyan] entries")
        console.print(f"Total size: [cyan]{total_size / 1024:.1f} KB[/cyan]")
        console.print(f"Cache dir: [dim]{settings.cache_dir}[/dim]")
        return

    console.print("Use --clear to clear cache or --stats to view statistics.")


if __name__ == "__main__":
    app()
