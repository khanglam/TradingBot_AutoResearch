"""Tests for core.sse_tail polling tailer."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path

import pytest

from core.sse_tail import tail_file


async def _collect(tail_iter, n: int, timeout: float = 3.0):
    out = []
    deadline = asyncio.get_event_loop().time() + timeout
    async for line in tail_iter:
        if line.startswith("data:"):
            out.append(line)
            if len(out) >= n:
                return out
        if asyncio.get_event_loop().time() > deadline:
            return out
    return out


def test_emits_appended_lines(tmp_path):
    log_path = tmp_path / "log.jsonl"
    log_path.write_text("")  # ensure exists

    async def run():
        tail_iter = tail_file(log_path, replay=False).__aiter__()

        def writer():
            time.sleep(0.3)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"event": "a"}) + "\n")
                f.flush()
                os.fsync(f.fileno())
                f.write(json.dumps({"event": "b"}) + "\n")
                f.flush()
                os.fsync(f.fileno())

        t = threading.Thread(target=writer)
        t.start()
        out = await _collect(tail_iter, 2, timeout=4.0)
        t.join()
        return out

    out = asyncio.run(run())
    assert len(out) >= 2
    assert "event" in out[0]


def test_replay_emits_existing_lines(tmp_path):
    log_path = tmp_path / "log.jsonl"
    log_path.write_text(json.dumps({"event": "x"}) + "\n"
                        + json.dumps({"event": "y"}) + "\n")

    async def run():
        tail_iter = tail_file(log_path, replay=True).__aiter__()
        return await _collect(tail_iter, 2, timeout=2.0)

    out = asyncio.run(run())
    assert len(out) >= 2
