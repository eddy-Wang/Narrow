# Agent Architecture

## Runtime graph

```text
START
  -> rule_parse
       |-> validate_patch --------------------|
       |-> semantic_fallback -> validate_patch|-> update_state
  -> build_query
       |-> lexical_retrieve ---------|
       |-> dense_retrieve_fallback --|-> rrf_fusion
       |-> attribute_retrieve -------|
                                         -> constraint_filter
                                              |-> rerank_fallback
                                              |-> relax_and_backfill -> rerank_fallback
                                                   -> information_gain_question
                                                   -> build_response
                                                   -> validate_response
                                                   -> END
```

The graph defaults to an offline deterministic orchestrator. The semantic
fallback node can optionally call DeepSeek when explicitly enabled and given a
key; otherwise it uses local rules. No semantic path can retrieve or recommend
catalog identifiers.

## Semantic state update

`rule_parse` first emits a bounded JSON `StatePatch` containing an action,
category, constraints, fields to remove, no-preference fields, confidence, and
fallback reasons. The confidence router sends standard high-confidence protocol
messages directly to validation. Ambiguous negation, comparison/reference,
conditional budgets, and messages with no structured signal use
`semantic_fallback`.

The local fallback handles common material/color/style/use-case/features,
negative scopes, comparative expressions, conditional preferred/maximum
budgets, and intent-replacement markers. `validate_patch` normalizes values,
deduplicates constraints, and makes negative constraints win collisions before
`update_state` mutates conversation state.

DeepSeek is disabled by default. When `SHOPPING_AGENT_ENABLE_LLM=true` and
`DEEPSEEK_API_KEY` is non-empty, the same node requests a strict JSON patch via
the OpenAI-compatible Chat Completions interface. Any import, network, JSON, or
validation failure immediately falls back to the deterministic implementation.

## Persistent state

LangGraph checkpoints one JSON-serializable state per evaluator session/thread.
It contains active and superseded constraints, no-preference and asked fields,
per-route candidates, fused and filtered candidates, question scores, output
validation errors, and previously recommended identifiers. Explicit intent
overrides retire earlier soft preferences and reset recommendation novelty.

## Retrieval

Three routes execute in parallel:

- `lexical_retrieve`: field-weighted SQLite FTS5/BM25 over title, category,
  features, details, store, and description;
- `dense_retrieve_fallback`: a 512-dimensional stable feature-hash vector index
  with phrase features and a small apparel concept normalization map;
- `attribute_retrieve`: deterministic material, color, style, use-case, brand,
  category, and price-bucket indexes.

The dense fallback has a dense-retriever interface but is not represented as a
neural embedding model. It avoids network/model dependencies and can later be
replaced behind the same node contract.

Weighted reciprocal-rank fusion combines the routes. Explicit high-confidence
hard constraints are then applied centrally. If fewer than 30 products survive,
the graph runs a broader category query and backfills candidates without
discarding the hard constraints.

## Reranking fallback

`rerank_fallback` is the current cross-encoder substitute. It combines exact and
partial constraint coverage, category and query coverage, route/RRF evidence,
semantic and attribute scores, a weak profile match, review-count quality,
contradiction penalties, and cross-turn novelty. Its output includes an
explainable score and matched-field labels.

## Clarification and validation

The first discovery turns use the broad `other` action defined by the published
simulator protocol. Later turns estimate normalized entropy for candidate
category, material, color, style, brand, budget, and use-case values, multiplied
by attribute coverage. Previously asked and no-preference attributes are
excluded.

The final validation node enforces catalog membership, uniqueness, Top-K limits,
and the allowed `ask_attribute` vocabulary before the official adapter returns.

## Future local-model replacements

The fallback interfaces are intentionally stable. A selected offline embedding
model can replace `LocalDenseIndex`, and a selected local cross-encoder can
replace `FallbackReranker`, without changing graph topology or the evaluator API.
