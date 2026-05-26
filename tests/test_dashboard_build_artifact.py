"""Test the dashboard build artifact exists and is well-formed."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST = REPO_ROOT / "dashboard" / "dist"


@pytest.mark.skipif(not DIST.exists(), reason="dashboard not built")
def test_dashboard_dist_index_html_exists():
    idx = DIST / "index.html"
    assert idx.exists()
    body = idx.read_text(encoding="utf-8")
    assert '<div id="root">' in body or 'id="root"' in body


@pytest.mark.skipif(not DIST.exists(), reason="dashboard not built")
def test_dashboard_has_assets():
    assets = DIST / "assets"
    assert assets.exists()
    js = list(assets.glob("*.js"))
    css = list(assets.glob("*.css"))
    assert len(js) >= 1, "no JS bundle"
    assert len(css) >= 1, "no CSS bundle"
