# TechJam Conversational Search — Engineering Handoff

Last updated: 2026-08-27 (Asia/Singapore)

This document captures the current working state so development can continue on
another device without relying on chat history.

## 0. Read this before switching devices

The current branch is `main` at commit `19a8d71`, but the algorithm work in this
document is **not committed yet**. Cloning the repository elsewhere right now
will not include these changes.

Before switching devices, either:

1. commit and push the working tree; or
2. copy the entire `techjam-conversational-search` directory to the new device.

Suggested Git workflow, after reviewing the diff:

```powershell
git status
git diff --check
git add README.md docs/agent_architecture.md langgraph.json pyproject.toml uv.lock `
  src/shopping_agent tests scripts .env.example PROJECT_HANDOFF.md
git commit -m "Build offline hybrid LangGraph shopping agent"
git push
```

Do **not** add `.env`. It is ignored by Git and currently contains a configured
DeepSeek key. Transfer that key separately through a password manager or create
a new key on the new device.

The 60 MB `data/catalog.jsonl` and compressed catalog may also need to be copied
or downloaded again; they are not normal source-code artifacts.

## 1. Project objective

Build a multi-turn shopping search Agent that identifies a hidden target product
from a frozen 50,000-product Amazon Clothing, Shoes & Jewelry catalog within ten
turns.

The official interface is:

```python
class Agent:
    def reset(self, session_id: str, user_profile: dict) -> None: ...

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict: ...
```

Only exact `parent_asin` matches count. Every turn can return up to ten products
and one structured `ask_attribute`.

Core score:

```text
TechnicalScore = 0.50 × HitRate@10 + 0.30 × MRR + 0.20 × Efficiency
Efficiency = clip((11 - MTTC) / 10, 0, 1)
```

Lower MTTC is better. A miss is assigned turn 11 for MTTC calculation.

## 2. Current system in one sentence

The current implementation is an offline-first, deterministic LangGraph Agent
with explicit conversation state, rule/semantic fallback parsing, parallel BM25
+ hashed-semantic + attribute retrieval, RRF fusion, constraint filtering,
fallback reranking, information-gain questioning, and optional DeepSeek JSON
state parsing behind a confidence gate.

No LLM is required for normal operation. DeepSeek is optional and failures fall
back to local logic.

## 3. Runtime architecture

```text
reset(session_id, user_profile)
              |
respond(user_message, turn, top_k)
              |
              v
          rule_parse
              |
       confidence_router
       /              \
high confidence     low confidence
      |                  |
      |          semantic_fallback
      |          /               \
      |   DeepSeek enabled      local rules
      |   and key present       fallback
       \                 /
            validate_patch
                  |
             update_state
                  |
              build_query
       /             |              \
lexical_retrieve  dense_fallback  attribute_retrieve
       \             |              /
                 rrf_fusion
                      |
              constraint_filter
                 /          \
        enough candidates   fewer than 30
                 |               |
                 |       relax_and_backfill
                  \             /
                 rerank_fallback
                        |
            information_gain_question
                        |
                 build_response
                        |
                validate_response
                        |
           message + ask_attribute + Top 10
```

LangGraph Studio should show these as separate nodes, including the three-way
retrieval fan-out and the candidate-shortage conditional branch.

## 4. Conversation state

`ShoppingState` is defined in `src/shopping_agent/state.py`. Important fields:

```text
session_id, turn, top_k, user_message, user_profile
category
active_constraints
superseded_constraints
no_preference
asked_attributes
intent_changed
semantic_patch
semantic_confidence
semantic_fallback_reasons
semantic_usage
lexical_candidates
dense_candidates
attribute_candidates
fused_candidates
filtered_candidates
ranked_candidates
constraints_relaxed
recommended_asins
question_scores
recommendations
errors
```

Constraints are checkpointed as plain dictionaries, then validated with
Pydantic at node boundaries. This avoids unsafe custom-class checkpoint
deserialization.

The evaluator-facing Agent uses an `InMemorySaver`; the Studio/Agent Server build
compiles without a custom saver because Agent Server injects persistence.

## 5. Semantic state update

Implemented in `src/shopping_agent/semantic_state.py`.

Every semantic interpretation must emit a bounded `StatePatch`:

```json
{
  "action": "add|replace|remove|no_preference",
  "category": null,
  "constraints": [],
  "remove_fields": [],
  "no_preference": [],
  "retire_soft": false,
  "confidence": 0.0,
  "parser": "rules|fallback|deepseek",
  "fallback_reasons": []
}
```

The semantic layer cannot retrieve products or generate ASINs.

### Local fallback coverage

- material, color, style, use case, category and common features;
- negation scope such as `don't want leather`;
- neutral language such as `don't mind black`;
- comparative/reference language such as `something lighter, not that tall`;
- preferred versus maximum conditional budgets;
- `actually`, `instead`, `forget`, and `ignore` intent replacement;
- patch deduplication and positive/negative collision resolution.

