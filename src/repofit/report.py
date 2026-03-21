"""Report generation — Markdown, CSV, JSON output."""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime

from repofit.models import AnalyzedRepo, ParsedRequirements

logger = logging.getLogger("repofit")

RECOMMENDATION_ICON = {
    "Strong Candidate": "✅",
    "Review Further": "🔍",
    "Low Priority": "⚠️",
    "Not Suitable": "❌",
}

FIRST_PLACE_ICON = "🏆"


def generate_executive_summary(
    analyzed: list[AnalyzedRepo], reqs: ParsedRequirements, llm=None,
) -> str:
    """Generate LLM-powered executive summary (3-5 sentences)."""
    strong = [a for a in analyzed if a.recommendation == "Strong Candidate"]
    review = [a for a in analyzed if a.recommendation == "Review Further"]
    not_suitable = [a for a in analyzed if a.recommendation == "Not Suitable"]

    if llm:
        top_repos = [
            {"name": a.repo.full_name, "score": a.overall_score, "fit": a.fit_score.score,
             "language": a.repo.primary_language, "recommendation": a.recommendation}
            for a in analyzed[:10]
        ]
        prompt = (
            f"Write a 3-5 sentence executive summary for a repository evaluation report.\n\n"
            f"Project: {reqs.project_name}\n"
            f"Summary: {reqs.project_summary}\n"
            f"Total evaluated: {len(analyzed)}\n"
            f"Strong candidates: {len(strong)}\n"
            f"Review further: {len(review)}\n"
            f"Not suitable: {len(not_suitable)}\n\n"
            f"Top repos: {json.dumps(top_repos)}\n\n"
            f"Write a concise analytical summary highlighting: dominant trends, "
            f"top recommendation with why, key gaps observed, and actionable next steps. "
            f"Do NOT use markdown formatting. Plain text only."
        )
        try:
            return llm.complete("You are a technical report writer. Output plain text, no JSON.", prompt, json_mode=False)
        except Exception as e:
            logger.warning("LLM executive summary failed: %s", e)

    # Fallback: template-based
    parts = [f"Evaluated {len(analyzed)} repositories for the {reqs.project_name} project."]
    parts.append(f"Found {len(strong)} strong candidate(s) and {len(review)} worth further review.")
    if strong:
        top = strong[0]
        parts.append(
            f"The top recommendation is {top.repo.full_name} (score: {top.overall_score:.0f}/100), "
            f"which {top.summary[:150] if top.summary else 'closely matches the requirements'}."
        )
    if not_suitable:
        parts.append(
            f"{len(not_suitable)} repository(ies) were marked as not suitable due to "
            f"licensing issues or inactivity."
        )
    return " ".join(parts)


