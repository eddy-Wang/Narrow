# Component Interfaces

## Intent understanding

Input: latest message plus maintained category, constraints, semantic query,
intent summary, and optional profile.

Output: `understanding.state_patch.StatePatch` containing structured updates,
the complete semantic query, summary, language, confidence, and parser source.

The understanding layer cannot retrieve products or invent identifiers.

## Semantic retrieval

Implement `retrieval.interfaces.SemanticRetriever`:

```python
def search(self, query: str, limit: int = 200) -> list[dict]: ...
```

Each candidate must include `parent_asin`. Route-specific rank and score fields
may be added without changing the shared candidate identity.

## Candidate ranking

Implement `ranking.interfaces.CandidateRanker.rank`. The ranker receives fused
candidates, semantic query, category, active constraints, profile, and previous
recommendations. It returns candidates sorted best-first with
`reranker_score`.

## Orchestration

`orchestration.graph.build_shopping_graph` assembles the topology and accepts
optional semantic-retriever and ranker implementations. Node names are stable
because evaluation traces use them as identifiers.

## Public application service

```python
session_id = agent.start_session(user_profile={})
result = agent.chat(session_id, user_message, top_k=10)
state = agent.get_intent_state(session_id)
```

`application.competition_adapter.CompetitionAgent` preserves the organizer's
`reset/respond` contract. Product clients should use `start_session/chat`.

## Change policy

Backward-compatible fields may be added. Removing or renaming state keys,
candidate identity, graph node names, or public response fields requires an
architecture decision record and a trace/evaluator migration plan.
