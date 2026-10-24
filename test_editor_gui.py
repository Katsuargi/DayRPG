"""GUI smoke for the read-only content viewer (Phase 2a).

Run: python test_editor_gui.py — skips (exit 0) without a display.
Headless write-layer tests live elsewhere (2b); this file only proves
the viewer opens live, fixtures, and broken content without crashing.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

try:
    import tkinter as tk

    _probe = tk.Tk()
    _probe.withdraw()
    _probe.destroy()
except tk.TclError:
    print("GUI smoke skipped: no display available")
    raise SystemExit(0)

from content import CONTENT_FILES  # noqa: E402
from editor import ContentViewer  # noqa: E402


def build(dirpath: Path):
    root = tk.Tk()
    root.withdraw()
    viewer = ContentViewer(root, dirpath)
    root.update()  # force layout so widget queries are real
    return root, viewer


# 1) live content: renders, zero problems, title names the directory
root, viewer = build(_ROOT / "content")
assert viewer.bundle is not None
assert viewer.problems == [], viewer.problems
assert "Content Viewer" in root.title()
assert str((_ROOT / "content").resolve()) in root.title()
assert viewer.file_list.size() == len(CONTENT_FILES)
assert ("items", "berries") in viewer._blocks  # schema-rendered record
assert not viewer.fixtures

# actions must show the gather block as sub-rows (incl. difficulty) —
# this pins the opt-wrapper unwrap that once hid it in a raw dict string
idx_actions = list(CONTENT_FILES).index("actions")
viewer.file_list.selection_set(idx_actions)
viewer._render_file(idx_actions)
_texts: list[str] = []


def _collect(widget) -> None:
    if isinstance(widget, tk.Label):
        _texts.append(str(widget.cget("text")))
    for child in widget.winfo_children():
        _collect(child)


_collect(viewer.records_frame)
assert "gather:" in [t.strip() for t in _texts], "nested block header missing"
assert any(t.strip().endswith("difficulty") for t in _texts), \
    "difficulty row missing under gather"
root.destroy()

# 2) fixtures dir: visually distinct (banner flag + title tag)
root, viewer = build(_ROOT / "tests" / "fixtures" / "content")
assert viewer.fixtures is True
assert "[FIXTURES]" in root.title()
root.destroy()

# 3) broken set (parse fail + schema fail + BOM): opens, lists, jumps
tmp = Path(tempfile.mkdtemp(prefix="viewer_broken_"))
try:
    for f in (_ROOT / "tests" / "fixtures" / "content").glob("*.json"):
        shutil.copy(f, tmp / f.name)
    items = json.loads((tmp / "items.json").read_text(encoding="utf-8"))
    items[0]["start"] = "seven"  # wrong type (schema problem)
    (tmp / "items.json").write_text(json.dumps(items, indent=2),
                                    encoding="utf-8")
    (tmp / "events.json").write_text("{ not json", encoding="utf-8")
    balance = tmp / "balance.json"
    balance.write_bytes(b"\xef\xbb\xbf" + balance.read_bytes())  # BOM: fine
    root, viewer = build(tmp)
    assert viewer.bundle is None, "a parse failure makes the set unusable"
    assert viewer.problems, "problems must be listed"
    assert viewer.problems_list.size() == len(viewer.problems)
    # problem-click path with an unusable bundle must not raise
    viewer.problems_list.selection_set(0)
    viewer._on_problem_click()
    root.update()
    root.destroy()
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("GUI smoke OK: viewer (live, fixtures, broken)")