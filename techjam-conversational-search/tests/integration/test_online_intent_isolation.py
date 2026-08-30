"""Online decisions must never acquire constraints from offline parsers."""

import json

import pytest

from shopping_agent.application.service import ShoppingAgent
from shopping_agent.domain.schemas import Constraint
from shopping_agent.infrastructure.llm import deepseek
from shopping_agent.understanding import interpreter
from shopping_agent.understanding.state_patch import StatePatch, validate_state_patch


def test_online_graph_preserves_model_intent_and_trace(tmp_path, monkeypatch):
    path = tmp_path / "catalog.jsonl"
    path.write_text(json.dumps({
        "parent_asin": "TARGET", "title": "Boho blouse",
        "categories": ["Clothing"], "price": 30,
        "features": ["Boho style without sacrificing comfort"],
    }) + "\n", encoding="utf-8")
    monkeypatch.setenv("SHOPPING_AGENT_ENABLE_LLM", "true")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("SHOPPING_DENSE_BACKEND", "local")

    def forbidden(*args, **kwargs):
        pytest.fail("Offline parser or dialogue policy ran in online mode")

    monkeypatch.setattr(interpreter, "rule_state_patch", forbidden)
    monkeypatch.setattr(interpreter, "semantic_fallback_patch", forbidden)
    monkeypatch.setattr("shopping_agent.dialogue.decision.choose_question", forbidden)

    def model_intent(payload):
        assert "rule_patch" not in payload
        return StatePatch(
            category="clothing", semantic_query="boho blouse", retrieval_intent="unknown",
            constraints=[Constraint(field="style", value="boho", strength="soft",
                                    source_turn=payload["turn"])], confidence=0.9,
        ), {"prompt_tokens": 10, "completion_tokens": 5}

    def model_dialogue(payload):
        assert "fallback_suggestion" not in payload
        return {"action": "recommend", "message": "Here is a boho blouse."}, {
            "prompt_tokens": 8, "completion_tokens": 4,
        }

    monkeypatch.setattr(interpreter, "request_state_patch", model_intent)
    monkeypatch.setattr(deepseek, "request_dialogue_decision", model_dialogue)
    agent = ShoppingAgent(path)
    agent.reset("online", {})
    for turn, message in enumerate([
        "I want a blouse", "Boho style", "A key requirement is: boho without sacrificing.",
    ], start=1):
        result = agent.respond("online", message, turn, 10)
        assert result["recommendations"][0]["parent_asin"] == "TARGET"
        state = agent.get_intent_state("online")
        assert state["retrieval_intent"] == "unknown"  # no 'key requirement' heuristic
        assert [c["value"] for c in state["active_constraints"]] == ["boho"]
    updates = [row["updates"] for row in agent.get_turn_trace("online", 3)]
    patch = next(u["semantic_patch"] for u in updates if "semantic_patch" in u)
    assert patch["parser"] == "deepseek"
    assert patch["model_output"]["constraints"][0]["value"] == "boho"
    # Check the checkpoint too: unchanged provenance need not repeat in diff traces.
    values = agent.graph.get_state({"configurable": {"thread_id": agent._thread_ids["online"]}}).values
    assert values["dialogue_parser"] == "deepseek"
    assert values["dialogue_model_output"]["action"] == "recommend"


def test_online_without_key_does_not_become_offline(monkeypatch):
    monkeypatch.setenv("SHOPPING_AGENT_ENABLE_LLM", "true")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="requires DEEPSEEK_API_KEY"):
        interpreter.resolve_semantic_patch("red shoes", 1)


def test_online_validation_does_not_choose_negative_over_positive():
    patch = StatePatch(parser="deepseek", constraints=[
        Constraint(field="feature", value="comfort", operator="contains"),
        Constraint(field="feature", value="comfort", operator="not_contains"),
    ])
    with pytest.raises(ValueError, match="contradictory"):
        validate_state_patch(patch)


def test_online_dialogue_failure_does_not_choose_local_question(monkeypatch):
    from shopping_agent.dialogue.decision import decide_dialogue

    monkeypatch.setattr(deepseek, "is_configured", lambda: True)

    def unavailable(payload):
        raise TimeoutError("provider timeout")

    monkeypatch.setattr(deepseek, "request_dialogue_decision", unavailable)
    with pytest.raises(RuntimeError, match="Online dialogue failed.*TimeoutError"):
        decide_dialogue(
            turn=1, user_message="shoes", conversation_history=[], active_constraints=[],
            no_preference=set(), asked_attributes=[], pending_question=None, question_history=[],
            candidate_attributes=[{"color": {"red"}}, {"color": {"blue"}}],
            ranked_candidates=[], known_attributes=set(), language="en",
        )
