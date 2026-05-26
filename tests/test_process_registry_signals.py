"""Tests for cross-platform start/stop via core.process_registry."""

from __future__ import annotations

import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

from core import process_registry


@pytest.fixture(autouse=True)
def _clear_registry():
    process_registry._REGISTRY.clear()
    yield
    process_registry._REGISTRY.clear()


def test_start_stop_sleep_subprocess(tmp_path):
    # Make a fake "loop.py" that just sleeps so we don't trigger real loop logic
    fake_loop = tmp_path / "loop.py"
    fake_loop.write_text(textwrap.dedent("""
        import sys, time, argparse
        p = argparse.ArgumentParser()
        p.add_argument('--campaign'); p.add_argument('--iters'); p.add_argument('--run-id')
        p.parse_args()
        time.sleep(30)
    """).strip())
    rl = process_registry.start_loop("crypto", "rid1", cwd=tmp_path, iters=1)
    time.sleep(0.5)
    stat = process_registry.status("crypto")
    assert stat["alive"] is True
    assert process_registry.stop_loop("crypto", timeout=5.0) is True
    time.sleep(0.2)
    process_registry.cleanup_dead()
    assert process_registry.status("crypto") is None or not process_registry.status("crypto")["alive"]


def test_start_rejects_when_already_running(tmp_path):
    fake_loop = tmp_path / "loop.py"
    fake_loop.write_text("import time; time.sleep(10)")
    process_registry.start_loop("crypto", "r1", cwd=tmp_path, iters=1)
    with pytest.raises(RuntimeError, match="already running"):
        process_registry.start_loop("crypto", "r2", cwd=tmp_path, iters=1)
    process_registry.stop_loop("crypto", timeout=3.0)
