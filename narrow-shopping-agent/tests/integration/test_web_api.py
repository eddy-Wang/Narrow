import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from shopping_agent.web import Evaluation, create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    catalog = tmp_path/"catalog.jsonl"
    catalog.write_text(json.dumps({"parent_asin": "A", "title": "Black shoes", "price": 20,
        "categories": ["Shoes"], "features": ["black"], "details": {}, "average_rating": 4.5}) + "\n")
    # HTTP settings update process environment; do not leak them to other suites.
    with patch.dict("os.environ"):
        yield create_app(catalog, tmp_path/"runs")


@pytest.mark.parametrize("with_catalog", [True, False])
def test_empty_history_and_trace_entry_are_portable(app, with_catalog):
    if not with_catalog:
        app.state.runtime.catalog.unlink()
    with TestClient(app) as client:
        capabilities = client.get("/api/capabilities").json()
        assert capabilities["catalog"]["available"] is with_catalog
        assert capabilities["trace_url"] == "http://127.0.0.1:3000/"
        if not with_catalog:
            assert client.post("/api/chat/sessions").status_code == 503
            assert client.post("/api/evaluations", json={"mode": "native", "count": 1}).status_code == 503
        assert client.get("/api/evaluations").json()["runs"] == []


def test_local_api_blocks_foreign_origins_credentials_redirect_and_missing_key(app):
    with TestClient(app) as client:
        assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
        assert client.post("/api/chat/sessions", headers={"Origin": "https://evil.example"}).status_code == 403
        settings = {k: v for k, v in client.get("/api/settings").json().items()
                    if k not in {"revision", "openai_configured", "model_presets"}}
        assert client.put("/api/settings", json=settings | {"base_url": "https://evil.example"}).status_code == 422
        assert client.put("/api/settings", json=settings | {"provider": "openai"}).status_code == 422
        assert client.post("/api/evaluations", json={"mode": "simulator-realistic", "count": 101}).status_code == 422
        assert client.get("/api/evaluations/missing/result").status_code == 404


def test_frontend_can_set_write_only_process_local_openai_key(app):
    secret = "sk-test-only-never-echo-this-value"
    with TestClient(app) as client:
        rejected = client.put("/api/settings/openai/key", json={"api_key": secret},
                              headers={"Origin": "https://evil.example"})
        assert rejected.status_code == 403
        assert "OPENAI_API_KEY" not in os.environ

        configured = client.put("/api/settings/openai/key", json={"api_key": secret})
        assert configured.status_code == 200
        assert configured.json()["openai_configured"] is True
        assert secret not in configured.text
        assert os.environ["OPENAI_API_KEY"] == secret
        assert client.get("/api/capabilities").json()["openai_configured"] is True

        settings = {k: v for k, v in configured.json().items()
                    if k not in {"revision", "openai_configured", "model_presets"}}
        selected = client.put("/api/settings", json=settings | {"provider": "openai"})
        assert selected.status_code == 200
        assert secret not in selected.text

        assert client.put("/api/settings/openai/key", json={"api_key": "contains whitespace"}).status_code == 422
        assert client.put("/api/settings/openai/key", json={"api_key": secret, "extra": secret}).status_code == 422
        assert client.put("/api/settings/openai/key", json={"api_key": f"  {secret}\n"}).status_code == 200
        assert os.environ["OPENAI_API_KEY"] == secret


def test_chat_uses_existing_final_agent_contract_and_enriches_products(app, monkeypatch):
    import shopping_agent.web as web
    class Agent:
        def start_session(self, sid):
            self.sid = sid
        def chat(self, sid, message, top_k):
            assert sid == self.sid and message == "shoes" and top_k == 10
            return {"message": "Here are shoes", "recommendations": [{"parent_asin": "A"}]}
        def get_intent_state(self, sid):
            return {"semantic_query": "black shoes"}
        def release_session(self, sid):
            assert sid == self.sid
    monkeypatch.setattr(web, "create_agent", lambda catalog: Agent())
    with TestClient(app) as client:
        session = client.post("/api/chat/sessions").json()
        response = client.post(f'/api/chat/sessions/{session["id"]}/messages', json={"message": "shoes"})
        assert response.status_code == 200
        assert response.json()["recommendations"][0]["title"] == "Black shoes"
        assert response.json()["intent"]["semantic_query"] == "black shoes"
        assert client.delete(f'/api/chat/sessions/{session["id"]}').status_code == 204


def test_worker_commands_reuse_final_scripts_without_demo_backend(app):
    runtime = app.state.runtime
    for mode in ("native", "simulator-benchmark", "simulator-realistic"):
        options = Evaluation(mode=mode, count=2, reranker="lambdamart")
        job = {"id": "test", "mode": mode, "config": options.model_dump(exclude={"mode"})}
        command = runtime.command(job)
        assert not any("demo_api" in argument for argument in command)
        if mode == "native":
            assert "--no-llm" in command
            assert command[command.index("--ltr-model-dir")+1].endswith("lambdamart_synthetic_2000")
        else:
            assert "user_simulator.cli" in command
            assert "shopping_agent.web:create_agent" in command


def test_delete_cannot_escape_run_directory(app, tmp_path):
    external = tmp_path/"must_keep.txt"
    external.write_text("keep")
    app.state.runtime.jobs[".."] = {"id": "..", "status": "completed"}
    with TestClient(app) as client:
        response = client.request("DELETE", "/api/evaluations", json={"ids": [".."]})
        assert response.status_code == 409
        assert external.read_text() == "keep"
