"""Tests for app.py REST endpoints (no SSE / no subprocess)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module


@pytest.fixture
def client():
    return TestClient(app_module.app)


def test_campaigns_returns_both(client):
    r = client.get("/api/campaigns")
    assert r.status_code == 200
    data = r.json()
    names = {c["name"] for c in data}
    assert names == {"crypto", "stocks"}


def test_results_empty_when_no_tsv(client):
    r = client.get("/api/results/crypto")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_results_unknown_campaign_404(client):
    r = client.get("/api/results/foo")
    assert r.status_code == 404


def test_equity_404_when_missing(client):
    r = client.get("/api/equity/crypto/abc123/1")
    assert r.status_code == 404


def test_start_loop_rejects_unknown_campaign(client):
    r = client.post("/api/loop/foo/start", json={"iters": 1})
    assert r.status_code == 404


def test_start_loop_rejects_bad_iters(client):
    r = client.post("/api/loop/crypto/start", json={"iters": 0})
    assert r.status_code == 400
    r = client.post("/api/loop/crypto/start", json={"iters": 10_000})
    assert r.status_code == 400
