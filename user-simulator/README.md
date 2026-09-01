# User simulator

[Project home](../README.md) · [Workbench](../demo-frontend/README.md) ·
[Testing and artifacts](../docs/TESTING.md)

This optional package evaluates the Agent with deterministic user state and
either template or LLM-generated wording. It is not used by the primary
`run_evaluation.ps1` command.

## Protocols

User goals, profiles, and policies produce structured conversation actions.
Templates or an optional LLM then verbalize those actions; the LLM does not
choose the target, state transitions, acceptance, intent overrides, or
constraint relaxation.

| Mode | Scenario source | Success criterion |
|---|---|---|
| `techjam` | Public competition scenarios and profiles | Specified `parent_asin`, with intent-override gating and Hit@10/MRR/MTTC |
| `realistic` | Deterministically generated needs from the catalog | Configured hard and soft constraints are satisfied |

Hidden goals and unrevealed constraints stay inside the simulator. Metrics
from the two protocols are reported separately.

## Direct use

Reuse the Agent environment; do not create a second virtual environment. From
the repository root:

```powershell
uv run --project techjam-conversational-search --extra web --extra ltr --extra deepseek `
  --with-editable user-simulator --group dev --cache-dir .uv-cache `
  python -m user_simulator.cli run --preset techjam `
  --catalog-path techjam-conversational-search/data/catalog.jsonl `
  --sessions-path techjam-conversational-search/data/public_set.jsonl `
  --agent-class shopping_agent.agent:ShoppingAgent --limit 10 `
  --output integration_runs/manual-techjam/result.json `
  --report-output integration_runs/manual-techjam/report.md
```

Use `--preset realistic` for needs-based simulation. Direct CLI runs use the
Agent's default reranker unless an adapter is supplied; workbench settings do
not change an independent CLI process.

## Output

`result.json` contains `schema_version`, `mode`, `evaluation`, `turn_metrics`,
`latency`, `model_usage`, `mode_specific_metrics`, and `sessions`. Unknown
prices or unavailable usage counts remain `null`. `--report-output` writes a
human-readable Markdown summary. All run output belongs in ignored directories
and is not versioned.

## Files

| Path | Purpose |
|---|---|
| `configs/techjam_benchmark.yaml` | Competition-style protocol defaults |
| `configs/realistic.yaml` | Needs-based protocol defaults |
| `src/user_simulator/cli.py` | Command-line entry |
| `src/user_simulator/datasets.py`, `personas.py` | Scenario and persona construction |
| `src/user_simulator/policy.py`, `simulator.py`, `techjam.py` | Conversation policies and protocol execution |
| `src/user_simulator/acceptance.py`, `metrics.py`, `reporting.py` | Success checks, metrics, and reports |
| `src/user_simulator/adapters.py`, `verbalizers.py`, `models.py` | Agent adapters, wording, and shared models |
| `tests/` | Protocol, model, and reporting checks |
| `pyproject.toml` | Package metadata and dependencies |

Source data responsibility is documented in
[DATA_ATTRIBUTION.md](../techjam-conversational-search/DATA_ATTRIBUTION.md).
