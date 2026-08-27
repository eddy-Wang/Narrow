from __future__ import annotations

import json
import os
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from shopping_agent.intent import COLORS, MATERIALS, classify_attribute, parse_message
from shopping_agent.schemas import Attribute, Constraint


class StatePatch(BaseModel):
    """A bounded semantic update; it cannot retrieve or recommend products."""

    action: Literal["add", "replace", "remove", "no_preference"] = "add"
    category: str | None = None
    constraints: list[Constraint] = Field(default_factory=list, max_length=20)
    remove_fields: list[Attribute] = Field(default_factory=list)
    no_preference: list[Attribute] = Field(default_factory=list)
    retire_soft: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    parser: Literal["rules", "fallback", "deepseek"] = "rules"
    fallback_reasons: list[str] = Field(default_factory=list)


PROTOCOL_MARKERS = (
    "i'm looking for",
    "a key requirement is:",
    "what matters is:",
    "what i need is:",
    "i don't have a preference for",
    "i don't have an additional preference for",
)

REFERENCE_MARKERS = (
    " it ", " that ", " those ", " them ", " one ", " ones ",
    "lighter", "shorter", "taller", "smaller", "larger",
)

CATEGORY_TERMS = {
    "boot": "boots",
    "boots": "boots",
    "shoe": "shoes",
    "shoes": "shoes",
    "sneaker": "sneakers",
    "sneakers": "sneakers",
    "jacket": "jackets",
    "coat": "coats",
    "dress": "dresses",
    "shirt": "shirts",
    "pants": "pants",
    "jeans": "jeans",
    "bag": "bags",
    "purse": "handbags",
    "belt": "belts",
    "watch": "watches",
}

STYLE_TERMS = {
    "formal": "formal",
    "dressy": "formal",
    "casual": "casual",
    "vintage": "vintage",
    "sporty": "sport",
    "athletic": "sport",
}

USE_CASE_TERMS = {
    "running": "running",
    "hiking": "hiking",
    "work": "work",
    "office": "work",
    "gym": "gym",
    "winter": "winter",
    "outdoor": "outdoor",
}

FEATURE_TERMS = {
    "waterproof": "waterproof",
    "water resistant": "water resistant",
    "breathable": "breathable",
    "lightweight": "lightweight",
    "lighter": "lightweight",
    "warm": "warm",
    "durable": "durable",
}


def _constraint(
    field: Attribute,
    value: str | float,
    turn: int,
    *,
    operator: str = "contains",
    strength: str = "soft",
    confidence: float = 0.8,
) -> Constraint:
    return Constraint(
        field=field,
        operator=operator,  # type: ignore[arg-type]
        value=value,
        strength=strength,  # type: ignore[arg-type]
        confidence=confidence,
        source_turn=turn,
    )


def rule_state_patch(message: str, turn: int) -> StatePatch:
    parsed = parse_message(message, turn)
    lowered = f" {message.casefold()} "
    reasons: list[str] = []
    protocol_language = any(marker in lowered for marker in PROTOCOL_MARKERS)
    structured_protocol = any(
        marker in lowered
        for marker in (
            "a key requirement is:", "what matters is:", "what i need is:",
            "i don't have a preference for", "i don't have an additional preference for",
        )
    )

    has_negative_language = bool(
        re.search(r"\b(?:not|no|avoid|without|don't want|do not want)\b", lowered)
    ) and "don't have a preference" not in lowered
    has_negative_constraint = any(item.operator == "not_contains" for item in parsed.constraints)
    if not structured_protocol and has_negative_language and not has_negative_constraint:
        reasons.append("unresolved_negation")

    if not structured_protocol and any(marker in lowered for marker in REFERENCE_MARKERS):
        reasons.append("reference_or_comparison")

    amounts = re.findall(r"\$\s*(\d+(?:\.\d+)?)", message)
    if not structured_protocol and (
        len(amounts) > 1
        or (amounts and any(marker in lowered for marker in ("if possible", "stretch", "unless")))
    ):
        reasons.append("conditional_budget")

    extracted = bool(parsed.category or parsed.constraints or parsed.no_preference or parsed.override)
    if protocol_language:
        confidence = 0.97
    elif extracted:
        confidence = 0.78
    else:
        confidence = 0.25
        reasons.append("no_structured_signal")
    if reasons:
        confidence = min(confidence, 0.55)

    return StatePatch(
        action="replace" if parsed.override else ("no_preference" if parsed.no_preference else "add"),
        category=parsed.category,
        constraints=parsed.constraints,
        no_preference=sorted(parsed.no_preference),
        retire_soft=parsed.override,
        confidence=confidence,
        parser="rules",
        fallback_reasons=list(dict.fromkeys(reasons)),
    )