def generate_markdown(
    analyzed: list[AnalyzedRepo], reqs: ParsedRequirements,
    profile_name: str | None = None, llm=None,
) -> str:
    """Generate full Markdown report."""
    lines: list[str] = []

    # Header
    lines.append("# RepoFit Analysis Report\n")
    lines.append(f"**Project:** {reqs.project_name}")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Candidates evaluated:** {len(analyzed)}")
    if profile_name:
        lines.append(f"**Profile:** {profile_name}")
    lines.append(f"**Domains:** {', '.join(reqs.domains)}\n")

    # Executive summary (LLM-generated)
    lines.append("## Executive Summary\n")
    summary_text = generate_executive_summary(analyzed, reqs, llm)
    lines.append(summary_text)
    lines.append("")

    # Top Recommendations
    lines.append("## Top Recommendations\n")
    for i, a in enumerate(analyzed, 1):
        icon = FIRST_PLACE_ICON if i == 1 else RECOMMENDATION_ICON.get(a.recommendation, "")
        lines.append(f"### {icon} {i}. {a.repo.full_name} — Score: {a.overall_score:.0f}/100 — {a.recommendation}\n")
        if a.summary:
            lines.append(f"> {a.summary}\n")

        # Metrics table
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Stars | {a.repo.stars:,} |")
        lines.append(f"| Last Activity | {a.repo.pushed_at[:10] if a.repo.pushed_at else '--'} |")
        lines.append(f"| License | {a.repo.license_spdx or a.repo.license or '--'} |")
        lines.append(f"| Language | {a.repo.primary_language or '--'} |")
        # Contributors (90d) per spec, fallback to total
        if a.repo.contributors_last_90d:
            lines.append(f"| Contributors (90d) | {a.repo.contributors_last_90d} |")
        else:
            lines.append(f"| Contributors | {a.repo.contributors_total or '--'} |")
        if a.repo.openssf_score is not None:
            lines.append(f"| OpenSSF Score | {a.repo.openssf_score:.1f}/10 |")
        lines.append("")

        # Fit score
        lines.append(f"**Fit Score:** {a.fit_score.score:.0f}/100 -- {a.fit_explanation}\n")

        # Pros
        if a.pros:
            lines.append("**Pros:**")
            for p in a.pros:
                lines.append(f"- {p}")
            lines.append("")

        # Cons
        if a.cons:
            lines.append("**Cons:**")
            for c in a.cons:
                lines.append(f"- {c}")
            lines.append("")

        # Risk factors
        if a.risk_factors:
            lines.append("**Risk Factors:**")
            for r in a.risk_factors:
                lines.append(f"- {r}")
            lines.append("")

        # Score breakdown
        lines.append("**Score Breakdown:**")
        lines.append(f"- Fit: {a.fit_score.score:.0f}/100 ({a.fit_score.weight:.0%})")
        lines.append(f"- Activity: {a.activity_score.score:.0f}/100 ({a.activity_score.weight:.0%})")
        lines.append(f"- Community: {a.community_score.score:.0f}/100 ({a.community_score.weight:.0%})")
        lines.append(f"- Popularity: {a.popularity_score.score:.0f}/100 ({a.popularity_score.weight:.0%})")
        lines.append(f"- Quality: {a.quality_score.score:.0f}/100 ({a.quality_score.weight:.0%})")
        lines.append("\n---\n")

    # Comparison Matrix
    lines.append("## Comparison Matrix\n")
    lines.append("| Repository | Score | Fit | Activity | License | Language | Stars | Recommendation |")
    lines.append("|------------|-------|-----|----------|---------|----------|-------|----------------|")
    for a in analyzed:
        icon = RECOMMENDATION_ICON.get(a.recommendation, "")
        stars_str = _format_stars(a.repo.stars)
        lines.append(
            f"| {a.repo.full_name} "
            f"| {a.overall_score:.0f} "
            f"| {a.fit_score.score:.0f} "
            f"| {a.activity_score.score:.0f} "
            f"| {a.repo.license_spdx or '--'} "
            f"| {a.repo.primary_language or '--'} "
            f"| {stars_str} "
            f"| {icon} {a.recommendation} |"
        )
    lines.append("")

    # Domain Grouping
    domains = _group_by_domain(analyzed, reqs)
    if domains:
        lines.append("## Domain Grouping\n")
        for domain, repos in domains.items():
            lines.append(f"### {domain}")
            for j, a in enumerate(repos, 1):
                lines.append(f"{j}. **{a.repo.full_name}** -- {a.overall_score:.0f}/100 -- {a.summary[:80] if a.summary else ''}")
            lines.append("")

    # Methodology — read actual weights from first analyzed repo
    lines.append("## Methodology\n")
    if analyzed:
        a0 = analyzed[0]
        lines.append(
            f"Scoring weights: "
            f"Fit {a0.fit_score.weight:.0%}, "
            f"Activity {a0.activity_score.weight:.0%}, "
            f"Community {a0.community_score.weight:.0%}, "
            f"Popularity {a0.popularity_score.weight:.0%}, "
            f"Quality {a0.quality_score.weight:.0%}.\n"
        )
    else:
        lines.append("Scoring weights: Fit 35%, Activity 20%, Community 15%, Popularity 15%, Quality 15%.\n")
    lines.append("- **Fit** (LLM-powered): Measures how well the repository's purpose, features, and "
                 "architecture align with the project requirements. Scored by analyzing README, topics, "
                 "and description against the PRD's must-have and nice-to-have criteria.")
    lines.append("- **Activity**: Rule-based scoring of commit recency (last push date), commit velocity "
                 "(commits in last 90 days), release frequency (releases in last 180 days), and issue activity.")
    lines.append("- **Community**: Contributor count (total and recent), presence of contributing guidelines "
                 "and code of conduct.")
    lines.append("- **Popularity**: Log-normalized stars and forks, dependent repository count, watcher count.")
    lines.append("- **Quality**: License type (permissive bonus), CI/CD detection, test suite presence, "
                 "README quality, changelog, and OpenSSF Scorecard score where available.")
    lines.append("\nRecommendation thresholds: Strong Candidate >= 75, Review Further >= 50, "
                 "Low Priority >= 30. Hard gates: no license, forbidden license (per profile), "
                 "or > 1 year inactive automatically disqualify.")
    lines.append("")

    return "\n".join(lines)


