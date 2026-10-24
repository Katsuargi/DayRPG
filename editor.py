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
import sys
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from content import (CONTENT_FILES, SCHEMA, collect_references, ContentError,
                     StaleWriteError, save, try_load_content_with_state,
                     validate_bundle)

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
        key = (fname, rec_id)
        if key in self._editing:
            self._editing.discard(key)
            self._forms.pop(key, None)
        else:
            self._editing.add(key)
        self._render_file(self._current_idx)

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
            optional = False
            while isinstance(spec, tuple) and spec[0] in ("opt", "nullable"):
                optional = optional or spec[0] == "opt"
                spec = spec[1]
            if optional or not isinstance(spec, str):
                continue  # absent optional; pair/ref/nested start unset
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
        if self.bundle is None or SCHEMA[fname].get("kind") != "array":
            return
        base = "new_" + (fname[:-1] if fname.endswith("s") else fname)
        rec_id = self._next_id(fname, base)
        getattr(self.bundle, fname).append(
            self._default_record(fname, rec_id))
        self._unsaved_ids.add((fname, rec_id))
        self._editing.add((fname, rec_id))  # a new record opens for edit
        self._mark_dirty(fname)
        self._render_file(self._current_idx)

    def _on_duplicate(self, fname: str, rec_id: str) -> None:
        if self.bundle is None or SCHEMA[fname].get("kind") != "array":
            return
        source = next((r for rid, r in self._records_of(fname)
                       if rid == rec_id), None)
        if source is None:
            return
        new_id = self._next_id(fname, f"{rec_id}_copy")
        new_rec = copy.deepcopy(source)
        if isinstance(new_rec, dict) and "id" in new_rec:
            new_rec["id"] = new_id
        getattr(self.bundle, fname).append(new_rec)  # D5: appends at end
        self._unsaved_ids.add((fname, new_id))
        self._mark_dirty(fname)
        self._render_file(self._current_idx)

    def _on_move(self, fname: str, rec_id: str, delta: int) -> None:
        if self.bundle is None or SCHEMA[fname].get("kind") != "array":
            return
        recs = getattr(self.bundle, fname)
        ids = [rid for rid, _ in self._records_of(fname)]
        if rec_id not in ids:
            return
        pos = ids.index(rec_id)
        target = pos + delta
        if not 0 <= target < len(recs):
            return
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
        if self.bundle is None or SCHEMA[fname].get("kind") != "array":
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
            recs.pop(ids.index(rec_id))
        self._unsaved_ids.discard((fname, rec_id))
        self._editing.discard((fname, rec_id))
        self._forms.pop((fname, rec_id), None)
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
        for fname in result.written:
            self.dirty.discard(fname)
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
            tk.Label(self.records_frame, anchor="w", fg=MUTED_FG,
                     text="cannot render — the file set failed to parse "
                          "(see Problems; fix in an external editor)"
                     ).pack(fill="x", padx=12)
            return
        if SCHEMA[fname].get("kind") == "array":
            tk.Button(self.records_frame, text="+ add record",
                      command=lambda f=fname: self._on_add(f)).pack(
                anchor="e", padx=8, pady=(0, 2))
        for rec_id, rec in self._records_of(fname):
            self._render_record(fname, rec_id, rec)
        # rows/forms are rebuilt constantly — rebind hover-scroll (and its
        # wheel "break" guard) onto every widget just created
        self._bind_scroll(self.records_frame)

    def _render_record(self, fname: str, rec_id: str, rec) -> None:
        header = tk.Label(self.records_frame, anchor="w", bg="#e8e8f0",
                          font=(None, 9, "bold"), text=f"  {rec_id}")
        header.pack(fill="x", padx=4, pady=(6, 1))
        self._blocks[(fname, rec_id)] = header
        if self.bundle is not None and isinstance(rec, dict):
            self._record_buttons(fname, rec_id,
                                 SCHEMA[fname].get("kind") == "array")
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
        editable_id = (fname, rec_id) in viewer._unsaved_ids  # D7
        for field, fspec in spec.items():
            self._add_field(parent, field, fspec, record.get(field),
                            field in record, editable_id=editable_id)

    def _add_field(self, parent, field, fspec, value, present, *,
                   editable_id=False) -> None:
        was_opt = False
        spec = fspec
        while isinstance(spec, tuple) and spec[0] in ("opt", "nullable"):
            was_opt = was_opt or spec[0] == "opt"
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
            self._add_combo(row, field, list(spec[1]), value)
            return
        if isinstance(spec, tuple) and spec[0] == "ref":
            self._add_combo(row, field, self._ref_ids(spec[1]), value)
            return
        if isinstance(spec, tuple) and spec[0] == "pair":
            self._add_pair(row, field, spec, value, was_opt)
            return
        # nested / list / dyn_ref / dict_int: shown read-only until their
        # 2d editors land — never silently hidden
        if not present:
            text = "— absent"
        elif value is None:
            text = "— null"
        else:
            text = self.viewer._value_text(fspec, value, self.fname)
        tk.Label(row, anchor="w", text=text).pack(side="left")
        tk.Label(row, anchor="w", fg=MUTED_FG,
                 text="  (not editable yet — 2d)").pack(side="left")

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
        self._changed()

    def _add_combo(self, row, field, values, value) -> None:
        var = tk.StringVar(value="" if value is None else str(value))
        ttk.Combobox(row, textvariable=var, values=values, width=50,
                     state="readonly").pack(side="left", fill="x",
                                            expand=True)
        self.vars[field] = var

        def on_change(*_a, _f=field):
            self.record[_f] = var.get()
            self._changed()
        var.trace_add("write", on_change)

    def _add_pair(self, row, field, spec, value, was_opt) -> None:
        left_spec, right_spec = spec[1], spec[2]
        while isinstance(right_spec, tuple) and right_spec[0] in (
                "opt", "nullable"):
            right_spec = right_spec[1]
        rkind = right_spec if isinstance(right_spec, str) else "string"
        seq = (value if isinstance(value, (list, tuple)) and len(value) == 2
               else (None, None))
        var_l = tk.StringVar(value="" if seq[0] is None else str(seq[0]))
        var_r = tk.StringVar(value="" if seq[1] is None else str(seq[1]))
        sub = left_spec
        while isinstance(sub, tuple) and sub[0] in ("opt", "nullable"):
            sub = sub[1]
        if isinstance(sub, tuple) and sub[0] == "ref":
            ttk.Combobox(row, textvariable=var_l, state="readonly",
                         values=self._ref_ids(sub[1]), width=32).pack(
                side="left")
        else:
            tk.Entry(row, textvariable=var_l, width=24).pack(side="left")
        tk.Label(row, text="·").pack(side="left", padx=3)
        tk.Entry(row, textvariable=var_r, width=7).pack(side="left")

        def on_change(*_a, _f=field, _l=var_l, _r=var_r, _k=rkind,
                      _o=was_opt):
            left, right = _l.get(), _r.get()
            if _o and left == "" and right == "":
                self.record.pop(_f, None)  # cleared optional pair
            else:
                self.record[_f] = [left, self._coerce(_k, right)]
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
        self.viewer.dirty.add(self.fname)
        self.viewer.problems = list(validate_bundle(self.viewer.bundle))
        self.viewer._refresh_lists()


def main(argv: list[str]) -> int:
    target = (Path(argv[1]) if len(argv) > 1
              else Path(__file__).resolve().parent / "content")
    root = tk.Tk()
    ContentViewer(root, target)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))