# Evaluation Analysis

Run: `20260827_232525_+0800`

## What changed with LLM-first intent understanding

| Metric | Local fallback | DeepSeek traced run | Change |
|---|---:|---:|---:|
| Hit Rate@10 | 0.820000 | 0.900000 | +0.080000 |
| MRR | 0.329188 | 0.362373 | +0.033185 |
| MTTC | 4.005000 | 3.305000 | -0.700000 |
| Technical Score | 0.648656 | 0.712612 | +0.063956 |

The LLM path materially improves recall and reaches the target earlier, but MRR
is still modest relative to Hit Rate. The target is often retrieved but not
ranked near the top, so reranking remains a major opportunity.

## Runtime profile

- 200 sessions, 641 turns, 180 hits, 20 misses.
- Average simulated conversation length: 3.205 turns.
- Mean Agent response latency: 1,428.3 ms.
- Median Agent response latency: 1,378.4 ms.
- P95 Agent response latency: 1,927.2 ms.
- Maximum Agent response latency: 3,268.3 ms.
- Prompt tokens: 477,292 (744.6 per turn).
- Completion tokens: 85,125 (132.8 per turn).
- Total tokens: 562,417 (877.4 per turn).

The 1,452.9-second wall time includes checkpoint reconstruction and writing a
32 MB node trace. It is not representative of production response latency.

## Trace integrity

- All 200 session records are present.
- All 641 conversation turns are present.
- 7,039 node-stage records are present.
- All 641 intent-understanding stages report `parser=deepseek`.
- No provider fallback was observed.
- Three turns in `public_0197` stopped during reranking because one catalog price
  was the string `—`. The run preserves these errors. The numeric-price guard was
  fixed after this baseline and has a regression test, but this run was not
  rewritten or rescored.

## Most important behavioral finding

The clarification policy asked about `brand` on 199 of 200 first turns. This is
mathematically understandable because brand has high entropy, but it produces
poor real-user questions involving obscure marketplace brands. Candidate entropy
alone is not an adequate measure of question utility.

Question counts across all turns:

| Attribute | Count |
|---|---:|
| brand | 200 |
| style | 89 |
| material | 70 |
| use_case | 64 |
| color | 62 |
| budget | 43 |
| no question | 113 |

The next policy should combine expected candidate reduction with user
answerability and business relevance. A practical default priority is use case,
category/shape, material, functional feature, size, style, budget, color, then
brand unless the user already mentioned a brand.

## Scenario observations

- Buying performs best on speed (`MTTC=2.4375`).
- Intent Override has the best ranking quality (`MRR=0.489854`) but naturally
  takes longer (`MTTC=5.0`) because the simulator changes intent mid-session.
- Boundary has a high hit rate (`0.9`) but the lowest MRR (`0.250397`), suggesting
  that no-preference answers do not help the current reranker focus.
- Browsing is the largest segment and has 9 misses, so it should dominate the
  next qualitative error review.

## Recommended next experiments

1. Replace raw entropy with a question-utility score that penalizes obscure or
   high-cardinality brands and rewards answerable attributes.
2. Track target presence and rank at lexical, semantic, attribute, fusion,
   filtering, and reranking stages to separate recall failures from ranking
   failures.
3. Replace the hashed semantic fallback with the intended embedding/vector DB
   implementation and compare route-level recall.
4. Add a learned or LLM reranker experiment; the current gap between Hit Rate
   and MRR indicates that candidate ordering is a bottleneck.
