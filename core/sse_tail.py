"""Cross-platform tail-f for JSONL files via async polling.

Yields each complete `\n`-terminated line as an SSE event. Reopens on
inode/size shrink (rotation). No inotify, no `tail -f` — works on Windows.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import AsyncIterator, Optional


HEARTBEAT_INTERVAL = 15.0
POLL_INTERVAL = 0.25


async def tail_file(path: Path, *, replay: bool = False) -> AsyncIterator[str]:
    """Async generator yielding full lines from `path`.

    Yields control between polls so a single event loop can serve multiple
    streams. Emits SSE keepalive comments via the helper format.
    """
    path = Path(path)
    last_heartbeat = asyncio.get_event_loop().time()

    while not path.exists():
        await asyncio.sleep(POLL_INTERVAL)
        now = asyncio.get_event_loop().time()
        if now - last_heartbeat >= HEARTBEAT_INTERVAL:
            last_heartbeat = now
            yield ":keepalive\n\n"

    f = open(path, "r", encoding="utf-8", errors="replace")
    try:
        if not replay:
            f.seek(0, os.SEEK_END)
        inode = path.stat().st_ino if hasattr(path.stat(), "st_ino") else None
        buffer = ""
        while True:
            chunk = f.read()
            if chunk:
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        yield f"data: {line}\n\n"
            await asyncio.sleep(POLL_INTERVAL)
            now = asyncio.get_event_loop().time()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                last_heartbeat = now
                yield ":keepalive\n\n"
            # Rotation detection
            try:
                st = path.stat()
                cur_inode = st.st_ino if hasattr(st, "st_ino") else None
                if (inode is not None and cur_inode is not None and inode != cur_inode) \
                        or st.st_size < f.tell():
                    f.close()
                    f = open(path, "r", encoding="utf-8", errors="replace")
                    inode = cur_inode
                    buffer = ""
            except FileNotFoundError:
                await asyncio.sleep(POLL_INTERVAL)
    finally:
        try:
            f.close()
        except Exception:
            pass
