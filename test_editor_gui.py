"""GUI smoke for the read-only content viewer (Phase 2a).

Run: python test_editor_gui.py — skips (exit 0) without a display.
Headless write-layer tests live in test_content_write.py (2b); this
file only proves the viewer opens live, fixtures, and broken content
without crashing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

try:
    import tkinter as tk
except ImportError:
    print("GUI smoke skipped: tkinter not installed")
    raise SystemExit(0)

try:
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

# --- 2c: hybrid forms + Save-All through the 2b write layer ------------------
import editor as editor_mod  # noqa: E402  (dialog seam: patchable, no modals)

dialogued: list[tuple] = []
_real = {name: getattr(editor_mod.messagebox, name) for name in
         ("showerror", "showinfo", "showwarning", "askyesno",
          "askyesnocancel")}


def _rec(name, result=None):
    def _fn(*args, **kwargs):
        dialogued.append((name,) + args)
        return result
    return _fn


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


tmp = Path(tempfile.mkdtemp(prefix="forms_"))
try:
    for f in (_ROOT / "tests" / "fixtures" / "content").glob("*.json"):
        shutil.copy(f, tmp / f.name)
    for _n in ("showerror", "showinfo", "showwarning"):
        setattr(editor_mod.messagebox, _n, _rec(_n))
    editor_mod.messagebox.askyesno = _rec("askyesno", True)

    root, viewer = build(tmp)
    idx_items = list(CONTENT_FILES).index("items")
    viewer.file_list.selection_set(idx_items)
    viewer._render_file(idx_items)

    # read-only by default: no input widgets anywhere in the stack
    _inputs = [w for w in _walk(viewer.records_frame)
               if w.winfo_class() in ("Entry", "TEntry", "TCombobox")]
    assert not _inputs, "viewer must stay read-only until Edit"

    # Edit mounts the form; saved ids are locked (D7)
    viewer._on_edit_toggle("items", "berries")
    form = viewer._forms[("items", "berries")]
    assert isinstance(form, editor_mod.RecordForm)
    assert form.vars["id"].get() == "berries"
    form.vars["id"].set("hacked")
    assert viewer.bundle.items[0]["id"] == "berries", \
        "saved ids must ignore edits (D7)"

    # a name edit flows into the bundle, marks dirty, revalidates live
    form.vars["name"].set("Wild Berries")
    assert viewer.bundle.items[0]["name"] == "Wild Berries"
    assert "items" in viewer.dirty

    # a bad edit names its problem and blocks Save-All, disk untouched
    before_items = (tmp / "items.json").read_bytes()
    form.vars["start"].set("seven")
    assert any("'start'" in p for p in viewer.problems), viewer.problems
    dialogued.clear()
    viewer._on_save()
    assert dialogued and dialogued[0][0] == "showerror", dialogued
    assert (tmp / "items.json").read_bytes() == before_items
    assert "items" in viewer.dirty

    # fixed → clean → save writes, dirty clears, reload round-trips
    form.vars["start"].set("2")
    assert viewer.problems == [], viewer.problems
    viewer._on_save()
    assert viewer.dirty == set(), viewer.dirty
    saved = json.loads((tmp / "items.json").read_bytes())
    assert saved[0]["name"] == "Wild Berries", "edit must round-trip"
    viewer.reload()
    assert viewer.bundle.items[0]["name"] == "Wild Berries"
    assert ("items", "berries") not in viewer._unsaved_ids

    # D7: referenced records refuse deletion; unreferenced ones confirm
    dialogued.clear()
    viewer._on_delete("items", "wood")
    assert dialogued and dialogued[0][0] == "showerror", dialogued
    assert any(r["id"] == "wood" for r in viewer.bundle.items)
    # only the incoming-reference direction blocks a delete: pick an item
    # nothing references (computed, not guessed)
    _used = {(e[3], e[4]) for e in collect_references(viewer.bundle)}
    _free = [r["id"] for r in viewer.bundle.items
             if ("items", r["id"]) not in _used]
    assert _free, "fixture must contain an unreferenced item"
    editor_mod.messagebox.askyesno = _rec("askyesno", True)  # confirm
    viewer._on_delete("items", _free[0])     # not referenced → deletes
    assert not any(r["id"] == _free[0] for r in viewer.bundle.items)
    editor_mod.messagebox.askyesno = _rec("askyesno", True)

    # D5: reorder swaps, banners once per file
    before_ids = [r["id"] for r in viewer.bundle.items]
    dialogued.clear()
    viewer._on_move("items", "wood", -1)
    assert [r["id"] for r in viewer.bundle.items] == \
        [before_ids[1], before_ids[0]] + before_ids[2:]
    assert any(d[0] == "showinfo" and "Reorder" in d[1]
               for d in dialogued), dialogued
    dialogued.clear()
    viewer._on_move("items", "wood", +1)     # back to original order
    assert not any(d[0] == "showinfo" for d in dialogued), \
        "the D5 banner fires once per file"
    viewer._on_save()                        # settle the disk state
    assert viewer.dirty == set()

    # add: appends, opens for edit, id editable until first save (D7),
    # and the empty name blocks Save-All naming the problem (constraint 3)
    n_before = len(viewer.bundle.items)
    viewer._on_add("items")
    assert len(viewer.bundle.items) == n_before + 1
    new_rec = viewer.bundle.items[-1]
    assert new_rec["id"].startswith("new_item"), new_rec["id"]
    assert ("items", new_rec["id"]) in viewer._editing
    form2 = viewer._forms[("items", new_rec["id"])]
    dialogued.clear()
    viewer._on_save()
    assert dialogued and dialogued[0][0] == "showerror", dialogued
    form2.vars["id"].set("test_item")        # unsaved ids are editable
    assert viewer.bundle.items[-1]["id"] == "test_item"
    form2.vars["name"].set("Test Item")
    assert viewer.problems == [], viewer.problems
    viewer._on_save()
    saved = json.loads((tmp / "items.json").read_bytes())
    assert len(saved) == n_before + 1 and saved[-1]["id"] == "test_item"
    assert saved[-1]["name"] == "Test Item"

    # duplicate appends at the end (D5) — source from a survivor (the
    # unreferenced item above may be gone)
    _src = viewer.bundle.items[0]["id"]
    viewer._on_duplicate("items", _src)
    assert viewer.bundle.items[-1]["id"] == f"{_src}_copy"
    assert "items" in viewer.dirty

    # unsaved guard: CANCEL stays put, DISCARD reloads clean (D11 paths)
    dialogued.clear()
    editor_mod.messagebox.askyesnocancel = _rec("askyesnocancel", None)
    viewer._on_reload_click()
    assert dialogued and dialogued[0][0] == "askyesnocancel"
    assert "items" in viewer.dirty, "CANCEL must not throw edits away"
    editor_mod.messagebox.askyesnocancel = _rec("askyesnocancel", False)
    viewer._on_reload_click()
    assert viewer.dirty == set() and \
        viewer.bundle.items[-1]["id"] != f"{_src}_copy", "discard = reload"

    # D11 stale: disk changed under us → CANCEL writes nothing,
    # confirmed overwrite wins
    viewer.file_list.selection_set(idx_items)
    viewer._render_file(idx_items)
    viewer._on_edit_toggle("items", "berries")
    form3 = viewer._forms[("items", "berries")]
    form3.vars["name"].set("Stale Test")
    external = json.loads((tmp / "items.json").read_bytes())
    external[0]["tooltip"] = "external edit"
    (tmp / "items.json").write_bytes(
        (json.dumps(external, ensure_ascii=False, indent=2)
         + "\n").encode("utf-8"))
    dialogued.clear()
    editor_mod.messagebox.askyesnocancel = _rec("askyesnocancel", None)
    viewer._on_save()
    assert dialogued and dialogued[0][0] == "askyesnocancel"
    assert b"external edit" in (tmp / "items.json").read_bytes(), \
        "CANCEL must leave the external change alone"
    assert "items" in viewer.dirty
    editor_mod.messagebox.askyesnocancel = _rec("askyesnocancel", True)
    viewer._on_save()
    saved = json.loads((tmp / "items.json").read_bytes())
    assert saved[0]["name"] == "Stale Test", "overwrite wins (D11)"
    assert viewer.dirty == set()

    # close with nothing unsaved: no dialog, straight out
    dialogued.clear()
    viewer._on_close()
    assert not dialogued, "clean close must not prompt"
finally:
    for _n, _fn in _real.items():
        setattr(editor_mod.messagebox, _n, _fn)
    shutil.rmtree(tmp, ignore_errors=True)

print("GUI smoke OK: 2c forms, save, guards")

# --- 2d: one edit + one blocked bad edit per file (D17: form model only) ----
dialogued.clear()
_real2 = {name: getattr(editor_mod.messagebox, name) for name in
          ("showerror", "showinfo", "showwarning", "askyesno",
           "askyesnocancel")}
tmp2 = Path(tempfile.mkdtemp(prefix="forms2_"))
try:
    for f in (_ROOT / "tests" / "fixtures" / "content").glob("*.json"):
        shutil.copy(f, tmp2 / f.name)
    for _n in ("showerror", "showinfo", "showwarning"):
        setattr(editor_mod.messagebox, _n, _rec(_n))
    editor_mod.messagebox.askyesno = _rec("askyesno", True)
    editor_mod.messagebox.askyesnocancel = _rec("askyesnocancel", True)

    root2, viewer = build(tmp2)

    def _first_id(fname):
        return viewer._records_of(fname)[0][0]

    def _btn(text, which=-1):
        """Chrome is buttons (D17: existence-level), values are model."""
        found = [w for w in _walk(viewer.records_frame)
                 if w.winfo_class() == "Button"
                 and str(w.cget("text")) == text]
        assert found, f"no {text!r} button"
        return found[which]

    def _roundtrip(fname, edit_field, new_value, expected,
                   bad_field, bad_value):
        """2d acceptance for one file: bad edit blocks (nothing
        written), repair, then edit→save→reload through the form."""
        rec_id = _first_id(fname)
        idx = list(CONTENT_FILES).index(fname)
        viewer.file_list.selection_set(idx)
        viewer._render_file(idx)
        viewer._on_edit_toggle(fname, rec_id)
        form = viewer._forms[(fname, rec_id)]
        assert form is not None, f"{fname}: Edit must mount a form"
        # blocked bad edit: live problem + showerror + still dirty
        orig = form.vars[bad_field].get()
        form.vars[bad_field].set(bad_value)
        assert viewer.problems, f"{fname}: bad edit must surface live"
        dialogued.clear()
        viewer._on_save()
        assert dialogued and dialogued[0][0] == "showerror", \
            f"{fname}: save blocked, got {dialogued}"
        assert viewer.dirty, f"{fname}: blocked save keeps the file dirty"
        form.vars[bad_field].set(orig)          # repair the buffer
        assert viewer.problems == [], (fname, viewer.problems)
        # edit → save → reload round-trip, with the D15 ● lifecycle
        form.vars[edit_field].set(new_value)
        assert (fname, rec_id) in viewer._record_dirty, "D15 marks edits"
        viewer._on_save()
        assert viewer.dirty == set(), (fname, viewer.dirty)
        assert (fname, rec_id) not in viewer._record_dirty, \
            "D15: saving clears the mark"
        viewer.reload()                          # also clears pane state
        data = dict(viewer._records_of(fname))[rec_id]
        assert data[edit_field] == expected, (fname, data[edit_field])

    _roundtrip("skills", "name", "Endurance", "Endurance",
               "start_level", "many")
    _roundtrip("stats", "name", "Might", "Might",
               "start_level", "nope")
    _roundtrip("events", "text", "A strange quiet falls.",
               "A strange quiet falls.", "check", "sometimes")
    _roundtrip("balance", "EVENT_CHANCE", "0.42", 0.42,
               "EVENT_CHANCE", "often")
    _roundtrip("actions", "label", "Gather Snacks", "Gather Snacks",
               "behavior", "juggling")
    _roundtrip("patterns", "work", "13", 13, "skill_req", "soon")

    # D14 pane: Edit mounts the single-record pane, Done leaves it, and
    # a jump is browse intent that unmounts it
    a0 = _first_id("actions")
    idx_a = list(CONTENT_FILES).index("actions")
    viewer.file_list.selection_set(idx_a)
    viewer._render_file(idx_a)
    viewer._on_edit_toggle("actions", a0)
    assert viewer._pane_edit == ("actions", a0)
    assert set(viewer._blocks) == {("actions", a0)}, \
        "the pane shows exactly one record"
    viewer._on_edit_toggle("actions", a0)        # Done → browsing
    assert viewer._pane_edit is None
    assert len(viewer._blocks) > 1, "stacked browsing returns"
    viewer._on_edit_toggle("actions", a0)        # back into the pane
    other = viewer._records_of("actions")[1][0]
    viewer._jump_to("actions", other)
    assert viewer._pane_edit is None, "a jump is browse intent (D14)"

    # D16 on the pane record: nested gather (child form), nullable
    # skill "(none)" ↔ null, and the checks list editor
    gather_id = next(rid for rid, rec in viewer._records_of("actions")
                     if isinstance(rec, dict) and "gather" in rec)
    viewer._on_edit_toggle("actions", gather_id)
    gather_rec = dict(viewer._records_of("actions"))[gather_id]
    form = viewer._forms[("actions", gather_id)]
    assert "gather" in form.groups, "nested block mounts a child form"
    child = form.groups["gather"]
    child.vars["success"].set("You pocket {amount} treasures.")
    assert gather_rec["gather"]["success"] == \
        "You pocket {amount} treasures."
    form.vars["skill"].set("(none)")
    assert gather_rec["skill"] is None, "nullable (none) stores null"
    skill0 = next(iter(viewer.bundle.skills))
    form.vars["skill"].set(skill0)
    assert gather_rec["skill"] == skill0

    assert "checks" in form.rowvars
    n0 = len(form.rowvars["checks"])
    _btn("+ add row").invoke()
    _btn("+ add row").invoke()
    assert len(form.rowvars["checks"]) == n0 + 2, "rows append"
    row = form.rowvars["checks"][-1]
    stats0 = next(iter(viewer.bundle.stats))
    row[0].set("stats")                          # dyn_ref sibling filter
    row[1].set(stats0)
    assert gather_rec["checks"][-1] == ["stats", stats0]
    second_row = form.rowvars["checks"][1]
    _btn("↓", 1).invoke()                        # first ↓ is record ops
    assert form.rowvars["checks"][0] is second_row, "rows reorder"
    _btn("✕", -1).invoke()                       # remove the added rows
    _btn("✕", -1).invoke()
    assert len(form.rowvars["checks"]) == n0
    viewer._on_save()
    assert viewer.dirty == set(), "pane edits save cleanly"

    # D16 dict_int (patterns.materials): qty edit, add/remove, and a
    # key that survives the save — with constraint-4 key order intact
    p_id = _first_id("patterns")
    idx_p = list(CONTENT_FILES).index("patterns")
    viewer.file_list.selection_set(idx_p)
    viewer._render_file(idx_p)
    viewer._on_edit_toggle("patterns", p_id)
    pform = viewer._forms[("patterns", p_id)]
    mats = pform.rowvars["materials"]
    assert mats, "fixture patterns declare materials"
    key0 = mats[0][0].get()
    mats[0][1].set("7")
    assert viewer.bundle.patterns[p_id]["materials"][key0] == 7
    n_mats = len(mats)
    _btn("+ material").invoke()
    assert len(pform.rowvars["materials"]) == n_mats + 1, \
        "an empty-key row waits for its key (no phantom collapse)"
    _btn("✕", n_mats).invoke()  # materials ✕s trail from 0; effects' ✕
    # comes last (E5), so "last" would remove the wrong row
    assert len(pform.rowvars["materials"]) == n_mats
    _btn("+ material").invoke()
    existing = set(viewer.bundle.patterns[p_id]["materials"])
    item0 = next(r["id"] for r in viewer.bundle.items
                 if r["id"] not in existing)
    mrows = pform.rowvars["materials"]
    mrows[-1][0].set(item0)
    mrows[-1][1].set("3")
    assert viewer.bundle.patterns[p_id]["materials"].get(item0) == 3
    viewer._on_save()
    assert viewer.dirty == set()
    viewer.reload()
    pats = dict(viewer._records_of("patterns"))[p_id]
    assert pats["materials"][key0] == 7 and pats["materials"][item0] == 3, \
        "materials round-trip through the row editor"
    assert list(pats["materials"])[0] == key0, \
        "constraint 4: key order survives (appended, never reordered)"

    # clean close: no dialog, straight out
    dialogued.clear()
    viewer._on_close()
    assert not dialogued, "clean close must not prompt"
finally:
    for _n, _fn in _real2.items():
        setattr(editor_mod.messagebox, _n, _fn)
    shutil.rmtree(tmp2, ignore_errors=True)

print("GUI smoke OK: 2d forms, pane, nested editors")

# --- 2d-ops: dict record ops (D18) -------------------------------------------
dialogued.clear()
_real3 = {name: getattr(editor_mod.messagebox, name) for name in
          ("showerror", "showinfo", "showwarning", "askyesno",
           "askyesnocancel")}
tmp3 = Path(tempfile.mkdtemp(prefix="forms3_"))
try:
    for f in (_ROOT / "tests" / "fixtures" / "content").glob("*.json"):
        shutil.copy(f, tmp3 / f.name)
    for _n in ("showerror", "showinfo", "showwarning"):
        setattr(editor_mod.messagebox, _n, _rec(_n))
    editor_mod.messagebox.askyesno = _rec("askyesno", True)
    editor_mod.messagebox.askyesnocancel = _rec("askyesnocancel", True)

    root3, viewer = build(tmp3)
    idx_s = list(CONTENT_FILES).index("skills")
    viewer.file_list.selection_set(idx_s)
    viewer._render_file(idx_s)

    # dict files get Add: key-based record, synthetic id row (D18)
    n_skills = len(viewer.bundle.skills)
    _btn("+ add record").invoke()
    assert len(viewer.bundle.skills) == n_skills + 1, "dict add works"
    new_key = next(k for k in viewer.bundle.skills
                   if k.startswith("new_skill"))
    assert ("skills", new_key) in viewer._editing, "add opens for edit"
    sform = viewer._forms[("skills", new_key)]
    assert "id" in sform.vars, "dict records edit their key (D18)"
    sform.vars["id"].set("fishing")
    assert "fishing" in viewer.bundle.skills and new_key not in \
        viewer.bundle.skills, "the key renames in place"
    assert list(viewer.bundle.skills)[-1] == "fishing", \
        "renamed key keeps its appended position (order is data)"
    assert ("skills", "fishing") in viewer._editing, "sets retarget"
    # uniqueness: renaming onto an existing key never clobbers it
    sform.vars["id"].set("foraging")
    assert "foraging" in viewer.bundle.skills and "fishing" in \
        viewer.bundle.skills, "taken keys are ignored"
    sform.vars["id"].set("fishing")
    sform.vars["name"].set("Fishing")
    sform.vars["start_level"].set("1")
    assert viewer.problems == [], viewer.problems

    # D7 still applies to dict records: referenced foraging refuses
    dialogued.clear()
    viewer._on_delete("skills", "foraging")
    assert dialogued and dialogued[0][0] == "showerror", dialogued
    assert "foraging" in viewer.bundle.skills

    # duplicate appends a key-based copy (D5)
    viewer._on_duplicate("skills", "fishing")
    assert list(viewer.bundle.skills)[-1] == "fishing_copy", \
        list(viewer.bundle.skills)

    # reorder swaps key pairs and banners once (D5)
    dialogued.clear()
    before_keys = list(viewer.bundle.skills)
    pos = before_keys.index("fishing")
    assert pos > 0, "appended record has a predecessor to swap with"
    viewer._on_move("skills", "fishing", -1)
    after_keys = list(viewer.bundle.skills)
    assert after_keys == (before_keys[:pos - 1]
                          + [before_keys[pos], before_keys[pos - 1]]
                          + before_keys[pos + 1:]), after_keys
    assert any(d[0] == "showinfo" and "Reorder" in d[1]
               for d in dialogued), dialogued

    # save → reload: keys, order, and edits all persist
    viewer._on_save()
    assert viewer.dirty == set(), viewer.dirty
    viewer.reload()
    assert viewer.bundle.skills["fishing"]["name"] == "Fishing"
    assert list(viewer.bundle.skills) == after_keys, \
        "dict key order survives the save (constraint 4)"

    # --- D19: the full fishing authoring pass --------------------------------
    # items: add `fish` (array add + id rename + fields)
    idx_i = list(CONTENT_FILES).index("items")
    viewer.file_list.selection_set(idx_i)
    viewer._render_file(idx_i)
    _btn("+ add record").invoke()
    iform = viewer._forms[("items", viewer.bundle.items[-1]["id"])]
    iform.vars["id"].set("fish")
    iform.vars["name"].set("Fish")
    iform.vars["start"].set("0")
    assert viewer.problems == [], viewer.problems

    # actions: add the gather action in the pane; the same-session skill
    # dropdown resolves `fishing` (D12) and the id rename keeps the pane
    idx_a = list(CONTENT_FILES).index("actions")
    viewer.file_list.selection_set(idx_a)
    viewer._render_file(idx_a)
    _btn("+ add record").invoke()
    aform = viewer._forms[viewer._pane_edit]
    aform.vars["id"].set("go_fishing")
    assert viewer._pane_edit == ("actions", "go_fishing"), \
        "the pane follows a mid-form id rename (D14)"
    aform.vars["label"].set("Go Fishing")
    aform.vars["behavior"].set("gather_item")
    aform.vars["skill"].set("fishing")
    assert aform.groups, "the gather child form mounts (D16)"
    gform = aform.groups["gather"]
    gform.vars["item"].set("fish")
    gform.rowvars["yield"][0][0].set("1")
    gform.rowvars["yield"][0][1].set("3")
    gform.vars["success"].set("you reeled in a catch ({amount} fish).")
    gform.vars["fail"].set("the line came back empty.")
    gform.vars["difficulty"].set("4")
    assert viewer.problems == [], viewer.problems

    # items: add `fishing_rod` — a tool whose pair targets the new action
    viewer.file_list.selection_set(idx_i)
    viewer._render_file(idx_i)
    _btn("+ add record").invoke()
    rform = viewer._forms[("items", viewer.bundle.items[-1]["id"])]
    rform.vars["id"].set("fishing_rod")
    rform.vars["name"].set("Fishing Rod")
    rform.vars["start"].set("0")
    _btn("+ add effect").invoke()     # E4: items have a legal type now
    erow = rform.rowvars["effects"][0]
    erow["action"].set("go_fishing")
    erow["add"].set("1")
    rod = viewer.bundle.items[-1]
    assert rod["effects"] == [{"type": "yield_bonus", "when": "always",
                               "action": "go_fishing", "add": 1}], rod
    assert viewer.problems == [], viewer.problems

    # ONE Save-All for items + actions; reload proves every link
    viewer._on_save()
    assert viewer.dirty == set(), viewer.dirty
    viewer.reload()
    skills = viewer.bundle.skills
    items = {r["id"]: r for r in viewer.bundle.items}
    acts = {a["id"]: a for a in viewer.bundle.actions}
    assert skills["fishing"]["name"] == "Fishing"
    assert items["fish"]["name"] == "Fish"
    assert items["fishing_rod"]["effects"] == [
        {"type": "yield_bonus", "when": "always",
         "action": "go_fishing", "add": 1}]
    assert acts["go_fishing"]["behavior"] == "gather_item"
    assert acts["go_fishing"]["skill"] == "fishing"
    assert acts["go_fishing"]["gather"]["item"] == "fish"
    assert acts["go_fishing"]["stat_xp"] is None, "house-style null (D18)"
    assert ("actions", "go_fishing", "skill", "skills", "fishing") in \
        collect_references(viewer.bundle), "the graph sees the new edges"
    assert viewer.problems == [], viewer.problems

    # clean close: no dialog
    dialogued.clear()
    viewer._on_close()
    assert not dialogued, "clean close must not prompt"
finally:
    for _n, _fn in _real3.items():
        setattr(editor_mod.messagebox, _n, _fn)
    shutil.rmtree(tmp3, ignore_errors=True)

print("GUI smoke OK: 2d-ops dict ops + fishing pass")

# --- 2e: repair flow (D4) — line/column, open-external, reload, run-check ---
dialogued.clear()
_real4 = {name: getattr(editor_mod.messagebox, name) for name in
          ("showerror", "showinfo", "showwarning", "askyesno",
           "askyesnocancel")}
_real_startfile = getattr(os, "startfile", None)
tmp4 = Path(tempfile.mkdtemp(prefix="forms4_"))
try:
    for f in (_ROOT / "tests" / "fixtures" / "content").glob("*.json"):
        shutil.copy(f, tmp4 / f.name)
    for _n in ("showerror", "showinfo", "showwarning"):
        setattr(editor_mod.messagebox, _n, _rec(_n))
    editor_mod.messagebox.askyesno = _rec("askyesno", True)
    editor_mod.messagebox.askyesnocancel = _rec("askyesnocancel", True)

    # corrupt items.json (missing comma → parse error with line/column)
    ipath = tmp4 / "items.json"
    good = ipath.read_bytes()
    broken = good.replace(b'"id": "berries"', b'"id" "berries"', 1)
    assert broken != good, "corruption must actually bite"
    ipath.write_bytes(broken)

    root4, viewer = build(tmp4)
    assert viewer.bundle is None, "the set is unusable until repaired"
    parse_probs = [p for p in viewer.problems if p.file == "items.json"]
    assert parse_probs, viewer.problems
    assert parse_probs[0].line is not None and \
        parse_probs[0].column is not None, "structured line/column (D4)"

    # the unusable view lists THIS file's problems and the repair flow
    idx_i = list(CONTENT_FILES).index("items")
    viewer.file_list.selection_set(idx_i)
    viewer._render_file(idx_i)
    labels = [str(w.cget("text")) for w in _walk(viewer.records_frame)
              if w.winfo_class() == "Label"]
    assert any("line" in t and "column" in t for t in labels), labels
    assert any("repair:" in t for t in labels), labels

    # Open external hands the SELECTED file to the OS default editor
    _opened: list = []
    if _real_startfile is not None:
        os.startfile = lambda p: _opened.append(str(p))
        viewer._on_open_external()
        assert _opened and _opened[0].endswith("items.json"), _opened

    # fix externally (slightly non-canonical) → Reload loads the set
    ipath.write_bytes(good + b"\n")
    viewer._on_reload_click()            # nothing dirty → no prompt
    assert viewer.bundle is not None and viewer.problems == [], \
        (viewer.bundle, viewer.problems)

    # save path after repair: one edit → Save-All re-canonicalizes (D10)
    viewer.file_list.selection_set(idx_i)
    viewer._render_file(idx_i)
    viewer._on_edit_toggle("items", "berries")
    vform = viewer._forms[("items", "berries")]
    vform.vars["tooltip"].set("Repaired batch.")
    dialogued.clear()
    viewer._on_save()
    assert viewer.dirty == set(), viewer.dirty
    assert any(d[0] == "showinfo" and "Reformatted" in str(d[1])
               for d in dialogued), dialogued
    disk = ipath.read_bytes()
    assert b"Repaired batch." in disk and disk.endswith(b"\n") and \
        not disk.endswith(b"\n\n"), "Save-All writes canonical bytes"
    viewer.reload()
    assert dict(viewer._records_of("items"))["berries"]["tooltip"] == \
        "Repaired batch.", "the repaired+edited record round-trips"

    # Run check: buttons exist, completion reports on the UI thread
    bar_buttons = [str(w.cget("text")) for w in _walk(root4)
                   if w.winfo_class() == "Button"]
    assert "Run check" in bar_buttons and "Open external" in bar_buttons
    dialogued.clear()
    viewer._check_done(0, "check_live: OK (simulated)")
    assert "OK" in str(viewer.status_label.cget("text"))
    assert dialogued and dialogued[0][0] == "showinfo"
    viewer._check_done(1, "problems everywhere")
    assert "FAILED" in str(viewer.status_label.cget("text"))
    assert dialogued[-1][0] == "showerror"

    # THE acceptance: check_live against the REPAIRED directory
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "check_live.py"), str(tmp4)],
        capture_output=True, text=True, cwd=str(_ROOT), timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # clean close
    dialogued.clear()
    viewer._on_close()
    assert not dialogued, "clean close must not prompt"
finally:
    for _n, _fn in _real4.items():
        setattr(editor_mod.messagebox, _n, _fn)
    if _real_startfile is not None:
        os.startfile = _real_startfile
    shutil.rmtree(tmp4, ignore_errors=True)

print("GUI smoke OK: 2e repair flow + run-check")

# --- E5 (mount check): effects render generated text + editable model --------
# Generated text (D4) in the stacked viewer; the form registers an
# editable rowvars model (D17); mounting never mutates the record; the
# fixture's own effects validate clean (E2 pair). Full edit/save/
# reload/legality coverage follows in the E5 block below.
tmp5 = Path(tempfile.mkdtemp(prefix="effects_"))
try:
    for f in (_ROOT / "tests" / "fixtures" / "content").glob("*.json"):
        shutil.copy(f, tmp5 / f.name)
    root5, viewer5 = build(tmp5)
    assert viewer5.problems == [], viewer5.problems  # E2 pair legal

    # stacked read-only view renders the generated text, not the raw dict
    idx_p = list(CONTENT_FILES).index("patterns")
    viewer5.file_list.selection_set(idx_p)
    viewer5._render_file(idx_p)
    stacked = [str(w.cget("text")) for w in _walk(viewer5.records_frame)
               if w.winfo_class() == "Label"]
    assert any("+10% recovery" in t for t in stacked), stacked

    # E5: the record form registers an editable effects model (D17)
    viewer5._on_edit_toggle("patterns", "lean_to")
    form5 = viewer5._forms[("patterns", "lean_to")]
    assert "effects" in form5.rowvars and "effects" not in form5.vars
    assert form5.rowvars["effects"][0]["type"].get() == "recovery_bonus"
    rows = [str(w.cget("text")) for w in _walk(viewer5.records_frame)
            if w.winfo_class() == "Label"]
    assert any("+10% recovery" in t for t in rows), rows  # generated text
    lean = dict(viewer5.bundle.patterns)["lean_to"]
    assert lean["effects"] == [{"type": "recovery_bonus", "mult": 0.1}], \
        "mounting a form must not mutate the record"

    dialogued.clear()
    viewer5._on_close()
    assert not dialogued, "problems are not unsaved edits — clean close"
finally:
    shutil.rmtree(tmp5, ignore_errors=True)

print("GUI smoke OK: E1/E5 effects render + editable model mount")

# --- E5: editable rows — edit/type-swap/save/reload/remove/add, gating --------
tmp6 = Path(tempfile.mkdtemp(prefix="effects5_"))
_msgs6: list = []
_real6 = {n: getattr(editor_mod.messagebox, n) for n in
          ("showerror", "showinfo", "showwarning", "askyesno",
           "askyesnocancel")}


def _rec6(name, ret=None):
    def _f(*_a, **_k):
        _msgs6.append(name)
        return ret
    return _f


try:
    for f in (_ROOT / "tests" / "fixtures" / "content").glob("*.json"):
        shutil.copy(f, tmp6 / f.name)
    for n in ("showerror", "showinfo", "showwarning"):
        setattr(editor_mod.messagebox, n, _rec6(n))
    editor_mod.messagebox.askyesno = _rec6("askyesno", True)
    editor_mod.messagebox.askyesnocancel = _rec6("askyesnocancel", True)

    root6, viewer6 = build(tmp6)

    def _btn6(text, which=-1):
        found = [w for w in _walk(viewer6.records_frame)
                 if w.winfo_class() == "Button"
                 and str(w.cget("text")) == text]
        assert found, f"no {text!r} button"
        return found[which]

    # 1) type swap reseeds params and surfaces legality live (N1)
    idx_p6 = list(CONTENT_FILES).index("patterns")
    viewer6._render_file(idx_p6)
    viewer6._on_edit_toggle("patterns", "lean_to")
    f6 = viewer6._forms[("patterns", "lean_to")]
    rv6 = f6.rowvars["effects"][0]
    assert rv6["type"].get() == "recovery_bonus"
    assert rv6["mult"].get() == "0.1"
    rv6["type"].set("yield_bonus")            # legal on items only (E4)
    rv6 = f6.rowvars["effects"][0]
    assert "action" in rv6, "params reseeded for the new type"
    assert any("not (yet) allowed on patterns records" in p
               for p in viewer6.problems), viewer6.problems
    rv6["type"].set("recovery_bonus")
    rv6 = f6.rowvars["effects"][0]
    assert viewer6.problems == [], viewer6.problems

    # 2) write-through + generated preview (D4)
    rv6["mult"].set("0.25")
    lean6 = dict(viewer6.bundle.patterns)["lean_to"]
    assert lean6["effects"][0]["mult"] == 0.25, lean6["effects"]
    assert "patterns" in viewer6.dirty
    labels6 = [str(w.cget("text")) for w in _walk(viewer6.records_frame)
               if w.winfo_class() == "Label"]
    assert any("+25% recovery" in t for t in labels6), labels6

    # 3) save → reload roundtrip through the headless write layer
    viewer6._on_save()
    assert viewer6.dirty == set()
    assert "showerror" not in _msgs6, _msgs6
    saved6 = json.loads((tmp6 / "patterns.json").read_bytes())
    assert saved6["lean_to"]["effects"][0]["mult"] == 0.25, saved6
    viewer6.reload()
    viewer6._render_file(idx_p6)
    viewer6._on_edit_toggle("patterns", "lean_to")
    f6 = viewer6._forms[("patterns", "lean_to")]
    assert f6.rowvars["effects"][0]["mult"].get() == "0.25"

    # 4) Tunables shows the number (E5 S3): patterns → lean_to → effects
    viewer6._show_view("tunables")
    _t6 = viewer6.tunables_tree

    def _f6(parent, label):
        for node in _t6.get_children(parent):
            if _t6.item(node, "text") == label:
                return node
        return None

    _pnode = _f6("", "patterns.json")
    _lnode = _f6(_pnode, "lean_to")
    _enode = _f6(_lnode, "effects")
    _entry = _f6(_enode, "1. recovery_bonus")
    _mult = _f6(_entry, "mult")
    assert _mult is not None and str(_t6.item(_mult, "values")[0]) == "0.25", \
        "effect numbers missing from Tunables"
    viewer6._show_view("files")

    # 5) remove pops the optional field; add re-creates with the
    #    record's legal type (N1) and an explicit trigger (D8).
    #    (No re-render here: the view round-trip kept the pane form
    #    mounted, and toggling again would flip it OFF — _render_file
    #    does not clear _editing, only reload() does.)
    _x = [w for w in _walk(viewer6.records_frame)
          if w.winfo_class() == "Button" and str(w.cget("text")) == "✕"]
    _x[-1].invoke()          # effects is the last patterns field → last ✕
    lean6 = dict(viewer6.bundle.patterns)["lean_to"]
    assert "effects" not in lean6, "was_opt field pops when emptied"
    assert viewer6.problems == [], viewer6.problems
    _btn6("+ add effect").invoke()
    lean6 = dict(viewer6.bundle.patterns)["lean_to"]
    assert lean6["effects"][0]["type"] == "recovery_bonus", lean6
    assert lean6["effects"][0]["when"] == "always", \
        "explicit trigger on creation (D8)"

    # 6) N1 gating: items offer no add until E4; check:false forbids;
    #    check:true events offer the add (default side satisfies N2)
    # E4 enabled items×yield_bonus — the add button appears; drive the
    # form model (D17) so the revalidation actually refreshes
    idx_i6 = list(CONTENT_FILES).index("items")
    viewer6._render_file(idx_i6)
    viewer6._on_edit_toggle("items", "berries")
    _btn6("+ add effect").invoke()
    fb6 = viewer6._forms[("items", "berries")]
    erow_b = fb6.rowvars["effects"][0]
    assert erow_b["type"].get() == "yield_bonus", \
        "items' only legal type comes first"
    assert erow_b["when"].get() == "always", erow_b["when"].get()
    erow_b["add"].set("1")          # default int 0 predates the >=1 rule
    berries6 = next(r for r in viewer6.bundle.items if r["id"] == "berries")
    assert berries6["effects"][0]["add"] == 1, berries6["effects"]
    assert viewer6.problems == [], viewer6.problems
    idx_e6 = list(CONTENT_FILES).index("events")
    viewer6._render_file(idx_e6)
    viewer6._on_edit_toggle("events", "quiet_moment")
    _noeff = [w for w in _walk(viewer6.records_frame)
              if w.winfo_class() == "Button"
              and str(w.cget("text")) == "+ add effect"]
    assert not _noeff, "check:false events cannot declare effects"
    _labels_e = [str(w.cget("text")) for w in _walk(viewer6.records_frame)
                 if w.winfo_class() == "Label"]
    assert any("check:false events cannot declare" in t
               for t in _labels_e), _labels_e
    viewer6._render_file(idx_e6)
    viewer6._on_edit_toggle("events", "wandering_thoughts")
    _btn6("+ add effect").invoke()
    wander = dict(viewer6.bundle.events)["wandering_thoughts"]
    added = wander["effects"][-1]
    assert added["type"] == "vital_delta", added
    assert added["when"] == "on_failure", \
        "auto-added event entry defaults to on_failure (N2-friendly)"
    assert viewer6.problems == [], viewer6.problems

    # 7) save + clean close (no dialog)
    dialogued.clear()
    viewer6._on_save()
    viewer6._on_close()
    assert not dialogued, "clean close must not prompt"
finally:
    for _n, _fn in _real6.items():
        setattr(editor_mod.messagebox, _n, _fn)
    shutil.rmtree(tmp6, ignore_errors=True)

print("GUI smoke OK: E5 editable effect rows + gating + Tunables")