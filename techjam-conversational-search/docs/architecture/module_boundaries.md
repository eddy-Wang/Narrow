# Module Boundaries and Team Ownership

## Source layout

```text
src/shopping_agent/
├─ application/       product service and competition adapter
├─ orchestration/     LangGraph topology, node glue, and routing
├─ domain/            stable schemas, state, intent primitives, text normalization
├─ understanding/     StatePatch, fallback parsing, prompts, interpretation
├─ retrieval/         interfaces, lexical, semantic, attribute, and fusion routes
├─ ranking/           ranker interface and fallback implementation
├─ dialogue/          candidate-driven question policy and response construction
├─ infrastructure/    DeepSeek, persistence, and vector-store adapters
└─ observability/     checkpoint trace reconstruction
```

Top-level modules such as `shopping_agent.agent`, `shopping_agent.graph`, and
`shopping_agent.semantic_state` are compatibility facades. New code must import
from the package paths above.

## Ownership

| Area | Primary paths | Stable boundary |
|---|---|---|
| Intent and state | `domain/`, `understanding/` | `StatePatch` |
| Retrieval | `retrieval/`, `infrastructure/vector_store/` | `SemanticRetriever` |
| Ranking | `ranking/` | `CandidateRanker` |
| Conversation policy | `dialogue/` | question decision and response state |
| Agent topology | `orchestration/` | `ShoppingGraphNodes` methods and state keys |
| Product/API | `application/` | `start_session/chat` |
| Evaluation/trace | `observability/`, `scripts/` | JSONL artifact schemas |

Each area should have one primary reviewer. Changes to a stable boundary require
review from the owners of both the producer and consumer modules.

## Dependency direction

```text
application
    ↓
orchestration ──→ observability
    ↓
understanding / retrieval / ranking / dialogue
    ↓
domain
```

Infrastructure adapters implement capabilities consumed by the upper layers.
Domain code must not import LangGraph, provider SDKs, evaluator code, or scripts.
Retrieval and ranking implementations must not import orchestration.

## Collaboration rules

1. `orchestration/graph.py` owns topology only; no algorithm implementation.
2. Node methods coordinate components but do not contain provider SDK calls.
3. New retrievers and rankers implement existing protocols and are injected.
4. The competition evaluator stays outside the product core.
5. Large run artifacts stay under timestamped `evaluation_runs/` directories.
6. Legacy compatibility modules may re-export symbols but must contain no logic.
7. Every module change adds a unit test; cross-node behavior belongs in
   integration or regression tests.
