"""Thin subprocess wrappers around `git`. Always takes explicit `cwd`."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable, Optional


class GitError(RuntimeError):
    pass


def _run(args: list[str], cwd: Path, *, capture: bool = True,
         check: bool = True, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=capture, text=True, env=env)
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()}")
    return proc


def current_branch(cwd: Path) -> str:
    out = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd).stdout.strip()
    return out


def assert_campaign_branch(cwd: Path, campaign: str) -> None:
    branch = current_branch(cwd)
    expected = f"autoresearch/{campaign}"
    if branch != expected:
        raise GitError(
            f"branch guard: expected {expected}, got {branch} in {cwd}"
        )


def commit_all(cwd: Path, message: str, *,
               author_name: str = "loop-bot",
               author_email: str = "loop@autoresearch.local",
               paths: Optional[Iterable[str]] = None) -> str:
    import os

    full_env = os.environ.copy()
    full_env.update({
        "GIT_AUTHOR_NAME": author_name,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": author_name,
        "GIT_COMMITTER_EMAIL": author_email,
    })

    if paths:
        _run(["add", "--", *list(paths)], cwd, env=full_env)
    else:
        _run(["add", "-A"], cwd, env=full_env)
    proc = _run(["commit", "-m", message], cwd, env=full_env, check=False)
    if proc.returncode != 0:
        if "nothing to commit" in (proc.stdout + proc.stderr):
            return ""
        raise GitError(f"git commit failed: {proc.stderr}")
    return _run(["rev-parse", "HEAD"], cwd).stdout.strip()


def reset_workdir(cwd: Path, paths: Iterable[str]) -> None:
    _run(["checkout", "--", *list(paths)], cwd, check=False)


def short_sha(cwd: Path) -> str:
    return _run(["rev-parse", "--short", "HEAD"], cwd).stdout.strip()
