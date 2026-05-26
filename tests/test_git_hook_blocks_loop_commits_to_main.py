"""The pre-commit hook must block loop-bot commits to main but allow humans."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest


HOOK = """#!/bin/sh
branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
email="$(git config user.email)"
if [ "$branch" = "main" ] && [ "$email" = "loop@autoresearch.local" ]; then
  echo "pre-commit: refusing loop-bot commit to main." >&2
  exit 1
fi
exit 0
"""


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "human@x"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "human"], check=True)
    (path / "a.txt").write_text("a")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)
    hooks_proc = subprocess.run(["git", "-C", str(path), "rev-parse", "--git-path", "hooks"],
                                capture_output=True, text=True, check=True)
    hooks_dir = (path / hooks_proc.stdout.strip()).resolve()
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook = hooks_dir / "pre-commit"
    hook.write_text(HOOK)
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell hook")
def test_hook_blocks_loop_bot_on_main(tmp_path):
    _init_repo(tmp_path)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email",
                    "loop@autoresearch.local"], check=True)
    (tmp_path / "a.txt").write_text("b")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    proc = subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "loop change"],
                          capture_output=True, text=True)
    assert proc.returncode != 0
    assert "refusing loop-bot" in (proc.stderr + proc.stdout)


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell hook")
def test_hook_allows_human_on_main(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("b")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    proc = subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "human change"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
