from __future__ import annotations

from typing import Any

from shopping_agent.domain.state import ShoppingState


ATTRIBUTE_LABELS_ZH = {
    "category": "品类",
    "material": "材质",
    "color": "颜色",
    "size": "尺码",
    "style": "风格",
    "brand": "品牌",
    "budget": "价格区间",
    "feature": "功能",
    "use_case": "使用场景",
}


def build_agent_response(state: ShoppingState) -> dict[str, Any]:
    """Build a localized answer from ranked candidates and question context."""

    top_k = min(max(int(state.get("top_k", 10)), 1), 10)
    recommendations = [
        {
            "parent_asin": str(item["parent_asin"]),
            "score": round(float(item["reranker_score"]), 6),
        }
        for item in state.get("ranked_candidates", [])[:top_k]
    ]
    attribute = state.get("ask_attribute")
    options = [
        str(item.get("value", "")).replace("_", " ")
        for item in state.get("question_options", [])
    ]
    language = state.get("user_language", "en")
    generated_message = str(state.get("dialogue_message", "")).strip()
    if generated_message:
        message = generated_message
    elif attribute and language == "zh":
        label = ATTRIBUTE_LABELS_ZH.get(attribute, attribute)
        if len(options) >= 2:
            message = f"当前结果在{label}上主要有{'、'.join(options)}，你更偏向哪一种？"
        else:
            message = f"为了进一步缩小结果，你对{label}有什么偏好吗？"
    elif attribute:
        label = attribute.replace("_", " ")
        if len(options) >= 2:
            message = (
                f"The current matches mainly differ by {label}: "
                f"{', '.join(options)}. Which do you prefer?"
            )
        else:
            message = f"To narrow these matches, do you have a preference for {label}?"
    else:
        message = (
            "我已经根据你目前的要求筛选出最接近的结果。"
            if language == "zh"
            else "Here are the closest matches for your current requirements."
        )
    semantic_usage = state.get("semantic_usage", {})
    dialogue_usage = state.get("dialogue_usage", {})
    return {
        "response_message": message,
        "recommendations": recommendations,
        "usage": {
            "prompt_tokens": int(semantic_usage.get("prompt_tokens", 0))
            + int(dialogue_usage.get("prompt_tokens", 0)),
            "completion_tokens": int(semantic_usage.get("completion_tokens", 0))
            + int(dialogue_usage.get("completion_tokens", 0)),
        },
    }
