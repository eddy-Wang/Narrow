import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from evaluator.trace_export import STAGES, PRODUCERS, build_payload, write_trace, load_rows
from shopping_agent.observability.tracing import compact_trace_values
from scripts.evaluate_parallel_with_traces import _merge_node_traces


def dump(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def jsonl(path, values):
    path.write_text("".join(json.dumps(value) + "\n" for value in values), encoding="utf-8")


@pytest.fixture
def run(tmp_path):
    dump(tmp_path / "run_config.json", {"run_id": "test", "model": "local", "sample_count": 1})
    session = {"sample_id": "s1", "scenario_type": "buying", "hit": True,
               "first_hit_turn": 2, "best_rank": 1, "reciprocal_rank": 1,
               "target_parent_asin": "A", "target_product": {"title": "Belt"}}
    jsonl(tmp_path / "sessions.jsonl", [session])
    jsonl(tmp_path / "turns.jsonl", [
        {"sample_id": "s1", "turn": t, "recommended_parent_asins": [] if t == 1 else ["A"]}
        for t in (1, 2)
    ])
    # Real checkpoint semantics: a node ran again, but unchanged output is omitted.
    nodes = [{"sample_id": "s1", "turn": t, "stage_index": i,
              "nodes": [PRODUCERS[name]],
              "updates": {key: {"count": 30, "top": [{"parent_asin": "A"}]}} if t == 1 else {}}
             for t in (1, 2) for i, (name, _, key) in enumerate(STAGES)]
    jsonl(tmp_path / "node_traces.jsonl", nodes)
    return tmp_path


def test_single_run_carries_checkpoint_diffs_and_exports_all_nodes(run):
    output = write_trace(run)
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schemaVersion"] == 1
    assert data["run"]["workers"] == 1
    second = data["sessions"][0]["turns"][1]
    assert second["stages"][0]["targetRank"] == 1
    assert len(second["nodeTrace"]) == 6
    assert second["diagnosis"] == "hit"


def test_completed_aggregate_is_portable_without_original_shard_paths(run):
    (run / "shards").mkdir()
    dump(run / "summary.json", {"sample_count": 1, "hit_rate_at_10": 1, "mrr": 1})
    assert build_payload(run)["run"]["sampleCount"] == 1


def test_rejects_mismatched_summary_and_duplicate_turns(run):
    dump(run / "summary.json", {"sample_count": 1, "hit_rate_at_10": 0, "mrr": 1})
    with pytest.raises(ValueError, match="summary"):
        build_payload(run)
    jsonl(run / "turns.jsonl", [{"sample_id": "s1", "turn": 1}] * 2)
    with pytest.raises(ValueError, match="Duplicate"):
        build_payload(run)


def test_failed_turn_without_nodes_does_not_reuse_previous_candidates(run):
    rows = [json.loads(line) for line in (run / "node_traces.jsonl").read_text().splitlines()]
    jsonl(run / "node_traces.jsonl", [row for row in rows if row["turn"] == 1])
    second = build_payload(run)["sessions"][0]["turns"][1]
    assert all(stage["status"] == "unknown" for stage in second["stages"][:-1])


def test_snapshot_node_updates_do_not_ship_entire_candidate_pools(run):
    node = build_payload(run)["sessions"][0]["turns"][0]["nodeTrace"][0]
    evidence = node["updates"]["lexical_candidates"]
    assert "top" not in evidence
    assert evidence["count"] == 30 and evidence["targetRank"] == 1


def test_full_capture_exports_exact_rank_beyond_500_and_carries_diffs(run):
    candidates = [{"parent_asin": str(i)} for i in range(550)]
    candidates[536] = {"parent_asin": "A", "reranker_score": 0.0123}
    updates = compact_trace_values({key: candidates for _, _, key in STAGES}, 0)
    nodes = [{"sample_id": "s1", "turn": turn, "stage_index": i, "nodes": [PRODUCERS[name]],
              "updates": {key: updates[key]} if turn == 1 else {}}
             for turn in (1, 2) for i, (name, _, key) in enumerate(STAGES)]
    jsonl(run / "node_traces.jsonl", nodes)
    for turn in build_payload(run)["sessions"][0]["turns"]:
        for stage in turn["stages"][:-1]:
            assert stage["targetRank"] == 537
            assert stage["status"] == "present"
            assert stage["signal"]["reranker_score"] == 0.0123


def test_jsonl_stream_preserves_unicode_and_tolerates_only_partial_last_row(tmp_path):
    path = tmp_path / "rows.jsonl"
    text = json.dumps({"title": "a\u2028b\u0085c"}, ensure_ascii=False)
    path.write_text(text + '\n{"incomplete":', encoding="utf-8")
    assert load_rows(path) == [{"title": "a\u2028b\u0085c"}]
    path.write_text(text + '\n{"incomplete":\n', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_rows(path)


def test_parallel_merge_preserves_all_candidates(tmp_path):
    shards = []
    for index in range(2):
        shard = tmp_path / str(index)
        shard.mkdir()
        snapshot = {"count": 550, "top": [{"parent_asin": str(i)} for i in range(550)]}
        jsonl(shard / "node_traces.jsonl", [{"sample_id": str(index), "turn": 1, "stage_index": 1,
              "updates": {"ranked_candidates": snapshot}}])
        shards.append({"run_path": str(shard), "shard_index": index})
    output = tmp_path / "merged.jsonl"
    _merge_node_traces(output, shards, "full-run")
    rows = load_rows(output)
    assert len(rows) == 2
    assert all(len(row["updates"]["ranked_candidates"]["top"]) == 550 for row in rows)
    assert all(row["aggregate_run_id"] == "full-run" for row in rows)


def test_evaluation_automatically_writes_trace_without_api(tmp_path):
    root = Path(__file__).resolve().parents[2]
    product = {"parent_asin": "A", "title": "Black leather belt", "categories": ["Belts"],
               "features": ["leather", "black"], "details": {}, "description": [],
               "store": "Example", "price": 30, "average_rating": 4.5, "rating_number": 100}
    jsonl(tmp_path / "catalog.jsonl", [product] + [{**product, "parent_asin": f"extra-{i:03}"} for i in range(300)])
    jsonl(tmp_path / "dataset.jsonl", [{"sample_id": "smoke", "scenario_type": "buying",
        "user_profile": {}, "ground_truth": {"parent_asin": "A"}}])
    env = {**os.environ, "SHOPPING_AGENT_ENABLE_LLM": "false", "SHOPPING_DENSE_BACKEND": "local",
           "SHOPPING_AGENT_RERANKER": "precise"}
    subprocess.run([sys.executable, str(root / "scripts/evaluate_with_traces.py"), "--no-llm",
        "--catalog", str(tmp_path / "catalog.jsonl"), "--dataset", str(tmp_path / "dataset.jsonl"),
        "--output-root", str(tmp_path / "output")], cwd=root, env=env, check=True, capture_output=True, timeout=60)
    result_dir = Path((tmp_path / "output/LATEST.txt").read_text(encoding="utf-8").strip())
    payload = json.loads((result_dir / "trace.json").read_text(encoding="utf-8"))
    assert payload["run"]["sampleCount"] == 1
    assert payload["run"]["llmEnabled"] is False
    assert payload["sessions"][0]["turns"][0]["nodeTrace"]
    config = json.loads((result_dir / "run_config.json").read_text(encoding="utf-8"))
    assert config["candidate_limit_per_node"] == 0
    assert config["candidate_capture"] == "full"
    pools = [value for node in load_rows(result_dir / "node_traces.jsonl")
             for value in node.get("updates", {}).values()
             if isinstance(value, dict) and "top" in value and "count" in value]
    assert any(pool["count"] > 200 for pool in pools)
    assert all(len(pool["top"]) == pool["count"] for pool in pools)
