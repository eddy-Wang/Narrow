# Narrow roadmap

Narrow is an early-stage open-source project. This roadmap lists intended work,
not shipped features or adoption claims. Priorities may change as real users
and contributors provide evidence.

## Near term

- Add small, redistributable catalog fixtures for a complete five-minute demo.
- Publish provider-neutral state and dialogue adapter interfaces.
- Add multilingual state-transition and constraint-conflict evaluations.
- Measure latency and token cost separately for understanding and dialogue.
- Add retrieval ablations for route weights, cutoff depth, and backfill policy.

## Ranking and retrieval

- Add pluggable vector-store adapters with reproducible local baselines.
- Improve learning-to-rank training with leakage-resistant dataset splits.
- Report confidence intervals and per-scenario failure categories.
- Explore diversity-aware reranking without weakening hard constraints.

## Reliability and safety

- Add schema-migration tests for persisted conversation state.
- Add adversarial tests for prompt injection inside catalog metadata.
- Add configurable retention controls for conversation and trace data.
- Document production deployment, rate limiting, and secret-management patterns.

## Community

- Label self-contained starter contributions after the public interfaces settle.
- Publish a versioned evaluation protocol and contribution guide for new datasets.
- Use GitHub issues for proposals and link merged work back to this roadmap.
