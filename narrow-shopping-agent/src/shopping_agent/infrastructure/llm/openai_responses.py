from __future__ import annotations

import json
import os
from typing import Any

from shopping_agent.understanding.prompts import INTENT_SYSTEM_PROMPT
from shopping_agent.understanding.state_patch import StatePatch, normalize_raw_state_patch


class OpenAIInvalidResponse(Exception):
    """The OpenAI response could not be validated against the requested contract."""

    def __init__(self, message: str, *, kind: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind


def _is_transient_provider_error(exc: Exception) -> bool:
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


def _usage_dict(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    return {
        "prompt_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "output_tokens", 0) or 0),
    }


def _sum_usage(*parts: dict[str, int]) -> dict[str, int]:
    return {
        "prompt_tokens": sum(int(part.get("prompt_tokens", 0)) for part in parts),
        "completion_tokens": sum(int(part.get("completion_tokens", 0)) for part in parts),
    }


def _client() -> Any:
    from openai import OpenAI

    return OpenAI(api_key=os.getenv("OPENAI_API_KEY", "").strip())


def _responses_request(
    *,
    instructions: str,
    input_text: str,
    schema_name: str,
    schema: dict[str, Any],
    max_output_tokens: int,
) -> tuple[str, dict[str, int]]:
    client = _client()
    request = {
        "model": os.getenv("OPENAI_MODEL", "gpt-5.5"),
        "instructions": instructions,
        "input": input_text,
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": schema,
                "strict": False,
            },
            "verbosity": "low",
        },
        "reasoning": {
            "effort": os.getenv("OPENAI_REASONING_EFFORT", "low"),
        },
        "max_output_tokens": max_output_tokens,
        "store": False,
    }
    response = None
    for attempt in range(2):
        try:
            response = client.responses.create(**request)
            break
        except Exception as exc:  # noqa: BLE001 - normalize provider failures
            if attempt == 1 or not _is_transient_provider_error(exc):
                raise
    if response is None:  # pragma: no cover
        raise RuntimeError("OpenAI request failed without a response")
    content = getattr(response, "output_text", None)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("OpenAI response output_text is empty")
    return content, _usage_dict(response)


def _repair_once(
    *,
    instructions: str,
    original_input: str,
    invalid_content: str,
    error_message: str,
    schema_name: str,
    schema: dict[str, Any],
    max_output_tokens: int,
) -> tuple[str, dict[str, int]]:
    return _responses_request(
        instructions=instructions,
        input_text=(
            original_input
            + "\n\nThe previous response was invalid:\n"
            + invalid_content
            + "\n\nValidation error:\n"
            + error_message
            + "\nReturn a corrected object only. Preserve values that were already valid."
        ),
        schema_name=schema_name,
        schema=schema,
        max_output_tokens=max_output_tokens,
    )


def request_state_patch(payload: dict[str, Any]) -> tuple[StatePatch, dict[str, int]]:
    input_text = "Return the JSON state patch for:\n" + json.dumps(payload, ensure_ascii=False)
    schema = StatePatch.model_json_schema()
    try:
        content, usage = _responses_request(
            instructions=INTENT_SYSTEM_PROMPT,
            input_text=input_text,
            schema_name="shopping_state_patch",
            schema=schema,
            max_output_tokens=1000,
        )
    except Exception as exc:
        raise OpenAIInvalidResponse("OpenAI returned no valid StatePatch", kind="intent") from exc

    repair_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    try:
        raw = json.loads(content)
        patch = StatePatch.model_validate(normalize_raw_state_patch(raw))
    except Exception as first_exc:
        try:
            repaired, repair_usage = _repair_once(
                instructions=INTENT_SYSTEM_PROMPT,
                original_input=input_text,
                invalid_content=content,
                error_message=str(first_exc),
                schema_name="shopping_state_patch_repair",
                schema=schema,
                max_output_tokens=1000,
            )
            patch = StatePatch.model_validate(normalize_raw_state_patch(json.loads(repaired)))
        except Exception as repair_exc:
            raise OpenAIInvalidResponse(
                "OpenAI returned an invalid StatePatch after one repair attempt",
                kind="intent",
            ) from repair_exc
    return patch, _sum_usage(usage, repair_usage)


_DIALOGUE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["ask", "recommend", "confirm", "end"]},
        "ask_attribute": {
            "type": ["string", "null"],
            "enum": [
                "category", "material", "color", "size", "style", "brand",
                "budget", "feature", "use_case", "other", None,
            ],
        },
        "message": {"type": "string", "maxLength": 1000},
        "reason": {"type": "string", "maxLength": 300},
    },
    "required": ["action", "ask_attribute", "message", "reason"],
    "additionalProperties": False,
}


def request_dialogue_decision(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    from shopping_agent.dialogue.prompts import DIALOGUE_DECISION_SYSTEM_PROMPT

    input_text = "Return the JSON dialogue decision for:\n" + json.dumps(payload, ensure_ascii=False)
    try:
        content, usage = _responses_request(
            instructions=DIALOGUE_DECISION_SYSTEM_PROMPT,
            input_text=input_text,
            schema_name="shopping_dialogue_decision",
            schema=_DIALOGUE_SCHEMA,
            max_output_tokens=700,
        )
        result = json.loads(content)
        if not isinstance(result, dict):
            raise TypeError("dialogue decision is not an object")
        return result, {**usage, "repair_attempts": 0}
    except Exception as first_exc:
        invalid_content = locals().get("content", "")
        if not invalid_content:
            raise OpenAIInvalidResponse(
                "OpenAI returned no valid dialogue decision", kind="dialogue",
            ) from first_exc
        try:
            repaired, repair_usage = _repair_once(
                instructions=DIALOGUE_DECISION_SYSTEM_PROMPT,
                original_input=input_text,
                invalid_content=invalid_content,
                error_message=str(first_exc),
                schema_name="shopping_dialogue_decision_repair",
                schema=_DIALOGUE_SCHEMA,
                max_output_tokens=700,
            )
            result = json.loads(repaired)
            if not isinstance(result, dict):
                raise TypeError("dialogue decision is not an object")
            return result, {**_sum_usage(usage, repair_usage), "repair_attempts": 1}
        except Exception as repair_exc:
            raise OpenAIInvalidResponse(
                "OpenAI returned an invalid dialogue decision after one repair attempt",
                kind="dialogue",
            ) from repair_exc


def repair_dialogue_decision(
    payload: dict[str, Any],
    invalid_result: dict[str, Any],
    error_message: str,
) -> tuple[dict[str, Any], dict[str, int]]:
    from shopping_agent.dialogue.prompts import DIALOGUE_DECISION_SYSTEM_PROMPT

    original_input = "Return the JSON dialogue decision for:\n" + json.dumps(
        payload, ensure_ascii=False,
    )
    try:
        repaired, usage = _repair_once(
            instructions=DIALOGUE_DECISION_SYSTEM_PROMPT,
            original_input=original_input,
            invalid_content=json.dumps(invalid_result, ensure_ascii=False),
            error_message=error_message,
            schema_name="shopping_dialogue_policy_repair",
            schema=_DIALOGUE_SCHEMA,
            max_output_tokens=700,
        )
        result = json.loads(repaired)
        if not isinstance(result, dict):
            raise TypeError("dialogue decision is not an object")
        return result, usage
    except Exception as exc:
        raise OpenAIInvalidResponse(
            "OpenAI returned an invalid dialogue decision after one repair attempt",
            kind="dialogue",
        ) from exc
