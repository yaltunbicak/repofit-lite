"""Multi-provider LLM abstraction (Gemini, Anthropic, OpenAI)."""

from __future__ import annotations

import json
import logging

from repofit.config import Settings

logger = logging.getLogger("repofit")

_SEED = 42


class LLMConfigurationError(Exception):
    """Raised when LLM provider is misconfigured (missing API key, etc.)."""


class LLMEmptyResponseError(Exception):
    """Raised when LLM returns empty or null response."""


class LLMClient:
    """Unified LLM client. Only the selected provider's SDK is initialized."""

    def __init__(self, settings: Settings) -> None:
        self.provider = settings.llm_provider
        self.model = settings.llm_model
        self.max_tokens = settings.llm_max_tokens
        self._client: object = None
        self._init_provider(settings)

    def _init_provider(self, settings: Settings) -> None:
        if self.provider == "gemini":
            if not settings.gemini_api_key:
                raise LLMConfigurationError(
                    "API key for provider 'gemini' is not set. "
                    "Set the GEMINI_API_KEY environment variable."
                )
            from google import genai
            self._client = genai.Client(api_key=settings.gemini_api_key)

        elif self.provider == "anthropic":
            if not settings.anthropic_api_key:
                raise LLMConfigurationError(
                    "API key for provider 'anthropic' is not set. "
                    "Set the ANTHROPIC_API_KEY environment variable."
                )
            import anthropic
            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        elif self.provider == "openai":
            if not settings.openai_api_key:
                raise LLMConfigurationError(
                    "API key for provider 'openai' is not set. "
                    "Set the OPENAI_API_KEY environment variable."
                )
            import openai
            self._client = openai.OpenAI(api_key=settings.openai_api_key)

        else:
            raise LLMConfigurationError(f"Unknown LLM provider: {self.provider}")

    def complete(self, system: str, user: str, json_mode: bool = True) -> str:
        """Send a prompt and return the text response."""
        logger.debug("LLM call [%s/%s] system=%d chars, user=%d chars",
                      self.provider, self.model, len(system), len(user))

        if self.provider == "gemini":
            return self._complete_gemini(system, user, json_mode)
        elif self.provider == "anthropic":
            return self._complete_anthropic(system, user, json_mode)
        elif self.provider == "openai":
            return self._complete_openai(system, user, json_mode)
        raise LLMConfigurationError(f"Unknown provider: {self.provider}")

    def _validate_text(self, text: str | None, provider: str) -> str:
        """Validate LLM response text is non-empty."""
        if not text or not text.strip():
            raise LLMEmptyResponseError(
                f"LLM ({provider}/{self.model}) returned empty response"
            )
        return text

    def _complete_gemini(self, system: str, user: str, json_mode: bool = True) -> str:
        from google.genai import types
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=self.max_tokens,
            temperature=0.0,
            seed=_SEED,
        )
        if json_mode:
            config.response_mime_type = "application/json"
        response = self._client.models.generate_content(
            model=self.model, contents=user, config=config,
        )
        return self._validate_text(response.text, "gemini")

    def _complete_anthropic(self, system: str, user: str, json_mode: bool = True) -> str:
        sys_prompt = system
        if json_mode:
            sys_prompt += (
                "\n\nIMPORTANT: You must respond with ONLY valid JSON. "
                "No markdown formatting, no code blocks, no explanation -- just raw JSON."
            )
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0.0,
            system=sys_prompt,
            messages=[{"role": "user", "content": user}],
        )
        if not response.content:
            raise LLMEmptyResponseError("Anthropic returned empty content list")
        return self._validate_text(response.content[0].text, "anthropic")

    def _complete_openai(self, system: str, user: str, json_mode: bool = True) -> str:
        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": 0.0,
            "seed": _SEED,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = self._client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content if response.choices else None
        return self._validate_text(text, "openai")

    def complete_json(self, system: str, user: str) -> dict | list:
        """Send a prompt and parse the JSON response. Retry once on parse failure."""
        raw = self.complete(system, user, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("JSON parse failed, retrying with stricter prompt")
            stricter = system + "\n\nYour previous response was not valid JSON. Return ONLY valid JSON."
            raw = self.complete(stricter, user, json_mode=True)
            return json.loads(raw)
