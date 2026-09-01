from __future__ import annotations

import json
import os

from dotenv import load_dotenv

from shopping_agent.understanding.interpreter import resolve_semantic_patch, rule_state_patch


def main() -> int:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY", "").strip():
        print(json.dumps({"ok": False, "error": "OPENAI_API_KEY is empty"}))
        return 2

    # A smoke test should exercise the configured provider regardless of the
    # default production switch. This process-only override does not edit .env.
    os.environ["SHOPPING_AGENT_ENABLE_LLM"] = "true"
    message = "I need something that won't soak through on rainy hikes, preferably under $90."
    patch, usage = resolve_semantic_patch(
        message,
        1,
        rule_state_patch(message, 1),
        current_category="jackets",
    )
    result = {
        "ok": patch.parser == "openai",
        "parser": patch.parser,
        "confidence": patch.confidence,
        "category": patch.category,
        "constraints": [
            {
                "field": item.field,
                "operator": item.operator,
                "value": item.value,
                "strength": item.strength,
            }
            for item in patch.constraints
        ],
        "usage": usage,
        "fallback_reasons": patch.fallback_reasons,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
