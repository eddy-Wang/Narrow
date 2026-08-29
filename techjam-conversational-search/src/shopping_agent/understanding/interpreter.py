from __future__ import annotations

import re
from typing import Any, Literal

from shopping_agent.domain.schemas import Constraint
from shopping_agent.infrastructure.llm.deepseek import (
    DeepSeekInvalidResponse,
    is_configured,
    request_state_patch,
)
from shopping_agent.understanding.fallback_parser import (
    rule_state_patch,
    semantic_fallback_patch,
)
from shopping_agent.understanding.prompts import DEEPSEEK_SYSTEM_PROMPT
from shopping_agent.understanding.state_patch import (
    StatePatch,
    apply_state_patch,
    validate_state_patch,
)


def _detect_language(message: str) -> Literal["zh", "en", "other"]:
    if re.search(r"[\u3400-\u9fff]", message):
        return "zh"
    if re.search(r"[a-z]", message, re.IGNORECASE):
        return "en"
    return "other"


def _fallback_semantic_query(
    message: str,
    category: str | None,
    constraints: list[Constraint],
) -> str:
    positive = [
        str(item.value)
        for item in constraints
        if item.operator != "not_contains" and item.field != "budget"
    ]
    parts = [category or "", *positive]
    if not any(parts):
        cleaned = re.sub(r"\s+", " ", message).strip()
        return cleaned[:500]
    return " ".join(
        dict.fromkeys(part.strip() for part in parts if part.strip())
    )[:500]


OVERRIDE_SENSITIVE_FIELDS = {"color", "size", "style", "brand", "use_case"}
ADDITIVE_MARKERS = (" also ", " as well", " either ", " both ", " or ")
CORRECTION_MARKERS = ("make it", "switch to", "change to", "rather", "instead")
QUESTION_ANSWER_FIELDS = {"material", "color", "size", "style", "brand", "feature", "use_case"}
QUESTION_REQUEST_MARKERS = (
    "more option", "show more", "something else", "not sure", "don't know",
    "do not know", "no preference", "doesn't matter", "does not matter",
)


def _should_implicitly_replace(
    message: str,
    active_constraints: list[dict[str, Any]],
    incoming: list[Constraint],
) -> bool:
    """Recognize a bounded same-field correction without erasing additive values."""

    lowered = f" {message.casefold()} "
    if any(marker in lowered for marker in ADDITIVE_MARKERS):
        return False

    active_by_field: dict[str, set[str]] = {}
    for value in active_constraints:
        if value.get("operator") == "not_contains":
            continue
        field = str(value.get("field", ""))
        active_by_field.setdefault(field, set()).add(
            str(value.get("value", "")).casefold()
        )

    incoming_by_field: dict[str, set[str]] = {}
    for item in incoming:
        if item.operator == "not_contains" or item.field not in OVERRIDE_SENSITIVE_FIELDS:
            continue
        incoming_by_field.setdefault(item.field, set()).add(str(item.value).casefold())

    conflicting_fields = [
        field
        for field, values in incoming_by_field.items()
        if len(values) == 1
        and active_by_field.get(field)
        and values.isdisjoint(active_by_field[field])
    ]
    if not conflicting_fields:
        return False
    concise_reply = len(re.findall(r"[a-z0-9]+", lowered)) <= 5
    return concise_reply or any(marker in lowered for marker in CORRECTION_MARKERS)


def _question_answer_constraint(
    message: str,
    turn: int,
    previous_ask_attribute: str | None,
    previous_question_options: list[dict[str, Any]],
    patch: StatePatch,
) -> Constraint | None:
    """Interpret a concise free-text reply in the context of our last question."""

    if (
        previous_ask_attribute not in QUESTION_ANSWER_FIELDS
        or previous_ask_attribute in patch.no_preference
        or any(item.field == previous_ask_attribute for item in patch.constraints)
    ):
        return None
    lowered = message.casefold().strip()
    if not lowered or any(marker in lowered for marker in QUESTION_REQUEST_MARKERS):
        return None

    value = ""
    for option in previous_question_options:
        candidate = str(option.get("value", "")).strip()
        if candidate and candidate.casefold() in lowered:
            value = candidate
            break
    if not value:
        field_pattern = previous_ask_attribute.replace("_", r"[ _-]")
        explicit = re.search(
            rf"\b{field_pattern}\b\s*(?:is|would be|:)?\s*([a-z0-9][a-z0-9&' -]{{0,50}})",
            message,
            re.IGNORECASE,
        )
        if explicit:
            value = explicit.group(1).strip(" .,!?")
    if not value and len(re.findall(r"[a-z0-9]+", lowered)) <= 4:
        value = re.sub(
            r"^(?:i(?:'d| would)?\s+)?(?:prefer|want|like|choose)\s+",
            "",
            message.strip(),
            flags=re.IGNORECASE,
        ).strip(" .,!?")
    if not value:
        return None
    return Constraint(
        field=previous_ask_attribute,  # type: ignore[arg-type]
        value=value,
        strength="soft",
        confidence=0.88,
        source_turn=turn,
    )


