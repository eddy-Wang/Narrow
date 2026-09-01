from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn


def _fail(zh: str, en: str, *, detail: str | None = None) -> NoReturn:
    print(f"[错误] {zh}\n[ERROR] {en}", file=sys.stderr, flush=True)
    if detail:
        secret = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if secret:
            detail = detail.replace(secret, "[REDACTED]")
        print(f"[原因 / Reason]\n{detail}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def _worker_failure(shard_index: int, return_code: int, shard_dir: Path) -> str:
    """Return a bilingual error with the worker's useful stderr tail."""
    stderr_path = shard_dir / "stderr.log"
    stdout_path = shard_dir / "stdout.log"
    detail = ""
    for path in (stderr_path, stdout_path):
        try:
            with path.open("rb") as handle:
                handle.seek(0, 2)
                handle.seek(max(0, handle.tell() - 65536))
                lines = [line for line in handle.read().decode("utf-8", errors="replace").splitlines() if line.strip()]
        except OSError:
            continue
        if lines:
            detail = "\n".join(lines[-12:])[-4000:]
            break
    secret = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if secret:
        detail = detail.replace(secret, "[REDACTED]")
    return (
        f"[错误] 评测 worker {shard_index + 1} 执行失败（退出码 {return_code}）。\n"
        f"[ERROR] Evaluation worker {shard_index + 1} failed (exit code {return_code}).\n"
        + (f"[原因 / Reason]\n{detail}\n" if detail else "[原因 / Reason]\nworker 未输出错误详情 / worker produced no error detail\n")
        + f"[日志 / Logs] {stderr_path} | {stdout_path}"
    )


def _print_worker_errors(path: Path, offset: int) -> int:
    """Forward complete error lines once, without replaying worker progress logs."""
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            while line := handle.readline():
                if not line.endswith(b"\n"):
                    break
                offset = handle.tell()
                text = line.decode("utf-8", errors="replace").rstrip()
                if text.startswith("[错误 / ERROR]"):
                    print(text, file=sys.stderr, flush=True)
    except OSError:
        pass
    return offset


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        rows = []
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                _fail(f"JSONL 格式错误：{path}，第 {line_number} 行。",
                      f"Invalid JSONL: {path}, line {line_number}.", detail=exc.msg)
        return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _merge_node_traces(path: Path, shard_runs: list[dict[str, Any]], run_id: str) -> None:
    """Copy full candidate traces one row at a time; readers group by sample/turn/stage."""
    with path.open("w", encoding="utf-8") as output:
        for shard in shard_runs:
            with (Path(shard["run_path"]) / "node_traces.jsonl").open(encoding="utf-8") as source:
                for line in source:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    row.update(aggregate_run_id=run_id, shard_index=shard["shard_index"])
                    output.write(json.dumps(row, ensure_ascii=False) + "\n")


def _last_jsonl_row(path: Path) -> dict[str, Any]:
    """Read only a small tail; tolerate a worker still writing its last line."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - 65536))
            lines = handle.read().splitlines()
        for line in reversed(lines):
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    return row
            except (ValueError, UnicodeDecodeError):
                continue
    except OSError:
        pass
    return {}


def _shard_progress(raw_root: Path) -> tuple[int, dict[str, Any]]:
    try:
        run_dir = Path((raw_root / "LATEST.txt").read_text(encoding="utf-8").strip())
        with (run_dir / "sessions.jsonl").open("rb") as handle:
            completed = sum(1 for line in handle if line.strip() and line.endswith(b"\n"))
        return completed, _last_jsonl_row(run_dir / "turns.jsonl")
    except OSError:
        return 0, {}


def _duration(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def _print_progress(processes, shards, started: float) -> None:
    completed = 0
    details = []
    for index, process, _, _, raw_root in processes:
        count, last = _shard_progress(raw_root)
        completed += count
        label = f"w{index + 1}={count}/{len(shards[index])}"
        if process.poll() is not None:
            label += f" exit={process.returncode}"
        elif last:
            label += f" last:{last.get('sample_id')}/turn{last.get('turn')}"
            if last.get("error"):
                label += " ERROR"
        else:
            label += " loading/waiting"
        details.append(label)
    total = sum(len(shard) for shard in shards)
    elapsed = time.perf_counter() - started
    eta = _duration(elapsed * max(total - completed, 0) / completed) if completed else "estimating"
    print(
        f"[progress] {completed}/{total} ({100 * completed / max(total, 1):.1f}%) "
        f"elapsed={_duration(elapsed)} ETA~{eta}\n  " + " | ".join(details),
        flush=True,
    )


def _stop_workers(processes) -> None:
    """Ctrl+C must also stop Windows venv launcher child processes."""
    for _, process, _, _, _ in processes:
        if process.poll() is not None:
            continue
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        else:
            process.terminate()


def _summary(sessions: list[dict[str, Any]], usage: dict[str, int]) -> dict[str, Any]:
    from evaluator.local_evaluator import metric_summary

    score_rows = [
        {
            "hit": row["hit"],
            "first_hit_turn": row["first_hit_turn"],
            "best_rank": row["best_rank"],
            "reciprocal_rank": row["reciprocal_rank"],
        }
        for row in sessions
    ]
    overall = metric_summary(score_rows)
    efficiency = max(0.0, min(1.0, (11.0 - float(overall["mttc"])) / 10.0))
    technical_score = (
        0.50 * overall["hit_rate_at_10"]
        + 0.30 * overall["mrr"]
        + 0.20 * efficiency
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for session, score in zip(sessions, score_rows):
        grouped[str(session["scenario_type"])].append(score)
    return {
        **overall,
        "efficiency": round(efficiency, 6),
        "recommended_technical_score": round(technical_score, 6),
        "reported_token_usage": {
            **usage,
            "total_tokens": usage["prompt_tokens"] + usage["completion_tokens"],
        },
        "scenario_metrics": {
            name: metric_summary(grouped[name]) for name in sorted(grouped)
        },
    }


def _report(summary: dict[str, Any], config: dict[str, Any]) -> str:
    usage = summary["reported_token_usage"]
    lines = [
        "# Parallel Traced Evaluation Report",
        "",
        f"Run: `{config['run_id']}`  ",
        f"Model: `{config['model']}`  ",
        f"Workers: `{config['workers']}`  ",
        f"Samples: `{summary['sample_count']}`",
        "",
        "## Score",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Hit Rate@10 | {summary['hit_rate_at_10']:.6f} |",
        f"| MRR | {summary['mrr']:.6f} |",
        f"| MTTC | {summary['mttc']:.6f} |",
        f"| Efficiency | {summary['efficiency']:.6f} |",
        f"| Technical Score | {summary['recommended_technical_score']:.6f} |",
        f"| Failed turns / 失败轮次 | {summary.get('failed_turn_count', 0)} |",
        f"| Prompt tokens | {usage['prompt_tokens']} |",
        f"| Completion tokens | {usage['completion_tokens']} |",
        f"| Total tokens | {usage['total_tokens']} |",
        "",
        "## Scenario breakdown",
        "",
        "| Scenario | Samples | Hit Rate | MRR | MTTC |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, metrics in summary["scenario_metrics"].items():
        lines.append(
            f"| {name} | {metrics['sample_count']} | "
            f"{metrics['hit_rate_at_10']:.6f} | {metrics['mrr']:.6f} | "
            f"{metrics['mttc']:.6f} |"
        )
    lines.extend([
        "",
        "Complete aggregate data is stored in `sessions.jsonl`, `turns.jsonl`,",
        "and `node_traces.jsonl`. Per-worker raw outputs and logs are under `shards/`.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run traced LLM evaluation in isolated parallel shards and aggregate results"
    )
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--output-root", default="evaluation_runs/parallel_traced")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--ltr-model-dir", type=Path, help="Opt-in frozen LTR bundle and detailed audit")
    parser.add_argument("--ltr-ranker", choices=["precise", "linear_same_data", "lambdamart"], default="precise")
    parser.add_argument("--model", help="Model name; defaults to DEEPSEEK_MODEL from .env")
    parser.add_argument("--candidate-limit", type=int, default=0,
                        help="Candidates recorded per node: 0 saves all (default); positive values truncate")
    parser.add_argument("--progress-interval", type=float, default=10.0)
    args = parser.parse_args()
    if args.candidate_limit < 0:
        _fail("--candidate-limit 不能小于 0；0 表示保存全部候选。",
              "--candidate-limit must be >= 0; use 0 to save all candidates.")
    if args.candidate_limit:
        print("WARNING: candidate snapshots will be truncated; ranks beyond the limit may be unknown", flush=True)

    if args.workers < 1:
        _fail("--workers 必须至少为 1。", "--workers must be at least 1.")
    if args.progress_interval <= 0:
        _fail("--progress-interval 必须大于 0。", "--progress-interval must be positive.")

    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
    args.model = args.model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    reranker_config = {"mode": args.ltr_ranker if args.ltr_model_dir else "precise"}
    if args.ltr_model_dir:
        import hashlib
        reranker_config.update(model_dir=str(args.ltr_model_dir.resolve()),
            model_sha256=hashlib.sha256((args.ltr_model_dir/"model.txt").read_bytes()).hexdigest())
    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        _fail(
            "DEEPSEEK_API_KEY 为空；请在 techjam-conversational-search/.env 中配置。",
            "DEEPSEEK_API_KEY is empty; configure it in techjam-conversational-search/.env.",
        )

    dataset_path = (project_root / args.dataset).resolve()
    catalog_path = (project_root / args.catalog).resolve()
    for path in (catalog_path, dataset_path):
        if not path.is_file():
            _fail(f"找不到输入文件：{path}", f"Input file not found: {path}")
    print(f"Catalog: {catalog_path}\nDataset: {dataset_path}", flush=True)
    print(f"Model: {args.model} | Reranker: {reranker_config['mode']}", flush=True)
    samples = _load_jsonl(dataset_path)
    if not samples:
        _fail(f"测试集为空：{dataset_path}", f"Dataset is empty: {dataset_path}")
    worker_count = min(args.workers, max(len(samples), 1))
    print(f"Samples: {len(samples)} | Workers: {worker_count}", flush=True)
    run_id = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%z")
    output_root = (project_root / args.output_root).resolve()
    output_dir = output_root / run_id
    shards_dir = output_dir / "shards"
    shards_dir.mkdir(parents=True, exist_ok=False)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "LATEST.txt").write_text(str(output_dir) + "\n", encoding="utf-8")
    config = {
        "run_id": run_id,
        "model": args.model,
        "workers": worker_count,
        "llm_enabled": True,
        "dense_backend": os.getenv("SHOPPING_DENSE_BACKEND", "local"),
        "catalog": str(catalog_path),
        "dataset": str(dataset_path),
        "sample_count": len(samples),
        "candidate_limit_per_node": args.candidate_limit,
        "candidate_capture": "full" if args.candidate_limit == 0 else "limited",
        "reranker": reranker_config,
        "started_at": datetime.now().astimezone().isoformat(),
    }
    (output_dir / "run_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    shards: list[list[dict[str, Any]]] = [[] for _ in range(worker_count)]
    for index, sample in enumerate(samples):
        shards[index % worker_count].append(sample)

    env = os.environ.copy()
    env["DEEPSEEK_MODEL"] = args.model
    env["SHOPPING_AGENT_ENABLE_LLM"] = "true"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    processes: list[tuple[int, subprocess.Popen[str], Any, Any, Path]] = []
    started = time.perf_counter()
    for shard_index, shard_samples in enumerate(shards):
        shard_dir = shards_dir / f"shard_{shard_index:02d}"
        shard_dir.mkdir()
        shard_dataset = shard_dir / "dataset.jsonl"
        _write_jsonl(shard_dataset, shard_samples)
        raw_root = shard_dir / "run"
        stdout_handle = (shard_dir / "stdout.log").open("w", encoding="utf-8")
        stderr_handle = (shard_dir / "stderr.log").open("w", encoding="utf-8")
        command = [
            sys.executable,
            str(project_root / "scripts" / "evaluate_with_traces.py"),
            "--llm",
            "--catalog",
            str(catalog_path),
            "--dataset",
            str(shard_dataset),
            "--output-root",
            str(raw_root),
            "--candidate-limit",
            str(args.candidate_limit),
        ]
        if args.ltr_model_dir:
            command += ["--ltr-model-dir", str(args.ltr_model_dir.resolve()), "--ltr-ranker", args.ltr_ranker]
        try:
            process = subprocess.Popen(
                command, cwd=project_root, env=env,
                stdout=stdout_handle, stderr=stderr_handle, text=True,
            )
        except Exception:
            _stop_workers(processes)
            stdout_handle.close()
            stderr_handle.close()
            for _, _, out, err, _ in processes:
                out.close()
                err.close()
            raise
        processes.append((shard_index, process, stdout_handle, stderr_handle, raw_root))
        print(
            f"started shard {shard_index + 1}/{worker_count}: "
            f"samples={len(shard_samples)} pid={process.pid}",
            flush=True,
        )

    pending = {item[0] for item in processes}
    error_offsets = {item[0]: 0 for item in processes}
    failures: list[str] = []
    next_progress = time.perf_counter()
    try:
        while pending:
            for shard_index, process, stdout_handle, stderr_handle, _ in processes:
                if shard_index not in pending:
                    continue
                error_offsets[shard_index] = _print_worker_errors(
                    Path(stderr_handle.name), error_offsets[shard_index],
                )
                return_code = process.poll()
                if return_code is None:
                    continue
                error_offsets[shard_index] = _print_worker_errors(
                    Path(stderr_handle.name), error_offsets[shard_index],
                )
                stdout_handle.close()
                stderr_handle.close()
                pending.remove(shard_index)
                print(
                    f"finished shard {shard_index + 1}/{worker_count}: exit={return_code} "
                    f"remaining={len(pending)}",
                    flush=True,
                )
                if return_code != 0:
                    failures.append(_worker_failure(
                        shard_index, return_code, output_dir / "shards" / f"shard_{shard_index:02d}",
                    ))
            if time.perf_counter() >= next_progress or not pending:
                _print_progress(processes, shards, started)
                next_progress = time.perf_counter() + args.progress_interval
            if failures:
                _stop_workers(processes)
                break
            if pending:
                time.sleep(min(2, args.progress_interval))
    except KeyboardInterrupt:
        _stop_workers(processes)
        print("[已停止 / Stopped] 已停止所有评测 worker；保留已有日志和产物。\n"
              "All evaluation workers stopped. Partial logs and artifacts are preserved.", flush=True)
        raise SystemExit(130)
    finally:
        for _, _, stdout_handle, stderr_handle, _ in processes:
            stdout_handle.close()
            stderr_handle.close()

    if failures:
        print("\n\n".join(failures), file=sys.stderr, flush=True)
        raise SystemExit(1)

    aggregate_sessions: list[dict[str, Any]] = []
    aggregate_turns: list[dict[str, Any]] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    shard_runs: list[dict[str, Any]] = []
    for shard_index, _, _, _, raw_root in processes:
        run_path = Path((raw_root / "LATEST.txt").read_text(encoding="utf-8").strip())
        shard_summary = json.loads((run_path / "summary.json").read_text(encoding="utf-8"))
        for key in usage:
            usage[key] += int(shard_summary["reported_token_usage"].get(key, 0))
        for filename, target in (
            ("sessions.jsonl", aggregate_sessions),
            ("turns.jsonl", aggregate_turns),
        ):
            for row in _load_jsonl(run_path / filename):
                row["aggregate_run_id"] = run_id
                row["shard_index"] = shard_index
                target.append(row)
        shard_runs.append({
            "shard_index": shard_index,
            "run_path": str(run_path),
            "summary": shard_summary,
        })

    aggregate_sessions.sort(key=lambda row: str(row["sample_id"]))
    aggregate_turns.sort(key=lambda row: (str(row["sample_id"]), int(row["turn"])))
    _write_jsonl(output_dir / "sessions.jsonl", aggregate_sessions)
    _write_jsonl(output_dir / "turns.jsonl", aggregate_turns)
    _merge_node_traces(output_dir / "node_traces.jsonl", shard_runs, run_id)
    if args.ltr_model_dir:
        for filename in ("llm_calls.jsonl", "rank_calls.jsonl"):
            with (output_dir/filename).open("w", encoding="utf-8") as handle:
                for shard in shard_runs:
                    with (Path(shard["run_path"])/filename).open(encoding="utf-8") as source:
                        for line in source:
                            if line.strip():
                                row = json.loads(line)
                                row.update(aggregate_run_id=run_id, shard_index=shard["shard_index"])
                                handle.write(json.dumps(row, ensure_ascii=False)+"\n")

    summary = _summary(aggregate_sessions, usage)
    failed_turns = sum(bool(row.get("error")) for row in aggregate_turns)
    summary.update({
        "run_id": run_id,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "workers": worker_count,
        "model": args.model,
        "reranker": reranker_config,
        "shard_runs": shard_runs,
        "failed_turn_count": failed_turns,
    })
    (output_dir / "run_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "report.md").write_text(_report(summary, config), encoding="utf-8")
    from evaluator.trace_export import write_trace

    write_trace(output_dir)
    print(json.dumps({**summary, "output_dir": str(output_dir)}, ensure_ascii=False, indent=2))
    if failed_turns:
        _fail(f"评测已完成，但有 {failed_turns} 个轮次出错；完整结果已保留。",
              f"Evaluation completed with {failed_turns} failed turns; full results are preserved.",
              detail=f"轮次详情 / Turn details: {output_dir / 'turns.jsonl'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        location = traceback.extract_tb(exc.__traceback__)[-1]
        _fail("评测主进程执行失败。", "Evaluation coordinator failed.",
              detail=f"{type(exc).__name__}: {exc}\n位置 / Location: {location.filename}:{location.lineno}")
