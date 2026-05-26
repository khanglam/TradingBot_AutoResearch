"""Validate that each GitHub Actions workflow YAML is parseable and has
the keys we expect."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _all_workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


def test_workflows_dir_exists():
    assert WORKFLOWS.exists(), "expected .github/workflows/"
    assert _all_workflow_files(), "no workflow YAML files found"


@pytest.mark.parametrize("path", _all_workflow_files(), ids=lambda p: p.name)
def test_workflow_parses(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "name" in data
    # YAML loads `on:` as bool True (it's a YAML reserved word) — accept either
    assert "on" in data or True in data, "missing 'on' trigger"
    assert "jobs" in data


def test_expected_workflows_present():
    names = {p.name for p in _all_workflow_files()}
    expected = {"tests.yml", "loop-crypto.yml", "loop-stocks.yml",
                "sync_branches.yml", "scan.yml", "paper.yml",
                "_reusable_loop.yml"}
    assert expected.issubset(names), f"missing: {expected - names}"
