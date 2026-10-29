"""tkinter front-end for Day Scheduler RPG.

All game rules live in `game_core.py` (content in `content/*.json`);
this file only renders state and drives the day sequence:
slots -> events -> summary -> sleep -> next day.
"""

from __future__ import annotations

import json
import os
import time
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

from content import ContentError, effect_text

try:
    from game_core import (
        ACTION_LABELS,
        ACTION_ORDER,
        BUILD,
        CRAFT,
        EVENT_DIFFICULTY,
        GameEngine,
        INVENTORY_TOOLTIPS,
        ITEM_NAMES,
        ITEM_ORDER,
        PATTERNS,
        SKILL_NAMES,
        SKILL_TOOLTIPS,
        SLOT_NAMES,
        STAT_NAMES,
        STAT_TOOLTIPS,
        format_changes,
    )
except ContentError as exc:
    # Refuse to launch with a readable dialog instead of a traceback:
    # the message already names every file and field to fix.
    _root = tk.Tk()
    _root.withdraw()
    messagebox.showerror(
        "Day Scheduler RPG — content failed to load", str(exc)
    )
    _root.destroy()
    raise SystemExit(1) from exc

from check_live import run_live_check

# --- Theme (kept UI-side so a pygame port can restyle freely) -----------

APP_BG = "#24243a"
PANEL_BG = "#32324e"
CELL_BG = "#2a2a44"
PANEL_FG = "#e8e8f2"
HEADER_FG = "#ffd76a"
MUTED_FG = "#9a9ab8"
HEALTH_FG = "#ff7a7a"
ENERGY_FG = "#7ee787"
HUNGER_FG = "#ffb86b"
GOLD_FG = "#ffd76a"
DAY_FG = "#8fd3ff"
EVENT_FG = "#ff8ad8"

ACTION_CHOICES = [ACTION_LABELS[action_id] for action_id in ACTION_ORDER]
LABEL_TO_ID = {label: action_id for action_id, label in ACTION_LABELS.items()}

DIALOG_BG = "#3a3a58"

#: Font family resolved at startup — Segoe UI is only the fallback; Tk's
#: platform default family is used whenever it can be determined.
FAMILY = "Segoe UI"


def _init_family() -> None:
    global FAMILY
    try:
        FAMILY = tkfont.nametofont("TkDefaultFont").actual("family")
    except tk.TclError:
        pass


# --- Hover tooltips ---------------------------------------------------------

LEVEL_TOOLTIP = (
    "Overall experience. Each level needs 20 more XP than the last."
)
# STAT/SKILL/INVENTORY tooltips moved to content/*.json — they describe
# content entries — and are imported from game_core above.


class Tooltip:
    """Hover popup for left-panel rows; text may be a callable.

    Attach one Tooltip per row (pass every label of that row) so the
    popup survives hovering any part of it. Add explanation text to new
    rows by passing `tooltip=...` — no layout changes needed.
    """

    DELAY_MS = 400

    def __init__(self, root: tk.Tk, widgets, text) -> None:
        self.root = root
        self.text = text
        self._after_id = None
        self._tip: tk.Toplevel | None = None
        for widget in widgets:
            widget.bind("<Enter>", self._schedule, add="+")
            widget.bind("<Leave>", self._hide, add="+")
            widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, event) -> None:
        self._hide()
        x, y = event.x_root, event.y_root
        self._after_id = self.root.after(
            self.DELAY_MS, lambda: self._show(x, y)
        )

    def _show(self, x: int, y: int) -> None:
        text = self.text() if callable(self.text) else self.text
        if not text:
            return
        tip = tk.Toplevel(self.root)
        tip.wm_overrideredirect(True)
        tk.Label(
            tip, text=text, bg="#12121f", fg="#e8e8f2",
            font=(FAMILY, 9), justify="left", wraplength=320,
            padx=8, pady=6,
        ).pack()
        tip.update_idletasks()
        tip.wm_geometry(f"+{x + 16}+{y + 14}")
        tip.lift()
        self._tip = tip

    def _hide(self, _event=None) -> None:
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


class DaySchedulerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.engine = GameEngine()
        self._executing = False
        _init_family()

        root.title("Day Scheduler RPG — Isekai Survival")
        root.configure(bg=APP_BG)
        root.minsize(940, 680)

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "RPG.TCombobox",
            fieldbackground=APP_BG,
            background="#3a3a5c",
            foreground=PANEL_FG,
            arrowcolor=HEADER_FG,
            selectbackground=HEADER_FG,
            selectforeground="#1a1a28",
        )
        style.map(
            "RPG.TCombobox",
            fieldbackground=[("readonly", APP_BG)],
            foreground=[("readonly", PANEL_FG)],
        )

        # Top-bar state variables
        self.day_var = tk.StringVar()
        self.health_var = tk.StringVar()
        self.hunger_var = tk.StringVar()
        self.gold_var = tk.StringVar()
        self.energy_var = tk.StringVar()
        self.status_var = tk.StringVar()

        root.grid_rowconfigure(1, weight=1)
        root.grid_columnconfigure(0, weight=1)

        self._build_top_bar()
        self._build_body()
        self._build_status()
        self.refresh()
        self.status_var.set(
            "Plan the three time slots, then press Execute Day."
        )

    # --- Layout ----------------------------------------------------------

    def _build_top_bar(self) -> None:
        bar = tk.Frame(self.root, bg=PANEL_BG)
        bar.grid(row=0, column=0, sticky="ew")

        tk.Label(
            bar, textvariable=self.day_var, bg=PANEL_BG, fg=DAY_FG,
            font=(FAMILY, 13, "bold"), padx=16, pady=8,
        ).pack(side="left")
        tk.Label(
            bar, textvariable=self.health_var, bg=PANEL_BG, fg=HEALTH_FG,
            font=(FAMILY, 11, "bold"), padx=16,
        ).pack(side="left")
        tk.Label(
            bar, textvariable=self.energy_var, bg=PANEL_BG, fg=ENERGY_FG,
            font=(FAMILY, 11, "bold"), padx=16,
        ).pack(side="left")
        tk.Label(
            bar, textvariable=self.hunger_var, bg=PANEL_BG, fg=HUNGER_FG,
            font=(FAMILY, 11, "bold"), padx=16,
        ).pack(side="left")
        tk.Label(
            bar, textvariable=self.gold_var, bg=PANEL_BG, fg=GOLD_FG,
            font=(FAMILY, 11, "bold"), padx=16,
        ).pack(side="left")
        tk.Label(
            bar, text="Day Scheduler RPG", bg=PANEL_BG, fg=MUTED_FG,
            font=(FAMILY, 10, "italic"), padx=16,
        ).pack(side="right")
        controls = tk.Frame(bar, bg=PANEL_BG)
        controls.pack(side="right", padx=10, pady=4)
        self.save_btn = tk.Button(
            controls, text="Save", font=(FAMILY, 9), bg="#3f3f5c",
            fg=PANEL_FG, activebackground="#4c4c70", relief="flat",
            padx=10, pady=1, command=self._save_game,
        )
        self.save_btn.pack(side="left", padx=3)
        self.load_btn = tk.Button(
            controls, text="Load", font=(FAMILY, 9), bg="#3f3f5c",
            fg=PANEL_FG, activebackground="#4c4c70", relief="flat",
            padx=10, pady=1, command=self._load_game,
        )
        self.load_btn.pack(side="left", padx=3)


    def _build_body(self) -> None:
        body = tk.Frame(self.root, bg=APP_BG)
        body.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        self._build_stats_panel(body)
        self._build_planner(body)

    def _build_stats_panel(self, parent: tk.Widget) -> None:
        # Scrollable left column: everything worth referencing mid-event
        # (stats, skills, buildings, tools, inventory) lives here so the
        # day planner keeps the wide right-hand side for dialogs.
        container = tk.Frame(parent, bg=PANEL_BG, width=300)
        container.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        container.grid_propagate(False)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        canvas = tk.Canvas(
            container, bg=PANEL_BG, highlightthickness=0, width=274
        )
        scrollbar = ttk.Scrollbar(
            container, orient="vertical", command=canvas.yview
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.left_canvas = canvas

        panel = tk.Frame(canvas, bg=PANEL_BG)
        panel_id = canvas.create_window((0, 0), window=panel, anchor="nw")
        panel.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(panel_id, width=e.width),
        )
        panel.grid_columnconfigure(0, weight=1)

        self.player_level_var = tk.StringVar()
        self.player_xp_var = tk.StringVar()
        self.stat_vars: dict[str, tuple[tk.StringVar, tk.StringVar]] = {}
        self.skill_vars: dict[str, tuple[tk.StringVar, tk.StringVar]] = {}
        self.tool_vars: dict[str, tk.StringVar] = {}

        row = self._section_header(panel, 0, "CHARACTER")
        row = self._progress_row(
            panel, row, "Level", self.player_level_var, self.player_xp_var,
            tooltip=LEVEL_TOOLTIP,
        )

        row = self._section_header(panel, row, "STATS")
        for key in self.engine.stats:
            level_var, xp_var = tk.StringVar(), tk.StringVar()
            self.stat_vars[key] = (level_var, xp_var)
            row = self._progress_row(
                panel, row, STAT_NAMES.get(key, key.title()), level_var,
                xp_var, tooltip=STAT_TOOLTIPS.get(key),
            )

        row = self._section_header(panel, row, "SKILLS")
        for key in self.engine.skills:
            level_var, xp_var = tk.StringVar(), tk.StringVar()
            self.skill_vars[key] = (level_var, xp_var)
            row = self._progress_row(
                panel, row, SKILL_NAMES.get(key, key.title()), level_var,
                xp_var, tooltip=SKILL_TOOLTIPS.get(key),
            )

        # Buildings fill in only once finished (future upgrades replace
        # the row entirely when a tier changes).
        row = self._section_header(panel, row, "BUILDINGS")
        self.buildings_list = tk.Frame(panel, bg=PANEL_BG)
        self.buildings_list.grid(row=row, column=0, columnspan=2,
                                 sticky="ew", padx=6)
        row += 1

        row = self._section_header(panel, row, "TOOLS")
        for pattern in PATTERNS.values():
            if pattern.kind != CRAFT:
                continue
            var = tk.StringVar()
            self.tool_vars[pattern.id] = var
            row = self._kv_row(
                panel, row, pattern.name, var,
                tooltip=self._pattern_tooltip(pattern),
            )

        row = self._section_header(panel, row, "INVENTORY")
        items = [item for item in ITEM_ORDER if item in self.engine.inventory]
        items += [item for item in self.engine.inventory if item not in items]
        self.inventory_vars: dict[str, tk.StringVar] = {}
        for item in items:
            var = tk.StringVar()
            self.inventory_vars[item] = var
            row = self._kv_row(
                panel, row, ITEM_NAMES.get(item, item), var,
                tooltip=INVENTORY_TOOLTIPS.get(item),
            )

        tk.Label(
            panel, text="Location: Forest Edge", bg=PANEL_BG, fg=PANEL_FG,
            anchor="w", font=(FAMILY, 10),
        ).grid(row=row, column=0, sticky="ew", padx=14, pady=(14, 2))
        tk.Label(
            panel, text="Stats, skills & balance are placeholders.",
            bg=PANEL_BG, fg=MUTED_FG, anchor="w", font=(FAMILY, 9, "italic"),
        ).grid(row=row + 1, column=0, sticky="ew", padx=14, pady=(0, 12))

        # The wheel scrolls the panel only while the pointer is inside it.
        self._bind_mousewheel(canvas)
        self._bind_mousewheel(panel)

    def _bind_mousewheel(self, widget: tk.Widget) -> None:
        widget.bind("<MouseWheel>", self._on_mousewheel)
        for child in widget.winfo_children():
            self._bind_mousewheel(child)

    def _on_mousewheel(self, event) -> None:
        try:
            self.left_canvas.yview_scroll(
                int(-1 * (event.delta // 120)), "units"
            )
        except tk.TclError:
            pass  # canvas is gone

    def _kv_row(self, parent: tk.Widget, row: int, name: str,
                value_var: tk.StringVar, tooltip: str | None = None) -> int:
        """Name/value row used by tools and inventory."""
        name_label = tk.Label(
            parent, text=name, bg=PANEL_BG, fg=MUTED_FG, anchor="w",
            font=(FAMILY, 10),
        )
        name_label.grid(row=row, column=0, sticky="w", padx=(14, 4), pady=2)
        value_label = tk.Label(
            parent, textvariable=value_var, bg=PANEL_BG, fg=PANEL_FG,
            font=(FAMILY, 9, "bold"), anchor="e",
        )
        value_label.grid(row=row, column=1, sticky="e", padx=(4, 14), pady=2)
        if tooltip:
            Tooltip(self.root, (name_label, value_label), tooltip)
        return row + 1

    def _section_header(self, parent: tk.Widget, row: int, text: str) -> int:
        tk.Label(
            parent, text=text, bg=PANEL_BG, fg=HEADER_FG, anchor="w",
            font=(FAMILY, 10, "bold"),
        ).grid(row=row, column=0, columnspan=3, sticky="ew", padx=14,
               pady=(10, 2))
        return row + 1

    def _progress_row(self, parent: tk.Widget, row: int, name: str,
                      level_var: tk.StringVar, xp_var: tk.StringVar,
                      tooltip: str | None = None) -> int:
        name_label = tk.Label(
            parent, text=name, bg=PANEL_BG, fg=MUTED_FG, anchor="w",
            font=(FAMILY, 10),
        )
        name_label.grid(row=row, column=0, sticky="w", padx=(14, 4), pady=2)
        level_label = tk.Label(
            parent, textvariable=level_var, bg=PANEL_BG, fg=PANEL_FG,
            font=(FAMILY, 10, "bold"), width=4, anchor="e",
        )
        level_label.grid(row=row, column=1, sticky="e", pady=2)
        xp_label = tk.Label(
            parent, textvariable=xp_var, bg=PANEL_BG, fg=MUTED_FG,
            font=(FAMILY, 9), width=9, anchor="e",
        )
        xp_label.grid(row=row, column=2, sticky="e", padx=(4, 14), pady=2)
        if tooltip:
            Tooltip(self.root, (name_label, level_label, xp_label), tooltip)
        return row + 1

    @staticmethod
    def _pattern_effect(pattern) -> str:
        """D4: generated text when the record carries effects; the
        legacy hand string stays the fallback for records without
        (E4 retires the axe's string when it migrates)."""
        if pattern.effects:
            return "; ".join(effect_text(e) for e in pattern.effects)
        return pattern.effect

    def _pattern_tooltip(self, pattern) -> str:
        text = f"{pattern.name} — {pattern.description}"
        effect = self._pattern_effect(pattern)
        if effect:
            text += f"\nEffect: {effect}"
        return text

    def _rebuild_buildings(self) -> None:
        """BUILDINGS lists only what has actually been finished."""
        for child in self.buildings_list.winfo_children():
            child.destroy()
        if not self.engine.buildings:
            tk.Label(
                self.buildings_list, text="None yet.", bg=PANEL_BG,
                fg=MUTED_FG, anchor="w", font=(FAMILY, 9, "italic"),
            ).pack(anchor="w", padx=8, pady=2)
            return
        for building in self.engine.buildings:
            pattern = PATTERNS.get(building)
            name = (pattern.name if pattern
                    else building.replace("_", " ").title())
            label = tk.Label(
                self.buildings_list, text=name, bg=PANEL_BG, fg=PANEL_FG,
                anchor="w", font=(FAMILY, 10),
            )
            label.pack(anchor="w", padx=8, pady=2)
            if pattern is not None:
                Tooltip(self.root, (label,), self._pattern_tooltip(pattern))

    def _build_planner(self, parent: tk.Widget) -> None:
        panel = tk.Frame(parent, bg=PANEL_BG)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.grid_columnconfigure(2, weight=1)
        self.planner_panel = panel  # anchors event/pattern dialogs

        tk.Label(
            panel, text="DAY PLANNER", bg=PANEL_BG, fg=HEADER_FG,
            font=(FAMILY, 11, "bold"), anchor="w",
        ).grid(row=0, column=0, columnspan=3, sticky="ew", padx=16,
               pady=(12, 2))
        tk.Label(
            panel, text="Pick one action per time slot, then execute the day.",
            bg=PANEL_BG, fg=MUTED_FG, anchor="w",
            font=(FAMILY, 9),
        ).grid(row=1, column=0, columnspan=3, sticky="ew", padx=16,
               pady=(0, 8))

        self.slot_combos: list[ttk.Combobox] = []
        self.slot_result_labels: list[tk.Label] = []

        for i, slot_name in enumerate(SLOT_NAMES):
            row = i + 2
            tk.Label(
                panel, text=slot_name, bg=PANEL_BG, fg=PANEL_FG,
                font=(FAMILY, 11, "bold"), width=9, anchor="w",
            ).grid(row=row, column=0, sticky="w", padx=(16, 6), pady=6)

            combo = ttk.Combobox(
                panel, values=ACTION_CHOICES, state="readonly",
                width=15, style="RPG.TCombobox", font=(FAMILY, 10),
            )
            combo.set(ACTION_LABELS[self.engine.slot_actions[i]])
            combo.grid(row=row, column=1, sticky="w", padx=6, pady=6)
            combo.bind(
                "<<ComboboxSelected>>",
                lambda _event, index=i: self._on_action_selected(index),
            )
            self.slot_combos.append(combo)

            result = tk.Label(
                panel, text="", bg=PANEL_BG, fg=PANEL_FG, anchor="w",
                font=(FAMILY, 10),
            )
            result.grid(row=row, column=2, sticky="w", padx=10, pady=6)
            self.slot_result_labels.append(result)

        btn_row = tk.Frame(panel, bg=PANEL_BG)
        btn_row.grid(row=len(SLOT_NAMES) + 2, column=0, columnspan=3,
                     sticky="ew", padx=16, pady=(14, 16))
        self.execute_btn = tk.Button(
            btn_row, text="Execute Day", font=(FAMILY, 12, "bold"),
            bg=HEADER_FG, fg="#1a1a28", activebackground="#ffe39a",
            activeforeground="#1a1a28", relief="flat", padx=24, pady=6,
            command=self.execute_day,
        )
        self.execute_btn.pack(side="left")
        tk.Label(
            btn_row,
            text=(
                f"Runs all {len(SLOT_NAMES)} slots in order "
                f"({self.engine.EVENT_CHANCE:.0%} event chance each)."
            ),
            bg=PANEL_BG, fg=MUTED_FG, font=(FAMILY, 9),
        ).pack(side="left", padx=14)

    def _build_status(self) -> None:
        tk.Label(
            self.root, textvariable=self.status_var, bg=APP_BG,
            fg=MUTED_FG, anchor="w", justify="left",
            font=(FAMILY, 10), padx=12, pady=7,
        ).grid(row=2, column=0, sticky="ew")


    # --- State display ---------------------------------------------------

    def refresh(self) -> None:
        """Push engine state into the widgets."""
        engine = self.engine
        self.day_var.set(f"Day {engine.day}")
        self.health_var.set(f"Health {engine.health}/{engine.MAX_VITAL}")
        # Direction made explicit: MAX_VITAL = starving, 0 = content.
        self.hunger_var.set(
            f"Hunger {engine.hunger}/{engine.MAX_VITAL} "
            f"({engine.MAX_VITAL} = starving)"
        )
        self.gold_var.set(f"Gold {engine.gold}")
        self.energy_var.set(f"Energy {engine.energy}/{engine.MAX_VITAL}")
        for item, var in self.inventory_vars.items():
            var.set(str(engine.inventory.get(item, 0)))
        for pattern_id, var in self.tool_vars.items():
            count = engine.inventory.get(pattern_id, 0)
            var.set(f"×{count}" if count else "—")
        self._rebuild_buildings()
        self.player_level_var.set(str(engine.level))
        self.player_xp_var.set(f"{engine.xp}/{engine.xp_next}")
        for key, (level_var, xp_var) in self.stat_vars.items():
            progress = engine.stats[key]
            level_var.set(str(progress.level))
            xp_var.set(f"{progress.xp}/{progress.xp_next}")
        for key, (level_var, xp_var) in self.skill_vars.items():
            progress = engine.skills[key]
            level_var.set(str(progress.level))
            xp_var.set(f"{progress.xp}/{progress.xp_next}")
        try:
            self.save_btn.configure(
                state="disabled"
                if self._executing or engine.game_over else "normal"
            )
            self.load_btn.configure(
                state="disabled" if self._executing else "normal"
            )
        except tk.TclError:
            pass

    def _on_action_selected(self, index: int) -> None:
        label = self.slot_combos[index].get()
        action_id = LABEL_TO_ID.get(label)
        if action_id is not None:
            try:
                self.engine.set_slot_action(index, action_id)
            except RuntimeError:
                pass  # day is executing; combos are disabled anyway

    def _set_planning_enabled(self, enabled: bool) -> None:
        state = "readonly" if enabled else "disabled"
        for combo in self.slot_combos:
            combo.configure(state=state)

    # --- Day execution ---------------------------------------------------

    def execute_day(self) -> None:
        """Run the three time slots in order, pausing for events.

        Any failure mid-day is cleaned up in `finally`, so the planner
        is never left locked and the engine can abort the half-run day.
        """
        if self._executing or self.engine.game_over:
            return
        self._executing = True
        self._set_planning_enabled(False)
        self.execute_btn.configure(state="disabled", text="Day running…")
        for label in self.slot_result_labels:
            label.configure(text="", fg=PANEL_FG)

        engine = self.engine
        failure: BaseException | None = None
        try:
            engine.begin_day()

            results = []
            for index in range(len(SLOT_NAMES)):
                result = engine.run_slot(
                    index, pattern_provider=self._pick_pattern
                )
                results.append(result)

                changes = format_changes(result.changes) or "no change"
                suffix = "   [EVENT]" if result.event_triggered else ""
                if not result.success:
                    suffix = "   [FAILED]" + suffix
                    color = HEALTH_FG
                elif result.event_triggered:
                    color = EVENT_FG
                else:
                    color = PANEL_FG
                self.slot_result_labels[index].configure(
                    text=changes + suffix, fg=color,
                )
                self.refresh()
                self.status_var.set(
                    f"{result.slot_name} — {result.action_label}: {changes}. "
                    f"{result.note}"
                )
                self.root.update()

                if result.event_triggered:
                    self._show_event_dialog(result)
                    fallback = "the event passes without incident…"
                    detail = (
                        result.event.note
                        if result.event is not None else fallback
                    )
                    self.status_var.set(f"{result.slot_name}: {detail}")
                    self.root.update()

            self._show_summary(results)
        except tk.TclError:
            # Main window was closed mid-day; `finally` still cleans up.
            pass
        except Exception as exc:  # unexpected error — report, then unlock
            failure = exc
        finally:
            # On the success path _finish_day() has already done this.
            if engine.day_in_progress:
                engine.abort_day()
            if self._executing:
                self._executing = False
                detail = f": {failure}" if failure is not None else ""
                self._safe_restore_controls()
                self._safe_status(f"Day aborted{detail} — planning unlocked.")

    def _pick_pattern(self, action_id: str) -> str | None:
        """Planner-side pattern picker for Build/Craft slots.

        Non-modal (no grab): the player can still scroll the left panel
        while choosing. Returns the chosen pattern id, or None to skip.
        """
        verb = ACTION_LABELS[action_id]
        chosen: list[str | None] = [None]
        dlg = self._make_dialog(f"{verb} — choose a pattern")
        tk.Label(
            dlg, text=f"{verb}: choose a pattern", bg=DIALOG_BG,
            fg=HEADER_FG, font=(FAMILY, 14, "bold"),
        ).pack(padx=24, pady=(16, 6))

        def choose(pattern_id: str | None) -> None:
            chosen[0] = pattern_id
            dlg.destroy()

        patterns = self.engine.patterns_for(action_id)
        if not patterns:
            tk.Label(
                dlg,
                text="Nothing left to work on — everything is finished.",
                bg=DIALOG_BG, fg=MUTED_FG, font=(FAMILY, 10, "italic"),
            ).pack(padx=24, pady=4)

        for pattern in patterns:
            box = tk.Frame(dlg, bg=DIALOG_BG)
            box.pack(fill="x", padx=24, pady=4)
            tk.Label(
                box, text=pattern.name, bg=DIALOG_BG, fg=PANEL_FG,
                font=(FAMILY, 11, "bold"), anchor="w",
            ).pack(fill="x")
            blurb = pattern.description
            effect = self._pattern_effect(pattern)
            if effect:
                blurb += f"\nEffect: {effect}"
            tk.Label(
                box, text=blurb, bg=DIALOG_BG, fg=MUTED_FG,
                font=(FAMILY, 9, "italic"), anchor="w",
                wraplength=360, justify="left",
            ).pack(fill="x")

            engine = self.engine
            skill = engine.skills.get(pattern.skill)
            skill_name = SKILL_NAMES.get(
                pattern.skill, pattern.skill.title()
            )
            skill_ok = skill is not None and skill.level >= pattern.skill_req
            store = (engine.buildings if pattern.kind == BUILD
                     else engine.inventory)
            owned_count = store.get(pattern.id, 0)
            owned = pattern.kind == BUILD and bool(owned_count)
            costs = ", ".join(
                f"{qty} {ITEM_NAMES.get(item, item)}"
                for item, qty in pattern.materials.items()
            )
            have = ", ".join(
                f"{ITEM_NAMES.get(item, item)} {engine.inventory.get(item, 0)}"
                for item in pattern.materials
            )
            material_missing = any(
                engine.inventory.get(item, 0) < qty
                for item, qty in pattern.materials.items()
            )
            details = (
                f"Needs {skill_name} {pattern.skill_req} · "
                f"{costs} (you: {have})"
            )
            if pattern.kind == CRAFT and owned_count:
                details += f" · you own {owned_count}"
            progress = engine.projects.get(pattern.id, 0)
            if progress:
                details += f" · progress {progress}/{pattern.work}"
            tk.Label(
                box, text=details, bg=DIALOG_BG,
                fg=PANEL_FG if skill_ok and not material_missing
                else HEALTH_FG,
                font=(FAMILY, 9), anchor="w",
            ).pack(fill="x")

            if owned:
                reason = "already finished"
            elif not skill_ok:
                reason = f"needs {skill_name} {pattern.skill_req}"
            elif material_missing:
                reason = "not enough materials"
            else:
                reason = ""
            if reason:
                tk.Label(
                    box, text=reason, bg=DIALOG_BG, fg=HEALTH_FG,
                    font=(FAMILY, 9), anchor="w",
                ).pack(fill="x")
            tk.Button(
                box, text="Start", font=(FAMILY, 9, "bold"),
                bg=HEADER_FG, fg="#1a1a28", activebackground="#ffe39a",
                relief="flat", padx=14, pady=1,
                state="disabled" if reason else "normal",
                command=lambda pid=pattern.id: choose(pid),
            ).pack(anchor="e", pady=2)

        tk.Button(
            dlg, text="Skip this slot", font=(FAMILY, 10),
            bg="#3f3f5c", fg=PANEL_FG, activebackground="#4c4c70",
            relief="flat", padx=16, pady=3,
            command=lambda: choose(None),
        ).pack(pady=(10, 16))
        dlg.protocol("WM_DELETE_WINDOW", lambda: choose(None))
        self._wait_for(dlg, grab=False, over_planner=True)
        return chosen[0]

    def _show_event_dialog(self, result) -> None:
        """Modal box: 'An event has triggered!' + the placeholder check."""
        dlg = self._make_dialog("Something happened…")
        tk.Label(
            dlg, text="An event has triggered!", bg=DIALOG_BG, fg=EVENT_FG,
            font=(FAMILY, 15, "bold"),
        ).pack(padx=32, pady=(22, 8))
        event = result.event
        lines: list[str] = []
        if event is not None and event.text:
            lines.append(event.text)
        if event is None:
            lines.append("Events are still a placeholder.")
        elif event.check:
            outcome = "SUCCESS" if event.success else "FAILURE"
            lines.append(
                f"Check: {event.check} — d20 {event.die} + {event.bonus} "
                f"= {event.roll} vs DC {EVENT_DIFFICULTY}  →  {outcome}"
            )
            if event.changes:
                lines.append(format_changes(event.changes))
        else:
            lines.append("No check — nothing changes.")
        detail = "\n".join(lines)
        tk.Label(
            dlg, bg=DIALOG_BG, fg=PANEL_FG, justify="center",
            font=(FAMILY, 10),
            text=(
                f"{result.slot_name} — {result.action_label}\n"
                f"{detail}\n"
                "Press Advance to continue the day."
            ),
        ).pack(padx=32, pady=(0, 16))
        tk.Button(
            dlg, text="Advance", font=(FAMILY, 11, "bold"),
            bg=HEADER_FG, fg="#1a1a28", activebackground="#ffe39a",
            relief="flat", padx=28, pady=4, command=dlg.destroy,
        ).pack(pady=(0, 22))
        # No grab: the player can scroll stats/inventory while deciding.
        self._wait_for(dlg, grab=False, over_planner=True)

    def _make_dialog(self, title: str) -> tk.Toplevel:
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.configure(bg=DIALOG_BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        return dlg

    def _wait_for(self, dlg: tk.Toplevel, *, grab: bool = True,
                  over_planner: bool = False) -> None:
        """Block until `dlg` closes.

        Centers on the main window, or over the day planner when the
        dialog is event-like. With grab=False the rest of the window
        stays interactive (the caller still blocks in Python, but the
        player can scroll the left panel).
        """
        dlg.update_idletasks()
        if over_planner and getattr(self, "planner_panel", None) is not None:
            anchor = self.planner_panel
            x = anchor.winfo_rootx() + max(
                0, (anchor.winfo_width() - dlg.winfo_width()) // 2
            )
        else:
            x = self.root.winfo_x() + max(
                0, (self.root.winfo_width() - dlg.winfo_width()) // 2
            )
        y = self.root.winfo_y() + max(
            0, (self.root.winfo_height() - dlg.winfo_height()) // 3
        )
        dlg.geometry(f"+{x}+{y}")
        try:
            dlg.wait_visibility()  # grab_set can fail before mapped
            if grab:
                dlg.grab_set()
        except tk.TclError:
            pass
        self.root.wait_window(dlg)


    # --- Day end ---------------------------------------------------------

    def _show_summary(self, results) -> None:
        """Modal end-of-day summary; Accept triggers the sleep cycle."""
        summary = self.engine.build_summary()
        dlg = self._make_dialog("Day Summary")

        tk.Label(
            dlg, text=f"Day {summary['day']} — Summary", bg=DIALOG_BG,
            fg=HEADER_FG, font=(FAMILY, 15, "bold"),
        ).pack(padx=28, pady=(20, 10))

        rows = tk.Frame(dlg, bg=DIALOG_BG)
        rows.pack(padx=28, fill="x")
        for result in results:
            row = tk.Frame(rows, bg=DIALOG_BG)
            row.pack(fill="x", pady=3)
            changes = format_changes(result.changes) or "no change"
            event_tag = ""
            if result.event_triggered:
                event = result.event
                if event is not None and event.check:
                    verdict = "SUCCESS" if event.success else "FAILURE"
                    event_tag = f"   ⚠ event {verdict}!"
                else:
                    event_tag = "   ⚠ event!"
            tk.Label(
                row,
                text=f"{result.slot_name} · {result.action_label}: {changes}"
                     f"{event_tag}",
                bg=DIALOG_BG,
                fg=EVENT_FG if result.event_triggered else PANEL_FG,
                font=(FAMILY, 10, "bold"), anchor="w",
            ).pack(side="left")
            tk.Label(
                row, text=result.note, bg=DIALOG_BG, fg=MUTED_FG,
                font=(FAMILY, 9), anchor="e", wraplength=300,
                justify="right",
            ).pack(side="right")

        tk.Frame(dlg, bg=MUTED_FG, height=1).pack(
            fill="x", padx=28, pady=10
        )
        totals = format_changes(summary["totals"]) or "nothing changed"
        tk.Label(
            dlg, text=f"Totals: {totals}", bg=DIALOG_BG, fg=HEADER_FG,
            font=(FAMILY, 11, "bold"),
        ).pack(padx=28, pady=(0, 4))
        tk.Label(
            dlg, text="Accept to sleep and begin the next day.",
            bg=DIALOG_BG, fg=MUTED_FG, font=(FAMILY, 9, "italic"),
        ).pack(padx=28, pady=(0, 12))

        def accept() -> None:
            dlg.destroy()
            self._finish_day()

        tk.Button(
            dlg, text="Accept", font=(FAMILY, 11, "bold"),
            bg=HEADER_FG, fg="#1a1a28", activebackground="#ffe39a",
            relief="flat", padx=32, pady=4, command=accept,
        ).pack(pady=(0, 20))
        # Closing the window counts as accepting.
        dlg.protocol("WM_DELETE_WINDOW", accept)
        self._wait_for(dlg)

    def _finish_day(self) -> None:
        """Sleep, roll over (or die), and re-enable planning."""
        report = self.engine.complete_day()
        self._executing = False
        self._set_planning_enabled(True)
        self.execute_btn.configure(state="normal", text="Execute Day")
        for label in self.slot_result_labels:
            label.configure(text="", fg=PANEL_FG)
        self.refresh()
        if report.game_over:
            self.status_var.set(
                f"{report.game_over_reason} "
                f"You survived {self.engine.day} day(s)."
            )
            self._show_game_over()
            return
        self.status_var.set(
            f"Sleep — {report.note} "
            f"({format_changes(report.changes) or 'no change'}). "
            f"Day {report.new_day} begins."
        )


    # --- Recovery, game over, persistence --------------------------------

    def _safe_status(self, message: str) -> None:
        try:
            self.status_var.set(message)
        except tk.TclError:
            pass  # window is gone

    def _safe_restore_controls(self) -> None:
        try:
            self._set_planning_enabled(True)
            self.execute_btn.configure(state="normal", text="Execute Day")
            for label in self.slot_result_labels:
                label.configure(text="", fg=PANEL_FG)
            self.refresh()
        except tk.TclError:
            pass  # window is gone

    def _sync_combos_from_engine(self) -> None:
        for i, combo in enumerate(self.slot_combos):
            combo.set(ACTION_LABELS[self.engine.slot_actions[i]])

    def _show_game_over(self) -> None:
        """Lock the planner and offer a fresh start."""
        self._set_planning_enabled(False)
        self.execute_btn.configure(state="disabled", text="Game Over")
        self.save_btn.configure(state="disabled")

        dlg = self._make_dialog("Game Over")
        tk.Label(
            dlg, text="GAME OVER", bg=DIALOG_BG, fg=HEALTH_FG,
            font=(FAMILY, 18, "bold"),
        ).pack(padx=36, pady=(24, 8))
        tk.Label(
            dlg,
            text=self.engine.game_over_reason or "Your journey has ended.",
            bg=DIALOG_BG, fg=PANEL_FG, font=(FAMILY, 11),
        ).pack(padx=36, pady=(0, 4))
        tk.Label(
            dlg, text=f"You survived {self.engine.day} day(s).",
            bg=DIALOG_BG, fg=MUTED_FG, font=(FAMILY, 10, "italic"),
        ).pack(padx=36, pady=(0, 16))

        def restart() -> None:
            dlg.destroy()
            self._restart_game()

        tk.Button(
            dlg, text="Begin Anew", font=(FAMILY, 11, "bold"),
            bg=HEADER_FG, fg="#1a1a28", activebackground="#ffe39a",
            relief="flat", padx=30, pady=4, command=restart,
        ).pack(pady=(0, 22))
        # Closing the window also restarts — there is no other way out.
        dlg.protocol("WM_DELETE_WINDOW", restart)
        self._wait_for(dlg)

    def _restart_game(self) -> None:
        self.engine = GameEngine()
        self._executing = False
        self._sync_combos_from_engine()
        self._set_planning_enabled(True)
        self.execute_btn.configure(state="normal", text="Execute Day")
        for label in self.slot_result_labels:
            label.configure(text="", fg=PANEL_FG)
        self.refresh()
        self.status_var.set("A new life begins — plan your first day.")

    def _save_game(self) -> None:
        if self._executing or self.engine.game_over:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Save Game",
            defaultextension=".json",
            filetypes=[("Day Scheduler RPG save", "*.json"),
                       ("All files", "*.*")],
        )
        if not path:
            return
        # Atomic like the content write layer: temp file → fsync →
        # replace, with a short retry for transient Windows locks
        # (antivirus/indexer). The temp name matches .gitignore's
        # .*.json.tmp pattern; git is NOT the net for saves (untracked).
        tmp = os.path.join(os.path.dirname(path),
                           "." + os.path.basename(path) + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(self.engine.to_dict(), handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())  # survive crash/power-cut
            for attempt in range(3):
                try:
                    os.replace(tmp, path)  # atomic swap (D9 pattern)
                    break
                except PermissionError:
                    if attempt == 2:
                        raise
                    time.sleep(0.15)
        except OSError as exc:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            self._safe_status(f"Save failed: {exc}")
            return
        self._safe_status(f"Game saved to {path}")

    def _load_game(self) -> None:
        if self._executing:
            return
        path = filedialog.askopenfilename(
            parent=self.root, title="Load Game",
            filetypes=[("Day Scheduler RPG save", "*.json"),
                       ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                self.engine = GameEngine.from_dict(json.load(handle))
        except (OSError, ValueError) as exc:
            self._safe_status(f"Load failed: {exc}")
            return
        self._sync_combos_from_engine()
        self.refresh()
        if self.engine.game_over:
            self._safe_status("Loaded save — the journey has ended.")
            self._show_game_over()
        else:
            self.status_var.set(f"Game loaded — Day {self.engine.day}.")


def main() -> None:
    # Startup gate: full content validation + a few seeded days must pass
    # before the window opens (refuse with a dialog, never a traceback).
    problems = run_live_check()
    if problems:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Content check failed — fix content/*.json",
            "\n".join(problems),
        )
        root.destroy()
        raise SystemExit(1)
    root = tk.Tk()
    DaySchedulerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
