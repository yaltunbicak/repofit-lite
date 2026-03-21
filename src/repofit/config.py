"""Settings and environment configuration using pydantic-settings."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("repofit")


class Settings(BaseSettings):
    """Application settings loaded automatically from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-flash"
    llm_max_tokens: int = 8192

    # LLM API Keys
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # GitHub
    github_token: str | None = None
    github_tokens: list[str] = Field(default_factory=list)

    # GitLab
    gitlab_token: str | None = None
    gitlab_url: str = "https://gitlab.com"

    # ecosyste.ms
    ecosystems_email: str | None = None

    # Cache
    cache_dir: Path = Path("./cache")
    cache_ttl_hours: int = 24

    @field_validator("github_tokens", mode="before")
    @classmethod
    def parse_github_tokens(cls, v: str | list[str] | None) -> list[str]:
        if isinstance(v, str):
            return [t.strip() for t in v.split(",") if t.strip()]
        if isinstance(v, list):
            return [t for t in v if t and t.strip()]
        return []

    @model_validator(mode="after")
    def merge_single_token(self) -> Settings:
        """Ensure github_token is included in github_tokens list."""
        if self.github_token and self.github_token not in self.github_tokens:
            self.github_tokens.insert(0, self.github_token)
        return self


def get_settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# Profile System
# ---------------------------------------------------------------------------

class ProfileConfig:
    """Validated profile structure. Fields match what the code actually reads."""
    # Not a Pydantic model to avoid breaking existing YAML profiles
    # that may have extra fields. Validation is opt-in via load_profile().
    pass


def _find_profiles_dir() -> Path:
    cwd = Path.cwd() / "profiles"
    if cwd.exists():
        return cwd
    pkg = Path(__file__).parent.parent.parent / "profiles"
    if pkg.exists():
        return pkg
    return cwd


def list_profiles() -> list[dict[str, str]]:
    profiles_dir = _find_profiles_dir()
    results = []
    for yaml_file in sorted(profiles_dir.rglob("*.yaml")):
        try:
            data = _load_yaml(yaml_file)
            results.append({
                "name": data.get("name", yaml_file.stem),
                "file": str(yaml_file.relative_to(profiles_dir)),
                "description": data.get("description", ""),
            })
        except Exception:
            pass
    return results


def load_profile(name: str) -> dict:
    profiles_dir = _find_profiles_dir()
    for candidate in [
        profiles_dir / f"{name}.yaml",
        profiles_dir / "examples" / f"{name}.yaml",
    ]:
        if candidate.exists():
            profile = _load_yaml(candidate)
            _validate_profile_weights(profile)
            return profile
    raise FileNotFoundError(f"Profile '{name}' not found in {profiles_dir}")


def _validate_profile_weights(profile: dict) -> None:
    """Warn if scoring weights don't sum to 1.0 and normalize them."""
    weights = profile.get("scoring_weights")
    if not weights:
        return
    total = sum(weights.values())
    if abs(total - 1.0) > 0.01:
        logger.warning("Profile weights sum to %.2f, not 1.0. Normalizing.", total)
        profile["scoring_weights"] = {k: v / total for k, v in weights.items()}


_MERGE_MAP = {
    "preferred_languages": ("preferred_languages", []),
    "preferred_frameworks": ("preferred_frameworks", []),
    "deployment_preference": ("deployment_model", None),
    "maturity_preference": ("maturity_preference", "any"),
    "community_size_preference": ("community_size_preference", "any"),
}


def merge_profile_with_requirements(profile: dict, reqs) -> None:
    """Merge profile defaults into requirements. Document values take precedence."""
    # Simple fields: profile is default only if reqs has default/empty value
    for profile_key, (reqs_attr, default_val) in _MERGE_MAP.items():
        profile_val = profile.get(profile_key)
        if not profile_val:
            continue
        current = getattr(reqs, reqs_attr, default_val)
        if current == default_val or (isinstance(current, list) and not current):
            setattr(reqs, reqs_attr, profile_val)

    # Domains: profile only if PRD extracted none
    if not reqs.domains and profile.get("domains_of_interest"):
        reqs.domains = profile["domains_of_interest"]


def _load_yaml(path: Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