def _negative_phrases(message: str) -> list[str]:
    cleaned = re.sub(r"\bdon't mind\b[^,.;]*", "", message, flags=re.IGNORECASE)
    pattern = re.compile(
        r"(?:don't want|do not want|avoid|without|not(?: that)?|no)\s+"
        r"(?:any\s+)?([a-z][a-z -]{1,35}?)(?=\s+(?:but|and|or)|[,.;!?]|$)",
        re.IGNORECASE,
    )
    return [match.group(1).strip() for match in pattern.finditer(cleaned)]


def semantic_fallback_patch(
    message: str,
    turn: int,
    rule_patch: StatePatch,
    *,
    current_category: str = "",
) -> StatePatch:
    """Deterministically enrich an uncertain rule patch.

    This is the local substitute for a future structured semantic model call.
    """

    lowered = message.casefold()
    constraints = list(rule_patch.constraints)
    negative_values = _negative_phrases(message)
    negative_text = " ".join(negative_values).casefold()

    for value in negative_values:
        normalized = "tall" if value in {"that tall", "tall"} else value
        constraints.append(_constraint(
            classify_attribute(normalized),
            normalized,
            turn,
            operator="not_contains",
            strength="hard",
            confidence=0.88,
        ))

    category = rule_patch.category
    for term, normalized in CATEGORY_TERMS.items():
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            if not any(term in value.casefold() for value in negative_values):
                category = normalized
                break
    category = category or current_category or None

    for material in MATERIALS:
        if re.search(rf"\b{re.escape(material)}\b", lowered) and material not in negative_text:
            constraints.append(_constraint("material", material, turn, confidence=0.9))
    for color in COLORS:
        if re.search(rf"\b{re.escape(color)}\b", lowered) and color not in negative_text:
            constraints.append(_constraint("color", color, turn, confidence=0.88))
    for term, normalized in STYLE_TERMS.items():
        if re.search(rf"\b{re.escape(term)}\b", lowered) and term not in negative_text:
            constraints.append(_constraint("style", normalized, turn, confidence=0.86))
    for term, normalized in USE_CASE_TERMS.items():
        if re.search(rf"\b{re.escape(term)}\b", lowered) and term not in negative_text:
            constraints.append(_constraint("use_case", normalized, turn, confidence=0.86))
    for term, normalized in FEATURE_TERMS.items():
        if term in lowered and term not in negative_text:
            constraints.append(_constraint("feature", normalized, turn, confidence=0.84))

    budget_matches = list(re.finditer(
        r"(?:under|below|up to|no more than|stretch to)\s*\$?\s*(\d+(?:\.\d+)?)",
        lowered,
    ))
    for match in budget_matches:
        prefix = match.group(0)
        soft = "if possible" in lowered and "stretch to" not in prefix
        constraints.append(_constraint(
            "budget",
            float(match.group(1)),
            turn,
            operator="lte",
            strength="soft" if soft else "hard",
            confidence=0.9,
        ))

    action = rule_patch.action
    retire_soft = rule_patch.retire_soft
    if any(marker in lowered for marker in ("actually", "instead", "forget ", "ignore ")):
        action = "replace"
        retire_soft = True

    return validate_state_patch(StatePatch(
        action=action,
        category=category,
        constraints=constraints,
        remove_fields=rule_patch.remove_fields,
        no_preference=rule_patch.no_preference,
        retire_soft=retire_soft,
        confidence=max(rule_patch.confidence, 0.78 if constraints or category else 0.4),
        parser="fallback",
        fallback_reasons=rule_patch.fallback_reasons,
    ))


DEEPSEEK_SYSTEM_PROMPT = """You extract a JSON state patch for a shopping search system.
Return one JSON object only. Never recommend products or invent identifiers.

Schema:
{
  "action": "add|replace|remove|no_preference",
  "category": "string or null",
  "constraints": [{
    "field": "category|material|color|size|style|brand|budget|feature|use_case|other",
    "operator": "contains|not_contains|eq|lte|gte",
    "value": "string or number",
    "strength": "hard|soft",
    "confidence": 0.0,
    "source_turn": 1
  }],
  "remove_fields": [],
  "no_preference": [],
  "retire_soft": false,
  "confidence": 0.0,
  "fallback_reasons": []
}

Extract every explicit constraint, including use case and occasion. Newest
explicit preferences override conflicting history. Negation must use
not_contains. Long-term profile preferences are never hard constraints.
"""


def _deepseek_enabled() -> bool:
    return os.getenv("SHOPPING_AGENT_ENABLE_LLM", "false").strip().casefold() in {
        "1", "true", "yes", "on",
    }


