from pathlib import Path

from shopping_agent.orchestration.graph import build_shopping_graph


PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Agent Server injects its own checkpointer, so the Studio graph must compile
# without the in-process saver used by the evaluator-facing Agent adapter.
graph = build_shopping_graph(
    catalog_path=PROJECT_ROOT / "data" / "catalog.jsonl",
    managed_persistence=True,
)
