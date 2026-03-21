"""Tests for document parser — LLM mocked."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from repofit.models import ParsedRequirements
from repofit.parser import parse_document

SAMPLE_LLM_RESPONSE = {
    "project_name": "AI Agent Platform",
    "project_summary": "An AI agent orchestration platform for creating and managing autonomous agents.",
    "primary_keywords": ["AI agents", "LangGraph", "multi-agent", "orchestration", "tool calling"],
    "secondary_keywords": ["LLM", "RAG", "FastAPI", "workflow"],
    "negative_keywords": ["blockchain", "crypto"],
    "preferred_languages": ["Python", "TypeScript"],
    "preferred_frameworks": ["FastAPI", "LangGraph"],
    "deployment_model": "on-premise",
    "domains": ["AI Agents and Orchestration", "LLM Apps and RAG"],
    "must_have": ["REST API", "Multi-agent collaboration", "Tool calling"],
    "nice_to_have": ["Visual workflow builder", "Plugin system"],
    "deal_breakers": ["GPL license", "No activity in 12 months"],
    "maturity_preference": "production-ready",
    "community_size_preference": "large",
}


def test_parse_document_returns_parsed_requirements(tmp_path: Path):
    """Parser should return valid ParsedRequirements from mocked LLM."""
    doc = tmp_path / "test.md"
    doc.write_text("# Test PRD\nBuild an AI agent platform.", encoding="utf-8")

    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = SAMPLE_LLM_RESPONSE

    result = parse_document(doc, mock_llm)

    assert isinstance(result, ParsedRequirements)
    assert result.project_name == "AI Agent Platform"
    assert "AI agents" in result.primary_keywords
    assert len(result.primary_keywords) == 5
    assert result.deployment_model == "on-premise"
    assert result.maturity_preference == "production-ready"


def test_parse_document_calls_llm_with_content(tmp_path: Path):
    """Parser should pass document content to LLM."""
    doc = tmp_path / "test.md"
    doc.write_text("# My Project\nSome requirements here.", encoding="utf-8")

    mock_llm = MagicMock()
    mock_llm.complete_json.return_value = SAMPLE_LLM_RESPONSE

    parse_document(doc, mock_llm)

    mock_llm.complete_json.assert_called_once()
    args = mock_llm.complete_json.call_args
    assert "My Project" in args[0][1]  # user prompt contains doc content


def test_parse_document_empty_file_raises(tmp_path: Path):
    """Parser should raise on empty input file."""
    doc = tmp_path / "empty.md"
    doc.write_text("", encoding="utf-8")

    mock_llm = MagicMock()

    try:
        parse_document(doc, mock_llm)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "empty" in str(e).lower()


def test_parsed_requirements_defaults():
    """ParsedRequirements should have sensible defaults."""
    reqs = ParsedRequirements(project_name="Test", project_summary="Test project")
    assert reqs.preferred_languages == []
    assert reqs.maturity_preference == "any"
    assert reqs.community_size_preference == "any"
    assert reqs.deployment_model is None
