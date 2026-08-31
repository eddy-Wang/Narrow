"""Versioned, portable Trace JSON; no model imports, downloads, or API replay.

Only completed sessions contribute metrics. Truncated candidate snapshots never
prove absence; unknown ranks stay unknown. Original evaluation files are read-only.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

SCHEMA = "shopping-agent.trace"
SCHEMA_VERSION = 1

STAGES = (
    ("lexical", "词法召回", "lexical_candidates"),
    ("dense", "语义召回", "dense_candidates"),
    ("attribute", "属性召回", "attribute_candidates"),
    ("fusion", "粗排融合", "fused_candidates"),
    ("filter", "硬约束过滤", "filtered_candidates"),
    ("rerank", "精排", "ranked_candidates"),
)
STAGE_KEYS = {key: (name, label) for name, label, key in STAGES}
PRODUCERS = {
    "lexical": "lexical_retrieve", "dense": "dense_retrieve_fallback",
    "attribute": "attribute_retrieve", "fusion": "rrf_fusion",
    "filter": "constraint_filter", "rerank": "rerank_fallback",
}


def iter_rows(path: Path):
    if not path.exists():
        return
    # A full trace may be large. Physical JSONL lines also preserve Unicode
    # line separators inside product text, unlike str.splitlines().
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                if line.endswith("\n"):
                    raise
                # Only an interrupted, unterminated final row is tolerated.


def load_rows(path: Path) -> list[dict]:
    return list(iter_rows(path))


def snapshot_stage(name: str, label: str, snapshot: dict | None, target: str) -> dict:
    top = (snapshot or {}).get("top", [])
    count = (snapshot or {}).get("count")
    rank = next((i for i, item in enumerate(top, 1) if item.get("parent_asin") == target), None)
    status = "present" if rank else "absent" if count is not None and count <= len(top) else "unknown"
    found = top[rank - 1] if rank else {}
    signal = {k: v for k, v in found.items() if k.endswith(("_score", "_rank", "_explanation"))
              or k in {"route_weights", "route_ranks", "constraint_evidence", "constraint_boost", "retrieval_intent"}}
    return dict(name=name, label=label, count=count, targetRank=rank, status=status,
                snapshotLimit=len(top), signal=signal or None)


def diagnosis(stages: list[dict], active: bool) -> tuple[str, str]:
    by = {s["name"]: s for s in stages}
    if by["response"]["targetRank"]:
        if not active:
            return "gated", "目标已推荐，但意图覆盖尚未生效"
        return "hit", f"目标进入最终推荐第 {by['response']['targetRank']} 名"
    ranked = by["rerank"]
    if ranked["targetRank"] and ranked["targetRank"] <= 10:
        return "response", "目标在精排 Top 10 中，但最终推荐未包含目标"
    if by["filter"]["status"] == "present" and (
        (ranked["targetRank"] or 0) > 10
        or (ranked["count"] is not None and ranked["snapshotLimit"] >= 10)
    ):
        return "rerank", "目标通过过滤，但精排后不在 Top 10（依据保存的快照）"
    if by["filter"]["status"] == "absent" and by["fusion"]["status"] == "present":
        return "filter", "完整过滤快照中没有目标商品"
    if by["fusion"]["status"] == "absent" and any(by[k]["status"] == "present" for k in ("lexical", "dense", "attribute")):
        return "fusion", "召回包含目标，但完整粗排输出中没有目标；可能涉及融合截断或粗排内部过滤"
    if all(by[k]["status"] == "absent" for k in ("lexical", "dense", "attribute")):
        return "recall", "三路完整召回快照均没有目标"
    return "unknown", "目标未进入最终推荐；快照只保存候选前部，无法确定具体流失阶段"


def compact_node(row: dict, target: str) -> dict:
    """Keep every node update, representing candidate pools by target evidence."""
    updates = {}
    for key, value in row.get("updates", {}).items():
        if key in STAGE_KEYS:
            name, label = STAGE_KEYS[key]
            updates[key] = snapshot_stage(name, label, value, target)
        else:
            updates[key] = value
    return dict(names=row.get("nodes", []), step=row.get("step"),
                createdAt=row.get("created_at"), updates=updates)


def build_payload(run: Path) -> dict:
    run = Path(run)
    config = json.loads((run / "run_config.json").read_text(encoding="utf-8"))
    sessions, turns = [], []
    # Completed aggregate files are portable: prefer them to machine-specific
    # absolute LATEST pointers. Also support single-process and partial runs.
    if (run / "sessions.jsonl").exists():
        raw_runs = [run]
    elif (run / "shards").is_dir():
        raw_runs = []
        for shard in sorted((run / "shards").iterdir()):
            latest = shard / "run" / "LATEST.txt"
            if not latest.exists():
                continue
            raw = Path(latest.read_text(encoding="utf-8").strip())
            if not raw.is_dir():
                matches = sorted((shard / "run").glob("*/sessions.jsonl"))
                if len(matches) != 1:
                    raise ValueError(f"Cannot resolve shard run: {shard.name}")
                raw = matches[0].parent
            raw_runs.append(raw)
    else:
        raise ValueError("Missing sessions.jsonl or shards directory")
    for raw in raw_runs:
        sessions.extend(load_rows(raw / "sessions.jsonl"))
        turns.extend(load_rows(raw / "turns.jsonl"))
    if not sessions:
        raise ValueError("No completed sessions are available yet")
    ids = {s["sample_id"] for s in sessions}
    if len(ids) != len(sessions):
        raise ValueError("Duplicate session IDs in shards")
    by_turn = defaultdict(list)
    by_session = defaultdict(list)
    targets = {s["sample_id"]: s["target_parent_asin"] for s in sessions}
    for raw in raw_runs:
        for node in iter_rows(raw / "node_traces.jsonl"):
            if node["sample_id"] not in targets:
                continue
            # Extract exact target evidence before discarding each full pool.
            # Memory retained for export scales with nodes, not all candidates.
            compact = compact_node(node, targets[node["sample_id"]])
            compact["stage_index"] = node["stage_index"]
            by_turn[(node["sample_id"], node["turn"])].append(compact)
    for t in turns:
        by_session[t["sample_id"]].append(t)
    if len({(t["sample_id"], t["turn"]) for t in turns}) != len(turns):
        raise ValueError("Duplicate sample/turn records")
    output, counts = [], Counter()
    for session in sorted(sessions, key=lambda s: s["sample_id"]):
        sid, target = session["sample_id"], session["target_parent_asin"]
        state, output_turns = {}, []
        for t in sorted(by_session[sid], key=lambda t: t["turn"]):
            # Trace updates are checkpoint diffs: unchanged values carry forward.
            current_nodes = sorted(by_turn[(sid, t["turn"])], key=lambda n: n["stage_index"])
            seen = {name for n in current_nodes for name in n.get("names", [])}
            for n in current_nodes:
                state.update(n.get("updates", {}))
            stages = [state[key] if PRODUCERS[name] in seen and key in state
                      else snapshot_stage(name, label, None, target)
                      for name, label, key in STAGES]
            final = [{"parent_asin": asin} for asin in t.get("recommended_parent_asins", [])]
            stages.append(snapshot_stage("response", "最终 Top 10", {"count": len(final), "top": final}, target))
            active = bool(t.get("override_applied", True))
            code, reason = diagnosis(stages, active)
            intent = t.get("intent_state") or {}
            output_turns.append(dict(
                turn=t["turn"], userMessage=t.get("user_message", ""),
                agentMessage=t.get("agent_response", {}).get("message", ""),
                recommendedAsins=t.get("recommended_parent_asins", []),
                semanticQuery=intent.get("semantic_query", ""), constraints=intent.get("active_constraints", []),
                evaluationActive=active, relaxed=bool(state.get("constraints_relaxed")),
                latencyMs=t.get("latency_ms", 0), diagnosis=code, reason=reason, stages=stages,
                error=t.get("error"), nodeTrace=[{k: v for k, v in n.items() if k != "stage_index"}
                                                for n in current_nodes],
                usage=t.get("agent_response", {}).get("usage", {}),
            ))
        if not output_turns:
            raise ValueError(f"Completed session {sid} has no turn logs")
        active_turns = [t for t in output_turns if t["evaluationActive"]]
        representative = next((t for t in active_turns if t["diagnosis"] == "hit"), None)
        representative = representative or next((t for t in active_turns if t["diagnosis"] not in ("unknown", "gated")), output_turns[-1])
        code = "hit" if session["hit"] else representative["diagnosis"]
        counts[code] += 1
        product = session.get("target_product") or {}
        output.append(dict(
            sampleId=sid, scenario=session["scenario_type"], hit=bool(session["hit"]),
            firstHitTurn=session.get("first_hit_turn"), bestRank=session.get("best_rank"),
            diagnosis=code, diagnosisReason=representative["reason"], turns=output_turns,
            target=dict(parentAsin=target, title=product.get("title", ""),
                        category=" / ".join(product.get("categories", [])[-3:]),
                        price=product.get("price"), rating=product.get("average_rating")),
        ))
    n = len(sessions)
    hit_rate = sum(s["hit"] for s in sessions) / n
    mrr = sum(s.get("reciprocal_rank", 0) for s in sessions) / n
    mttc = sum(s["first_hit_turn"] if s["hit"] else 11 for s in sessions) / n
    expected = config.get("sample_count", n)
    if n > expected:
        raise ValueError("Completed sessions exceed configured sample count")
    if (run / "summary.json").exists():
        summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
        if summary["sample_count"] != n or abs(summary["hit_rate_at_10"] - hit_rate) > 0.000001 or abs(summary["mrr"] - mrr) > 0.000001:
            raise ValueError("Saved summary does not match session records")
    return dict(schema=SCHEMA, schemaVersion=SCHEMA_VERSION, run=dict(
        id=config["run_id"], model=config.get("model", "unknown"), workers=config.get("workers", 1), reranker=config.get("reranker"),
        llmEnabled=config.get("llm_enabled"), denseBackend=config.get("dense_backend", "unknown"),
        sampleCount=n, expectedSampleCount=expected, partial=n != expected,
        incompleteSampleCount=len(set(by_session) - ids), snapshotMode=True,
        hitRate=hit_rate, mrr=mrr, mttc=mttc, technicalScore=.5 * hit_rate + .3 * mrr + .2 * (11 - mttc) / 10,
        diagnosisCounts=dict(counts),
    ), sessions=output)


def write_trace(run: Path, output: Path | None = None) -> Path:
    payload = build_payload(run)
    destination = output or run / "trace.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(destination)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(f"Saved portable trace: {write_trace(args.run_dir, args.output)}")


if __name__ == "__main__":
    main()
