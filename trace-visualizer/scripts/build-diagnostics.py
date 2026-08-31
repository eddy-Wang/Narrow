from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SITE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_ROOT = SITE_ROOT.parent / "techjam-conversational-search"
DEFAULT_EVALUATION_ROOT = DEFAULT_PROJECT_ROOT / "evaluation_runs" / "parallel_pro_200"

# Freeze the pre-migration fit for historical main runs. Using today's default
# weights would silently change the meaning of their replayed ranks.
LEGACY_PRECISE_WEIGHTS = {
    "exact_matches": -0.5059620374702732,
    "partial_matches": -16.319593300125614,
    "category_match": 1.1545720987697576,
    "term_coverage": 3.1478954332186824,
    "lexical_signal": 5.583730290442667,
    "rrf_raw": 60.50718504951105,
    "dense_raw": -2.785817996711811,
    "attribute_raw": 0.48373242928076143,
    "profile_match": 0.9653461568603957,
    "quality": 21.904037688336764,
    "contradictions": -4.186928093131388,
    "budget_penalty": 0.0,
    "novelty_penalty": -1.5694228370472272,
}


def build_replay_nodes(catalog, reranker_config, *, new_coarse: bool, dense_backend: str = "local"):
    from shopping_agent.domain.schemas import Constraint
    from shopping_agent.orchestration.nodes import ShoppingGraphNodes
    from shopping_agent.ranking.fallback import FallbackReranker
    from shopping_agent.ranking.precise import PreciseReranker
    from shopping_agent.retrieval.attributes import AttributeIndex
    from shopping_agent.retrieval.coarse import CoarseRanker
    from shopping_agent.retrieval.fusion import reciprocal_rank_fusion
    from shopping_agent.retrieval.semantic import LocalDenseIndex

    # This historical helper has never supported replaying embedding runs.
    # Export their recorded snapshots instead of substituting local retrieval.
    if dense_backend != "local":
        raise ValueError("BGE retrieval replay is unsupported; use scripts/export_trace.py for recorded evidence")
    mode = reranker_config["mode"]
    if mode not in {"precise", "fallback"}:
        raise ValueError("Retired or unsupported reranker; use scripts/export_trace.py for recorded evidence")
    semantic = LocalDenseIndex(catalog)
    attributes = AttributeIndex(catalog)
    reranker = PreciseReranker(catalog_products=catalog.products) if mode == "precise" else FallbackReranker()
    if not new_coarse and reranker_config["mode"] == "precise":
        reranker = PreciseReranker(catalog_products=catalog.products, weights=LEGACY_PRECISE_WEIGHTS)

    class LegacyNodes(ShoppingGraphNodes):
        def dense_retrieve(self, state):
            return {"dense_candidates": self.semantic_retriever.search(
                state.get("semantic_query", "") or state.get("search_query", ""), limit=200)}

        def attribute_retrieve(self, state):
            return {"attribute_candidates": self.attribute_index.search(
                state.get("category", ""),
                [Constraint.model_validate(item) for item in state.get("active_constraints", [])], limit=200)}

        def fuse_candidates(self, state):
            return {"fused_candidates": reciprocal_rank_fusion([
                (state.get("lexical_candidates", []), 1.0),
                (state.get("dense_candidates", []), 0.35),
                (state.get("attribute_candidates", []), 0.45),
            ])}

        def apply_constraints(self, state):
            constraints = [Constraint.model_validate(item) for item in state.get("active_constraints", [])]
            return {"filtered_candidates": [item for item in state.get("fused_candidates", [])
                    if not self.catalog.violates_hard_constraint(item, constraints)]}

    node_type = ShoppingGraphNodes if new_coarse else LegacyNodes
    return node_type(catalog=catalog, semantic_retriever=semantic, attribute_index=attributes,
                     coarse_ranker=CoarseRanker(catalog, semantic, attributes), reranker=reranker)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rank_of(items: list[dict[str, Any]], target: str) -> int | None:
    for index, item in enumerate(items, start=1):
        if str(item.get("parent_asin", "")) == target:
            return index
    return None


