from __future__ import annotations

from scripts.evaluate_parallel_with_traces import _duration, _last_jsonl_row, _shard_progress


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
