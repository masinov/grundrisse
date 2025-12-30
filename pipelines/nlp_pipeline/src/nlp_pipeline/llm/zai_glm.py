from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

import httpx

from nlp_pipeline.llm.client import LLMResponse
from nlp_pipeline.settings import settings


class ZaiGlmError(RuntimeError):
    pass


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """
    Best-effort extraction when providers wrap JSON in additional text.
    Returns the first parsable JSON object found, else None.
    """
    text = text.strip()
    if not text:
        return None

    # Fast path: exact JSON.
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    # Heuristic: find first {...} span and try parsing.
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        else:
            if ch == '"':
                in_str = True
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        obj = json.loads(candidate)
                        return obj if isinstance(obj, dict) else None
                    except Exception:
                        return None
    return None


@dataclass
class ZaiGlmClient:
    """
    Z.ai GLM client using the OpenAI-compatible chat completions endpoint.
    Docs summary provided by user:
    - POST {base_url}/chat/completions
    - Authorization: Bearer <key>
    - model: "glm-4.7"
    """

    api_key: str
    base_url: str = settings.zai_base_url
    model: str = settings.zai_model
    timeout_s: float = settings.zai_timeout_s
    http2: bool = True
    _client: httpx.Client | None = field(default=None, init=False, repr=False)

    def __enter__(self) -> "ZaiGlmClient":
        if self._client is None:
            timeout = httpx.Timeout(
                self.timeout_s, connect=self.timeout_s, read=self.timeout_s, write=self.timeout_s
            )
            self._client = httpx.Client(timeout=timeout, http2=self.http2)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def complete_json(self, *, prompt: str, schema: dict[str, Any]) -> LLMResponse:
        """
        Returns best-effort JSON. If the provider supports JSON mode, we request it; otherwise we still
        parse JSON from the returned content and rely on strict schema validation + retry upstream.
        """
        base = self.base_url.rstrip("/")
        # Allow callers to set either the API prefix or the full endpoint.
        url = base if base.endswith("/chat/completions") else base + "/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Return only valid JSON that conforms to the provided schema."},
                {"role": "user", "content": prompt},
            ],
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
        }

        # When doing structured extraction we want the "final" JSON in `message.content`.
        # Some Z.ai responses put only chain-of-thought into `reasoning_content` with empty `content`,
        # especially when thinking is enabled. So we disable thinking by default for this call.
        if settings.zai_thinking_enabled and not settings.zai_response_format_json:
            payload["thinking"] = {"type": "enabled"}
        elif not settings.zai_thinking_enabled:
            # Best-effort request to suppress thinking in outputs.
            payload["thinking"] = {"type": "disabled"}

        # OpenAI-style hint; if ignored, we still validate after parsing.
        if settings.zai_response_format_json:
            payload["response_format"] = {"type": "json_object"}

        last_exc: Exception | None = None
        for attempt in range(1, 4):
            started = time.time()
            try:
                client = self._client
                if client is None:
                    timeout = httpx.Timeout(
                        self.timeout_s,
                        connect=self.timeout_s,
                        read=self.timeout_s,
                        write=self.timeout_s,
                    )
                    client = httpx.Client(timeout=timeout, http2=self.http2)
                resp = client.post(url, headers=headers, json=payload)
                elapsed = time.time() - started
                last_exc = None
            except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                last_exc = exc
                # basic exponential backoff
                time.sleep(1.5 * attempt)
                continue

            if resp.status_code == 429:
                # Rate limit / quota shape; backoff and retry.
                time.sleep(1.5 * attempt)
                continue

            if resp.status_code >= 400:
                hint = ""
                try:
                    err = resp.json().get("error") or {}
                    if isinstance(err, dict) and err.get("code") == "1113":
                        hint = (
                            " (Z.ai reports insufficient balance/resource package; if your subscription is for the "
                            '"coding" resource, set GRUNDRISSE_ZAI_BASE_URL=https://api.z.ai/api/coding/paas/v4)'
                        )
                except Exception:
                    pass
                raise ZaiGlmError(f"Z.ai error {resp.status_code} from {url}: {resp.text[:500]}{hint}")

            break
        else:
            raise ZaiGlmError(f"Z.ai request timed out after retries to {url}: {last_exc}")

        data = resp.json()
        choice0 = (data.get("choices") or [{}])[0]
        message = choice0.get("message") or {}
        content = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""

        # Prefer `content`, but fall back if provider left it empty.
        chosen_text = content or reasoning

        parsed = _extract_json_object(chosen_text)

        # If provider ignored JSON mode and returned non-JSON, keep raw_text and let caller retry.

        usage = data.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")

        # Some providers include cost; if not present, keep None.
        cost_usd = None
        meta = data.get("meta") or {}
        if isinstance(meta, dict) and "cost_usd" in meta:
            cost_usd = meta.get("cost_usd")

        model_name = data.get("model") or self.model
        raw_hash = sha256(chosen_text.encode("utf-8")).hexdigest()
        _ = (elapsed, raw_hash)  # reserved for future logging/telemetry

        return LLMResponse(
            raw_text=chosen_text,
            json=parsed,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
        )