def target_signal(items: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    for item in items:
        if str(item.get("parent_asin", "")) != target:
            continue
        keys = (
            "lexical_score",
            "dense_score",
            "attribute_score",
            "rrf_score",
            "route_count",
            "reranker_score",
            "reranker_explanation",
            "route_weights",
            "route_ranks",
            "constraint_evidence",
            "constraint_boost",
            "coarse_score",
            "price",
            "average_rating",
            "rating_number",
        )
        return {key: item[key] for key in keys if key in item}
    return None


def stage(name: str, label: str, items: list[dict[str, Any]], target: str) -> dict[str, Any]:
    rank = rank_of(items, target)
    return {
        "name": name,
        "label": label,
        "count": len(items),
        "targetRank": rank,
        "status": "present" if rank is not None else "absent",
        "signal": target_signal(items, target),
    }


def diagnose(stages: list[dict[str, Any]], final_rank: int | None, evaluation_active: bool, *, new_coarse: bool = False) -> tuple[str, str]:
    by_name = {item["name"]: item for item in stages}
    recall_names = ("lexical", "dense", "attribute")
    recalled = any(by_name[name]["targetRank"] is not None for name in recall_names)
    if not recalled:
        return "recall", "三路召回都没有找回目标商品"
    if by_name["fusion"]["targetRank"] is None:
        if new_coarse:
            return "fusion", "目标在粗排内被 Top 500 截断或因硬约束过滤"
        return "fusion", "目标被 RRF Top 500 截断"
    if by_name["filter"]["targetRank"] is None:
        return "filter", "目标违反硬约束，被过滤节点删除"
    if by_name["rerank"]["targetRank"] is None:
        return "rerank", "目标未进入精排候选"
    if by_name["rerank"]["targetRank"] > 10:
        return "rerank", f"目标精排后位于第 {by_name['rerank']['targetRank']} 名，未进入 Top 10"
    if final_rank is None:
        return "response", "目标已进精排 Top 10，但未进入最终推荐"
    if not evaluation_active:
        return "gated", "目标已推荐，但意图覆盖尚未生效，官方评测暂不计命中"
    return "hit", f"目标进入最终推荐第 {final_rank} 名"


def resolve_run_root(evaluation_root: Path, run_dir: str | None) -> Path:
    if run_dir:
        candidate = Path(run_dir)
        return candidate.resolve() if candidate.is_absolute() else (Path.cwd() / candidate).resolve()
    latest_file = evaluation_root / "LATEST.txt"
    if not latest_file.exists():
        raise SystemExit(f"LATEST.txt not found: {latest_file}")
    candidate = Path(latest_file.read_text(encoding="utf-8").strip())
    return candidate.resolve() if candidate.is_absolute() else (evaluation_root / candidate).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay one traced official evaluation and build frontend diagnostics.json"
    )
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--evaluation-root", type=Path, default=DEFAULT_EVALUATION_ROOT)
    parser.add_argument(
        "--run-dir",
        help="Evaluation run directory. Omit to use <evaluation-root>/LATEST.txt.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=SITE_ROOT / "public" / "diagnostics.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    evaluation_root = args.evaluation_root.resolve()
    run_root = resolve_run_root(evaluation_root, args.run_dir)
    destination = args.output.resolve()

    required = ("sessions.jsonl", "turns.jsonl", "node_traces.jsonl", "summary.json")
    missing = [name for name in required if not (run_root / name).exists()]
    if missing:
        raise SystemExit(f"Run directory is incomplete ({', '.join(missing)}): {run_root}")

    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))
    from shopping_agent.retrieval.lexical import CatalogIndex

    sessions = load_jsonl(run_root / "sessions.jsonl")
    turns = load_jsonl(run_root / "turns.jsonl")
    nodes = load_jsonl(run_root / "node_traces.jsonl")
    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    config_path = run_root / "run_config.json"
    run_config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    # Trace evidence distinguishes the old fixed fusion from the migrated policy.
    new_coarse = any("retrieval_intent" in row.get("updates", {}) for row in nodes)
    # Historical runs used PreciseReranker. Never replay using an unrelated shell setting.
    reranker_config = run_config.get("reranker", {"mode": "precise"})

    turns_by_sample: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for turn in turns:
        turns_by_sample[str(turn["sample_id"])].append(turn)

    patch_action: dict[tuple[str, int], str] = {}
    for row in nodes:
        patch = row.get("updates", {}).get("semantic_patch")
        if isinstance(patch, dict):
            patch_action[(str(row["sample_id"]), int(row["turn"]))] = str(patch.get("action", "add"))

    catalog = CatalogIndex(project_root / "data" / "catalog.jsonl")
    graph_nodes = build_replay_nodes(
        catalog, reranker_config, new_coarse=new_coarse,
        dense_backend=run_config.get("dense_backend", "local"),
    )

    output_sessions: list[dict[str, Any]] = []
    diagnosis_counts: Counter[str] = Counter()

    for session_index, session in enumerate(sessions, start=1):
        sample_id = str(session["sample_id"])
        target = str(session["target_parent_asin"])
        recommended_history: list[str] = []
        output_turns: list[dict[str, Any]] = []

        for turn in sorted(turns_by_sample[sample_id], key=lambda item: int(item["turn"])):
            turn_number = int(turn["turn"])
            if patch_action.get((sample_id, turn_number)) == "replace":
                recommended_history = []

            intent = turn.get("intent_state") or {}
            state: dict[str, Any] = {
                "turn": turn_number,
                "user_message": turn.get("user_message", ""),
                "category": intent.get("category", ""),
                "active_constraints": intent.get("active_constraints", []),
                "semantic_query": intent.get("semantic_query", ""),
                "user_profile": session.get("user_profile", {}),
                "recommended_asins": list(recommended_history),
            }
            state.update(graph_nodes.build_query(state))
            if new_coarse and intent.get("retrieval_intent"):
                state["retrieval_intent"] = intent["retrieval_intent"]
            lexical = graph_nodes.lexical_retrieve(state)["lexical_candidates"]
            dense = graph_nodes.dense_retrieve(state)["dense_candidates"]
            attribute = graph_nodes.attribute_retrieve(state)["attribute_candidates"]
            state.update({
                "lexical_candidates": lexical,
                "dense_candidates": dense,
                "attribute_candidates": attribute,
            })
            fused = graph_nodes.fuse_candidates(state)["fused_candidates"]
            state["fused_candidates"] = fused
            filtered = graph_nodes.apply_constraints(state)["filtered_candidates"]
            state["filtered_candidates"] = filtered
            relaxed = len(filtered) < 30
            if relaxed:
                state.update(graph_nodes.relax_and_backfill(state))
            ranked = graph_nodes.rerank(state)["ranked_candidates"]
            final_ids = [
                {"parent_asin": parent_asin}
                for parent_asin in turn.get("recommended_parent_asins", [])
            ]
            final_rank = rank_of(final_ids, target)

            stages = [
                stage("lexical", "词法召回", lexical, target),
                stage("dense", "语义召回", dense, target),
                stage("attribute", "属性召回", attribute, target),
                stage("fusion", "粗排融合" if new_coarse else "RRF 融合", fused, target),
                stage("filter", "硬约束过滤", filtered, target),
                stage("rerank", "精排", ranked, target),
                stage("response", "最终 Top 10", final_ids, target),
            ]
            evaluation_active = bool(turn.get("override_applied", True))
            diagnosis, reason = diagnose(stages, final_rank, evaluation_active, new_coarse=new_coarse)
            output_turns.append({
                "turn": turn_number,
                "userMessage": turn.get("user_message", ""),
                "semanticQuery": intent.get("semantic_query", ""),
                "constraints": intent.get("active_constraints", []),
                "evaluationActive": evaluation_active,
                "relaxed": relaxed,
                "latencyMs": turn.get("latency_ms"),
                "diagnosis": diagnosis,
                "reason": reason,
                "stages": stages,
            })
            recommended_history.extend(turn.get("recommended_parent_asins", []))
            recommended_history = list(dict.fromkeys(recommended_history))

        active_turns = [item for item in output_turns if item["evaluationActive"]]
        representative = next((item for item in active_turns if item["diagnosis"] == "hit"), None)
        if representative is None and active_turns:
            priority = {"response": 0, "rerank": 1, "filter": 2, "fusion": 3, "recall": 4}
            representative = min(active_turns, key=lambda item: priority.get(item["diagnosis"], 9))
        representative = representative or output_turns[-1]
        session_diagnosis = "hit" if session.get("hit") else representative["diagnosis"]
        diagnosis_counts[session_diagnosis] += 1

        product = session.get("target_product") or {}
        output_sessions.append({
            "sampleId": sample_id,
            "scenario": session.get("scenario_type"),
            "hit": bool(session.get("hit")),
            "firstHitTurn": session.get("first_hit_turn"),
            "bestRank": session.get("best_rank"),
            "diagnosis": session_diagnosis,
            "diagnosisReason": representative["reason"],
            "target": {
                "parentAsin": target,
                "title": product.get("title", ""),
                "category": " / ".join(str(value) for value in product.get("categories", [])[-3:]),
                "price": product.get("price"),
                "rating": product.get("average_rating"),
            },
            "turns": output_turns,
        })
        if session_index % 20 == 0:
            print(f"diagnosed {session_index}/{len(sessions)}", flush=True)

    payload = {
        "run": {
            "id": summary.get("run_id"),
            "model": summary.get("model"),
            "reranker": reranker_config,
            "coarseRanker": "yxh_3" if new_coarse else "legacy_fixed_rrf",
            "evidenceSource": "replayed",
            "workers": summary.get("workers"),
            "sampleCount": summary.get("sample_count"),
            "hitRate": summary.get("hit_rate_at_10"),
            "mrr": summary.get("mrr"),
            "technicalScore": summary.get("recommended_technical_score"),
            "diagnosisCounts": dict(diagnosis_counts),
        },
        "sessions": output_sessions,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {destination} ({destination.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