### DeepSeek behavior

DeepSeek is called only when:

```text
semantic_confidence < 0.7 OR fallback_reasons is non-empty
AND SHOPPING_AGENT_ENABLE_LLM=true
AND DEEPSEEK_API_KEY is non-empty
```

The call uses the OpenAI-compatible Chat Completions interface, JSON output,
thinking disabled, and a strict State Patch prompt. The model patch is merged
with the local deterministic patch so model omissions cannot erase obvious
material/use-case/budget/negation signals. Negative constraints win conflicts.

Any missing package, timeout, network failure, empty response, invalid JSON, or
schema error automatically returns to the local fallback.

DeepSeek official API documentation used during implementation:
https://api-docs.deepseek.com/

Current official configuration selected:

```text
base_url = https://api.deepseek.com
model = deepseek-v4-flash
```

Do not use the retired `deepseek-chat` or `deepseek-reasoner` aliases.

## 6. Retrieval and ranking

### Lexical retrieval

`CatalogIndex` in `src/shopping_agent/catalog.py` builds an in-memory SQLite FTS5
index over:

```text
title, categories, features, details, store, description
```

Title and category fields receive the largest BM25 weights.

### Dense-shaped local fallback

`LocalDenseIndex` in `src/shopping_agent/retrieval.py` is not a neural embedding
model. It provides a replaceable dense-retriever interface using:

- 512-dimensional stable feature hashing;
- token/stem/bigram features;
- a small apparel concept map, e.g. winter/cold/thermal → warmth;
- compact array-backed postings.

This avoids model downloads and external APIs. A real local BGE/E5 embedding
model can replace it later behind the same node contract.

### Attribute retrieval

The attribute index covers category, material, color, style, use case, brand and
price buckets. Category-term postings avoid scanning all 50,000 products on each
turn.

### Fusion

Weighted reciprocal-rank fusion currently uses:

```text
BM25 route weight             1.00
hashed semantic route weight  0.35
attribute route weight        0.45
RRF rank constant            60
```

### Constraints and fallback

Explicit high-confidence hard constraints are applied after fusion. Missing
metadata is unknown, not automatically a contradiction. If fewer than 30
candidates survive, the graph runs a broader category query and backfills while
preserving hard constraints.

### Reranker fallback

`FallbackReranker` in `src/shopping_agent/ranking.py` is not a neural
cross-encoder. It combines:

- exact and partial constraint matches;
- query/category coverage;
- BM25, RRF, hashed-semantic and attribute evidence;
- weak profile and rating-count priors;
- hard contradiction penalties;
- cross-turn novelty penalties.

A real local cross-encoder can replace this class without changing graph
topology.

## 7. Clarification policy

Implemented in `src/shopping_agent/question_policy.py`.

The first two discovery turns use `ask_attribute="other"`, because the published
simulator can disclose up to two hidden values for that action. Boundary sessions
can use one extra broad question because the first answer is always no-preference.

Later turns compute:

```text
QuestionScore(attribute) = coverage(attribute) × normalized_entropy(attribute)
```

Previously asked and no-preference attributes are excluded.

## 8. Output validation

The final graph node enforces:

- catalog membership;
- unique ASINs;
- Top-K at most ten;
- allowed `ask_attribute` vocabulary;
- non-negative token usage;
- recommendation-history updates.

## 9. Current evaluation results

### Original organizer baseline

```text
HitRate@10      0.125
MRR             0.068034
MTTC            9.81
TechnicalScore  0.106710
```

### Best pre-semantic enhanced run

This was measured before splitting semantic state update into its own subgraph:

```text
HitRate@10      0.990
MRR             0.559062
MTTC            2.020
TechnicalScore  0.842319
Token usage     0
```

### Current local semantic-fallback run

```text
HitRate@10      0.985
MRR             0.554062
MTTC            2.055
Efficiency      0.8945
TechnicalScore  0.837619
Token usage     0
```

