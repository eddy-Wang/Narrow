# Agent Architecture

## Product boundary

The core system is a real-user conversational shopping agent. A user sends a
natural-language message; the agent owns turn counting, intent state, retrieval,
clarification, and recommendations. The competition `reset/respond` shape is a
thin compatibility adapter rather than the product architecture.

```python
session_id = agent.start_session(user_profile={})
result = agent.chat(session_id, "I need light waterproof shoes for city travel")
state = agent.get_intent_state(session_id)
```

## Runtime graph

```text
START
  -> understand_user (LLM-first, local failure fallback)
  -> validate_patch
  -> update_state
  -> build_query
       |-> lexical_retrieve  (lexical_query) --------|
       |-> semantic_retrieve (semantic_query) -------|-> rrf_fusion
       |-> attribute_retrieve (structured state) ----|
                                                         -> constraint_filter
                                                              |-> rerank_fallback
                                                              |-> relax_and_backfill
                                                                    -> rerank_fallback
                                                              -> information_gain_question
                                                              -> build_response
                                                              -> validate_response
                                                              -> END
```

## Dual representation of user intent

Every turn produces one bounded `StatePatch` with two representations:

- structured fields: category, positive/negative constraints, hard/soft
  strength, fields to remove, and explicit no-preference fields;
- `semantic_query`: one concise English product-search sentence representing
  the complete current intent for a multilingual embedding/vector database.

The patch also contains a user-facing intent summary and detected response
language. It cannot retrieve products or generate catalog identifiers.

When `SHOPPING_AGENT_ENABLE_LLM=true` and a DeepSeek key is configured, the LLM
is called on every user turn. The prompt includes current category, active
constraints, previous semantic query, intent summary, and optional user profile,
so references and changes can be resolved against maintained state. Provider,
network, JSON, or validation failures fall back to deterministic extraction.

## Persistent intent state

LangGraph checkpoints one JSON-serializable state per user session. Important
durable values include:

- active and superseded constraints;
- category, no-preference fields, and already-asked attributes;
- complete semantic query and intent summary;
- previously recommended products for novelty control.

An explicit replacement retires prior constraints for the fields being
replaced, including hard constraints. A new explicit preference also clears an
older no-preference marker for that field.

## Retrieval contracts

The graph intentionally separates three retrieval inputs:

- `lexical_query`: category, positive structured values, and semantic query for
  field-weighted SQLite FTS5/BM25;
- `semantic_query`: the clean LLM sentence sent only to the semantic retriever;
- structured state: attributes and hard constraints used for indexed coarse
  retrieval and centralized filtering.

`SemanticRetriever` is a replaceable boundary with `search(query, limit)`. The
current `LocalDenseIndex` is an offline hashed-vector fallback, not a production
embedding model. A vector database implementation can be injected without
changing graph topology.

Weighted reciprocal-rank fusion combines all routes. High-confidence hard
constraints are applied centrally. When too few products survive, a broader
category search backfills candidates without discarding hard constraints.

## Candidate-driven clarification

There are no evaluator-specific “first two turns ask other” rules. After each
retrieval and reranking pass, the agent analyzes the current Top-50 candidates.
For every unknown facet it calculates attribute coverage multiplied by
normalized entropy, excludes already-known, already-asked, and no-preference
fields, then selects the facet that best partitions the result set.

Representative values and counts are retained as `question_options`. The reply
therefore refers to actual differences in the current results, for example:

```text
当前结果在材质上主要有 leather、cotton，你更偏向哪一种？
```

If the result set has no meaningful unresolved split, the agent presents the
current recommendations without forcing another question.

## Reliability boundary

The final node enforces catalog membership, unique product identifiers, Top-K
limits, allowed question attributes, and non-negative usage accounting. The
local parser, local semantic index, and deterministic reranker are reliability
fallbacks; they are not the intended final intelligence components.
