"""Tests for sync_branches.sync_harness (dry-run + allowlist)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import sync_branches


def _init_repo(path: Path, branch: str = "main") -> None:
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@x"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)


def test_sync_harness_dry_run_lists_allowlisted_files(tmp_path):
    main_repo = tmp_path / "main"
    main_repo.mkdir()
    # Create a stand-in main repo with some allowlisted + non-allowlisted files
    (main_repo / "backtest.py").write_text("# backtest")
    (main_repo / "configs.toml").write_text("# configs")
    (main_repo / "core").mkdir()
    (main_repo / "core" / "config.py").write_text("# config")
    (main_repo / "strategies").mkdir()
    (main_repo / "strategies" / "crypto.py").write_text("# strategy — NOT in allowlist")
    (main_repo / "results_crypto.tsv").write_text("# NOT in allowlist")
    _init_repo(main_repo)
    subprocess.run(["git", "-C", str(main_repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(main_repo), "commit", "-q", "-m", "init"], check=True)

    # Worktree (just a sibling dir for the test, not a real git worktree)
    wt = tmp_path / "main-worktrees" / "crypto"
    wt.mkdir(parents=True)

    out = sync_branches.sync_harness("crypto", dry_run=True, base=main_repo)
    assert "backtest.py" in out["copied"]
    assert "configs.toml" in out["copied"]
    assert "core/config.py" in out["copied"]
    assert "strategies/crypto.py" not in out["copied"]
    assert "results_crypto.tsv" not in out["copied"]
