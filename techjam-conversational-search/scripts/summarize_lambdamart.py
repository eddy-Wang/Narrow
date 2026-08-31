"""Summarize a completed experiment without changing or selecting any model."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
from evaluator.local_evaluator import metric_summary


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    out = args.run
    summary = read(out / "summary.json")
    manifest = read(out / "split_manifest.json")
    names = ["precise", "linear_same_data", "lambdamart"]
    sessions = {name: read(out / (name+"_sessions.json"))["sessions"] for name in names}
    scenarios = sorted({sample["scenario_type"] for sample in manifest["test"]})
    by_scenario = {scenario: {name: metric_summary([s for s in sessions[name] if s["scenario_type"] == scenario])
                             for name in names} for scenario in scenarios}
    groups = read(out / "test_frozen_groups.json")
    recalled = {g["sample_id"] for g in groups if g["target"] in g["candidate_ids"]}
    candidate_coverage = {
        "sessions": len(manifest["test"]),
        "sessions_with_target_in_any_recorded_candidate_pool": len(recalled),
        "coverage": len(recalled) / len(manifest["test"]),
        "note": "Measured on baseline dialogue trajectories, excluding pre-override rounds; not the recall ceiling for other dialogue policies."
    }
    indexed = {name: {s["sample_id"]: s for s in rows} for name, rows in sessions.items()}
    changes = {}
    for baseline in ["precise", "linear_same_data"]:
        a, b = indexed[baseline], indexed["lambdamart"]
        changes[baseline] = {
            "tree_only_hits": [sid for sid in a if b[sid]["hit"] and not a[sid]["hit"]],
            "baseline_only_hits": [sid for sid in a if a[sid]["hit"] and not b[sid]["hit"]],
        }
    diagnostic = {"by_scenario": by_scenario, "candidate_coverage": candidate_coverage,
                  "hit_changes": changes}
    (out / "diagnostics.json").write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    lines = ["", "## 场景拆分（Hit@10 / MRR）", "",
             "| 场景 | 样本 | 原精排 | 同数据线性 | LambdaMART |",
             "|---|---:|---:|---:|---:|"]
    for scenario, results in by_scenario.items():
        cells = [f"{results[n]['hit_rate_at_10']:.3f} / {results[n]['mrr']:.4f}" for n in names]
        lines.append(f"| {scenario} | {results[names[0]]['sample_count']} | "+" | ".join(cells)+" |")
    lines += ["", "原精排对话轨迹中，至少一轮候选池包含目标的会话："
              f"{len(recalled)}/{len(manifest['test'])}。这是该轨迹下的召回覆盖，不是其他对话策略的召回上限。",
              "", "与同数据线性模型的配对 TechnicalScore 差值及95%区间："
              +json.dumps(summary["paired_lambdamart_vs_same_data_linear"], ensure_ascii=False),
              "", "隔离说明：新模型的训练/验证排除官方目标，但采集轨迹仍使用历史 Precise；"
              "历史 Precise 的训练目标与官方商品有重合。因此商品隔离约束针对新训练数据，不能声称整个系统从未接触过测试目标。",
              "", "延迟只统计每次 rank 调用，包含特征提取和打分；初始化不计入。"
              "冻结测试数据的额外采集发生在计时外，完整运行 wall_seconds 不用于比较精排延迟。"]
    report = out / "report.md"
    text = report.read_text(encoding="utf-8").split("\n## 场景拆分（Hit@10 / MRR）")[0]
    report.write_text(text.rstrip()+"\n"+"\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps(diagnostic, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
