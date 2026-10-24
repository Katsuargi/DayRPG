"""Read-only content viewer (Phase 2a). Run: python editor.py [content_dir]

Imports the content layer ONLY — never game_core (constraint 1) — so it
opens and diagnoses whatever the game refuses to load. Read-only by
design: this module contains no write code; the write layer (2b) is
headless, and editing arrives with the 2c forms. Every field of every file renders from content.SCHEMA
(D1), so a future content type (NPCs, merchants, ...) appears as soon
as it joins the schema — no viewer code changes.
"""

from __future__ import annotations

import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from content import (CONTENT_FILES, SCHEMA, collect_references,
                     try_load_content)

BANNER_BG = "#8b1a1a"
FLASH_BG = "#ffe39a"
MUTED_FG = "#666677"


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
        tk.Label(bar, text="  read-only (2a) — editing arrives with 2c",
                 anchor="w", fg=MUTED_FG).pack(side="left")
        tk.Button(bar, text="Reload", command=self.reload).pack(side="right")
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

    def _on_mousewheel(self, event) -> None:
        self.records_canvas.yview_scroll(-1 * (event.delta // 120), "units")

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
        self.bundle, self.problems = try_load_content(self.dir)
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

    def _rebuild(self) -> None:
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
            self.file_list.insert(
                "end",
                f"{fname:<9} {summary}" + (f"  ⚠{bad}" if bad else ""),
            )
        self.problems_list.delete(0, "end")
        if not self.problems:
            self.problems_list.insert("end", "✓ no problems")
        for prob in self.problems:
            owner = getattr(prob, "file", None) or "engine"
            self.problems_list.insert("end", f"{owner}: {prob}")
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

    # --- rendering --------------------------------------------------------

    def _clear_records(self) -> None:
        for child in self.records_frame.winfo_children():
            child.destroy()
        self._blocks.clear()

    def _render_file(self, index: int) -> None:
        self._clear_records()
        fname = CONTENT_FILES[index]
        tk.Label(self.records_frame, anchor="w", font=(None, 10, "bold"),
                 text=f"{fname}.json").pack(fill="x", padx=4, pady=(4, 2))
        if self.bundle is None:
            tk.Label(self.records_frame, anchor="w", fg=MUTED_FG,
                     text="cannot render — the file set failed to parse "
                          "(see Problems; fix in an external editor)"
                     ).pack(fill="x", padx=12)
            return
        for rec_id, rec in self._records_of(fname):
            self._render_record(fname, rec_id, rec)

    def _render_record(self, fname: str, rec_id: str, rec) -> None:
        header = tk.Label(self.records_frame, anchor="w", bg="#e8e8f0",
                          font=(None, 9, "bold"), text=f"  {rec_id}")
        header.pack(fill="x", padx=4, pady=(6, 1))
        self._blocks[(fname, rec_id)] = header
        self._render_ref_rows(fname, rec_id)
        if not isinstance(rec, dict):  # invalid data must still render
            tk.Label(self.records_frame, anchor="w", fg=ALERT_FG,
                     text=f"    not an object: {rec!r}").pack(fill="x",
                                                              padx=12)
            return
        spec = SCHEMA[fname]["fields"]
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


def main(argv: list[str]) -> int:
    target = (Path(argv[1]) if len(argv) > 1
              else Path(__file__).resolve().parent / "content")
    root = tk.Tk()
    ContentViewer(root, target)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))