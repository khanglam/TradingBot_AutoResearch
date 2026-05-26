"""End-to-end smoke test of loop.py with MOCK_LLM."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from datetime import date
from pathlib import Path

import pytest

from tests.fixtures.synthetic_data import write_fixture_parquet

REPO_ROOT = Path(__file__).resolve().parent.parent


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True)


@pytest.fixture
def worktree_repo(tmp_path, monkeypatch):
    """Create a self-contained repo at tmp_path that mirrors the real layout,
    checked out on autoresearch/crypto."""
    # Copy minimal subset
    files = [
        "configs.toml", "program.md", ".env.example",
        "loop.py", "backtest.py",
        "core/__init__.py", "core/config.py", "core/data_fetch.py",
        "core/backtest_lib.py", "core/diff_apply.py", "core/llm_client.py",
        "core/jsonl_logger.py", "core/git_ops.py",
        "strategies/__init__.py", "strategies/crypto.py", "strategies/stocks.py",
    ]
    for rel in files:
        src = REPO_ROOT / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)

    # Override configs.toml: tiny synthetic-data campaign
    (tmp_path / "configs.toml").write_text(textwrap.dedent("""
        [crypto]
        symbols              = ["BTC/USDT", "ETH/USDT"]
        exchange             = ""
        asset                = "crypto"
        timeframe            = "1d"
        strategy_path        = "strategies/crypto.py"
        data_fetch_start     = "2020-01-01"
        commission           = 0.001
        slippage             = 0.0
        min_trades           = 1
        max_drawdown_limit   = 1.0
        basket_std_penalty   = 0.5
        lockbox_months       = 3
        val_months           = 6
        optimize_metric      = "sharpe"
        promotion_floor_lockbox_sharpe     = 0.0
        promotion_floor_lockbox_min_trades = 1
    """).strip())

    # Write synthetic parquet for both symbols
    write_fixture_parquet("BTC/USDT", "crypto", "1d", tmp_path / "data", seed=1, n=800)
    write_fixture_parquet("ETH/USDT", "crypto", "1d", tmp_path / "data", seed=2, n=800)

    # Init git repo + autoresearch branch
    _git(["init", "-q", "-b", "main"], tmp_path)
    _git(["config", "user.email", "test@x"], tmp_path)
    _git(["config", "user.name", "test"], tmp_path)
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "init"], tmp_path)
    _git(["checkout", "-q", "-b", "autoresearch/crypto"], tmp_path)

    return tmp_path


def test_loop_smoke_one_iter_mock_llm(worktree_repo, monkeypatch):
    env = os.environ.copy()
    env["MOCK_LLM"] = "1"
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["CAMPAIGN"] = "crypto"
    proc = subprocess.run(
        [sys.executable, "loop.py", "--campaign", "crypto", "--iters", "1"],
        cwd=str(worktree_repo), env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"

    # JSONL: run_start and run_end events present
    log_path = worktree_repo / "logs" / "loop_crypto.jsonl"
    assert log_path.exists(), proc.stderr
    events = [json.loads(line) for line in log_path.read_text().strip().splitlines()]
    event_names = [e["event"] for e in events]
    assert "run_start" in event_names
    assert "run_end" in event_names
    assert "llm_response" in event_names

    # TSV exists with at least one row
    tsv = worktree_repo / "results_crypto.tsv"
    assert tsv.exists()
    lines = tsv.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2  # header + at least one
