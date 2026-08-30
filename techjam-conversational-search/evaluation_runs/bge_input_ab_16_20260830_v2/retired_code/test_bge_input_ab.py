"""Small, frozen-candidate input ablation. No LLM calls or production changes."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import html
import json
import os
from pathlib import Path
import random
import re
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HOME"] = str(ROOT / ".hf-cache")

from shopping_agent.domain.schemas import Constraint
from shopping_agent.ranking.cross_encoder import build_product_document, build_reranker_query


def rows(path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value)))).strip()


def norm(value):
    return " ".join(re.findall(r"\w+", clean(value).casefold()))


def flatten(value):
    if isinstance(value, dict):
        return [f"{k}: {clean(v)}" for k, v in value.items() if v not in (None, "", [])]
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value if v not in (None, "")]
    return [clean(value)] if value not in (None, "") else []


def compact_query(query, category, constraints, profile):
    # No target labels, hidden intent card, or new LLM interpretation is used.
    parts = [clean(query).rstrip(".") or clean(category)]
    if category and norm(category) not in norm(query):
        parts.append(f"Product type: {clean(category)}")
    seen = set()
    for c in constraints:
        key = (c.field, c.operator, norm(c.value), c.strength)
        if key in seen:
            continue
        seen.add(key)
        priority = "Must" if c.strength == "hard" else "Prefer to"
        value = clean(c.value)
        if c.field == "budget":
            relation = {"lte": "at most", "gte": "at least", "eq": "exactly"}.get(c.operator, c.operator)
            text = f"{priority} cost {relation} ${value}"
        elif c.operator == "not_contains":
            text = f"{priority} exclude {value} ({c.field})"
        else:
            relation = {"eq": "equal to", "contains": "including", "lte": "at most", "gte": "at least"}.get(c.operator, c.operator)
            text = f"{priority} have {c.field} {relation} {value}"
        parts.append(text)
    prefs = list(dict.fromkeys(flatten(profile.get("preference_tags"))))
    if prefs:
        parts.append("Prefer " + ", ".join(prefs))
    return ". ".join(p for p in parts if p) + "."


def compact_document(product):
    # Query-independent exact deduplication; keep factual values, move quality
    # metadata after product properties. No target-dependent evidence selection.
    lines, seen = [], set()
    fields = [("Product", "title"), ("Category", "categories"), ("Store", "store"),
              ("Price", "price"), ("Features", "features"), ("Details", "details"),
              ("Description", "description"), ("Average rating", "average_rating"),
              ("Rating count", "rating_number")]
    for label, field in fields:
        values = []
        for value in flatten(product.get(field)):
            pieces = re.split(r"(?<=[.!?])\s+", value) if field in {"features", "description"} else [value]
            for piece in pieces:
                key = norm(piece)
                if key and key not in seen:
                    seen.add(key)
                    values.append(piece)
        if values:
            lines.append(f"{label}: " + "; ".join(values))
    return "\n".join(lines)


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "evaluation_runs/main_full_trace_pro_200/20260830_154054_+0800")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    grouped = defaultdict(list)
    sessions = {s["sample_id"]: s for s in rows(args.source / "sessions.jsonl")}
    for s in sessions.values():
        grouped[s["scenario_type"]].append(s["sample_id"])
    rng = random.Random(20260830)
    selected = sorted(sid for name in sorted(grouped) for sid in rng.sample(sorted(grouped[name]), 4))
    assert len(selected) == 16
    turns = {}
    for row in rows(args.source / "turns.jsonl"):
        sid = row["sample_id"]
        if sid in selected and row["turn"] <= 3 and not row.get("error"):
            if sid not in turns or row["turn"] > turns[sid]["turn"]:
                turns[sid] = row
    assert len(turns) == 16
    snapshots = {}
    for row in rows(args.source / "node_traces.jsonl"):
        sid = row["sample_id"]
        # Traces contain state deltas: unchanged candidates carry forward.
        if sid in turns and row["turn"] <= turns[sid]["turn"]:
            snap = row.get("updates", {}).get("filtered_candidates")
            if snap is not None:
                assert len(snap["top"]) == snap["count"], "Require full candidate snapshots"
                snapshots[sid] = snap["top"]
    assert len(snapshots) == 16
    wanted = {p["parent_asin"] for group in snapshots.values() for p in group[:100]}
    products = {p["parent_asin"]: p for p in rows(ROOT / "data/catalog.jsonl") if p["parent_asin"] in wanted}
    cases = []
    for sid in selected:
        t, s = turns[sid], sessions[sid]
        intent = t["intent_state"]
        candidates = [{**products[p["parent_asin"]], **p} for p in snapshots[sid][:100]]
        target = s["target_parent_asin"]
        full_ids = [p["parent_asin"] for p in snapshots[sid]]
        cases.append(dict(sample_id=sid, scenario=s["scenario_type"], turn=t["turn"],
                          query=intent["semantic_query"], category=intent["category"],
                          constraints=intent["active_constraints"], profile=s["user_profile"],
                          target=target, candidates=candidates,
                          candidate_sha256=hashlib.sha256(json.dumps(candidates, sort_keys=True).encode()).hexdigest(),
                          target_input_rank=full_ids.index(target)+1 if target in full_ids else None,
                          source_precise_rank=t.get("raw_target_rank")))
    write_json(args.output / "frozen_inputs.json", cases)
    config = dict(source=str(args.source.resolve()), seed=20260830, sample_count=16,
                  selection="4 random sessions per scenario, independent of outcome; latest recorded non-error turn <=3",
                  model="BAAI/bge-reranker-v2-m3", top_n=100, max_length=512, batch_size=16,
                  llm_calls=0, source_pipeline="new coarse ranker; exact recorded candidates, not historical BGE replay",
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  variants={"A_original":"original query + original document", "B_query":"compact query + original document",
                            "C_document":"original query + deduplicated/reordered document", "D_both":"compact query + deduplicated/reordered document"})
    write_json(args.output / "config.json", config)
    print("Frozen 16 cases: " + ", ".join(f"{c['sample_id']}/t{c['turn']}" for c in cases), flush=True)
    import torch
    import sentence_transformers
    from sentence_transformers import CrossEncoder
    assert torch.cuda.is_available(), "GPU required for this bounded experiment"
    snapshot = ROOT / ".hf-cache/hub/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    model = CrossEncoder(str(snapshot), max_length=512, device="cuda", local_files_only=True)
    tokenizer = model.tokenizer
    config.update(torch=torch.__version__, sentence_transformers=sentence_transformers.__version__,
                  gpu=torch.cuda.get_device_name(0), model_revision=snapshot.name,
                  dtype=str(next(model.model.parameters()).dtype))
    write_json(args.output / "config.json", config)
    results = []
    with (args.output / "pairs.jsonl").open("w", encoding="utf-8") as pair_file:
        for case_i, case in enumerate(cases):
            constraints = [Constraint.model_validate(c) for c in case["constraints"]]
            old_q = build_reranker_query(case["query"], case["category"], constraints, case["profile"])
            new_q = compact_query(case["query"], case["category"], constraints, case["profile"])
            old_docs = [build_product_document(c) for c in case["candidates"]]
            new_docs = [compact_document(c) for c in case["candidates"]]
            variants = {"A_original":(old_q,old_docs), "B_query":(new_q,old_docs),
                        "C_document":(old_q,new_docs), "D_both":(new_q,new_docs)}
            result = {k:v for k,v in case.items() if k not in {"candidates", "profile"}}
            result["variants"] = {}
            # Rotate order to avoid always benchmarking one variant cold.
            names = list(variants)
            names = names[case_i % 4:] + names[:case_i % 4]
            for name in names:
                query, docs = variants[name]
                pairs = [(query, doc) for doc in docs]
                full = tokenizer([query]*len(docs), docs, padding=False, truncation=False)
                clipped = tokenizer([query]*len(docs), docs, padding=False, truncation=True, max_length=512)
                started = time.perf_counter()
                scores = model.predict(pairs, batch_size=16, show_progress_bar=False).tolist()
                elapsed = time.perf_counter() - started
                assert len(scores) == len(docs) and all(__import__('math').isfinite(v) for v in scores)
                order = sorted(range(len(scores)), key=lambda i:(-scores[i], int(case['candidates'][i].get('lexical_rank') or 999999)))
                ids = [case['candidates'][i]['parent_asin'] for i in order]
                rank = ids.index(case['target'])+1 if case['target'] in ids else None
                stats = []
                for i,candidate in enumerate(case['candidates']):
                    seq, kept = full.sequence_ids(i), clipped.sequence_ids(i)
                    stat = dict(full_tokens=len(full['input_ids'][i]), kept_tokens=len(clipped['input_ids'][i]),
                                query_tokens=seq.count(0), query_kept=kept.count(0), document_tokens=seq.count(1), document_kept=kept.count(1))
                    stats.append(stat)
                    pair_file.write(json.dumps(dict(sample_id=case['sample_id'],variant=name,asin=candidate['parent_asin'],
                                                   query=query,document=docs[i],score=scores[i],**stat),ensure_ascii=False)+"\n")
                v = dict(target_rank=rank, hit_at_10=bool(rank and rank<=10), reciprocal_rank=1/rank if rank else 0,
                         truncated_pairs=sum(s['full_tokens']>s['kept_tokens'] for s in stats),
                         mean_full_tokens=statistics.mean(s['full_tokens'] for s in stats),
                         total_dropped_tokens=sum(s['full_tokens']-s['kept_tokens'] for s in stats),
                         seconds=elapsed, top10=ids[:10], target_token_stats=next((stats[i] for i,c in enumerate(case['candidates']) if c['parent_asin']==case['target']),None))
                result['variants'][name] = v
            results.append(result)
            pair_file.flush()
            write_json(args.output/'results.json',results)
            print(f"{case_i+1}/16 {case['sample_id']} input={case['target_input_rank']} " + ' '.join(f"{n}={result['variants'][n]['target_rank']}" for n in variants),flush=True)
    total_pairs = sum(len(c['candidates']) for c in cases)
    summary = {}
    for name in config['variants']:
        values=[r['variants'][name] for r in results]
        summary[name]=dict(hits=sum(v['hit_at_10'] for v in values), hit_rate_at_10=statistics.mean(v['hit_at_10'] for v in values),
                           mrr=statistics.mean(v['reciprocal_rank'] for v in values),
                           truncated_pairs=sum(v['truncated_pairs'] for v in values), pair_count=total_pairs,
                           truncation_rate=sum(v['truncated_pairs'] for v in values)/total_pairs,
                           total_dropped_tokens=sum(v['total_dropped_tokens'] for v in values))
    summary['candidate_coverage']=sum(c['target_input_rank'] is not None and c['target_input_rank']<=100 for c in cases)
    summary['paired_D_vs_A']={label:sum((r['variants']['D_both']['target_rank'] or 101)*sign < (r['variants']['A_original']['target_rank'] or 101)*sign for r in results) for label,sign in [('improved',1),('worsened',-1)]}
    summary['paired_D_vs_A']['unchanged']=16-sum(summary['paired_D_vs_A'].values())
    write_json(args.output/'summary.json',summary)
    lines=['# BGE 输入小样本对照实验','',
           '16 个会话，每类场景随机抽 4 个（固定种子 20260830），每会话取已记录的第 1–3 轮中最后一轮。选样不看目标排名或命中。',
           '使用 20260830_154054 新粗排链路的完整快照，所有版本共享同一前 100 候选；从目录补齐快照省略的 Details/Description。没有重新调用 LLM，没有改生产排序器。',
           '这是固定请求状态的排序实验，不是完整多轮评测，也不是早先 BGE 失败运行的精确重放。原运行提前命中会停止，因此部分会话只有第一轮。',
           '四组均使用同一模型、float32、512 token 和 batch_size=16。B 保留已记录约束和偏好，改用自然语言表达；C 做 HTML/空白清理、精确重复片段删除、质量信息后移。没有按目标选取或生成商品证据。','',
           '| 版本 | Top10 命中 | MRR | 截断文本对 |','|---|---:|---:|---:|']
    for name in config['variants']:
        v=summary[name];lines.append(f"| {name} | {v['hits']}/16 | {v['mrr']:.4f} | {v['truncated_pairs']}/{total_pairs} ({v['truncation_rate']:.1%}) |")
    lines += ['',f"目标进入前 100 候选：{summary['candidate_coverage']}/16。候选外目标在所有版本均记为未命中、RR=0。",'',
              '| 样本 | 场景 | 轮次 | 输入排名 | A 原版 | B 只改需求 | C 只改商品 | D 全改 |','|---|---|---:|---:|---:|---:|---:|---:|']
    for r in results:
        vals=[str(r['variants'][name]['target_rank'] or '候选外') for name in config['variants']]
        lines.append(f"| {r['sample_id']} | {r['scenario']} | {r['turn']} | {r['target_input_rank'] or '不在候选池'} | " + ' | '.join(vals)+' |')
    lines += ['', 'MRR 为冻结候选前100内的 reciprocal rank 均值，不等同于比赛会话 MRR；样本很小且按场景均衡抽取，不代表官方场景比例。',
              '截断率只说明输入被截短，不能单独证明丢掉的是关键证据。C 同时改变去重与字段顺序，不能将效果只归因于去重。',
              'frozen_inputs.json 保存完整实验输入；pairs.jsonl 保存每个版本的实际文本、分数和截断计数；results.json 保存逐样本结果。']
    (args.output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
