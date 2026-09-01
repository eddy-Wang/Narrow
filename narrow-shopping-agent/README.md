# Narrow shopping agent

This package contains the retrieval, state-management, ranking, and dialogue
runtime used by Narrow. The default online path uses the OpenAI Responses API
with Structured Outputs for validated state patches and dialogue decisions.

## Setup

```bash
uv sync --extra web --extra ltr --extra openai --group dev
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`, then run the local API:

```bash
uv run --extra web python -m shopping_agent.web
```

The deterministic local fallback remains available for development and tests.
See the [root README](../README.md) for the full-stack quick start and
[testing guide](../docs/TESTING.md) for evaluation commands.

## Core pipeline

1. Validate a structured state patch against the current conversation state.
2. Build a canonical query from active constraints and user-profile signals.
3. Run lexical, dense, and attribute retrieval with a dynamic route policy.
4. Apply hard constraints, soft boosts, unknown-aware relaxation, and fusion.
5. Rerank candidates and select a high-information clarification when needed.

The public `agent.py` module exports the compatibility entry point for embedding
the runtime in external evaluators or applications.
