"""Thin LLM client over OpenRouter (dev tier) and Anthropic (eval tier)."""
import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from agent.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    raw: dict[str, Any]


class LLMClient:
    """Calls OpenRouter in dev mode, Anthropic in eval mode.

    `tier="dev"` uses OpenRouter with a configurable model (cheap). Used for Days 1-4.
    `tier="eval"` uses Anthropic Claude directly. Used for the sealed held-out run only.
    """

    def __init__(self, tier: str = "dev") -> None:
        self.settings = get_settings()
        self.tier = tier

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> LLMResponse:
        if self.tier == "dev":
            return self._openrouter(system, user, max_tokens=max_tokens, temperature=temperature)
        elif self.tier == "eval":
            return self._anthropic(system, user, max_tokens=max_tokens, temperature=temperature)
        else:
            raise ValueError(f"unknown tier {self.tier}")

    def _openrouter(
        self, system: str, user: str, *, max_tokens: int, temperature: float
    ) -> LLMResponse:
        if not self.settings.OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY unset")
        headers = {
            "Authorization": f"Bearer {self.settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.settings.DEV_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=body,
            timeout=60.0,
        )
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return LLMResponse(
            text=text,
            model=data.get("model", self.settings.DEV_MODEL),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )

    def _anthropic(
        self, system: str, user: str, *, max_tokens: int, temperature: float
    ) -> LLMResponse:
        if not self.settings.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY unset")
        from anthropic import Anthropic

        client = Anthropic(api_key=self.settings.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=self.settings.EVAL_MODEL,
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = "".join(block.text for block in resp.content if hasattr(block, "text"))
        return LLMResponse(
            text=text,
            model=resp.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            raw=resp.model_dump(),
        )