def resolve_semantic_patch(
    message: str,
    turn: int,
    rule_patch: StatePatch,
    *,
    current_category: str = "",
    active_constraints: list[dict[str, Any]] | None = None,
) -> tuple[StatePatch, dict[str, int]]:
    """Use DeepSeek only when explicitly enabled and configured; otherwise fallback."""

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not _deepseek_enabled() or not api_key:
        return semantic_fallback_patch(
            message,
            turn,
            rule_patch,
            current_category=current_category,
        ), {"prompt_tokens": 0, "completion_tokens": 0}

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        )
        payload = {
            "turn": turn,
            "current_category": current_category or None,
            "active_constraints": active_constraints or [],
            "user_message": message,
            "rule_patch": rule_patch.model_dump(mode="json"),
        }
        response = client.chat.completions.create(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            messages=[
                {"role": "system", "content": DEEPSEEK_SYSTEM_PROMPT},
                {"role": "user", "content": "Return the JSON state patch for:\n" + json.dumps(payload, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=800,
            stream=False,
            extra_body={"thinking": {"type": "disabled"}},
        )
        content = response.choices[0].message.content or ""
        model_patch = StatePatch.model_validate_json(content)
        local_patch = semantic_fallback_patch(
            message,
            turn,
            rule_patch,
            current_category=current_category,
        )
        # The provider adds semantic interpretation; deterministic extraction
        # remains a second source of evidence so a model omission cannot delete
        # obvious material, use-case, budget, or negation signals.
        patch = StatePatch(
            action=model_patch.action,
            category=model_patch.category or local_patch.category,
            constraints=[*local_patch.constraints, *model_patch.constraints],
            remove_fields=[*local_patch.remove_fields, *model_patch.remove_fields],
            no_preference=[*local_patch.no_preference, *model_patch.no_preference],
            retire_soft=local_patch.retire_soft or model_patch.retire_soft,
            confidence=max(local_patch.confidence, model_patch.confidence),
            parser="deepseek",
            fallback_reasons=model_patch.fallback_reasons,
        )
        usage = getattr(response, "usage", None)
        return validate_state_patch(patch), {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        }
    except Exception:
        fallback = semantic_fallback_patch(
            message,
            turn,
            rule_patch,
            current_category=current_category,
        )
        fallback.fallback_reasons = list(dict.fromkeys([
            *fallback.fallback_reasons,
            "deepseek_unavailable",
        ]))
        return fallback, {"prompt_tokens": 0, "completion_tokens": 0}


def validate_state_patch(patch: StatePatch) -> StatePatch:
    """Normalize, deduplicate, and resolve positive/negative collisions."""

    deduplicated: dict[tuple[str, str, str], Constraint] = {}
    for item in patch.constraints:
        if isinstance(item.value, str):
            item.value = re.sub(r"\s+", " ", item.value).strip(" .;,\t\n")
            if not item.value:
                continue
        elif item.field == "budget" and float(item.value) <= 0:
            continue
        key = (item.field, item.operator, str(item.value).casefold())
        deduplicated[key] = item

    negatives = {
        (item.field, str(item.value).casefold())
        for item in deduplicated.values()
        if item.operator == "not_contains"
    }
    constraints = [
        item
        for item in deduplicated.values()
        if item.operator == "not_contains"
        or (item.field, str(item.value).casefold()) not in negatives
    ]
    return patch.model_copy(update={
        "constraints": constraints[:20],
        "remove_fields": list(dict.fromkeys(patch.remove_fields)),
        "no_preference": list(dict.fromkeys(patch.no_preference)),
    })


def apply_state_patch(
    active_values: list[dict[str, Any]],
    patch: StatePatch,
) -> tuple[list[Constraint], list[Constraint]]:
    active = [Constraint.model_validate(value) for value in active_values]
    superseded: list[Constraint] = []

    if patch.retire_soft:
        superseded.extend(item for item in active if item.strength == "soft")
        active = [item for item in active if item.strength == "hard"]

    removed_fields = set(patch.remove_fields) | set(patch.no_preference)
    if removed_fields:
        superseded.extend(item for item in active if item.field in removed_fields)
        active = [item for item in active if item.field not in removed_fields]

    for incoming in patch.constraints:
        value = str(incoming.value).casefold()
        conflicts = [
            item for item in active
            if item.field == incoming.field
            and str(item.value).casefold() == value
            and item.operator != incoming.operator
        ]
        if conflicts:
            superseded.extend(conflicts)
            active = [item for item in active if item not in conflicts]
        key = (incoming.field, incoming.operator, value)
        if not any((item.field, item.operator, str(item.value).casefold()) == key for item in active):
            active.append(incoming)
    return active, superseded