### Current DeepSeek-enabled run

The public metrics were identical to the current local fallback run:

```text
HitRate@10      0.985
MRR             0.554062
MTTC            2.055
Efficiency      0.8945
TechnicalScore  0.837619
Prompt tokens   834
Output tokens   222
Total tokens    1,056
```

Scenario breakdown:

| Scenario | HitRate | MRR | MTTC |
|---|---:|---:|---:|
| Buying | 1.0000 | 0.507088 | 1.4625 |
| Browsing | 0.9875 | 0.522961 | 1.8750 |
| Boundary | 1.0000 | 0.528333 | 2.0000 |
| Intent Override | 0.9333 | 0.770833 | 4.1333 |

The API run did not mean 2,000 model calls. The evaluator stops after a hit, so
this run had approximately 408 actual Agent turns. The confidence router sent
only a few ambiguous turns to DeepSeek. API call count is not currently reported
as a separate field; only tokens are counted.

### DeepSeek smoke test

Input:

```text
I need something that won't soak through on rainy hikes, preferably under $90.
```

Final hybrid state patch:

```text
category=jackets
feature contains waterproof (hard)
use_case contains hiking (hard)
budget <= 90 (hard)
parser=deepseek
```

Most recent smoke usage:

```text
prompt tokens      371
completion tokens  137
total              508
```

## 10. Test status

Latest result:

```text
14 passed
```

Coverage includes:

- evaluator normalization and MTTC behavior;
- catalog retrieval;
- graph construction and official adapter compatibility;
- state accumulation and intent override;
- RRF multi-route reward;
- candidate-entropy question selection;
- negation scope;
- conditional budgets;
- comparative/reference fallback;
- provider-disabled safety behavior.

No live API unit test is part of `pytest`; use the explicit smoke script to avoid
accidental billing.

## 11. Environment and dependencies

Project requirements:

```text
Python >=3.12,<3.13
uv
LangGraph 1.x
Pydantic 2.x
SQLite with FTS5
```

Fresh setup:

```powershell
cd C:\path\to\techjam-conversational-search
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync --group dev
```

Install the optional DeepSeek/OpenAI-compatible client:

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync --extra deepseek --group dev
```

The lock file currently resolves the optional client to `openai==2.54.0`.

## 12. Environment variables and secrets

`.env.example` contains only placeholders. On the current device:

```text
DEEPSEEK_API_KEY is configured: yes
SHOPPING_AGENT_ENABLE_LLM: false
DEEPSEEK_BASE_URL: https://api.deepseek.com
DEEPSEEK_MODEL: deepseek-v4-flash
LANGSMITH_API_KEY is configured: no
LANGSMITH_TRACING: false
```

The real value of `DEEPSEEK_API_KEY` is intentionally not recorded here.

The smoke and API-evaluation scripts force the LLM switch to true only for their
own process. Normal evaluator and Studio runs follow `.env`.

To enable DeepSeek in normal Studio operation:

```env
DEEPSEEK_API_KEY=your-secret-key
SHOPPING_AGENT_ENABLE_LLM=true
```

## 13. Commands

### Unit tests

```powershell
.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_tmp
```

or:

```powershell
uv run pytest -q --basetemp=.pytest_tmp
```

### Offline public evaluation

```powershell
uv run python -m evaluator.local_evaluator --output results.json
```

### DeepSeek smoke test

```powershell
uv run python scripts/smoke_deepseek.py
```

This prints only the patch and usage; it never prints the key.

### DeepSeek-enabled public evaluation

```powershell
uv run python scripts/evaluate_with_deepseek.py --output results.json
```

### LangGraph Studio

Windows needs UTF-8 mode because the current CLI can otherwise try to read its
OpenAPI asset with GBK:

```powershell
$env:PYTHONUTF8 = "1"
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run langgraph dev
```

Expected endpoints:

```text
API      http://127.0.0.1:2024
Docs     http://127.0.0.1:2024/docs
Studio   https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

If 2024 is occupied, the CLI automatically selects another port. Use the URL
printed by that run.

Studio graph ID: `shopping_agent`.

Example raw Studio input:

```json
{
  "session_id": "studio-demo",
  "turn": 1,
  "top_k": 10,
  "user_message": "I need a waterproof jacket for hiking under $90.",
  "user_profile": {
    "preference_tags": ["comfort", "durability"]
  }
}
```

Graph startup currently builds all three indexes and can take roughly 20–25
seconds. Studio may print a slow-import warning, but the server starts.

