"""Test that scan.py emits no-op when no frozen strategy exists."""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest

from scan import scan_campaign

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_scan_noop_when_no_frozen_strategy(tmp_path, monkeypatch):
    # Build a tiny isolated base dir with no frozen marker
    base = tmp_path
    (base / "strategies").mkdir()
    # Don't create a .frozen.json marker
    result = scan_campaign("crypto", base=base)
    assert result["skipped"] is True
    assert "no frozen" in result["reason"]
