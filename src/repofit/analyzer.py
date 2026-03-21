"""Stage 4: LLM-powered fit analysis + orchestration."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

from repofit.llm_client import LLMClient
from repofit.models import AnalyzedRepo, EnrichedRepo, FitDimension, ParsedRequirements
from repofit.scoring import (
    compute_activity_score,
    compute_community_score,
    compute_popularity_score,
    compute_quality_score,
)
from repofit.utils import FileCache

logger = logging.getLogger("repofit")

ANALYZER_SYSTEM_PROMPT = """
You are a senior software architect evaluating open-source projects for
adoption. You will receive:
1. Project requirements extracted from a PRD
2. Metadata for up to 5 candidate repositories

For each repository, provide:
- fit_score (0-100): How well does this repo match the requirements?
- summary: 2-3 sentences describing what this repo does
- pros: Up to 5 specific advantages for THIS project's needs
- cons: Up to 5 specific disadvantages or gaps
- fit_explanation: Why it matches or doesn't (reference specific requirements)
- risk_factors: Up to 3 risks of adopting this repo
- similar_to: Which other repos in this batch serve the same purpose
- differentiator: What makes this repo unique vs the alternatives

SCORING RULES — be strict about core purpose alignment:
- Score fit 70-100 ONLY if the repository directly addresses the project's primary use case.
- Score fit 30-69 if the repository is a useful component but not a direct solution.
- Score fit below 30 if the repository only shares technology stack but serves a
  fundamentally different purpose (e.g., an API proxy when the requirement is for an
  orchestration platform, or an LLM gateway when the requirement is for an agent framework).
- A repository that uses FastAPI does NOT automatically fit an "AI agent platform" need.
- If the project specifies preferred languages (e.g., Python) and the repository's primary
  language is different (e.g., Java, TypeScript), deduct 10-15 points from fit score
  and mention the language mismatch in cons.

Be specific. Reference actual data (stars, last commit, license, languages).
Don't be generic. Tailor every assessment to the requirements.

Output valid JSON array. Nothing else.

