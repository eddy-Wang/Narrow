from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.evaluate_parallel_with_traces import (
    _duration,
    _last_jsonl_row,
    _load_jsonl,
    _print_worker_errors,
    _shard_progress,
    _worker_failure,
)


def test_duration():
    assert _duration(3661) == "01:01:01"
    assert _duration(-1) == "00:00:00"


def test_last_row_tolerates_partial_write(tmp_path):
    path = tmp_path / "turns.jsonl"
    path.write_text('{"turn":1}\n{"turn":2}\n{"turn":', encoding="utf-8")
    assert _last_jsonl_row(path) == {"turn": 2}


def test_last_row_tolerates_missing_file(tmp_path):
    assert _last_jsonl_row(tmp_path / "missing") == {}


def test_progress_counts_only_complete_sessions(tmp_path):
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    run = tmp_path / "run"
    run.mkdir()
    (raw_root / "LATEST.txt").write_text(str(run), encoding="utf-8")
    (run / "sessions.jsonl").write_text('{"hit":true}\n{"hit":', encoding="utf-8")
    (run / "turns.jsonl").write_text('{"sample_id":"public_0002","turn":3}\n', encoding="utf-8")
    assert _shard_progress(raw_root) == (1, {"sample_id": "public_0002", "turn": 3})


def test_worker_failure_reports_reason_and_log_paths_in_both_languages(tmp_path):
    shard = tmp_path / "shard_00"
    shard.mkdir()
    (shard / "stderr.log").write_text("Traceback\nRuntimeError: provider timed out\n", encoding="utf-8")

    message = _worker_failure(0, 1, shard)

    assert "[错误]" in message and "评测 worker 1 执行失败" in message
    assert "[ERROR]" in message and "Evaluation worker 1 failed" in message
    assert "RuntimeError: provider timed out" in message
    assert str(shard / "stderr.log") in message


def test_worker_errors_stream_complete_lines_once(tmp_path, capsys):
    path = tmp_path / "stderr.log"
    path.write_bytes("progress\n[错误 / ERROR] sample=A turn=2\n[错误 / ERROR] partial".encode())
    offset = _print_worker_errors(path, 0)
    assert capsys.readouterr().err == "[错误 / ERROR] sample=A turn=2\n"
    assert _print_worker_errors(path, offset) == offset
    assert capsys.readouterr().err == ""
    with path.open("ab") as handle:
        handle.write(b" completed\n")
    _print_worker_errors(path, offset)
    assert capsys.readouterr().err == "[错误 / ERROR] partial completed\n"


def test_invalid_dataset_reports_filename_and_line_in_both_languages(tmp_path, capsys):
    path = tmp_path / "users.jsonl"
    path.write_text('{}\nnot json\n', encoding="utf-8")
    with pytest.raises(SystemExit) as failure:
        _load_jsonl(path)
    assert failure.value.code == 1
    output = capsys.readouterr().err
    assert "JSONL 格式错误" in output and "Invalid JSONL" in output
    assert str(path) in output and "第 2 行" in output and "line 2" in output


def test_turn_error_preserves_root_cause_and_redacts_key(tmp_path, monkeypatch, capsys):
    from scripts.evaluate_with_traces import _error_chain, _print_turn_error

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    try:
        try:
            raise TimeoutError("provider timeout test-secret")
        except TimeoutError as cause:
            raise RuntimeError("Online intent failed") from cause
    except RuntimeError as error:
        message = _error_chain(error)
    _print_turn_error("sample-A", 3, message, tmp_path)
    output = capsys.readouterr().err
    assert "需求理解 / intent understanding" in output
    assert "sample=sample-A" in output and "turn=3" in output
    assert "TimeoutError: provider timeout" in output
    assert "test-secret" not in output and "[REDACTED]" in output
    assert str(tmp_path / "turns.jsonl") in output


@pytest.mark.parametrize("error", [None, "TimeoutError: provider timed out"])
def test_completed_evaluation_preserves_results_and_signals_failed_turns(tmp_path, monkeypatch, capsys, error):
    from scripts import evaluate_parallel_with_traces as evaluation

    dataset = tmp_path / "users.jsonl"
    dataset.write_text('{"sample_id":"sample-A"}\n', encoding="utf-8")
    output_root = tmp_path / "output"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-test-key")
    monkeypatch.setattr(evaluation.sys, "argv", [
        "evaluate", "--catalog", str(dataset), "--dataset", str(dataset),
        "--output-root", str(output_root), "--workers", "1",
    ])

    def completed_worker(command, **kwargs):
        raw_root = Path(command[command.index("--output-root") + 1])
        run = raw_root / "fixture"
        run.mkdir(parents=True)
        (raw_root / "LATEST.txt").write_text(str(run), encoding="utf-8")
        (run / "summary.json").write_text('{"reported_token_usage":{}}', encoding="utf-8")
        evaluation._write_jsonl(run / "sessions.jsonl", [{
            "sample_id": "sample-A", "scenario_type": "single", "target_parent_asin": "A",
            "hit": False, "first_hit_turn": None, "best_rank": None, "reciprocal_rank": 0,
        }])
        evaluation._write_jsonl(run / "turns.jsonl", [{
            "sample_id": "sample-A", "turn": 1, "error": error,
        }])
        (run / "node_traces.jsonl").write_text("", encoding="utf-8")
        return SimpleNamespace(pid=123, returncode=0, poll=lambda: 0)

    monkeypatch.setattr(evaluation.subprocess, "Popen", completed_worker)
    if error:
        with pytest.raises(SystemExit) as failure:
            evaluation.main()
        assert failure.value.code == 1
        stderr = capsys.readouterr().err
        assert "1 个轮次出错" in stderr and "1 failed turns" in stderr
    else:
        assert evaluation.main() == 0
        assert capsys.readouterr().err == ""

    run = Path((output_root / "LATEST.txt").read_text(encoding="utf-8").strip())
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    assert summary["failed_turn_count"] == int(bool(error))
    assert evaluation._load_jsonl(run / "turns.jsonl")[0]["error"] == error
    trace = json.loads((run / "trace.json").read_text(encoding="utf-8"))
    assert trace["sessions"][0]["turns"][0]["error"] == error
    assert (run / "report.md").is_file()
