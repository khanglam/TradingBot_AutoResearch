"""Pure-Python unified-diff applier — no GNU `patch` dependency.

Parses with `whatthepatch`; applies hunks ourselves with zero fuzz tolerance.
Preserves source newlines. Rejects diffs touching multiple files or files
outside an allowlist.

If parsing yields zero hunks but the diff contains a single fenced code block
with `python`, we treat it as a full-file replacement.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import whatthepatch


class DiffApplyError(RuntimeError):
    pass


@dataclass
class AppliedDiff:
    mode: str  # "hunks" | "full_file"
    file: str
    old_sha256: str
    new_sha256: str


_FENCE_RE = re.compile(
    r"```(?:python)?\s*\n(?P<body>.*?)\n```",
    re.DOTALL,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _detect_newline(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    return "\n"


def _read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    return text, _detect_newline(text)


def _strip_path_prefix(p: str) -> str:
    # whatthepatch keeps the a/ b/ prefixes; strip them for comparison
    if p.startswith(("a/", "b/")):
        return p[2:]
    return p


def _apply_hunks_to_lines(orig_lines: list[str], changes) -> list[str]:
    """Apply a list of whatthepatch Change objects to `orig_lines` (no newline).

    Rebuilds the file by walking the diff with strict (zero-fuzz) context
    matching. Raises DiffApplyError on mismatch.
    """
    if changes is None:
        raise DiffApplyError("no changes parsed")

    # Group by hunk (whatthepatch returns Change with .old, .new, .line attributes;
    # operations: old=None,new=N -> add; old=N,new=None -> del; both -> context)
    new_lines: list[str] = []
    cursor = 0  # index in orig_lines (0-based)

    # Build hunks: contiguous sequences sharing the same "starting old" anchor
    # whatthepatch groups all hunks into one Change list; we need to detect hunk
    # boundaries. Easiest: when `old` jumps non-contiguously, that's a new hunk.
    hunks: list[list] = []
    current: list = []
    last_old: int | None = None
    for ch in changes:
        old = ch.old
        if old is not None:
            if last_old is not None and old != last_old + 1:
                if current:
                    hunks.append(current)
                    current = []
            last_old = old
        current.append(ch)
    if current:
        hunks.append(current)

    for hunk in hunks:
        # Find first old line index in hunk
        first_old = next((ch.old for ch in hunk if ch.old is not None), None)
        if first_old is None:
            # Pure additions at file start
            start_idx = cursor
        else:
            start_idx = first_old - 1  # 1-based -> 0-based
            if start_idx < cursor:
                raise DiffApplyError(f"hunk old-line {first_old} precedes cursor {cursor + 1}")
            # Carry forward unchanged lines from cursor up to start_idx
            new_lines.extend(orig_lines[cursor:start_idx])
            cursor = start_idx

        # Walk hunk
        for ch in hunk:
            if ch.old is not None and ch.new is not None:
                # context
                if cursor >= len(orig_lines):
                    raise DiffApplyError(f"context line {ch.line!r} past EOF")
                if orig_lines[cursor] != ch.line:
                    raise DiffApplyError(
                        f"context mismatch at orig line {cursor + 1}: "
                        f"expected {ch.line!r}, got {orig_lines[cursor]!r}"
                    )
                new_lines.append(ch.line)
                cursor += 1
            elif ch.old is not None and ch.new is None:
                # delete
                if cursor >= len(orig_lines):
                    raise DiffApplyError(f"deletion past EOF at line {cursor + 1}")
                if orig_lines[cursor] != ch.line:
                    raise DiffApplyError(
                        f"deletion mismatch at orig line {cursor + 1}: "
                        f"expected {ch.line!r}, got {orig_lines[cursor]!r}"
                    )
                cursor += 1
            elif ch.old is None and ch.new is not None:
                # insert
                new_lines.append(ch.line)
            else:
                # both None — skip
                continue

    # Tail
    new_lines.extend(orig_lines[cursor:])
    return new_lines


def _full_file_from_fence(diff_text: str) -> str | None:
    matches = list(_FENCE_RE.finditer(diff_text))
    if len(matches) != 1:
        return None
    return matches[0].group("body")


def apply_unified_diff(diff_text: str, repo_root: Path,
                      *, allowed_paths: Iterable[str]) -> AppliedDiff:
    """Apply a unified diff to a file. Returns AppliedDiff or raises.

    `allowed_paths` is the set of repo-relative paths the diff is permitted
    to touch. Anything else ⇒ DiffApplyError.
    """
    repo_root = Path(repo_root)
    allowed = {str(Path(p)) for p in allowed_paths}

    patches = list(whatthepatch.parse_patch(diff_text))
    real_patches = [p for p in patches if p.header is not None and (p.changes or [])]

    if not real_patches:
        # Try full-file fallback
        body = _full_file_from_fence(diff_text)
        if body is None or len(allowed) != 1:
            raise DiffApplyError(
                "no diff hunks parsed and full-file fallback unavailable"
            )
        target_rel = next(iter(allowed))
        target_path = repo_root / target_rel
        if not target_path.exists():
            raise DiffApplyError(f"target file missing: {target_rel}")
        original, newline = _read_text(target_path)
        new_text = body if body.endswith("\n") else body + "\n"
        if newline == "\r\n":
            new_text = new_text.replace("\r\n", "\n").replace("\n", "\r\n")
        target_path.write_bytes(new_text.encode("utf-8"))
        return AppliedDiff(
            mode="full_file",
            file=target_rel,
            old_sha256=_sha(original),
            new_sha256=_sha(new_text),
        )

    if len(real_patches) > 1:
        raise DiffApplyError(
            f"diff touches {len(real_patches)} files; only 1 allowed"
        )

    patch = real_patches[0]
    new_path = _strip_path_prefix(patch.header.new_path or "")
    old_path = _strip_path_prefix(patch.header.old_path or "")
    # Prefer new_path, fall back to old_path
    target_rel = new_path or old_path
    if target_rel not in allowed:
        raise DiffApplyError(
            f"diff touches unauthorized path {target_rel!r}; allowed: {sorted(allowed)}"
        )

    target_path = repo_root / target_rel
    if not target_path.exists():
        raise DiffApplyError(f"target file missing: {target_rel}")

    original, newline = _read_text(target_path)
    # Split preserving no trailing newline so we work line-by-line
    orig_lines = original.split("\n")
    if original.endswith("\n"):
        orig_lines = orig_lines[:-1]  # drop trailing empty
    if newline == "\r\n":
        orig_lines = [ln.rstrip("\r") for ln in orig_lines]

    new_lines = _apply_hunks_to_lines(orig_lines, patch.changes)
    new_text = newline.join(new_lines) + (newline if original.endswith("\n") or new_lines else "")

    target_path.write_bytes(new_text.encode("utf-8"))
    return AppliedDiff(
        mode="hunks",
        file=target_rel,
        old_sha256=_sha(original),
        new_sha256=_sha(new_text),
    )