Schema for each item:
{
  "full_name": "owner/repo",
  "fit_score": 85,
  "summary": "...",
  "pros": ["...", "..."],
  "cons": ["...", "..."],
  "fit_explanation": "...",
  "risk_factors": ["..."],
  "similar_to": ["owner/repo2"],
  "differentiator": "..."
}
"""


def _fit_cache_key(repo_url: str, reqs: ParsedRequirements) -> str:
    """Deterministic cache key: hash(repo_url + requirements_hash)."""
    reqs_str = reqs.model_dump_json(exclude={"project_name"})
    combined = f"{repo_url}|{reqs_str}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


async def compute_fit_scores(
    repos: list[EnrichedRepo],
    reqs: ParsedRequirements,
    llm: LLMClient,
    fit_cache: FileCache | None = None,
    batch_size: int = 5,
    readme_chars: int = 500,
) -> dict[str, dict]:
    """Batch LLM fit analysis with per-repo caching."""
    results: dict[str, dict] = {}
    uncached_repos: list[EnrichedRepo] = []

    # Check cache for each repo
    for r in repos:
        if fit_cache:
            cache_key = _fit_cache_key(r.url, reqs)
            cached = fit_cache.get(cache_key)
            if cached:
                results[r.full_name] = cached
                logger.debug("Fit cache hit: %s", r.full_name)
                continue
        uncached_repos.append(r)

    if uncached_repos:
        logger.info("Fit analysis: %d cached, %d need LLM", len(results), len(uncached_repos))

    if not uncached_repos:
        return results

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        transient=False,
    ) as progress:
        total_batches = (len(uncached_repos) + batch_size - 1) // batch_size
        task = progress.add_task("LLM fit analysis...", total=total_batches)

        for i in range(0, len(uncached_repos), batch_size):
            batch = uncached_repos[i : i + batch_size]
            batch_data = []
            for r in batch:
                batch_data.append({
                    "full_name": r.full_name,
                    "description": r.description,
                    "stars": r.stars,
                    "language": r.primary_language,
                    "license": r.license_spdx or r.license,
                    "pushed_at": r.pushed_at,
                    "topics": r.topics[:10],
                    "has_ci": r.has_ci,
                    "has_tests": r.has_tests,
                    "readme_excerpt": (r.readme_excerpt or "")[:readme_chars],
                })

            user_prompt = (
                f"Requirements:\n{json.dumps(reqs.model_dump(), indent=2)}\n\n"
                f"Candidate repositories:\n{json.dumps(batch_data, indent=2)}"
            )

            try:
                analysis = llm.complete_json(ANALYZER_SYSTEM_PROMPT, user_prompt)
                parsed_items = []
                if isinstance(analysis, list):
                    parsed_items = analysis
                elif isinstance(analysis, dict):
                    parsed_items = analysis.get("results", analysis.get("repositories", [analysis]))
                    if not isinstance(parsed_items, list):
                        parsed_items = []

                for item in parsed_items:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("full_name", "")
                    if name:
                        results[name] = item
                        if fit_cache:
                            repo_obj = next((r for r in batch if r.full_name == name), None)
                            if repo_obj:
                                fit_cache.set(_fit_cache_key(repo_obj.url, reqs), item)
            except Exception as e:
                logger.warning("LLM fit analysis failed for batch %d: %s", i // batch_size, e)

            progress.advance(task)

    return results


_NO_LICENSE_VALUES = {"NOASSERTION", "NONE", "OTHER", ""}


def _normalize_spdx(spdx_id: str | None) -> str:
    """Normalize SPDX identifier using license-expression library."""
    if not spdx_id:
        return ""
    raw = spdx_id.strip()
    try:
        from license_expression import get_spdx_licensing
        licensing = get_spdx_licensing()
        parsed = licensing.parse(raw, validate=True)
        return str(parsed) if parsed else raw.upper()
    except Exception:
        return raw.upper()


def _is_license_forbidden(spdx: str, policy: dict) -> bool:
    """Check if license is forbidden by profile policy. Exact SPDX match after normalization."""
    forbidden = policy.get("forbidden", [])
    normalized_forbidden = {_normalize_spdx(f) for f in forbidden}
    normalized_spdx = _normalize_spdx(spdx)
    return normalized_spdx in normalized_forbidden


def assign_recommendation(analyzed: AnalyzedRepo, profile: dict | None = None) -> str:
    """Rule-based gates + score thresholds. Profile license policy checked."""
    repo = analyzed.repo

    # Gate: no license or meaningless license value
    spdx = (repo.license_spdx or "").strip().upper()
    if not repo.license or spdx in _NO_LICENSE_VALUES:
        return "Not Suitable"

    # Gate: profile license policy (forbidden + allowed)
    if profile:
        policy = profile.get("license_policy", {})
        if _is_license_forbidden(repo.license_spdx or "", policy):
            return "Not Suitable"
        # Check allowed whitelist if defined
        allowed = policy.get("allowed")
        if allowed:
            normalized_allowed = {_normalize_spdx(a) for a in allowed}
            if _normalize_spdx(repo.license_spdx or "") not in normalized_allowed:
                pass  # Don't block — allowed is advisory for now

    # Gate: inactive > 1 year
    if repo.pushed_at:
        try:
            pushed = datetime.fromisoformat(repo.pushed_at.replace("Z", "+00:00"))
            days = (datetime.now(timezone.utc) - pushed).days
            if days > 365:
                return "Not Suitable"
        except ValueError:
            return "Not Suitable"  # Unparseable date = conservative reject

    # Score-based thresholds (from profile or defaults)
    thresholds = profile.get("thresholds", {}) if profile else {}
    strong = thresholds.get("strong_candidate", 75)
    review = thresholds.get("review_further", 50)
    low = thresholds.get("low_priority", 30)

    if analyzed.overall_score >= strong:
        return "Strong Candidate"
    elif analyzed.overall_score >= review:
        return "Review Further"
    elif analyzed.overall_score >= low:
        return "Low Priority"
    return "Not Suitable"


_DEFAULT_WEIGHTS = {"fit": 0.35, "activity": 0.20, "community": 0.15, "popularity": 0.15, "quality": 0.15}


async def analyze_all(
    enriched: list[EnrichedRepo],
    reqs: ParsedRequirements,
    llm: LLMClient,
    profile: dict | None = None,
    cache_dir: Path | None = None,
    llm_budget: int | None = None,
    batch_size: int = 5,
    readme_chars: int = 500,
) -> list[AnalyzedRepo]:
    """Run full analysis: deterministic scores + LLM fit + recommendations."""

    # Fit result cache (per repo+PRD, 24h TTL)
    fit_cache = FileCache(cache_dir / "fit", ttl_hours=24) if cache_dir else None

    # Load weights from profile or use defaults, with validation
    weights = _DEFAULT_WEIGHTS.copy()
    if profile and "scoring_weights" in profile:
        known_keys = set(_DEFAULT_WEIGHTS.keys())
        for k, v in profile["scoring_weights"].items():
            if k in known_keys:
                weights[k] = v
            else:
                logger.warning("Unknown scoring weight key in profile: %s", k)

    # Normalize weights to sum to 1.0
    total = sum(weights.values())
    if abs(total - 1.0) > 0.01:
        logger.warning("Scoring weights sum to %.2f, normalizing to 1.0", total)
        weights = {k: v / total for k, v in weights.items()}

    w_fit = weights.get("fit", 0.35)
    w_act = weights.get("activity", 0.20)
    w_com = weights.get("community", 0.15)
    w_pop = weights.get("popularity", 0.15)
    w_qual = weights.get("quality", 0.15)

    # Phase A: Deterministic scoring
    analyzed_repos: list[AnalyzedRepo] = []
    for repo in enriched:
        analyzed = AnalyzedRepo(
            repo=repo,
            activity_score=compute_activity_score(repo),
            popularity_score=compute_popularity_score(repo),
            community_score=compute_community_score(repo),
            quality_score=compute_quality_score(repo),
        )
        analyzed.activity_score.weight = w_act
        analyzed.popularity_score.weight = w_pop
        analyzed.community_score.weight = w_com
        analyzed.quality_score.weight = w_qual
        analyzed_repos.append(analyzed)

    # Early elimination: sort by deterministic score, LLM-analyze only top half
    # Bottom half gets fit=0 — saves ~50% LLM cost
    # Compute deterministic scores for sorting
    det_scores: dict[str, float] = {}
    for analyzed in analyzed_repos:
        det = (
            analyzed.activity_score.score * w_act
            + analyzed.community_score.score * w_com
            + analyzed.popularity_score.score * w_pop
            + analyzed.quality_score.score * w_qual
        )
        det_scores[analyzed.repo.full_name] = det

    analyzed_repos.sort(key=lambda a: det_scores.get(a.repo.full_name, 0), reverse=True)

    # LLM budget from PipelineConfig or fallback to 50%
    if llm_budget is not None:
        budget = min(llm_budget, len(analyzed_repos))
    else:
        budget = max(1, min(len(analyzed_repos), round(len(analyzed_repos) * 0.5)))
    llm_candidates = analyzed_repos[:budget]
    skipped = analyzed_repos[budget:]

    if skipped:
        logger.info("Early elimination: top %d by deterministic score sent to LLM, %d skipped",
                     len(llm_candidates), len(skipped))

    # Phase B: LLM fit analysis (only for candidates that can reach threshold)
    llm_enriched = [a.repo for a in llm_candidates]
    fit_results = await compute_fit_scores(llm_enriched, reqs, llm, fit_cache,
                                           batch_size=batch_size, readme_chars=readme_chars)

    for analyzed in llm_candidates:
        llm_data = fit_results.get(analyzed.repo.full_name, {})
        fit_score_val = llm_data.get("fit_score", 0)

        analyzed.fit_score = FitDimension(
            name="Fit", score=float(fit_score_val), weight=w_fit,
            evidence=[llm_data.get("fit_explanation", "No LLM analysis available")],
        )
        analyzed.summary = llm_data.get("summary", analyzed.repo.description or "")
        analyzed.pros = llm_data.get("pros", [])
        analyzed.cons = llm_data.get("cons", [])
        analyzed.fit_explanation = llm_data.get("fit_explanation", "")
        analyzed.risk_factors = llm_data.get("risk_factors", [])
        analyzed.similar_to = llm_data.get("similar_to", [])
        analyzed.differentiator = llm_data.get("differentiator", "")

        analyzed.overall_score = (
            analyzed.fit_score.score * w_fit
            + analyzed.activity_score.score * w_act
            + analyzed.community_score.score * w_com
            + analyzed.popularity_score.score * w_pop
            + analyzed.quality_score.score * w_qual
        )

    # Skipped repos get fit=0 and deterministic-only overall
    for analyzed in skipped:
        analyzed.fit_score = FitDimension(name="Fit", score=0, weight=w_fit,
                                          evidence=["Skipped: deterministic scores too low"])
        analyzed.summary = analyzed.repo.description or ""
        analyzed.overall_score = (
            analyzed.activity_score.score * w_act
            + analyzed.community_score.score * w_com
            + analyzed.popularity_score.score * w_pop
            + analyzed.quality_score.score * w_qual
        )

    # Phase C: Recommendations
    all_repos = llm_candidates + skipped
    for analyzed in all_repos:
        analyzed.recommendation = assign_recommendation(analyzed, profile)

    all_repos.sort(key=lambda a: a.overall_score, reverse=True)
    return all_repos
