# Trace JSON v1 for Evaluation and the Viewer

[Chinese](TRACE_JSON_FORMAT.zh-CN.md) · [Testing and artifacts](TESTING.md) · [Viewer setup](../trace-visualizer/README.md)

This document is the reference for changing the exporter or viewer. Successful
Native runs from `scripts/evaluate_with_traces.py` and
`scripts/evaluate_parallel_with_traces.py` automatically write **`trace.json`**
to the run directory. Simulator traces are assembled by the workbench API from
saved results and do not create an additional file.

## Capture policy

The default `--candidate-limit 0` records complete candidate lists and ranks at
every stage. Single-process evaluation, parallel evaluation, the service trace
endpoint, and the one-command launcher all use this default. A positive limit
is only for explicitly truncated debugging and prints a warning.
`run_config.json` records `candidate_capture=full/limited`.

Complete candidates remain in raw `node_traces.jsonl`. The exporter extracts
the target product's presence, rank, and scores from each full candidate pool
into compact `trace.json`. The viewer can therefore show genuine ranks beyond
20 or 500 without loading every product. Missing evidence in older runs remains
`unknown`; the exporter never invents it.

## Use

1. Open Trace from a saved workbench run, or find a Native run's `trace.json`
   in the [artifact directory](TESTING.md).
2. For manual import, open the trace viewer and select **Choose Trace JSON**.
3. Inspect run metrics, samples, conversations, the target's rank at each
   stage, and saved node updates.

The browser reads the file locally and does not upload it. There is no need to
copy it into `public`, start a model, or repeat LLM calls. The repository does
not ship historical evaluation files. The viewer remains compatible with old
`diagnostics.json` files and can load an explicitly placed `public` file with
`?data=<filename>.json`. Invalid files produce an error without replacing the
currently displayed result.

Workbench deep links use `?runId=...&session=...&turn=...` to read saved
evidence from the local API; they do not rerun retrieval or ranking. When a
simulator lacks official per-turn gating, the exporter does not infer an exact
loss stage. In Realistic mode, the accepted or last recommended product is the
observed target. `diagnosticMode=agent` and `successRate` identify this mode and
must not be interpreted as an official hidden-target technical score.

## Export an older run

From `narrow-shopping-agent`, run:

```powershell
.\.venv\Scripts\python.exe scripts/export_trace.py --run-dir "path-to-existing-run"
```

The default output is `<run-dir>/trace.json`; use `--output "other-path.json"`
to override it. The exporter supports single-process logs, completed aggregate
logs, and interrupted shard logs. Complete aggregate files take precedence,
so the export does not depend on absolute shard paths from the original machine.

`summary.json` contains only metrics, and `results.json` normally lacks node
logs. A complete export requires `run_config.json`, `sessions.jsonl`,
`turns.jsonl`, and node logs, or their shard equivalents.

## Schema

```json
{
  "schema": "shopping-agent.trace",
  "schemaVersion": 1,
  "run": {
    "id": "20260830_120828_+0800",
    "model": "gpt-5.4",
    "workers": 6,
    "sampleCount": 200,
    "expectedSampleCount": 200,
    "partial": false,
    "snapshotMode": true,
    "hitRate": 0.955,
    "mrr": 0.460115,
    "mttc": 2.68,
    "technicalScore": 0.781934,
    "diagnosisCounts": {"hit": 191, "unknown": 9}
  },
  "sessions": ["sample objects described below"]
}
```

This is a structural example, not an importable result or an observed
diagnosis distribution.

| Level | Main fields |
|---|---|
| `sessions[]` | `sampleId`, `scenario`, `hit`, `firstHitTurn`, `bestRank`, `target`, `diagnosis`, `diagnosisReason`, `turns` |
| `turns[]` | `turn`, `userMessage`, `agentMessage`, `recommendedAsins`, `semanticQuery`, `constraints`, `evaluationActive`, `latencyMs`, `error`, `stages`, `nodeTrace` |
| `stages[]` | Ordered lexical / dense / attribute / fusion / filter / rerank / response stages with `count`, `targetRank`, `status`, `snapshotLimit`, and `signal` |
| `nodeTrace[]` | `names`, `step`, `createdAt`, and `updates`; candidate updates retain target evidence instead of embedding the full pool |

- `status=present`: the target is in the saved snapshot and `targetRank` is its
  actual rank there.
- `status=absent`: the complete saved candidate pool does not contain the target.
- `status=unknown`: capture was truncated or the stage did not run.
- Checkpoint updates are deltas. The exporter restores unchanged state per
  sample and turn without reusing unexecuted stage candidates after a failure.
- New coarse ranking may filter during fusion, so a missing target at fusion
  is not automatically attributed to an RRF cutoff.
- Partial runs calculate metrics only from completed sessions and explicitly
  record `partial` and the incomplete count.
- `nodeTrace` is a display summary. Complete raw candidate snapshots remain in
  `node_traces.jsonl`, limiting exposure of API configuration and local paths.
- The viewer rejects unsupported versions, malformed JSON, duplicate samples,
  invalid nesting, and files larger than 100 MB.

Export implementation: `narrow-shopping-agent/evaluator/trace_export.py`.
Viewer types and validation: `trace-visualizer/lib/trace.ts`. Legacy diagnostics
without version fields remain readable through the compatibility path.
