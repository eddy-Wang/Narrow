# Project guide

Narrow is split into four independently useful packages:

| Path | Purpose |
|---|---|
| `narrow-shopping-agent/` | Stateful shopping agent, retrieval, ranking, dialogue, and local HTTP API |
| `demo-frontend/` | Vue workbench for chat, evaluation, settings, and run history |
| `user-simulator/` | Deterministic and LLM-verbalized scenario evaluation |
| `trace-visualizer/` | Local inspection of retrieval and dialogue traces |

The main Python package uses the OpenAI Responses API for intent understanding
and dialogue decisions. Its model output is constrained by JSON schemas before
it can update canonical conversation state. Retrieval and ranking remain local,
so the model does not receive the complete product catalog.

Important entry points:

- `narrow-shopping-agent/agent.py`: embeddable agent interface.
- `narrow-shopping-agent/src/shopping_agent/application/service.py`: session lifecycle.
- `narrow-shopping-agent/src/shopping_agent/infrastructure/llm/openai_responses.py`: OpenAI adapter.
- `narrow-shopping-agent/src/shopping_agent/retrieval/`: dynamic multi-route retrieval.
- `narrow-shopping-agent/src/shopping_agent/ranking/`: deterministic and LambdaMART rerankers.
- `narrow-shopping-agent/src/shopping_agent/web.py`: localhost workbench API.

Local catalogs, credentials, evaluation outputs, caches, and virtual
environments are excluded from version control. Dataset origin and usage
constraints are documented in `narrow-shopping-agent/DATA_ATTRIBUTION.md`.
