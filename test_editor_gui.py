"""GUI smoke for the read-only content viewer (Phase 2a).

Run: python test_editor_gui.py — skips (exit 0) without a display.
Headless write-layer tests live in test_content_write.py (2b); this
file only proves the viewer opens live, fixtures, and broken content
without crashing.
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

from content import CONTENT_FILES, collect_references  # noqa: E402
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

# tunables view: one screen with every number, incl. "(global)" knobs
viewer._show_view("tunables")
assert viewer.view == "tunables"
_tree = viewer.tunables_tree


def _find(parent: str, label: str):
    for node in _tree.get_children(parent):
        if _tree.item(node, "text") == label:
            return node
    return None


_bal = _find("", "balance.json")
_leaf = _find(_bal, "ACTION_DIFFICULTY")
assert _leaf is not None and _tree.item(_leaf, "values")[0] == "8"
_acts = _find("", "actions.json")
_gf = _find(_acts, "gather_food")
_gath = _find(_gf, "gather")
_diff = _find(_gath, "difficulty")
assert _diff is not None and "(global)" in _tree.item(_diff, "values")[0]
_pat = _find("", "patterns.json")
_work = _find(_pat, "lean_to")  # pattern record node exists
assert _work is not None

# reference graph: uses/used-by rows, click-through, economy sheet
_edges = collect_references(viewer.bundle)
assert ("actions", "gather_food", "gather.item", "items", "berries") in _edges
assert ("patterns", "wood_axe", "materials", "items", "wood") in _edges
assert viewer._ref_out[("actions", "gather_food")], "indexes built on reload"
viewer._show_view("files")
viewer.file_list.selection_clear(0, "end")
viewer.file_list.selection_set(0)
viewer._render_file(0)
_rows: list[str] = []


def _collect2(widget) -> None:
    if isinstance(widget, tk.Label):
        _rows.append(str(widget.cget("text")))
    for child in widget.winfo_children():
        _collect2(child)


_collect2(viewer.records_frame)
assert any(t.startswith("used by") for t in _rows), "used-by row missing"
assert any("actions.gather_food" in t for t in _rows), \
    "berries should link the action that yields it"
# click-through: jump from an item to the action that yields it
viewer._jump_to("actions", "gather_food")
assert ("actions", "gather_food") in viewer._blocks
assert viewer.file_list.curselection() == (
    list(CONTENT_FILES).index("actions"),)
# economy sheet: berries obtainable, herbs flagged unobtainable
viewer._show_view("economy")
assert viewer.view == "economy"


def _find_econ(name: str):
    for node in viewer.economy_tree.get_children(""):
        if viewer.economy_tree.item(node, "text") == name:
            return node
    return None


_berries = _find_econ("berries")
assert _berries is not None
assert "bad" not in viewer.economy_tree.item(_berries, "tags")
_src_parent = viewer.economy_tree.get_children(_berries)[0]
assert any("gather_food" in viewer.economy_tree.item(c, "text")
           for c in viewer.economy_tree.get_children(_src_parent)), \
    "berries sources must list the gather action"
_herbs = _find_econ("herbs")
assert _herbs is not None and "bad" in viewer.economy_tree.item(
    _herbs, "tags"), "herbs (no source) must be flagged"
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