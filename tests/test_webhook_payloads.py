"""Tests for core.webhook payload shaping (no network)."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

from core.webhook import (
    _discord_payload,
    _slack_payload,
    _generic_payload,
    post_signal,
)


def test_discord_payload_shape():
    p = _discord_payload("BTC/USDT", "BUY", {"close": "70000.00", "bar": "2024-01-01"})
    assert "embeds" in p
    assert p["embeds"][0]["title"] == "BUY BTC/USDT"
    assert p["embeds"][0]["color"] == 0x2ECC71


def test_slack_payload_shape():
    p = _slack_payload("SPY", "SELL", {"close": "500.0"})
    assert "blocks" in p
    assert "SELL" in p["blocks"][0]["text"]["text"]


def test_generic_payload_shape():
    p = _generic_payload("QQQ", "HOLD", {"foo": "bar"})
    assert p == {"symbol": "QQQ", "signal": "HOLD", "foo": "bar"}


def test_post_signal_empty_url_is_noop():
    assert post_signal("", "discord", "BTC/USDT", "BUY") == -1


def test_post_signal_dispatches_to_requests():
    fake_resp = MagicMock(status_code=204)
    with patch("core.webhook.requests.post", return_value=fake_resp) as m:
        sc = post_signal("http://example/hook", "discord", "BTC/USDT", "BUY",
                         {"close": "70000"})
    assert sc == 204
    m.assert_called_once()
