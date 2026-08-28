from __future__ import annotations

import re
from dataclasses import dataclass, field

from shopping_agent.domain.schemas import Attribute, Constraint


MATERIALS = ("cotton", "polyester", "nylon", "leather", "wool", "spandex", "silk", "rayon", "fabric")
COLORS = ("black", "white", "blue", "red", "pink", "green", "brown", "gray", "grey", "purple", "yellow", "orange")


@dataclass
class ParsedIntent:
    category: str | None = None
    constraints: list[Constraint] = field(default_factory=list)
    no_preference: set[Attribute] = field(default_factory=set)
    override: bool = False


def classify_attribute(value: str) -> Attribute:
    lowered = value.lower()
    if "budget" in lowered or re.search(r"(?:\$|<=|under)\s*\d", lowered):
        return "budget"
    if any(material in lowered for material in MATERIALS):
        return "material"
    if any(word in lowered for word in ("color", *COLORS)):
        return "color"
    if any(word in lowered for word in ("size", "sizing", "width", "wide", "narrow")):
        return "size"
    if any(word in lowered for word in ("department", "style", "fit", "sleeve", "neck")):
        return "style"
    if any(word in lowered for word in ("hiking", "running", "gym", "winter", "outdoor", "work")):
        return "use_case"
    return "feature"


def _constraint(value: str, turn: int, *, strength: str = "soft") -> Constraint | None:
    value = re.sub(r"\s+", " ", value).strip(" .;,\t\n")
    if not value:
        return None
    attribute = classify_attribute(value)
    operator = "contains"
    parsed_value: str | float = value
    if attribute == "budget":
        match = re.search(r"\d+(?:\.\d+)?", value.replace(",", ""))
        if match:
            parsed_value = float(match.group())
            operator = "lte"
    return Constraint(
        field=attribute,
        operator=operator,
        value=parsed_value,
        strength="hard" if strength == "hard" else "soft",
        confidence=1.0,
        source_turn=turn,
    )


def parse_message(message: str, turn: int) -> ParsedIntent:
    """Parse simulator language and common natural variants conservatively."""

    result = ParsedIntent()
    normalized = re.sub(r"\s+", " ", message).strip()
    lowered = normalized.lower()
    result.override = any(
        marker in lowered
        for marker in ("actually", "instead", "ignore my earlier", "ignore the earlier", "what i need is")
    )

    no_preference = re.search(r"(?:no|don't have (?:an additional |a )?) preference for ([a-z_]+)", lowered)
    if no_preference:
        value = no_preference.group(1)
        if value in {
            "category", "material", "color", "size", "style", "brand",
            "budget", "feature", "use_case", "other",
        }:
            result.no_preference.add(value)  # type: ignore[arg-type]

    category = re.search(
        r"\blooking for (.+?)(?:\.\s|,\s(?:a key requirement|but\s|what i need)|[.!?]?$)",
        normalized,
        re.IGNORECASE,
    )
    if category:
        result.category = category.group(1).strip(" ,.")

    key_requirement = re.search(r"a key requirement is:\s*(.+)$", normalized, re.IGNORECASE)
    if key_requirement:
        item = _constraint(key_requirement.group(1), turn, strength="hard")
        if item:
            result.constraints.append(item)
        return result

    revealed = re.search(r"what matters is:\s*(.+)$", normalized, re.IGNORECASE)
    if revealed:
        for value in revealed.group(1).split(";"):
            item = _constraint(value, turn, strength="hard")
            if item:
                result.constraints.append(item)
        return result

    override_value = re.search(r"what i need is:\s*(.+)$", normalized, re.IGNORECASE)
    if override_value:
        item = _constraint(override_value.group(1), turn, strength="hard")
        if item:
            result.constraints.append(item)
        return result

    # Override sessions start with one free-form soft preference after category.
    if result.category:
        remainder = normalized[category.end():].strip(" ,.")
        if remainder and "still exploring" not in remainder.lower():
            item = _constraint(remainder, turn, strength="soft")
            if item:
                result.constraints.append(item)

    return result


def merge_constraints(
    active: list[Constraint],
    parsed: ParsedIntent,
) -> tuple[list[Constraint], list[Constraint]]:
    """Apply a parsed turn and return (active, newly superseded)."""

    kept = list(active)
    superseded: list[Constraint] = []
    if parsed.override:
        superseded = [item for item in kept if item.strength == "soft"]
        kept = [item for item in kept if item.strength == "hard"]

    for incoming in parsed.constraints:
        key = (incoming.field, incoming.operator, str(incoming.value).casefold())
        if any(
            (item.field, item.operator, str(item.value).casefold()) == key
            for item in kept
        ):
            continue
        kept.append(incoming)
    return kept, superseded
