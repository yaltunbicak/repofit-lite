"""Stage 1: LLM-powered document parsing with safety checks."""

from __future__ import annotations

import logging
from pathlib import Path

from repofit.llm_client import LLMClient
from repofit.models import ParsedRequirements

logger = logging.getLogger("repofit")

MAX_FILE_SIZE_BYTES = 512 * 1024  # 512 KB (~128K tokens at 4 chars/token)
ALLOWED_EXTENSIONS = {".md", ".txt", ".rst", ".adoc", ".tex", ".html", ".pdf"}

PARSER_SYSTEM_PROMPT = """
You are a technical analyst. Given a project document (PRD, architecture doc,
or description), extract structured requirements for finding matching
open-source repositories.

Be specific with keywords. Prefer technical terms over generic ones.
For example: "LangGraph" over "AI", "FastAPI" over "web framework".

Extract both what the project NEEDS and what it should AVOID.

If the document mentions specific technologies, frameworks, or patterns,
include those as primary_keywords.

Output valid JSON matching this exact schema:
{
  "project_name": "string",
  "project_summary": "2-3 sentence summary",
  "primary_keywords": ["max 10 most specific terms"],
  "secondary_keywords": ["max 15 broader related terms"],
  "negative_keywords": ["terms to exclude"],
  "preferred_languages": ["e.g. Python, TypeScript, Go"],
  "preferred_frameworks": ["e.g. FastAPI, NestJS, React"],
  "deployment_model": "on-premise | cloud | hybrid | any | null",
  "domains": ["e.g. AI Agents, Workflow Automation"],
  "must_have": ["required features"],
  "nice_to_have": ["optional features"],
  "deal_breakers": ["disqualifying traits"],
  "maturity_preference": "production-ready | growing | any",
  "community_size_preference": "large | medium | small-ok | any"
}

Output valid JSON matching the schema. Nothing else.
"""


def _check_file_safety(file_path: Path) -> None:
    """Pre-flight checks: file size, extension, binary detection."""
    # Extension check
    ext = file_path.suffix.lower()
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: {ext}. "
            f"Supported: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Size check
    size = file_path.stat().st_size
    if size > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"File too large: {size / 1024:.0f} KB (max {MAX_FILE_SIZE_BYTES // 1024} KB). "
            f"Use a shorter document or split into sections."
        )

    # Binary detection (null byte check on first 8KB)
    with open(file_path, "rb") as f:
        sample = f.read(8192)
        if b"\x00" in sample:
            raise ValueError(
                f"File appears to be binary: {file_path.name}. "
                f"Please provide a text file (.md, .txt, .rst)."
            )


def parse_document(file_path: Path, llm: LLMClient) -> ParsedRequirements:
    """Read a document and extract structured requirements via LLM."""
    logger.debug("Reading document: %s", file_path)

    _check_file_safety(file_path)

    content = file_path.read_text(encoding="utf-8")

    if not content.strip():
        raise ValueError(f"Input file is empty: {file_path}")

    user_prompt = f"Analyze the following project document and extract requirements:\n\n---\n{content}\n---"

    data = llm.complete_json(PARSER_SYSTEM_PROMPT, user_prompt)

    return ParsedRequirements.model_validate(data)
