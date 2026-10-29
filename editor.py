"""Read-only content viewer (Phase 2a). Run: python editor.py [content_dir]

Imports the content layer ONLY — never game_core (constraint 1) — so it
opens and diagnoses whatever the game refuses to load. Hybrid by design
(2c): read-only by default (the viewer you browse), each record opened
for editing with a schema-driven form; all writes go through
content.save() — this module holds no write primitives of its own.
Every field of every file renders from content.SCHEMA
(D1), so a future content type (NPCs, merchants, ...) appears as soon
as it joins the schema — no viewer code changes.
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from content import (CONTENT_FILES, SCHEMA, EFFECT_TYPES, collect_references,
                     ContentError, StaleWriteError, effect_text, save,
                     try_load_content_with_state, validate_bundle)

BANNER_BG = "#8b1a1a"
FLASH_BG = "#ffe39a"
MUTED_FG = "#666677"
ALERT_FG = "#b00020"


class ContentViewer:
    """Browse one content directory: files, records, problems."""

    _SCALAR = {"slug": str, "string": str, "int": int, "bool": bool,
               "number": (int, float)}

    def __init__(self, root: tk.Tk, content_dir: Path) -> None:
        self.root = root
        self.dir = Path(content_dir).resolve()
        self.fixtures = "fixtures" in self.dir.parts
        root.title(
            f"Content Viewer — {self.dir}"
            + ("  [FIXTURES]" if self.fixtures else "")
        )
        root.geometry("1150x720")
        self.bundle = None
        self.problems = []
        self._blocks: dict[tuple[str, str], tk.Widget] = {}
        self._ref_out: dict = {}
        self._ref_in: dict = {}
        # 2c editing state: D9/D11 load facts, dirty stems (the Save-All
        # input), records open in form mode, ids not yet on disk (D7:
        # still slug-editable), plus reorder-banner bookkeeping.
        self._state = None
        self.dirty: set[str] = set()
        self._editing: set[tuple[str, str]] = set()
        self._unsaved_ids: set[tuple[str, str]] = set()
        self._reorder_warned: set[str] = set()
        self._forms: dict[tuple[str, str], "RecordForm"] = {}
        self._current_idx = 0
        # 2d state: the single pane-mounted edit (D14, None while
        # browsing) and the per-record ● set (D15, session-scoped)
        self._pane_edit: tuple[str, str] | None = None
        self._record_dirty: set[tuple[str, str]] = set()
        self._renamed: dict[tuple[str, str], str] = {}  # D18 stale-id map
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_widgets()
        self.reload()

    # --- layout ----------------------------------------------------------

    def _build_widgets(self) -> None:
        if self.fixtures:
            tk.Label(
                self.root, anchor="w", padx=8, pady=3, bg=BANNER_BG,
                fg="white", font=(None, 10, "bold"),
                text="FIXTURES DIRECTORY — pinned by the engine tests; "
                     "the game does not run on these files",
            ).pack(fill="x")
        bar = tk.Frame(self.root)
        bar.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(bar, text=str(self.dir), anchor="w", fg=MUTED_FG).pack(
            side="left")
        self.status_label = tk.Label(bar, anchor="w", fg=MUTED_FG)
        self.status_label.pack(side="left")
        tk.Button(bar, text="Save-All", command=self._on_save).pack(
            side="right")
        tk.Button(bar, text="Open external",
                  command=self._on_open_external).pack(side="right")
        tk.Button(bar, text="Run check",
                  command=self._on_run_check).pack(side="right")
        tk.Button(bar, text="Reload",
                  command=self._on_reload_click).pack(side="right")
        views = tk.Frame(bar)
        views.pack(side="right", padx=(0, 8))
        self.btn_files = tk.Button(
            views, text="Browse", command=lambda: self._show_view("files"))
        self.btn_tun = tk.Button(
            views, text="Tunables",
            command=lambda: self._show_view("tunables"))
        self.btn_econ = tk.Button(
            views, text="Economy",
            command=lambda: self._show_view("economy"))
        self.btn_files.pack(side="left", padx=2)
        self.btn_tun.pack(side="left", padx=2)
        self.btn_econ.pack(side="left", padx=2)

        body = tk.PanedWindow(self.root, orient="horizontal", sashwidth=4)
        body.pack(fill="both", expand=True, padx=8, pady=4)

        left = tk.Frame(body, width=230)
        body.add(left, minsize=190)
        tk.Label(left, text="FILES", anchor="w", font=(None, 9, "bold")).pack(
            fill="x", padx=4)
        self.file_list = tk.Listbox(left, exportselection=False, width=30,
                                    activestyle="none")
        self.file_list.pack(fill="both", expand=True)
        self.file_list.bind("<<ListboxSelect>>", self._on_file_select)

        right = tk.Frame(body)
        body.add(right, minsize=430)

        # two stacked views: schema-driven records (Browse) and the
        # aggregate Tunables sheet; toggled by the toolbar buttons
        self.files_pane = tk.Frame(right)
        self.tunables_pane = tk.Frame(right)
        self.economy_pane = tk.Frame(right)
        self.records_canvas = tk.Canvas(self.files_pane,
                                        highlightthickness=0)
        scroll = tk.Scrollbar(self.files_pane, orient="vertical",
                              command=self.records_canvas.yview)
        self.records_frame = tk.Frame(self.records_canvas)
        self.records_frame.bind(
            "<Configure>",
            lambda _e: self.records_canvas.configure(
                scrollregion=self.records_canvas.bbox("all")),
        )
        self.records_canvas.create_window((0, 0), window=self.records_frame,
                                          anchor="nw")
        self.records_canvas.configure(yscrollcommand=scroll.set)
        self.records_canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.files_pane.pack(fill="both", expand=True)
        self._bind_scroll(self.records_frame)
        self._build_tunables_pane()
        self._build_economy_pane()

        self._show_view("files")

        panel = tk.LabelFrame(self.root, text="Problems", padx=6, pady=4)
        panel.pack(fill="x", padx=8, pady=(2, 8))
        self.problems_list = tk.Listbox(panel, height=5,
                                        exportselection=False)
        self.problems_list.pack(fill="x")
        self.problems_list.bind("<<ListboxSelect>>", self._on_problem_click)
        tk.Label(panel, anchor="w", fg=MUTED_FG,
                 text="click a problem to jump to its file and record"
                 ).pack(fill="x")

    def _bind_scroll(self, widget: tk.Widget) -> None:
        widget.bind("<MouseWheel>", self._on_mousewheel)
        for child in widget.winfo_children():
            self._bind_scroll(child)

    def _on_mousewheel(self, event) -> str:
        self.records_canvas.yview_scroll(-1 * (event.delta // 120), "units")
        # Stop class bindings: a readonly Combobox under the cursor would
        # otherwise change value while the user merely scrolls — hover
        # over any form widget must never edit anything.
        return "break"

    # --- tunables view (wholesale balance review, one screen) -------------

    def _show_view(self, which: str) -> None:
        """Toggle Browse (records) / Tunables (aggregate) / Economy (item
        flow) — each view is its own pane; only one is packed at a time."""
        self.view = which
        panes = {"files": self.files_pane, "tunables": self.tunables_pane,
                 "economy": self.economy_pane}
        for name, pane in panes.items():
            if name == which:
                pane.pack(fill="both", expand=True)
            else:
                pane.pack_forget()
        for name, btn in (("files", self.btn_files), ("tunables", self.btn_tun),
                          ("economy", self.btn_econ)):
            btn.config(relief="sunken" if name == which else "raised")

    def _build_tunables_pane(self) -> None:
        tk.Label(
            self.tunables_pane, anchor="w", font=(None, 10, "bold"),
            text="Tunables — every balance-relevant number across all "
                 "files (read-only; edit in the record or balance.json)",
        ).pack(fill="x", padx=4, pady=(4, 2))
        self.tunables_tree = ttk.Treeview(
            self.tunables_pane, columns=("value",), show="tree headings")
        self.tunables_tree.heading("#0", text="setting")
        self.tunables_tree.heading("value", text="value")
        self.tunables_tree.column("value", width=360, anchor="w")
        vsb = tk.Scrollbar(self.tunables_pane, orient="vertical",
                           command=self.tunables_tree.yview)
        self.tunables_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tunables_tree.pack(fill="both", expand=True)

    def _build_economy_pane(self) -> None:
        tk.Label(
            self.economy_pane, anchor="w", font=(None, 10, "bold"),
            text="Economy — per-item sources and sinks (content-declared "
                 "flows only)",
        ).pack(fill="x", padx=4, pady=(4, 2))
        self.economy_tree = ttk.Treeview(
            self.economy_pane, columns=("note",), show="tree headings")
        self.economy_tree.heading("#0", text="item / flow")
        self.economy_tree.heading("note", text="note")
        self.economy_tree.column("note", width=320, anchor="w")
        self.economy_tree.tag_configure("bad", foreground="#b00020")
        vsb = tk.Scrollbar(self.economy_pane, orient="vertical",
                           command=self.economy_tree.yview)
        self.economy_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.economy_tree.pack(fill="both", expand=True)
        tk.Label(
            self.economy_pane, anchor="w", fg=MUTED_FG, justify="left",
            text=(
                "Sources = how an item enters play (initial stock, gather "
                "yields, craft outputs). Sinks = content consumption "
                "(pattern materials); tools are equipment, not consumed. "
                "Engine-side consumption (e.g. Sleep eating food) is not "
                "content-declared. Red = nothing grants this item."),
        ).pack(fill="x", padx=4, pady=(0, 4))

    def _build_tunables(self) -> None:
        """Rebuild the aggregate sheet from the schema + current bundle."""
        tree = self.tunables_tree
        tree.delete(*tree.get_children())
        if self.bundle is None:
            tree.insert("", "end", text="cannot render — file set unusable",
                        values=("",))
            return
        for fname in CONTENT_FILES:
            spec = SCHEMA[fname]
            file_node = tree.insert("", "end", text=f"{fname}.json",
                                    values=("",), open=True)
            if spec["kind"] == "flat":
                recs = [("balance", getattr(self.bundle, fname))]
            else:
                recs = self._records_of(fname)
            for rec_id, rec in recs:
                parent = (file_node if spec["kind"] == "flat" else
                          tree.insert(file_node, "end", text=rec_id,
                                      values=("",), open=True))
                if isinstance(rec, dict):
                    self._tune_rows(tree, parent, fname, rec, spec["fields"])

    def _tune_rows(self, tree, parent, fname, rec, fields) -> None:
        for field, fspec in fields.items():
            spec = fspec
            while isinstance(spec, tuple) and spec[0] in ("opt", "nullable"):
                spec = spec[1]
            value = rec.get(field)
            if isinstance(spec, tuple) and spec[0] == "nested":
                node = tree.insert(parent, "end", text=field, values=("",),
                                   open=True)
                if isinstance(value, dict):
                    self._tune_rows(tree, node, fname, value, spec[1])
                else:
                    tree.insert(node, "end", text="(not an object)",
                                values=(f"{value!r} ⚠",))
                continue
            shown = None
            if isinstance(spec, str) and spec in ("int", "number"):
                if value is None and field == "difficulty":
                    shown = "(global)"  # knob exists; record uses the DC
                elif value is not None:
                    shown = self._value_text(spec, value, fname)
            elif (isinstance(spec, tuple) and spec[0] in ("pair", "dict_int")
                  and value is not None):
                shown = self._value_text(spec, value, fname)
            if shown is not None:
                tree.insert(parent, "end", text=field, values=(shown,))

    # --- references & economy ---------------------------------------------

    def _build_refs(self) -> None:
        """Reference-graph indexes (uses/used-by) + the economy sheet,
        both from content.collect_references — the same data 2c's
        delete-blocking will use."""
        self._ref_out = {}
        self._ref_in = {}
        if self.bundle is not None:
            for e in collect_references(self.bundle):
                self._ref_out.setdefault((e[0], e[1]), []).append(e)
                self._ref_in.setdefault((e[3], e[4]), []).append(e)
        self._build_economy()

    def _build_economy(self) -> None:
        """Fill the economy sheet: per-item sources and sinks. An item
        nothing grants is tagged bad (red)."""
        tree = self.economy_tree
        tree.delete(*tree.get_children())
        if self.bundle is None:
            return
        inbound_items = {}
        for (to_f, to_r), elist in self._ref_in.items():
            if to_f == "items":
                inbound_items[to_r] = elist
        sinks: dict[str, list] = {}
        for pid, pat in self.bundle.patterns.items():
            for mat, qty in pat["materials"].items():
                sinks.setdefault(mat, []).append((pid, qty))
        for rec in self.bundle.items:
            if not isinstance(rec, dict) or "id" not in rec:
                continue  # items.json is array-kind; be total anyway
            iid, item = rec["id"], rec
            sources = []
            if item.get("start", 0):
                sources.append(f"initial stock ×{item['start']}")
            for e in inbound_items.get(iid, []):
                if e[2] == "gather.item":
                    sources.append(f"{e[1]} (gather yield)")
            if iid in self.bundle.patterns:
                sources.append("craft pattern (id matches)")
            node = tree.insert("", "end", text=iid, open=True, values=("",),
                               tags=() if sources else ("bad",))
            snode = tree.insert(node, "end", text="sources", values=("",))
            for s in sources or ["NOTHING grants this item"]:
                tree.insert(snode, "end", text=s, values=("",))
            knode = tree.insert(node, "end", text="sinks", values=("",))
            for pid, qty in sinks.get(iid, []):
                tree.insert(knode, "end", text=f"{pid} ×{qty}", values=("",))
            if not sinks.get(iid):
                if item.get("tool_bonus"):
                    tree.insert(knode, "end",
                                text="equipment (held, not consumed)",
                                values=("",))
                else:
                    tree.insert(knode, "end", text="—", values=("",))

    def _render_ref_rows(self, fname: str, rec_id: str) -> None:
        """Uses/used-by rows: the content-declared reference graph around
        this record; each entry jumps through the graph on click (item ->
        the action that yields it, skill -> the pattern gated on it, ...)."""
        for title, edges, target_end in (
            ("uses", self._ref_out.get((fname, rec_id), []), "to"),
            ("used by", self._ref_in.get((fname, rec_id), []), "from"),
        ):
            if not edges:
                continue
            row = tk.Frame(self.records_frame)
            row.pack(fill="x", padx=8, pady=(0, 1))
            tk.Label(row, anchor="w", fg=MUTED_FG, text=title,
                     width=9).pack(side="left")
            for e in edges:
                tf, tr = (e[3], e[4]) if target_end == "to" else (e[0], e[1])
                link = tk.Label(row, anchor="w", fg="#1a5fb4", cursor="hand2",
                                text=f"{tf}.{tr} · {e[2]}")
                link.pack(side="left", padx=(0, 10))
                link.bind("<Button-1>",
                          lambda _ev, f=tf, r=tr: self._jump_to(f, r))

    # --- data ------------------------------------------------------------

    def reload(self) -> None:
        # One read yields bundle + D9 baseline + D11 hashes; a reload
        # also clears every editing flag — nothing unsaved survives it
        # (the button path asks first, this method is the bare reset).
        self.bundle, self._state = try_load_content_with_state(self.dir)
        self.problems = list(self._state.problems)
        self.dirty.clear()
        self._editing.clear()
        self._unsaved_ids.clear()
        self._reorder_warned.clear()
        self._forms.clear()
        self._pane_edit = None
        self._record_dirty.clear()
        self._renamed.clear()
        self._rebuild()

    def _records_of(self, fname: str) -> list[tuple[str, dict]]:
        """(record_id, record) pairs for a file, in file order."""
        data = getattr(self.bundle, fname)
        if fname == "balance":
            return [("balance", data)]
        if isinstance(data, list):
            return [(str(rec.get("id", f"#{i}")), rec)
                    for i, rec in enumerate(data)]
        return [(str(key), rec) for key, rec in data.items()]

    def _display_of(self, fname: str, value) -> str:
        """Human name for a referenced record id (best effort)."""
        if self.bundle is None:
            return str(value)
        try:
            for rec_id, rec in self._records_of(fname):
                if rec_id == value:
                    return str(rec.get("name") or rec.get("label")
                               or rec.get("text") or value)
        except AttributeError:  # unparseable sets have nothing to resolve
            pass
        return f"{value} ⚠"

    def _refresh_lists(self) -> None:
        """Rewrite file rows (dirty ● + problem counts) and the problem
        list. Keystroke-safe: it never touches the records pane, so an
        open form keeps its focus while live validation runs."""
        keep = self.file_list.curselection()
        self.file_list.delete(0, "end")
        per_file: dict[str, int] = {}
        for prob in self.problems:
            owner = getattr(prob, "file", None)
            per_file[owner] = per_file.get(owner, 0) + 1
        for fname in CONTENT_FILES:
            if self.bundle is None:
                summary = "— unusable"
            else:
                summary = f"{len(self._records_of(fname))} records"
            bad = per_file.get(f"{fname}.json", 0)
            mark = "● " if fname in self.dirty else "  "
            self.file_list.insert(
                "end",
                f"{mark}{fname:<9} {summary}" + (f"  ⚠{bad}" if bad else ""),
            )
        if keep:
            self.file_list.selection_set(keep[0])
        self.problems_list.delete(0, "end")
        if not self.problems:
            self.problems_list.insert("end", "✓ no problems")
        for prob in self.problems:
            owner = getattr(prob, "file", None) or "engine"
            self.problems_list.insert("end", f"{owner}: {prob}")
        if self.dirty:
            self.status_label.config(
                text="  unsaved: " + ", ".join(sorted(self.dirty)))
        else:
            self.status_label.config(text="  no unsaved changes")

    def _rebuild(self) -> None:
        self._refresh_lists()
        self.file_list.selection_set(0)
        self._build_refs()      # graph indexes must exist before rendering
        self._render_file(0)
        self._build_tunables()  # keep the aggregate sheet in sync

    # --- events -----------------------------------------------------------

    def _on_file_select(self, _event=None) -> None:
        sel = self.file_list.curselection()
        if sel:
            self._render_file(sel[0])

    def _on_problem_click(self, _event=None) -> None:
        sel = self.problems_list.curselection()
        if not sel or sel[0] >= len(self.problems):
            return
        prob = self.problems[sel[0]]
        owner = getattr(prob, "file", None) or ""
        fname = owner[: -len(".json")] if owner.endswith(".json") else ""
        record_id = str(getattr(prob, "record_id", "") or "")
        self._jump_to(fname, record_id)

    def _jump_to(self, fname: str, record_id: str) -> None:
        """Select the file, re-render, flash + scroll to the record — the
        shared click-through for problem rows and reference links."""
        if fname in CONTENT_FILES:
            # a jump is browse intent (D14): unmount a pane edit that
            # would mask the target; a pane edit on another file, or on
            # THE target itself, survives
            if (self._pane_edit is not None
                    and self._pane_edit[0] == fname
                    and self._pane_edit != (fname, record_id)):
                old = self._pane_edit
                self._pane_edit = None
                self._editing.discard(old)
                self._forms.pop(old, None)
            idx = list(CONTENT_FILES).index(fname)
            self.file_list.selection_clear(0, "end")
            self.file_list.selection_set(idx)
            self._render_file(idx)
        block = self._blocks.get((fname, record_id))
        if block is not None:
            block.configure(bg=FLASH_BG)
            self.root.after(1200, lambda: block.configure(bg=""))
            try:
                fraction = block.winfo_y() / max(
                    1, self.records_frame.winfo_height())
                self.records_canvas.yview_moveto(
                    min(0.95, max(0.0, fraction)))
            except tk.TclError:
                pass

    # --- 2c editing: record ops, save, guards --------------------------------

    def _record_buttons(self, fname: str, rec_id: str, ops: bool) -> None:
        """Edit/Done toggle (the hybrid mount switch) plus array-record
        operations (D5 reorder, D7 duplicate/delete)."""
        bar = tk.Frame(self.records_frame)
        bar.pack(fill="x", padx=8)
        tk.Button(
            bar, text="Done" if (fname, rec_id) in self._editing
            else "Edit", width=6,
            command=lambda: self._on_edit_toggle(fname, rec_id),
        ).pack(side="left")
        if ops:
            recs = self._records_of(fname)
            pos = next(i for i, (rid, _r) in enumerate(recs)
                       if rid == rec_id)
            tk.Button(bar, text="Duplicate", width=9,
                      command=lambda: self._on_duplicate(fname,
                                                         rec_id)).pack(
                side="left", padx=(8, 2))
            tk.Button(
                bar, text="↑", width=2,
                state="disabled" if pos == 0 else "normal",
                command=lambda: self._on_move(fname, rec_id, -1),
            ).pack(side="left", padx=1)
            tk.Button(
                bar, text="↓", width=2,
                state="disabled" if pos == len(recs) - 1 else "normal",
                command=lambda: self._on_move(fname, rec_id, +1),
            ).pack(side="left", padx=1)
            tk.Button(bar, text="Delete", width=7,
                      command=lambda: self._on_delete(fname, rec_id)).pack(
                side="left", padx=(8, 2))

    def _on_edit_toggle(self, fname: str, rec_id: str) -> None:
        rec_id = self._live_id(fname, rec_id)  # stale-closure safety (D18)
        key = (fname, rec_id)
        if key in self._editing:
            self._editing.discard(key)
            self._forms.pop(key, None)
            if self._pane_edit == key:
                self._pane_edit = None      # Done → back to browsing
        else:
            self._editing.add(key)
            if SCHEMA[fname].get("layout") == "pane":
                self._enter_pane(key)
        self._render_file(self._current_idx)

    def _enter_pane(self, key: tuple[str, str]) -> None:
        """D14: mount this record as THE pane edit (one at a time)."""
        if self._pane_edit is not None and self._pane_edit != key:
            old = self._pane_edit
            self._editing.discard(old)
            self._forms.pop(old, None)
        self._pane_edit = key

    def _live_id(self, fname: str, rec_id: str) -> str:
        """Buttons close over the id they rendered with; a rename (D7
        array ids, D18 dict keys) makes those closures stale — resolve
        to today's id (rename writes keep the map single-hop)."""
        return self._renamed.get((fname, rec_id), rec_id)

    def _record_rename(self, fname: str, old: str, new: str) -> None:
        """Remember a rename so stale closures still resolve; entries
        already pointing at `old` advance to `new` (chains compress)."""
        for key in self._renamed:
            if self._renamed[key] == old:
                self._renamed[key] = new
        self._renamed[(fname, old)] = new

    def _next_id(self, fname: str, base: str) -> str:
        existing = {rid for rid, _ in self._records_of(fname)}
        candidate, n = base, 1
        while candidate in existing:
            n += 1
            candidate = f"{base}_{n}"
        return candidate

    def _default_record(self, fname: str, rec_id: str) -> dict:
        """Schema-driven defaults: id = suggested slug, string = "",
        int/number = 0, bool = False; optional and exotic fields start
        absent — the form and validation finish the job (a half-filled
        record blocks Save-All naming its problems, per constraint 3)."""
        rec: dict = {}
        for field, fspec in SCHEMA[fname]["fields"].items():
            spec = fspec
            optional = nullable = False
            while isinstance(spec, tuple) and spec[0] in ("opt", "nullable"):
                optional = optional or spec[0] == "opt"
                nullable = nullable or spec[0] == "nullable"
                spec = spec[1]
            if nullable and not optional:
                # house style: nullable keys ship present as null (the
                # fixtures carry them and the engine reads with [])
                rec[field] = None
                continue
            if optional:
                continue  # absent until edited
            if isinstance(spec, tuple) and spec[0] in ("list", "dict_int"):
                rec[field] = [] if spec[0] == "list" else {}  # house style
                continue
            if not isinstance(spec, str):
                continue  # pair/ref/nested start unset (user chooses)
            if spec == "slug":
                rec[field] = rec_id
            elif spec == "string":
                rec[field] = ""
            elif spec in ("int", "number"):
                rec[field] = 0
            elif spec == "bool":
                rec[field] = False
        return rec

    def _mark_dirty(self, fname: str) -> None:
        """Any in-memory change: mark, revalidate live, refresh the
        panels — never the records pane (open forms keep focus)."""
        self.dirty.add(fname)
        self.problems = list(validate_bundle(self.bundle))
        self._refresh_lists()

    def _on_add(self, fname: str) -> None:
        if self.bundle is None or SCHEMA[fname].get("kind") not in (
                "array", "dict"):
            return
        base = "new_" + (fname[:-1] if fname.endswith("s") else fname)
        rec_id = self._next_id(fname, base)
        rec = self._default_record(fname, rec_id)
        if SCHEMA[fname].get("kind") == "dict":
            getattr(self.bundle, fname)[rec_id] = rec  # key = id (D18)
        else:
            getattr(self.bundle, fname).append(rec)
        self._unsaved_ids.add((fname, rec_id))
        self._editing.add((fname, rec_id))  # a new record opens for edit
        if SCHEMA[fname].get("layout") == "pane":
            self._enter_pane((fname, rec_id))
        self._mark_dirty(fname)
        self._render_file(self._current_idx)

    def _on_duplicate(self, fname: str, rec_id: str) -> None:
        rec_id = self._live_id(fname, rec_id)
        if self.bundle is None or SCHEMA[fname].get("kind") not in (
                "array", "dict"):
            return
        source = next((r for rid, r in self._records_of(fname)
                       if rid == rec_id), None)
        if source is None:
            return
        new_id = self._next_id(fname, f"{rec_id}_copy")
        new_rec = copy.deepcopy(source)
        if isinstance(new_rec, dict) and "id" in new_rec:
            new_rec["id"] = new_id
        if SCHEMA[fname].get("kind") == "dict":
            getattr(self.bundle, fname)[new_id] = new_rec  # key = id
        else:
            getattr(self.bundle, fname).append(new_rec)  # D5: at end
        self._unsaved_ids.add((fname, new_id))
        self._mark_dirty(fname)
        self._render_file(self._current_idx)

    def _on_move(self, fname: str, rec_id: str, delta: int) -> None:
        rec_id = self._live_id(fname, rec_id)
        if self.bundle is None or SCHEMA[fname].get("kind") not in (
                "array", "dict"):
            return
        recs = getattr(self.bundle, fname)
        ids = [rid for rid, _ in self._records_of(fname)]
        if rec_id not in ids:
            return
        pos = ids.index(rec_id)
        target = pos + delta
        if not 0 <= target < len(recs):
            return
        if SCHEMA[fname].get("kind") == "dict":
            # dict order is data: swap keys by rebuilding in place
            ids[pos], ids[target] = ids[target], ids[pos]
            swapped = {k: recs[k] for k in ids}
            recs.clear()
            recs.update(swapped)
        else:
            recs[pos], recs[target] = recs[target], recs[pos]
        if fname not in self._reorder_warned:  # D5 banner, once per file
            self._reorder_warned.add(fname)
            messagebox.showinfo(
                "Reorder shifts the seeds",
                "Record order is display order AND seeded-RNG input.\n"
                "Seeded results will shift — if engine tests should "
                "notice,\nre-pin the fixture deliberately (DEV_GUIDE: "
                "Testing workflow).")
        self._mark_dirty(fname)
        self._render_file(self._current_idx)

    def _on_delete(self, fname: str, rec_id: str) -> None:
        rec_id = self._live_id(fname, rec_id)
        if self.bundle is None or SCHEMA[fname].get("kind") not in (
                "array", "dict"):
            return
        # incoming edges only: deleting breaks whoever REFERENCES this
        # record (its own outgoing refs die with it — not a blocker)
        edges = [e for e in collect_references(self.bundle)
                 if e[3] == fname and e[4] == rec_id]
        if edges:  # D7: referenced records cannot be deleted
            listing = "\n".join(f"    {e[0]}.{e[1]} — {e[2]}"
                                for e in edges)
            messagebox.showerror(
                f"{rec_id} is still in use",
                "Delete blocked — these content records reference it:\n"
                + listing)
            return
        if not messagebox.askyesno(
                "Delete record",
                f"Remove {fname}.{rec_id} from the in-memory set?\n"
                "It reaches disk only when you Save-All."):
            return
        recs = getattr(self.bundle, fname)
        ids = [rid for rid, _ in self._records_of(fname)]
        if rec_id in ids:
            if isinstance(recs, dict):
                recs.pop(rec_id)
            else:
                recs.pop(ids.index(rec_id))
        self._unsaved_ids.discard((fname, rec_id))
        self._editing.discard((fname, rec_id))
        self._forms.pop((fname, rec_id), None)
        self._record_dirty.discard((fname, rec_id))
        if self._pane_edit == (fname, rec_id):
            self._pane_edit = None  # a deleted record can't stay mounted
        self._mark_dirty(fname)
        self._render_file(self._current_idx)

    def _on_save(self) -> None:
        """Save-All (D9): stage every dirty file, gate, temp→replace."""
        if self.bundle is None:
            messagebox.showerror(
                "Nothing to save",
                "The file set failed to parse — fix the problems first.")
            return
        if not self.dirty:
            messagebox.showinfo("Save", "No unsaved changes.")
            return
        self._save_through()

    def _save_through(self, overwrite: bool = False) -> bool:
        ordered = [n for n in CONTENT_FILES if n in self.dirty]
        try:
            result = save(self.bundle, self.dir, state=self._state,
                          dirty=ordered, overwrite_stale=overwrite)
        except StaleWriteError as exc:
            choice = messagebox.askyesnocancel(  # D11 dirty-buffer paths
                "Changed on disk",
                "These files changed on disk since you loaded them:\n  "
                + ", ".join(f"{f}.json" for f in exc.files)
                + "\n\nYES = overwrite the disk changes"
                  "\nNO = discard your changes and reload"
                  "\nCANCEL = keep editing, save nothing")
            if choice is True:
                return self._save_through(overwrite=True)
            if choice is False:
                self.reload()
            return choice is not None
        except ContentError as exc:
            messagebox.showerror(
                "Save blocked",
                "The edit would make the problem count worse — nothing "
                "was written. Fix these first:\n  "
                + "\n  ".join(str(p) for p in exc.problems))
            return False
        except OSError as exc:
            # locked/restricted file (antivirus, permissions): a plain
            # message, buffer stays dirty — never a console traceback
            messagebox.showerror("Save failed", str(exc))
            return False
        for fname in result.written:
            self.dirty.discard(fname)
            self._record_dirty = {k for k in self._record_dirty
                                  if k[0] != fname}
            for key in [k for k in self._unsaved_ids if k[0] == fname]:
                self._unsaved_ids.discard(key)  # on disk: D7 locks it
        # the write moved disk under us — refresh D9 baseline + D11 hashes
        _, self._state = try_load_content_with_state(self.dir)
        self.problems = list(validate_bundle(self.bundle))
        if result.skipped:
            messagebox.showwarning(
                "Saved, with skips",
                "Not written (still have problems of their own):\n  "
                + ", ".join(f"{f}.json" for f in result.skipped)
                + "\n  Every other dirty file was saved.")
        if result.reformatted:
            messagebox.showinfo(
                "Reformatted",
                "Saved, but these files weren't canonical (CRLF / odd "
                "indentation / BOM), so their formatting was rewritten "
                "(D10):\n  "
                + ", ".join(f"{f}.json" for f in result.reformatted))
        self._refresh_lists()
        self._render_file(self._current_idx)  # id locks refresh
        return True

    def _confirm_discard(self) -> bool:
        """The unsaved-changes guard: save / discard / cancel. True means
        the caller may proceed (either saved, or discard was chosen)."""
        if not self.dirty:
            return True
        choice = messagebox.askyesnocancel(
            "Unsaved changes",
            "Unsaved: " + ", ".join(sorted(self.dirty))
            + "\n\nYES = save first\nNO = discard them\nCANCEL = stay")
        if choice is None:
            return False
        if choice is True:
            return self._save_through()
        return True  # discard — the caller's reload/close re-reads disk

    def _on_reload_click(self) -> None:
        if not self._confirm_discard():
            return
        self.reload()

    def _on_close(self) -> None:
        if not self._confirm_discard():
            return
        self.root.destroy()

    # --- 2e: repair flow (D4: line/column + open-external + reload) ---------

    def _render_unusable(self, fname: str) -> None:
        """Bundle-None view for one file: its parse problems (structured
        line/column — D4) plus the repair flow. The raw pane stays
        deferred: fix externally, Reload, Save-All re-canonicalizes."""
        prefix = f"{fname}.json: "
        mine = [prob for prob in self.problems
                if getattr(prob, "file", None) == f"{fname}.json"]
        if not mine:  # this file parses; another file blocks the set
            tk.Label(self.records_frame, anchor="w", fg=MUTED_FG,
                     text="this file parses — the set loads once the "
                          "flagged file(s) are fixed (see Problems)",
                     ).pack(fill="x", padx=12)
            return
        tk.Label(self.records_frame, anchor="w", fg=MUTED_FG,
                 text="cannot render — the file set failed to parse",
                 ).pack(fill="x", padx=12)
        for prob in mine:
            text = str(prob)
            if text.startswith(prefix):
                text = text[len(prefix):]
            tk.Label(self.records_frame, anchor="w", fg=ALERT_FG,
                     text=f"    {text}").pack(fill="x", padx=12)
        tk.Label(self.records_frame, anchor="w", fg=MUTED_FG,
                 text="    repair: Open external (top bar) → edit in your "
                      "OS default → Reload; Save-All then re-canonicalizes.",
                 ).pack(fill="x", padx=12)

    def _on_open_external(self) -> None:
        """2e (D4): hand the SELECTED file to the OS default editor —
        fix there, then Reload (D11 watches the disk change)."""
        sel = self.file_list.curselection()
        if not sel:
            return
        path = self.dir / f"{CONTENT_FILES[sel[0]]}.json"
        if not path.exists():
            messagebox.showinfo("Open external",
                                f"{path.name} does not exist yet.")
            return
        try:
            if hasattr(os, "startfile"):  # Windows
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            messagebox.showerror("Open external",
                                 f"Could not open {path.name}: {exc}")

    def _on_run_check(self) -> None:
        """2e: spawn check_live.py against the OPENED directory (it
        takes a directory argument now). The wait happens on a worker
        thread — the UI never blocks."""
        self.status_label.config(text="  check running…")
        here = Path(__file__).resolve().parent
        try:
            proc = subprocess.Popen(
                [sys.executable, str(here / "check_live.py"), str(self.dir)],
                cwd=str(here), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True)
        except OSError as exc:
            self.status_label.config(text="  check failed to start")
            messagebox.showerror("Run check", str(exc))
            return

        def _wait() -> None:
            out = proc.communicate()[0] or ""
            self.root.after(
                0, lambda: self._check_done(proc.returncode, out))

        threading.Thread(target=_wait, daemon=True).start()

    def _check_done(self, code: int, out: str) -> None:
        """Completion re-enters the UI thread; report via dialog
        (patched headless in tests)."""
        self.status_label.config(
            text="  check: OK" if code == 0 else "  check: FAILED")
        tail = out[-3000:]
        if code == 0:
            messagebox.showinfo("Run check",
                                "check_live passed:\n\n" + tail)
        else:
            messagebox.showerror("Run check",
                                 "check_live failed:\n\n" + tail)

    # --- rendering --------------------------------------------------------

    def _clear_records(self) -> None:
        for child in self.records_frame.winfo_children():
            child.destroy()
        self._blocks.clear()

    def _render_file(self, index: int) -> None:
        self._clear_records()
        self._current_idx = index
        fname = CONTENT_FILES[index]
        tk.Label(self.records_frame, anchor="w", font=(None, 10, "bold"),
                 text=f"{fname}.json").pack(fill="x", padx=4, pady=(4, 2))
        if self.bundle is None:
            self._render_unusable(fname)
            return
        if self._pane_edit is not None and self._pane_edit[0] == fname:
            self._render_pane_edit(fname)
            self._bind_scroll(self.records_frame)
            return
        if SCHEMA[fname].get("kind") in ("array", "dict"):
            tk.Button(self.records_frame, text="+ add record",
                      command=lambda f=fname: self._on_add(f)).pack(
                anchor="e", padx=8, pady=(0, 2))
        for rec_id, rec in self._records_of(fname):
            self._render_record(fname, rec_id, rec)
        # rows/forms are rebuilt constantly — rebind hover-scroll (and its
        # wheel "break" guard) onto every widget just created
        self._bind_scroll(self.records_frame)

    def _header_text(self, fname: str, rec_id: str) -> str:
        """D15: the record's header line, with the session ● marker."""
        mark = "● " if (fname, rec_id) in self._record_dirty else ""
        return f"  {mark}{rec_id}"

    def _touch_record(self, fname: str, rec_id: str) -> None:
        """Mark one record edited and update its header IN PLACE —
        labels never hold focus, so this is keystroke-safe (the
        panels-only refresh rule is preserved)."""
        self._record_dirty.add((fname, rec_id))
        header = self._blocks.get((fname, rec_id))
        if header is not None:
            header.configure(text=self._header_text(fname, rec_id))

    def _render_pane_edit(self, fname: str) -> None:
        """D14 pane mount: exactly one record — add button, Done/ops,
        ref rows, form. No in-pane selection; Done returns to browsing."""
        rec_id = self._pane_edit[1]
        rec = next((r for rid, r in self._records_of(fname)
                    if rid == rec_id), None)
        if rec is None:  # vanished under us — fall back to browsing
            self._pane_edit = None
            self._editing.discard((fname, rec_id))
            self._forms.pop((fname, rec_id), None)
            self._render_file(self._current_idx)
            return
        tk.Label(self.records_frame, anchor="w", fg=MUTED_FG,
                 text="editing one record — Done returns to browsing"
                 ).pack(fill="x", padx=4)
        if SCHEMA[fname].get("kind") in ("array", "dict"):
            tk.Button(self.records_frame, text="+ add record",
                      command=lambda f=fname: self._on_add(f)).pack(
                anchor="e", padx=8, pady=(0, 2))
        self._render_record(fname, rec_id, rec)

    def _render_record(self, fname: str, rec_id: str, rec) -> None:
        header = tk.Label(self.records_frame, anchor="w", bg="#e8e8f0",
                          font=(None, 9, "bold"),
                          text=self._header_text(fname, rec_id))
        header.pack(fill="x", padx=4, pady=(6, 1))
        self._blocks[(fname, rec_id)] = header
        if self.bundle is not None and isinstance(rec, dict):
            self._record_buttons(fname, rec_id,
                                 SCHEMA[fname].get("kind")
                                 in ("array", "dict"))
        self._render_ref_rows(fname, rec_id)
        if not isinstance(rec, dict):  # invalid data must still render
            tk.Label(self.records_frame, anchor="w", fg=ALERT_FG,
                     text=f"    not an object: {rec!r}").pack(fill="x",
                                                              padx=12)
            return
        spec = SCHEMA[fname]["fields"]
        if (fname, rec_id) in self._editing:
            self._forms[(fname, rec_id)] = RecordForm(
                self, self.records_frame, fname, rec_id, rec, spec)
        else:
            self._forms.pop((fname, rec_id), None)
            for field, fspec in spec.items():
                self._render_field(fname, field, fspec, rec.get(field),
                                   depth=1, missing=field not in rec)

    def _render_field(self, fname: str, field: str, spec, value,
                      depth: int = 1, missing: bool = False) -> None:
        pad = "  " * depth
        # unwrap opt/nullable first so nested blocks (e.g. gather) render
        # as sub-rows, not a raw dict string
        while isinstance(spec, tuple) and spec[0] in ("opt", "nullable"):
            spec = spec[1]
        if (isinstance(spec, tuple) and spec[0] == "nested"
                and isinstance(value, dict)):
            tk.Label(self.records_frame, anchor="w", font=(None, 9, "italic"),
                     text=f"{pad}{field}:").pack(fill="x", padx=8)
            for sub, sspec in spec[1].items():
                self._render_field(fname, sub, sspec, value.get(sub),
                                   depth=depth + 2, missing=sub not in value)
            return
        if missing:
            shown, fg = "— absent", MUTED_FG
        elif value is None:
            shown, fg = "— null", MUTED_FG
        else:
            shown, fg = self._value_text(spec, value, fname), None
        row = tk.Frame(self.records_frame)
        row.pack(fill="x", padx=8)
        tk.Label(row, anchor="w", fg=MUTED_FG, text=f"{pad}{field}",
                 width=12 + depth * 2).pack(side="left")
        tk.Label(row, anchor="w", fg=fg, text=shown).pack(side="left")

    def _scalar_ok(self, spec: str, value) -> bool:
        if spec in ("int", "number"):
            return (isinstance(value, (int, float))
                    and not isinstance(value, bool))
        if spec == "bool":
            return isinstance(value, bool)
        return isinstance(value, str)  # slug, string

    def _value_text(self, spec, value, fname: str) -> str:
        """Render one value for its spec — total: never assumes shape."""
        if isinstance(spec, str):
            ok = self._scalar_ok(spec, value)
            return str(value) + ("" if ok else " ⚠ type")
        tag = spec[0]
        if tag in ("opt", "nullable"):
            return self._value_text(spec[1], value, fname)
        if tag == "enum":
            return str(value) + ("" if value in spec[1] else " ⚠ option")
        if tag == "ref":
            return f"{value} → {self._display_of(spec[1], value)}"
        if tag == "dyn_ref":
            return f"{value} (id checked against a sibling field)"
        if tag == "list":
            if not isinstance(value, list):
                return f"{value!r} ⚠ not a list"
            return ", ".join(
                self._value_text(spec[1], item, fname) for item in value)
        if tag == "pair":
            if not (isinstance(value, (list, tuple)) and len(value) == 2):
                return f"{value!r} ⚠ not a pair"
            return (f"{self._value_text(spec[1], value[0], fname)} · "
                    f"{self._value_text(spec[2], value[1], fname)}")
        if tag == "dict_int":
            if not isinstance(value, dict):
                return f"{value!r} ⚠ not an object"
            return ", ".join(
                f"{self._display_of(spec[1], key)} ×{qty}"
                for key, qty in value.items())
        if tag == "effect":
            # E1: generated text from the type union (binding D4) —
            # total-first, malformed entries render with a warning
            if not isinstance(value, dict):
                return f"{value!r} ⚠ not an effect"
            text = effect_text(value)
            if value.get("type") not in EFFECT_TYPES:
                text += " ⚠ type"
            return text
        if tag == "nested":
            return str(value) + ("" if isinstance(value, dict)
                                 else " ⚠ not an object")
        return str(value)


