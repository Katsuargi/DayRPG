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
    _btn("✕", -1).invoke()
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