def _local_result(
    message: str,
    turn: int,
    rule_patch: StatePatch,
    current_category: str,
    *,
    failure_reason: str | None = None,
    active_constraints: list[dict[str, Any]] | None = None,
    previous_ask_attribute: str | None = None,
    previous_question_options: list[dict[str, Any]] | None = None,
) -> tuple[StatePatch, dict[str, int]]:
    fallback = semantic_fallback_patch(
        message,
        turn,
        rule_patch,
        current_category=current_category,
    )
    contextual = _question_answer_constraint(
        message,
        turn,
        previous_ask_attribute,
        previous_question_options or [],
        fallback,
    )
    if contextual is not None:
        fallback.constraints.append(contextual)
        fallback.fallback_reasons = [
            reason for reason in fallback.fallback_reasons if reason != "no_structured_signal"
        ]
        fallback.fallback_reasons.append("previous_question_context")
        fallback.confidence = max(fallback.confidence, 0.88)
        fallback = validate_state_patch(fallback)
    if failure_reason:
        fallback.fallback_reasons = list(dict.fromkeys([
            *fallback.fallback_reasons,
            failure_reason,
        ]))
    if fallback.action != "replace" and _should_implicitly_replace(
        message,
        active_constraints or [],
        fallback.constraints,
    ):
        fallback.action = "replace"
        fallback.fallback_reasons = list(dict.fromkeys([
            *fallback.fallback_reasons,
            "implicit_override_heuristic",
        ]))
    fallback.semantic_query = _fallback_semantic_query(
        message,
        fallback.category,
        fallback.constraints,
    )
    fallback.intent_summary = fallback.semantic_query
    fallback.language = _detect_language(message)
    return fallback, {"prompt_tokens": 0, "completion_tokens": 0}


def resolve_semantic_patch(
    message: str,
    turn: int,
    rule_patch: StatePatch,
    *,
    current_category: str = "",
    active_constraints: list[dict[str, Any]] | None = None,
    current_semantic_query: str = "",
    intent_summary: str = "",
    user_profile: dict[str, Any] | None = None,
    previous_ask_attribute: str | None = None,
    previous_question_options: list[dict[str, Any]] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
) -> tuple[StatePatch, dict[str, int]]:
    """Interpret every turn with the configured LLM, with deterministic fallback."""

    if not is_configured():
        return _local_result(
            message,
            turn,
            rule_patch,
            current_category,
            active_constraints=active_constraints,
            previous_ask_attribute=previous_ask_attribute,
            previous_question_options=previous_question_options,
        )

    payload = {
        "turn": turn,
        "current_category": current_category or None,
        "active_constraints": active_constraints or [],
        "current_semantic_query": current_semantic_query or None,
        "current_intent_summary": intent_summary or None,
        "user_profile": user_profile or {},
        "previous_question": {
            "ask_attribute": previous_ask_attribute,
            "options": previous_question_options or [],
        } if previous_ask_attribute else None,
        "recent_conversation": (conversation_history or [])[-8:],
        "user_message": message,
        "rule_patch": rule_patch.model_dump(mode="json"),
    }
    try:
        model_patch, usage = request_state_patch(payload)
        local_patch = semantic_fallback_patch(
            message,
            turn,
            rule_patch,
            current_category=current_category,
        )
        patch = StatePatch(
            action=model_patch.action,
            category=model_patch.category or local_patch.category,
            constraints=[*local_patch.constraints, *model_patch.constraints],
            remove_fields=[*local_patch.remove_fields, *model_patch.remove_fields],
            no_preference=[*local_patch.no_preference, *model_patch.no_preference],
            retire_soft=local_patch.retire_soft or model_patch.retire_soft,
            semantic_query=model_patch.semantic_query or _fallback_semantic_query(
                message,
                model_patch.category or local_patch.category,
                [*local_patch.constraints, *model_patch.constraints],
            ),
            intent_summary=model_patch.intent_summary or model_patch.semantic_query,
            language=model_patch.language or _detect_language(message),
            confidence=max(local_patch.confidence, model_patch.confidence),
            parser="deepseek",
            fallback_reasons=model_patch.fallback_reasons,
        )
        return validate_state_patch(patch), usage
    except DeepSeekInvalidResponse:
        return _local_result(
            message,
            turn,
            rule_patch,
            current_category,
            failure_reason="deepseek_invalid_response",
            active_constraints=active_constraints,
            previous_ask_attribute=previous_ask_attribute,
            previous_question_options=previous_question_options,
        )
    except Exception:  # noqa: BLE001 - provider failures degrade to deterministic parsing
        return _local_result(
            message,
            turn,
            rule_patch,
            current_category,
            failure_reason="deepseek_unavailable",
            active_constraints=active_constraints,
            previous_ask_attribute=previous_ask_attribute,
            previous_question_options=previous_question_options,
        )


__all__ = [
    "DEEPSEEK_SYSTEM_PROMPT",
    "StatePatch",
    "apply_state_patch",
    "resolve_semantic_patch",
    "rule_state_patch",
    "semantic_fallback_patch",
    "validate_state_patch",
]
