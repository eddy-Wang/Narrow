from __future__ import annotations

import json
import os
from typing import Any

from shopping_agent.understanding.prompts import DEEPSEEK_SYSTEM_PROMPT
from shopping_agent.understanding.state_patch import StatePatch


class DeepSeekInvalidResponse(Exception):
    """The provider replied, but its content was not a valid StatePatch."""


def _is_transient_provider_error(exc: Exception) -> bool:
    """Return whether a provider failure is safe to retry once."""

    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code == 429 or isinstance(status_code, int) and status_code >= 500:
        return True
    return type(exc).__name__ in {
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "RateLimitError",
    }


def is_configured() -> bool:
    enabled = os.getenv("SHOPPING_AGENT_ENABLE_LLM", "false").strip().casefold() in {
        "1", "true", "yes", "on",
    }
    if enabled and not os.getenv("DEEPSEEK_API_KEY", "").strip():
        raise RuntimeError("Online mode requires DEEPSEEK_API_KEY; offline fallback is disabled")
    return enabled


def request_state_patch(payload: dict[str, Any]) -> tuple[StatePatch, dict[str, int]]:
    """Call DeepSeek's OpenAI-compatible JSON endpoint."""

    from openai import OpenAI

    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    request = {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "messages": [
            {"role": "system", "content": DEEPSEEK_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Return the JSON state patch for:\n"
                + json.dumps(payload, ensure_ascii=False),
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 800,
        "stream": False,
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    response = None
    for attempt in range(2):
        try:
            response = client.chat.completions.create(**request)
            break
        except Exception as exc:  # noqa: BLE001 - normalize provider SDK failures
            if attempt == 1 or not _is_transient_provider_error(exc):
                raise
    if response is None:  # pragma: no cover - defensive guard
        raise RuntimeError("DeepSeek request failed without a response")

    try:
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("response content is empty or not text")
        patch = StatePatch.model_validate_json(content)
    except Exception as exc:
        raise DeepSeekInvalidResponse("DeepSeek returned an invalid StatePatch") from exc

    usage = getattr(response, "usage", None)
    return patch, {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
    }


def request_dialogue_decision(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Request one structured dialogue-policy decision from DeepSeek."""

    from openai import OpenAI

    from shopping_agent.dialogue.prompts import DIALOGUE_DECISION_SYSTEM_PROMPT

    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    request = {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "messages": [
            {"role": "system", "content": DIALOGUE_DECISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Return the JSON dialogue decision for:\n"
                + json.dumps(payload, ensure_ascii=False),
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 500,
        "stream": False,
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    response = None
    for attempt in range(2):
        try:
            response = client.chat.completions.create(**request)
            break
        except Exception as exc:  # noqa: BLE001
            if attempt == 1 or not _is_transient_provider_error(exc):
                raise
    if response is None:  # pragma: no cover
        raise RuntimeError("DeepSeek request failed without a response")
    try:
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("response content is empty or not text")
        result = json.loads(content)
        if not isinstance(result, dict):
            raise TypeError("dialogue decision is not an object")
    except Exception as exc:
        raise DeepSeekInvalidResponse("DeepSeek returned an invalid dialogue decision") from exc
    usage = getattr(response, "usage", None)
    return result, {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
    }