## 14. Important files

| File | Responsibility |
|---|---|
| `starter/agent.py` | Official evaluator entry adapter |
| `src/shopping_agent/agent.py` | Session/thread adapter and output normalization |
| `src/shopping_agent/graph.py` | LangGraph construction and online orchestration |
| `src/shopping_agent/state.py` | Checkpointed graph state schema |
| `src/shopping_agent/schemas.py` | Constraint and response Pydantic models |
| `src/shopping_agent/intent.py` | Original protocol-oriented rule parser |
| `src/shopping_agent/semantic_state.py` | State Patch, confidence router inputs, local/DeepSeek semantic parsing |
| `src/shopping_agent/catalog.py` | Catalog storage, FTS5/BM25 and constraint checks |
| `src/shopping_agent/retrieval.py` | Hashed semantic index, attribute index and RRF |
| `src/shopping_agent/ranking.py` | Deterministic reranker fallback |
| `src/shopping_agent/question_policy.py` | Protocol-aware and information-gain questions |
| `src/shopping_agent/studio.py` | Agent Server/Studio graph export |
| `scripts/smoke_deepseek.py` | One-call safe provider smoke test |
| `scripts/evaluate_with_deepseek.py` | API-enabled official evaluator wrapper |
| `docs/agent_architecture.md` | Maintained architecture documentation |
| `langgraph.json` | Studio graph and `.env` configuration |
| `.env.example` | Secret-free configuration template |

## 15. Current uncommitted working tree

Modified:

```text
README.md
docs/agent_architecture.md
langgraph.json
pyproject.toml
src/shopping_agent/catalog.py
src/shopping_agent/graph.py
src/shopping_agent/state.py
tests/test_shopping_agent.py
uv.lock
```

New/untracked:

```text
.env.example
PROJECT_HANDOFF.md
scripts/evaluate_with_deepseek.py
scripts/smoke_deepseek.py
src/shopping_agent/question_policy.py
src/shopping_agent/ranking.py
src/shopping_agent/retrieval.py
src/shopping_agent/semantic_state.py
```

`.env` is ignored and must remain untracked.

## 16. Known limitations and open questions

1. **DeepSeek did not improve the template public set.** Local and API-enabled
   current metrics are identical. Its expected value is robustness to private
   paraphrases, negation and references.
2. **Intent Override is the weakest scenario.** HitRate is 0.9333 and MTTC is
   4.1333. Analyze state transitions and the missed override sessions first.
3. **Current semantic refactor is slightly below the best measured run.** The
   best was 0.842319; current is 0.837619. Recover that gap before adding more
   API calls.
4. **No paraphrase stress benchmark exists yet.** Create a fixed test set for
   negation, reference, conditional budgets, overrides and natural paraphrases;
   compare rules, local fallback and DeepSeek on State Patch accuracy.
5. **API call count is not reported.** Add `api_calls` and provider latency to
   diagnostics; the evaluator currently aggregates only prompt/completion tokens.
6. **Hashed semantic retrieval is not a real embedding model.** Benchmark a
   small offline BGE/E5 model if runtime/submission constraints allow it.
7. **Reranker is not a real cross-encoder.** Improve MRR using a local model or a
   learned ranker before expanding Agent autonomy.
8. **Startup is relatively slow.** Index construction takes around 20–25 seconds.
   Persisting deterministic indexes would improve Studio and evaluator startup.
9. **Public question policy is evaluator-aware.** `other` is unusually valuable
   in the published simulator. Keep a separate robust policy for protocol drift.
10. **Do not force 2,000 API calls just to show token usage.** The official
    evaluator stops after a hit. A fixed 200×10 load test should be a separate
    cost/latency benchmark, not presented as an official score.

## 17. Recommended next work

Priority order:

1. commit/push or copy the current workspace and transfer `.env` securely;
2. add explicit per-call DeepSeek latency/call-count diagnostics;
3. reproduce and inspect the missed Intent Override sessions;
4. build a semantic paraphrase stress set and measure State Patch exactness;
5. tune override reconciliation and recover/exceed TechnicalScore 0.842319;
6. improve MRR with a stronger local reranker;
7. only then consider a real embedding model or broader Agent control.

The intended architectural principle remains:

```text
LLM/Agent interprets uncertain language into a bounded State Patch.
Deterministic code owns state validation, retrieval, filtering, ranking,
question policy, catalog identifiers, and final output safety.
```
