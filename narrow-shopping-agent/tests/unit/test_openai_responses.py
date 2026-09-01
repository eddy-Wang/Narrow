from __future__ import annotations

import json
from types import SimpleNamespace

from shopping_agent.infrastructure.llm import openai_responses


class FakeResponses:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.requests: list[dict] = []

    def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(
            output_text=self.outputs.pop(0),
            usage=SimpleNamespace(input_tokens=11, output_tokens=7),
        )


def fake_client(outputs: list[str]):
    responses = FakeResponses(outputs)
    return SimpleNamespace(responses=responses), responses


def test_state_patch_uses_responses_structured_outputs(monkeypatch):
    client, responses = fake_client([
        json.dumps({
            "action": "add",
            "retrieval_intent": "buying",
            "parser": "openai",
            "category": "rain jackets",
            "semantic_query": "lightweight rain jacket for hiking",
            "constraints": [],
        })
    ])
    monkeypatch.setattr(openai_responses, "_client", lambda: client)
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")

    patch, usage = openai_responses.request_state_patch({"message": "rain jacket"})

    assert patch.parser == "openai"
    assert patch.category == "rain jackets"
    assert usage == {"prompt_tokens": 11, "completion_tokens": 7}
    request = responses.requests[0]
    assert request["model"] == "gpt-test"
    assert request["store"] is False
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["schema"]["type"] == "object"


def test_dialogue_invalid_json_gets_one_bounded_repair(monkeypatch):
    client, responses = fake_client([
        "not-json",
        json.dumps({
            "action": "recommend",
            "ask_attribute": None,
            "message": "Here are the strongest matches.",
            "reason": "constraints are sufficient",
        }),
    ])
    monkeypatch.setattr(openai_responses, "_client", lambda: client)

    decision, usage = openai_responses.request_dialogue_decision({"turn": 2})

    assert decision["action"] == "recommend"
    assert usage == {
        "prompt_tokens": 22,
        "completion_tokens": 14,
        "repair_attempts": 1,
    }
    assert len(responses.requests) == 2
    assert "previous response was invalid" in responses.requests[1]["input"]
