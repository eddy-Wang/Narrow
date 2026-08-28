from __future__ import annotations

import json
import os
from typing import Any

from shopping_agent.understanding.prompts import DEEPSEEK_SYSTEM_PROMPT
from shopping_agent.understanding.state_patch import StatePatch


def is_configured() -> bool:
    enabled = os.getenv("SHOPPING_AGENT_ENABLE_LLM", "false").strip().casefold() in {
        "1", "true", "yes", "on",
    }
    return enabled and bool(os.getenv("DEEPSEEK_API_KEY", "").strip())


def request_state_patch(payload: dict[str, Any]) -> tuple[StatePatch, dict[str, int]]:
    """Call DeepSeek's OpenAI-compatible JSON endpoint."""

    from openai import OpenAI

    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    response = client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        messages=[
            {"role": "system", "content": DEEPSEEK_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Return the JSON state patch for:\n"
                + json.dumps(payload, ensure_ascii=False),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=800,
        stream=False,
        extra_body={"thinking": {"type": "disabled"}},
    )
    content = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    return StatePatch.model_validate_json(content), {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
    }