class RecordForm:
    """Schema-driven editor for one record — the 2c seam.

    Draws one widget per content.SCHEMA field into `parent` and writes
    every edit straight into the in-memory record (the bundle's own
    dict), so displayed state and saveable state are the same object.
    The viewer mounts it inline inside a record block; a later layout
    (2d detail pane) can mount this same component elsewhere without
    changing it. Traces attach after the initial values, so mounting
    never reports itself as an edit.
    """

    def __init__(self, viewer: ContentViewer, parent: tk.Widget,
                 fname: str, rec_id: str, record: dict, spec: dict):
        self.viewer = viewer
        self.fname = fname
        self.rec_id = rec_id
        self.record = record
        self.vars: dict[str, tk.Variable] = {}
        self.rowvars: dict[str, list[list[tk.Variable]]] = {}
        self.groups: dict[str, "RecordForm"] = {}
        # an absent nested block goes live on its first edit, so merely
        # opening a form never mutates the bundle
        self._attach: tuple[dict, str] | None = None
        editable_id = (fname, rec_id) in viewer._unsaved_ids  # D7
        if editable_id and "id" not in spec:
            self._add_key_row(parent, rec_id)  # D18: dict key identity
        for field, fspec in spec.items():
            self._add_field(parent, field, fspec, record.get(field),
                            field in record, editable_id=editable_id)

    def _add_field(self, parent, field, fspec, value, present, *,
                   editable_id=False) -> None:
        was_opt = was_nullable = False
        spec = fspec
        while isinstance(spec, tuple) and spec[0] in ("opt", "nullable"):
            was_opt = was_opt or spec[0] == "opt"
            was_nullable = was_nullable or spec[0] == "nullable"
            spec = spec[1]
        row = tk.Frame(parent)
        row.pack(fill="x", padx=8)
        tk.Label(row, anchor="w", fg=MUTED_FG, text=f"    {field}",
                 width=12).pack(side="left")
        if isinstance(spec, str) and spec in ("slug", "string", "int",
                                              "bool", "number"):
            if editable_id and field == "id":
                self._add_new_id(row, value)
            else:
                self._add_scalar(row, field, spec, value, was_opt,
                                 readonly=(field == "id"))
            return
        if isinstance(spec, tuple) and spec[0] == "enum":
            self._add_combo(row, field, list(spec[1]), value,
                            nullable=was_nullable)
            return
        if isinstance(spec, tuple) and spec[0] == "ref":
            self._add_combo(row, field, self._ref_ids(spec[1]), value,
                            nullable=was_nullable)
            return
        if isinstance(spec, tuple) and spec[0] == "pair":
            self._add_pair(row, field, spec, value, was_opt)
            return
        if isinstance(spec, tuple) and spec[0] == "nested":
            self._add_nested(row, field, spec, value, was_opt, present)
            return
        if isinstance(spec, tuple) and spec[0] == "list":
            # effects (the ("effect", None) member) render read-only in
            # E1 — editable rows land with E5, and _add_list's ↑↓ chrome
            # would break order-is-data anyway (plan R17)
            if (isinstance(spec[1], tuple) and spec[1][0] == "effect"):
                self._add_effects_readonly(row, value, present)
                return
            self._add_list(row, field, spec, value, was_opt)
            return
        if isinstance(spec, tuple) and spec[0] == "dict_int":
            self._add_dict_int(row, field, spec, value, was_opt)
            return
        # dyn_ref never stands alone in shipped schemas (only inside
        # pairs/lists): shown read-only rather than hidden — total first
        if not present:
            text = "— absent"
        elif value is None:
            text = "— null"
        else:
            text = self.viewer._value_text(fspec, value, self.fname)
        tk.Label(row, anchor="w", text=text).pack(side="left")
        tk.Label(row, anchor="w", fg=MUTED_FG,
                 text="  (no editor for this spec)").pack(side="left")

    def _add_effects_readonly(self, row, value, present) -> None:
        """E1: effects render as one generated read-only line (editable
        rows land with E5). Absent stays absent — opening a form must
        never materialize the field (no bundle mutation on mount)."""
        if not present or not value:
            text = "— absent"
        elif not isinstance(value, list):
            text = f"{value!r} ⚠ not a list"
        else:
            text = "; ".join(
                self.viewer._value_text(("effect", None), entry, self.fname)
                for entry in value) or "— empty list"
        tk.Label(row, anchor="w", text=text).pack(side="left")
        if isinstance(value, list) and value:
            tk.Label(row, anchor="w", fg=MUTED_FG,
                     text="  (read-only — editing arrives with E5)"
                     ).pack(side="left")

    def _add_scalar(self, row, field, kind, value, was_opt, *,
                    readonly=False) -> None:
        text = "" if value is None else str(value)
        var = tk.StringVar(value=text)
        tk.Entry(row, textvariable=var, width=52 if kind == "string"
                 else 14, state="readonly" if readonly else "normal").pack(
            side="left", fill="x", expand=True)
        self.vars[field] = var
        if readonly:
            return  # D7: ids of saved records never change through us

        def on_change(*_a, _k=kind, _f=field, _o=was_opt):
            raw = var.get()
            if _o and raw == "":
                self.record.pop(_f, None)  # cleared optional = absent
            else:
                self.record[_f] = self._coerce(_k, raw)
            self._changed()
        var.trace_add("write", on_change)

    def _add_new_id(self, row, value) -> None:
        var = tk.StringVar(value="" if value is None else str(value))
        tk.Entry(row, textvariable=var, width=30).pack(side="left")
        self.vars["id"] = var

        def on_change(*_a, _v=var):
            self._write_new_id(_v.get())
        var.trace_add("write", on_change)

    def _write_new_id(self, new: str) -> None:
        """D7: a not-yet-saved record's id stays editable — retarget the
        bookkeeping sets so an unsaved record never gets id-locked."""
        viewer = self.viewer
        old_key, new_key = (self.fname, self.rec_id), (self.fname, new)
        self.record["id"] = new
        self.rec_id = new
        if old_key in viewer._unsaved_ids:
            viewer._unsaved_ids.discard(old_key)
            viewer._unsaved_ids.add(new_key)
        if old_key in viewer._editing:
            viewer._editing.discard(old_key)
            viewer._editing.add(new_key)
        if old_key in viewer._forms:
            viewer._forms[new_key] = viewer._forms.pop(old_key)
        if old_key in viewer._blocks:
            viewer._blocks[new_key] = viewer._blocks.pop(old_key)
        if viewer._pane_edit == old_key:
            viewer._pane_edit = new_key  # the pane follows the record (D14)
        viewer._record_dirty.discard(old_key)  # _changed re-marks new key
        viewer._record_rename(self.fname, old_key[1], new)
        self._changed()

    def _add_key_row(self, parent, rec_id: str) -> None:
        """D18: an unsaved dict record edits its KEY (dict schemas have
        no id field — the key IS the identity, D7-locked after save)."""
        row = tk.Frame(parent)
        row.pack(fill="x", padx=8)
        tk.Label(row, anchor="w", fg=MUTED_FG, text="    id",
                 width=12).pack(side="left")
        var = tk.StringVar(value=rec_id)
        tk.Entry(row, textvariable=var, width=30).pack(side="left")
        self.vars["id"] = var

        def on_change(*_a, _v=var):
            self._write_new_key(_v.get())
        var.trace_add("write", on_change)

    def _write_new_key(self, new: str) -> None:
        """Rename an unsaved dict record's key: position preserved (dict
        order is data), bookkeeping retargeted, rename recorded so
        stale button closures resolve (D18)."""
        if not new or new == self.rec_id:
            return
        viewer = self.viewer
        data = getattr(viewer.bundle, self.fname)
        if new in data:
            return  # keys must stay unique (D7) — ignore until free
        old_key, new_key = (self.fname, self.rec_id), (self.fname, new)
        pairs = list(data.items())
        data.clear()
        for k, v in pairs:
            data[new if k == self.rec_id else k] = v
        self.rec_id = new
        for store in (viewer._unsaved_ids, viewer._editing,
                      viewer._record_dirty):
            if old_key in store:
                store.discard(old_key)
                store.add(new_key)
        if old_key in viewer._forms:
            viewer._forms[new_key] = viewer._forms.pop(old_key)
        if old_key in viewer._blocks:
            viewer._blocks[new_key] = viewer._blocks.pop(old_key)
        if viewer._pane_edit == old_key:
            viewer._pane_edit = new_key  # the pane follows the record (D14)
        viewer._record_rename(self.fname, old_key[1], new)
        self._changed()

    def _add_combo(self, row, field, values, value, *,
                   nullable=False) -> None:
        """Enum/ref dropdown (D12: options from the in-memory bundle).
        nullable adds a "(none)" option stored as null — the stat-tied
        actions' `skill: null` case (D16)."""
        none_opt = ["(none)"] if nullable else []
        shown = ("(none)" if nullable and value is None
                 else "" if value is None else str(value))
        var = tk.StringVar(value=shown)
        ttk.Combobox(row, textvariable=var, values=none_opt + values,
                     width=50, state="readonly").pack(
            side="left", fill="x", expand=True)
        self.vars[field] = var

        def on_change(*_a, _f=field, _n=none_opt):
            raw = var.get()
            self.record[_f] = None if _n and raw == "(none)" else raw
            self._changed()
        var.trace_add("write", on_change)

    def _add_pair(self, row, field, spec, value, was_opt) -> None:
        """D16: a pair is two member widgets sharing a row (tool_bonus,
        difficulty_target, stat_xp). The right member's dyn_ref options
        track the left member — pair(rowvars) doubles as the model
        handle: rowvars[field] == [[left, right]] (D17)."""
        left_spec, right_spec = spec[1], spec[2]
        seq = (value if isinstance(value, (list, tuple)) and len(value) == 2
               else (None, None))
        var_l = tk.StringVar(value="" if seq[0] is None else str(seq[0]))
        var_r = tk.StringVar(value="" if seq[1] is None else str(seq[1]))
        self.rowvars[field] = [[var_l, var_r]]
        self._member(row, left_spec, var_l)
        tk.Label(row, text="·").pack(side="left", padx=3)
        self._member(row, right_spec, var_r, sibling=var_l)

        def on_change(*_a, _f=field, _l=var_l, _r=var_r, _o=was_opt,
                      _ls=left_spec, _rs=right_spec):
            left = self._coerce_member(_ls, _l.get())
            right = self._coerce_member(_rs, _r.get())
            if _o and left == "" and right == "":
                self.record.pop(_f, None)  # cleared optional pair
            else:
                self.record[_f] = [left, right]
            self._changed()
        var_l.trace_add("write", on_change)
        var_r.trace_add("write", on_change)

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _coerce(kind: str, raw: str):
        """Text -> declared type; unparseable text is kept as typed so
        validate_bundle names the bad edit (constraint 3, verbatim)."""
        if kind == "int":
            try:
                return int(raw)
            except ValueError:
                return raw
        if kind == "number":
            try:
                return float(raw)
            except ValueError:
                return raw
        if kind == "bool":
            if raw in ("True", "true"):
                return True
            if raw in ("False", "false"):
                return False
            return raw
        return raw  # slug / string

    def _ref_ids(self, target: str) -> list[str]:
        """D12: options resolve from the in-memory bundle, so records
        added this session are selectable immediately."""
        if self.viewer.bundle is None:
            return []
        return [str(rid) for rid, _ in self.viewer._records_of(target)]

    def _changed(self) -> None:
        if self._attach is not None:
            target, key = self._attach
            if key not in target:
                target[key] = self.record  # absent nested block goes live
            self._attach = None
        self.viewer.dirty.add(self.fname)
        self.viewer._touch_record(self.fname, self.rec_id)  # D15 ●
        self.viewer.problems = list(validate_bundle(self.viewer.bundle))
        self.viewer._refresh_lists()

    def _add_nested(self, row, field, spec, value, was_opt,
                    present) -> None:
        """D16: a nested block is a labeled group driven by a CHILD
        RecordForm over the same machinery (gather lands here)."""
        block = value if isinstance(value, dict) else {}
        group = tk.LabelFrame(row, text=f" {field} ", padx=4, pady=4)
        group.pack(side="left", fill="x", expand=True)
        child = RecordForm(self.viewer, group, self.fname, self.rec_id,
                           block, spec[1])
        if not present:
            child._attach = (self.record, field)
        self.groups[field] = child

    def _member(self, parent, mspec, var, sibling=None) -> None:
        """One member widget of a pair or list row (D16): scalar →
        entry, enum/ref → bundle dropdown (D12), dyn_ref → dropdown
        filtered by the row's `sibling` kind field (checks pattern)."""
        spec = mspec
        while isinstance(spec, tuple) and spec[0] in ("opt", "nullable"):
            spec = spec[1]
        if isinstance(spec, str) and spec in ("slug", "string", "int",
                                              "bool", "number"):
            tk.Entry(parent, textvariable=var,
                     width=8 if spec in ("int", "number") else 22).pack(
                side="left")
            return
        if isinstance(spec, tuple) and spec[0] == "enum":
            ttk.Combobox(parent, textvariable=var, values=list(spec[1]),
                         width=16, state="readonly").pack(side="left")
            return
        if isinstance(spec, tuple) and spec[0] == "ref":
            ttk.Combobox(parent, textvariable=var,
                         values=self._ref_ids(spec[1]), width=22,
                         state="readonly").pack(side="left")
            return
        if isinstance(spec, tuple) and spec[0] == "dyn_ref":
            dyn_map = spec[1]
            combo = ttk.Combobox(parent, textvariable=var, width=22,
                                 state="readonly")
            combo.pack(side="left")

            def refresh(*_a, _s=sibling, _m=dyn_map, _c=combo):
                fresh = (self._ref_ids(_m[str(_s.get())])
                         if _s is not None and str(_s.get()) in _m
                         else [])
                _c.configure(values=fresh)
                if _c.get() and _c.get() not in fresh:
                    _c.set(fresh[0] if fresh else "")
            if sibling is not None:
                sibling.trace_add("write", refresh)
            refresh()
            return
        tk.Entry(parent, textvariable=var, width=16).pack(side="left")

    @classmethod
    def _coerce_member(cls, mspec, text):
        """Member text → declared type (ids stay strings)."""
        spec = mspec
        while isinstance(spec, tuple) and spec[0] in ("opt", "nullable"):
            spec = spec[1]
        if isinstance(spec, str):
            return cls._coerce(spec, text)
        return text

    # --- D16 row editors (list / dict_int share this vocabulary) ------------

    @staticmethod
    def _svar(value) -> tk.Variable:
        return tk.StringVar(value="" if value is None else str(value))

    @classmethod
    def _var_row(cls, mspec, item) -> list[tk.Variable]:
        """Variables for one element row: scalar → one var, pair → two."""
        spec = mspec
        while isinstance(spec, tuple) and spec[0] in ("opt", "nullable"):
            spec = spec[1]
        if isinstance(spec, tuple) and spec[0] == "pair":
            seq = (item if isinstance(item, (list, tuple))
                   and len(item) == 2 else (None, None))
            return [cls._svar(seq[0]), cls._svar(seq[1])]
        return [cls._svar(item)]

    @classmethod
    def _coerce_row(cls, mspec, rvars):
        """A row's variables → the element value (typed)."""
        spec = mspec
        while isinstance(spec, tuple) and spec[0] in ("opt", "nullable"):
            spec = spec[1]
        if isinstance(spec, tuple) and spec[0] == "pair":
            return [cls._coerce_member(spec[1], rvars[0].get()),
                    cls._coerce_member(spec[2], rvars[1].get())]
        return cls._coerce_member(spec, rvars[0].get())

    def _default_element(self, mspec):
        """Sensible starting values for a new row (ids from the live
        bundle — D12; dyn_ref waits for its sibling's refresh)."""
        spec = mspec
        while isinstance(spec, tuple) and spec[0] in ("opt", "nullable"):
            spec = spec[1]
        if isinstance(spec, str):
            return {"int": 0, "number": 0, "bool": False}.get(spec, "")
        if isinstance(spec, tuple) and spec[0] == "enum":
            return spec[1][0] if spec[1] else ""
        if isinstance(spec, tuple) and spec[0] == "ref":
            ids = self._ref_ids(spec[1])
            return ids[0] if ids else ""
        if isinstance(spec, tuple) and spec[0] == "pair":
            return [self._default_element(spec[1]),
                    self._default_element(spec[2])]
        return ""

    def _build_row(self, parent, mspec, rvars) -> None:
        """Widgets for one element row (pair → [left · right])."""
        spec = mspec
        while isinstance(spec, tuple) and spec[0] in ("opt", "nullable"):
            spec = spec[1]
        if isinstance(spec, tuple) and spec[0] == "pair":
            self._member(parent, spec[1], rvars[0])
            tk.Label(parent, text="·").pack(side="left", padx=3)
            self._member(parent, spec[2], rvars[1], sibling=rvars[0])
        else:
            self._member(parent, spec, rvars[0])

    def _add_list(self, row, field, spec, value, was_opt) -> None:
        """D16: list editor — one row per element (member widget per
        `spec[1]`) with add/remove/↑↓ chrome. `rowvars[field]` holds one
        variable-list per row (D17). Rows never rebuild on value edits
        (focus-safe) — only add/remove/move clicks rebuild."""
        mspec = spec[1]
        items = list(value) if isinstance(value, list) else []
        container = tk.Frame(row)
        container.pack(side="left", fill="x", expand=True)
        self.rowvars[field] = [self._var_row(mspec, it) for it in items]

        def write(*_a):
            built = [self._coerce_row(mspec, rv)
                     for rv in self.rowvars[field]]
            if was_opt and not built:
                self.record.pop(field, None)
            else:
                self.record[field] = built
            self._changed()

        def rebuild():
            for child in container.winfo_children():
                child.destroy()
            rows = self.rowvars[field]
            for i, rv in enumerate(rows):
                line = tk.Frame(container)
                line.pack(fill="x")
                self._build_row(line, mspec, rv)
                tk.Button(line, text="✕", width=2,
                          command=lambda i=i: remove(i)).pack(
                    side="left", padx=(6, 1))
                tk.Button(line, text="↑", width=2,
                          state="disabled" if i == 0 else "normal",
                          command=lambda i=i: move(i, -1)).pack(
                    side="left")
                tk.Button(line, text="↓", width=2,
                          state="disabled" if i == len(rows) - 1
                          else "normal",
                          command=lambda i=i: move(i, +1)).pack(
                    side="left")
            tk.Button(container, text="+ add row",
                      command=add).pack(anchor="w")

        def remove(i):
            self.rowvars[field].pop(i)
            rebuild()
            write()

        def move(i, delta):
            rows = self.rowvars[field]
            j = i + delta
            if 0 <= j < len(rows):
                rows[i], rows[j] = rows[j], rows[i]
                rebuild()
                write()

        def add():
            rv = self._var_row(mspec, self._default_element(mspec))
            for v in rv:
                v.trace_add("write", write)
            self.rowvars[field].append(rv)
            rebuild()
            write()

        for rv in self.rowvars[field]:
            for v in rv:
                v.trace_add("write", write)
        rebuild()

    def _add_dict_int(self, row, field, spec, value, was_opt) -> None:
        """D16: dict_int editor (patterns.materials) — rows of
        (ref, int) with add/remove but NO reorder: rows only append or
        drop, so the recorded key order is written back unchanged
        (constraint 4). A duplicate key collapses on write and the rows
        rebuild from the record — the merge is visible, never silent.
        rowvars[field] = [[key_var, qty_var], ...] (D17)."""
        target = spec[1]
        items = dict(value) if isinstance(value, dict) else {}
        container = tk.Frame(row)
        container.pack(side="left", fill="x", expand=True)
        self.rowvars[field] = [
            [self._svar(k), self._svar(q)] for k, q in items.items()]

        def write(*_a):
            rows = self.rowvars[field]
            built: dict = {}
            for rv in rows:
                key = rv[0].get()
                if key:
                    built[key] = self._coerce_member("int", rv[1].get())
            if was_opt and not built:
                self.record.pop(field, None)
            else:
                self.record[field] = built
            keys = [rv[0].get() for rv in rows if rv[0].get()]
            if len(keys) != len(set(keys)):  # duplicate key merged —
                # show the surviving record, never a silent collapse
                self.rowvars[field] = [
                    [self._svar(k), self._svar(q)]
                    for k, q in self.record[field].items()]
                rebuild()
            self._changed()

        def rebuild():
            for child in container.winfo_children():
                child.destroy()
            rows = self.rowvars[field]
            for i, rv in enumerate(rows):
                line = tk.Frame(container)
                line.pack(fill="x")
                ttk.Combobox(line, textvariable=rv[0],
                             values=self._ref_ids(target), width=26,
                             state="readonly").pack(side="left")
                tk.Entry(line, textvariable=rv[1], width=7).pack(
                    side="left", padx=(4, 0))
                tk.Button(line, text="✕", width=2,
                          command=lambda i=i: remove(i)).pack(
                    side="left", padx=(6, 0))
            tk.Button(container, text="+ material",
                      command=add).pack(anchor="w")

        def remove(i):
            self.rowvars[field].pop(i)
            rebuild()
            write()

        def add():
            rv = [self._svar(""), self._svar("0")]
            for v in rv:
                v.trace_add("write", write)
            self.rowvars[field].append(rv)
            rebuild()  # empty key = no data change yet; write on pick

        for rv in self.rowvars[field]:
            for v in rv:
                v.trace_add("write", write)
        rebuild()


def main(argv: list[str]) -> int:
    target = (Path(argv[1]) if len(argv) > 1
              else Path(__file__).resolve().parent / "content")
    root = tk.Tk()
    ContentViewer(root, target)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))