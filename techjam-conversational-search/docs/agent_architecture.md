# Agent Architecture

## Runtime graph

```text
START
  -> parse_and_update
  -> build_query
  -> retrieve
  -> rerank
  -> select_question
  -> build_response
  -> END
```

The graph is a deterministic orchestrator. It does not let a model invent
catalog identifiers or decide which code path to run. `CatalogIndex` is built
once when the Agent starts and is captured by the graph nodes.

## Persistent state

LangGraph checkpoints one state per evaluator session/thread. The important
fields are:

- the active category and structured constraints;
- superseded soft constraints after an explicit intent override;
- attributes that received a no-preference answer;
- previously asked attributes;
- the current query, candidates, ranking, and output.

Constraints are checkpointed as plain dictionaries and validated with Pydantic
at node boundaries. This keeps serialization portable and the state inspectable.

## Turn behavior

1. Parse simulator language and common natural variants with deterministic
   rules. Explicit key requirements are hard; free-form initial preferences are
   soft.
2. Merge the new information into active state. An override retires earlier
   soft preferences while preserving explicit hard requirements.
3. Build a query from the category, all active constraints, and current raw
   message.
4. Retrieve up to 300 candidates from the local field-weighted SQLite FTS5
   index. Missing metadata is treated as unknown rather than a contradiction.
5. Rerank with exact constraint matches, partial coverage, category match,
   lexical rank, contradiction penalties, and a small review-count prior.
6. Return ten catalog-valid recommendations on every turn and ask for another
   preference during the early discovery turns.

## Extension points

The MVP is deliberately offline and has zero token cost. Planned replacements
fit behind existing node contracts:

- add dense candidate generation and reciprocal-rank fusion in `retrieve`;
- add an optional structured LLM fallback in `parse_and_update`;
- replace the hand-tuned scorer with a local cross-encoder or learned ranker;
- replace the early-turn clarification heuristic with candidate-set information
  gain.

The evaluator-facing `reset` and `respond` API does not change when these pieces
are added.
