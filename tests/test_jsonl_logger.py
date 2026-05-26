"""Tests for core.jsonl_logger."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from core.jsonl_logger import JsonlLogger


def test_writes_complete_lines(tmp_path):
    path = tmp_path / "log.jsonl"
    with JsonlLogger(path, "run1") as log:
        log.set_iter(1)
        log.event("hello", foo="bar")
        log.event("backtest_result", score=1.234)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    rec0 = json.loads(lines[0])
    assert rec0["event"] == "hello"
    assert rec0["payload"] == {"foo": "bar"}
    assert rec0["run_id"] == "run1"
    assert rec0["iter"] == 1


def test_concurrent_writes_no_partial(tmp_path):
    path = tmp_path / "log.jsonl"
    log = JsonlLogger(path, "run1")
    errors = []

    def worker(i):
        try:
            for j in range(50):
                log.event("tick", w=i, j=j, big="x" * 200)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    log.close()

    assert not errors
    raw_lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(raw_lines) == 4 * 50
    for ln in raw_lines:
        rec = json.loads(ln)  # raises if any line is partial
        assert rec["event"] == "tick"


def test_exit_logs_exception(tmp_path):
    path = tmp_path / "log.jsonl"
    try:
        with JsonlLogger(path, "r"):
            raise ValueError("boom")
    except ValueError:
        pass
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    last = json.loads(lines[-1])
    assert last["event"] == "error"
    assert last["payload"]["kind"] == "ValueError"
