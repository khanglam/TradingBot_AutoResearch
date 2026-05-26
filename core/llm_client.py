"""OpenRouter LLM client with streaming + mock mode.

Default model: minimax/minimax-m2 (overridable via OPENROUTER_MODEL).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, Optional


OPENROUTER_BASE = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "minimax/minimax-m2"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _is_mock() -> bool:
    return os.environ.get("MOCK_LLM", "").lower() in {"1", "true", "yes"}


def _mock_response_text() -> str:
    path = REPO_ROOT / "tests" / "fixtures" / "mock_llm_response.txt"
    if not path.exists():
        return (
            "Mutate the donchian window slightly to test sensitivity.\n\n"
            "```diff\n"
            "--- a/strategies/crypto.py\n"
            "+++ b/strategies/crypto.py\n"
            "@@ -33,7 +33,7 @@ class Strategy(_BaseStrategy):\n"
            "     donchian_n = 20\n"
            "     exit_n = 10\n"
            "     atr_n = 14\n"
            "-    atr_stop = 2.0\n"
            "+    atr_stop = 2.5\n"
            "     risk_frac = 0.5\n"
            "\n"
            "     def init(self):\n"
            "```\n"
        )
    return path.read_text(encoding="utf-8")


def stream_completion(messages: list[dict], *,
                      model: Optional[str] = None,
                      max_tokens: int = 8000,
                      temperature: float = 0.7) -> Iterator[str]:
    """Yield text deltas from an LLM streaming completion.

    If MOCK_LLM env is set, yields a fixed mock response (no network).
    """
    if _is_mock():
        text = _mock_response_text()
        # Simulate streaming chunks
        chunk = 64
        for i in range(0, len(text), chunk):
            yield text[i:i + chunk]
        return

    from openai import OpenAI

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    model = model or os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)
    client = OpenAI(api_key=api_key, base_url=OPENROUTER_BASE,
                    default_headers={
                        "HTTP-Referer": "https://github.com/local/tradingbot-autoresearch",
                        "X-Title": "TradingBot AutoResearch",
                    })
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True,
    )
    for chunk in stream:
        try:
            delta = chunk.choices[0].delta.content
        except (AttributeError, IndexError):
            delta = None
        if delta:
            yield delta
