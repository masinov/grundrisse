from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class LLMResponse:
    raw_text: str
    json: dict[str, Any] | None
    model_name: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None


class LLMClient(Protocol):
    def complete_json(self, *, prompt: str, schema: dict[str, Any]) -> LLMResponse: ...

