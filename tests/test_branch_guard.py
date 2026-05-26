"""Tests for branch guard via core.git_ops."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.git_ops import GitError, assert_campaign_branch, current_branch


def _init_repo(path: Path, branch: str = "main") -> None:
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@x"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "test"], check=True)
    (path / "a.txt").write_text("a")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)


def test_branch_guard_raises_on_main(tmp_path):
    _init_repo(tmp_path, "main")
    assert current_branch(tmp_path) == "main"
    with pytest.raises(GitError, match="branch guard"):
        assert_campaign_branch(tmp_path, "crypto")


def test_branch_guard_passes_on_campaign(tmp_path):
    _init_repo(tmp_path, "main")
    subprocess.run(["git", "-C", str(tmp_path), "checkout", "-q", "-b", "autoresearch/crypto"], check=True)
    assert_campaign_branch(tmp_path, "crypto")