def generate_csv(analyzed: list[AnalyzedRepo]) -> str:
    """Generate flat CSV report."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Repository", "URL", "Overall Score", "Fit", "Activity", "Community",
        "Popularity", "Quality", "Stars", "Forks", "Language", "License",
        "Recommendation", "Summary",
    ])
    for a in analyzed:
        writer.writerow([
            a.repo.full_name, a.repo.url, f"{a.overall_score:.1f}",
            f"{a.fit_score.score:.0f}", f"{a.activity_score.score:.0f}",
            f"{a.community_score.score:.0f}", f"{a.popularity_score.score:.0f}",
            f"{a.quality_score.score:.0f}", a.repo.stars, a.repo.forks,
            a.repo.primary_language or "", a.repo.license_spdx or "",
            a.recommendation, a.summary,
        ])
    return output.getvalue()


def generate_json(analyzed: list[AnalyzedRepo]) -> str:
    """Generate JSON report."""
    return json.dumps(
        [a.model_dump(mode="json") for a in analyzed],
        indent=2,
        ensure_ascii=False,
    )


def _format_stars(stars: int) -> str:
    if stars >= 1000:
        return f"{stars / 1000:.1f}k"
    return str(stars)


_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "ai agent": ["agent", "multi-agent", "agentic", "autonomous", "crew"],
    "llm": ["llm", "language-model", "langchain", "langgraph", "gpt", "prompt"],
    "rag": ["rag", "retrieval", "vector", "embedding", "knowledge-base", "semantic-search"],
    "workflow": ["workflow", "orchestration", "pipeline", "automation", "dag"],
    "mlops": ["mlops", "ml-platform", "model-serving", "experiment", "feature-store"],
    "computer vision": ["computer-vision", "image", "object-detection", "opencv", "yolo"],
    "iot": ["iot", "edge", "industrial", "sensor", "mqtt"],
    "backend": ["backend", "api-framework", "microservice", "rest-api", "fastapi"],
    "devops": ["devops", "observability", "monitoring", "logging", "kubernetes"],
    "test": ["testing", "qa", "test-automation", "selenium", "playwright"],
}


def _group_by_domain(
    analyzed: list[AnalyzedRepo], reqs: ParsedRequirements | None = None,
) -> dict[str, list[AnalyzedRepo]]:
    """Group repos by PRD domains using keyword taxonomy."""
    domains = reqs.domains if reqs and reqs.domains else []
    if not domains:
        groups: dict[str, list[AnalyzedRepo]] = {}
        for a in analyzed:
            key = (a.repo.topics[0].replace("-", " ").title()) if a.repo.topics else "Other"
            groups.setdefault(key, []).append(a)
        return groups

    groups: dict[str, list[AnalyzedRepo]] = {d: [] for d in domains}
    groups["Other"] = []

    for a in analyzed:
        searchable = " ".join(
            a.repo.topics + [a.repo.description or "", a.summary or ""]
        ).lower()

        best_domain = None
        best_score = 0
        for domain in domains:
            domain_key = domain.lower()
            # Get extra keywords from taxonomy
            extra_kw = []
            for key, kws in _DOMAIN_KEYWORDS.items():
                if key in domain_key:
                    extra_kw = kws
                    break
            # Combine domain words + taxonomy keywords
            words = [w for w in domain_key.split() if len(w) > 2] + extra_kw
            matches = sum(1 for w in words if w in searchable)
            # Bonus: full domain phrase match
            if domain_key in searchable:
                matches += 3
            if matches > best_score:
                best_score = matches
                best_domain = domain

        if best_domain and best_score > 0:
            groups[best_domain].append(a)
        else:
            groups["Other"].append(a)

    return {k: v for k, v in groups.items() if v}
