"""Structured JSONL logger.

Schema: `{ts, run_id, iter, event, payload}` — one JSON object per line.
fsync after every write so the SSE tailer sees lines immediately.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional


class JsonlLogger:
    def __init__(self, path: Path, run_id: str):
        self.path = Path(path)
        self.run_id = run_id
        self.iter = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(self.path, "a", encoding="utf-8", buffering=1)

    def set_iter(self, n: int) -> None:
        self.iter = n

    def event(self, name: str, **payload: Any) -> None:
        record = {
            "ts": time.time(),
            "run_id": self.run_id,
            "iter": self.iter,
            "event": name,
            "payload": payload,
        }
        line = json.dumps(record, default=str)
        self._f.write(line + "\n")
        self._f.flush()
        try:
            os.fsync(self._f.fileno())
        except OSError:
            pass

    def close(self) -> None:
        try:
            self._f.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.event("error", kind=exc_type.__name__, message=str(exc))
        self.close()
