"""Cross-platform start/stop of loop subprocesses.

Windows: CREATE_NEW_PROCESS_GROUP + CTRL_BREAK_EVENT signal.
POSIX:   start_new_session=True + os.killpg with SIGTERM (then SIGKILL).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RunningLoop:
    campaign: str
    run_id: str
    pid: int
    proc: subprocess.Popen


_REGISTRY: dict[str, RunningLoop] = {}


def _popen_kwargs_for_platform() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def start_loop(campaign: str, run_id: str, cwd: Path, iters: int,
               *, python_exe: Optional[str] = None,
               extra_env: Optional[dict] = None) -> RunningLoop:
    if campaign in _REGISTRY:
        existing = _REGISTRY[campaign]
        if existing.proc.poll() is None:
            raise RuntimeError(f"loop already running for {campaign} pid={existing.pid}")
        # else stale → remove
        del _REGISTRY[campaign]

    python_exe = python_exe or sys.executable
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    env.setdefault("CAMPAIGN", campaign)

    proc = subprocess.Popen(
        [python_exe, "loop.py", "--campaign", campaign,
         "--iters", str(iters), "--run-id", run_id],
        cwd=str(cwd), env=env,
        **_popen_kwargs_for_platform(),
    )
    rl = RunningLoop(campaign=campaign, run_id=run_id, pid=proc.pid, proc=proc)
    _REGISTRY[campaign] = rl
    return rl


def stop_loop(campaign: str, *, timeout: float = 10.0) -> bool:
    rl = _REGISTRY.get(campaign)
    if not rl or rl.proc.poll() is not None:
        return False

    if sys.platform == "win32":
        try:
            rl.proc.send_signal(signal.CTRL_BREAK_EVENT)
        except Exception:
            rl.proc.terminate()
    else:
        try:
            os.killpg(os.getpgid(rl.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            rl.proc.terminate()

    deadline = time.time() + timeout
    while time.time() < deadline:
        if rl.proc.poll() is not None:
            return True
        time.sleep(0.1)

    # Escalate
    try:
        if sys.platform != "win32":
            os.killpg(os.getpgid(rl.pid), signal.SIGKILL)
        else:
            rl.proc.kill()
    except Exception:
        rl.proc.kill()
    rl.proc.wait(timeout=5)
    return True


def status(campaign: str) -> Optional[dict]:
    rl = _REGISTRY.get(campaign)
    if not rl:
        return None
    alive = rl.proc.poll() is None
    return {"campaign": campaign, "run_id": rl.run_id, "pid": rl.pid, "alive": alive}


def cleanup_dead() -> None:
    dead = [k for k, v in _REGISTRY.items() if v.proc.poll() is not None]
    for k in dead:
        del _REGISTRY[k]
