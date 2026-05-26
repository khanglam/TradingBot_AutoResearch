"""Webhook posters for scan alerts. Supports discord, slack, generic."""

from __future__ import annotations

import json
from typing import Optional

import requests


def _discord_payload(symbol: str, signal: str, payload: dict) -> dict:
    color = {"BUY": 0x2ECC71, "SELL": 0xE74C3C, "HOLD": 0x95A5A6}.get(signal, 0x3498DB)
    return {
        "embeds": [{
            "title": f"{signal} {symbol}",
            "color": color,
            "fields": [{"name": k, "value": str(v), "inline": True}
                       for k, v in payload.items()],
        }]
    }


def _slack_payload(symbol: str, signal: str, payload: dict) -> dict:
    return {
        "blocks": [
            {"type": "section",
             "text": {"type": "mrkdwn",
                      "text": f"*{signal}* `{symbol}`\n" +
                              "\n".join(f"• {k}: {v}" for k, v in payload.items())}},
        ]
    }


def _generic_payload(symbol: str, signal: str, payload: dict) -> dict:
    return {"symbol": symbol, "signal": signal, **payload}


def post_signal(url: str, kind: str, symbol: str, signal: str,
                payload: Optional[dict] = None,
                *, timeout: int = 10) -> int:
    """Post a single signal. Returns HTTP status. Empty url → -1 (no-op)."""
    if not url:
        return -1
    payload = payload or {}
    if kind == "discord":
        body = _discord_payload(symbol, signal, payload)
    elif kind == "slack":
        body = _slack_payload(symbol, signal, payload)
    else:
        body = _generic_payload(symbol, signal, payload)
    resp = requests.post(url, json=body, timeout=timeout)
    return resp.status_code
