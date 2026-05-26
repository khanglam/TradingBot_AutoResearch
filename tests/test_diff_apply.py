"""Tests for core.diff_apply — pure-Python unified diff application."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.diff_apply import DiffApplyError, apply_unified_diff


HELLO_BEFORE = "def hello():\n    return 'hi'\n\n\ndef bye():\n    return 'bye'\n"

SINGLE_HUNK_DIFF = """\
--- a/strategies/x.py
+++ b/strategies/x.py
@@ -1,2 +1,2 @@
 def hello():
-    return 'hi'
+    return 'HI!'
"""

MULTI_FILE_DIFF = """\
diff --git a/strategies/x.py b/strategies/x.py
--- a/strategies/x.py
+++ b/strategies/x.py
@@ -1,1 +1,1 @@
-foo
+bar
diff --git a/other.py b/other.py
--- a/other.py
+++ b/other.py
@@ -1,1 +1,1 @@
-foo
+bar
"""

UNAUTHORIZED_DIFF = """\
--- a/loop.py
+++ b/loop.py
@@ -1,1 +1,1 @@
-foo
+bar
"""

CONTEXT_MISMATCH_DIFF = """\
--- a/strategies/x.py
+++ b/strategies/x.py
@@ -1,2 +1,2 @@
 def NONEXISTENT():
-    return 'hi'
+    return 'HI!'
"""

FULL_FILE_FALLBACK = """\
Here is the new strategy:
```python
def hello():
    return 'replaced'
```
"""


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "strategies").mkdir()
    (tmp_path / "strategies" / "x.py").write_text(HELLO_BEFORE, encoding="utf-8")
    return tmp_path


def test_apply_single_hunk_unix_newlines(repo):
    out = apply_unified_diff(SINGLE_HUNK_DIFF, repo,
                             allowed_paths={"strategies/x.py"})
    assert out.mode == "hunks"
    assert out.file == "strategies/x.py"
    text = (repo / "strategies" / "x.py").read_text(encoding="utf-8")
    assert "return 'HI!'" in text
    assert "return 'hi'" not in text
    assert text.endswith("\n")


def test_apply_single_hunk_windows_newlines(repo):
    target = repo / "strategies" / "x.py"
    target.write_bytes(HELLO_BEFORE.replace("\n", "\r\n").encode("utf-8"))
    apply_unified_diff(SINGLE_HUNK_DIFF, repo, allowed_paths={"strategies/x.py"})
    text = target.read_bytes().decode("utf-8")
    assert "\r\n" in text
    assert "return 'HI!'" in text


def test_reject_multi_file_diff(repo):
    (repo / "other.py").write_text("foo\n", encoding="utf-8")
    with pytest.raises(DiffApplyError, match="touches 2 files"):
        apply_unified_diff(MULTI_FILE_DIFF, repo,
                           allowed_paths={"strategies/x.py", "other.py"})


def test_reject_unauthorized_path(repo):
    (repo / "loop.py").write_text("foo\n", encoding="utf-8")
    with pytest.raises(DiffApplyError, match="unauthorized path"):
        apply_unified_diff(UNAUTHORIZED_DIFF, repo,
                           allowed_paths={"strategies/x.py"})


def test_reject_on_context_mismatch(repo):
    with pytest.raises(DiffApplyError, match="context mismatch|deletion mismatch"):
        apply_unified_diff(CONTEXT_MISMATCH_DIFF, repo,
                           allowed_paths={"strategies/x.py"})


def test_full_file_fallback(repo):
    out = apply_unified_diff(FULL_FILE_FALLBACK, repo,
                             allowed_paths={"strategies/x.py"})
    assert out.mode == "full_file"
    text = (repo / "strategies" / "x.py").read_text(encoding="utf-8")
    assert text.strip() == "def hello():\n    return 'replaced'"


def test_idempotent_application_fails_second_time(repo):
    apply_unified_diff(SINGLE_HUNK_DIFF, repo, allowed_paths={"strategies/x.py"})
    with pytest.raises(DiffApplyError):
        apply_unified_diff(SINGLE_HUNK_DIFF, repo, allowed_paths={"strategies/x.py"})
