"""Core game logic for Day Scheduler RPG.

This module is intentionally free of any UI imports so the same rules
can be reused with a different frontend (Ren'Py, pygame, ...) later on.

All game content — items, skills, stats, actions, patterns, events, and
balance numbers — lives in content/*.json and is loaded strictly (no
silent fallback) via content.load_content() at import time. This file
holds behavior and engine state; the content files hold the data.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Tuple

from content import (
    BALANCE_KEYS,
    BEHAVIOR_HANDLERS,
    Content,
    GATHER_ITEM,
    Problem,
    load_content,
    validate_bundle,
)

# --- Content loading -------------------------------------------------------
# Strict: a broken content/*.json raises ContentError naming file+field,
# right here at import time. There is deliberately no fallback to built-in
# defaults — git/backup is the rollback, never stale data. This line must
# stay above every derived table below, the GameEngine class body (its
# attribute mirrors read module globals), and def clamp (MAX_VITAL binds
# as a default argument at def time).
CONTENT: Content = load_content()

# --- Action identifiers -------------------------------------------------
# Action ids: the planner, save-data, and event-reference vocabulary.
# content/actions.json entries carry these ids plus a "behavior" that
# selects the handler (see ACTION_BEHAVIOR).

GATHER_FOOD = "gather_food"
GATHER_WOOD = "gather_wood"
REST = "rest"
BUILD = "build"
CRAFT = "craft"

#: The plan a fresh game starts with (planner defaults).
DEFAULT_SLOT_ACTIONS: Tuple[str, ...] = (GATHER_FOOD, GATHER_WOOD, REST)

ACTION_LABELS: Dict[str, str] = {
    entry["id"]: entry["label"] for entry in CONTENT.actions
}

#: Order actions appear in the planner UI (= order in content/actions.json).
ACTION_ORDER: Tuple[str, ...] = tuple(
    entry["id"] for entry in CONTENT.actions
)

#: The three time slots of a day.
SLOT_NAMES: Tuple[str, ...] = ("Morning", "Midday", "Evening")

#: Governing skill per action (rest has none — only skilled tasks train).
ACTION_SKILL: Dict[str, str] = {
    entry["id"]: entry["skill"]
    for entry in CONTENT.actions
    if entry["skill"] is not None
}

#: Behavior shared by the Build and Craft actions (the "build_craft"
#: key in content.py BEHAVIOR_HANDLERS): run_slot owns the routing
#: because it needs the pattern picker; _apply_action rejects it.
BUILD_CRAFT = "build_craft"

#: Behavior name per action id, from each action's "behavior" field
#: (values are keys in content.py BEHAVIOR_HANDLERS). Dispatch keys on
#: this — an action reuses an existing behavior for free; adding a
#: behavior name means implementing GameEngine._apply_<name>.
ACTION_BEHAVIOR: Dict[str, str] = {
    entry["id"]: entry["behavior"] for entry in CONTENT.actions
}

#: Per-action gather config (item, yield range, messages, optional tool
#: bonus/difficulty) from each gather_item action's "gather" block —
#: strict load guarantees the block is valid, so a new gather kind is
#: pure content (no handler code).
ACTION_GATHER: Dict[str, dict] = {
    entry["id"]: entry["gather"] for entry in CONTENT.actions
    if entry["behavior"] == GATHER_ITEM
}

#: tool_bonus: item id -> (action id it serves, flat bonus) — from
#: items.json. A gather action scans inventory for items tagged with
#: ITS id and applies the highest amount (copies never stack).
TOOL_BONUSES: Dict[str, Tuple[str, int]] = {
    entry["id"]: tuple(entry["tool_bonus"])
    for entry in CONTENT.items
    if "tool_bonus" in entry
}

#: difficulty_target: action id -> (kind, key) — explicit aim for an
#: action's difficulty check when it shouldn't default to the skill in
#: ACTION_SKILL (e.g. a gather checking Strength). Absent = aim at the
#: action's own skill (the pre-existing behavior, unchanged).
ACTION_TARGETS: Dict[str, Tuple[str, str]] = {
    entry["id"]: tuple(entry["difficulty_target"])
    for entry in CONTENT.actions
    if "difficulty_target" in entry
}

#: Attributes consulted by an event check for each action as (kind, key)
#: pairs, where kind is 'stats' or 'skills'. From content/actions.json.
ACTION_CHECKS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    entry["id"]: tuple((kind, key) for kind, key in entry["checks"])
    for entry in CONTENT.actions
}

#: Per-attempt stat XP: action id -> (stat key, amount), from each
#: action's "stat_xp" field (null = no stat training, e.g. today all).
ACTION_STAT_XP: Dict[str, Tuple[str, int]] = {
    entry["id"]: (entry["stat_xp"][0], entry["stat_xp"][1])
    for entry in CONTENT.actions
    if entry["stat_xp"] is not None
}

#: Display names for stats and skills (keys match the engine tables).
STAT_NAMES: Dict[str, str] = {
    key: record["name"] for key, record in CONTENT.stats.items()
}
SKILL_NAMES: Dict[str, str] = {
    key: record["name"] for key, record in CONTENT.skills.items()
}

#: Hover help for the left panel — lives with the content it describes
#: (moved out of main.py so the Ren'Py frontend reads the same source).
INVENTORY_TOOLTIPS: Dict[str, str] = {
    entry["id"]: entry.get("tooltip", "") for entry in CONTENT.items
}
SKILL_TOOLTIPS: Dict[str, str] = {
    key: record.get("tooltip", "") for key, record in CONTENT.skills.items()
}
STAT_TOOLTIPS: Dict[str, str] = {
    key: record.get("tooltip", "") for key, record in CONTENT.stats.items()
}



# --- Patterns (build/craft blueprints) ------------------------------------

@dataclass(frozen=True)
class Pattern:
    """A build or craft blueprint the player can attempt."""

    id: str
    name: str
    kind: str  # BUILD or CRAFT
    skill: str  # governing skill key
    skill_req: int  # required skill level to attempt
    materials: Dict[str, int]  # cost per attempt (lost even on failure)
    work: int  # successful attempts needed to finish
    description: str
    effect: str = ""  # mechanic explanation, shown in tooltips
    difficulty: int | None = None  # DC override; None = ACTION_DIFFICULTY


#: All known patterns, from content/patterns.json; ids are persisted in
#: saves, so keep them stable (rename = migration, see DEV_GUIDE).
PATTERNS: Dict[str, Pattern] = {
    key: Pattern(
        id=key,
        name=record["name"],
        kind=record["kind"],  # "build"/"craft" — same strings as BUILD/CRAFT
        skill=record["skill"],
        skill_req=record["skill_req"],
        materials=dict(record["materials"]),
        work=record["work"],
        description=record["description"],
        effect=record.get("effect", ""),
        difficulty=record.get("difficulty"),
    )
    for key, record in CONTENT.patterns.items()
}


# --- Random events ---------------------------------------------------------

@dataclass(frozen=True)
class RandomEvent:
    """A named random event drawn when the per-slot event roll fires.

    `actions` limits which actions can trigger it (empty = any action);
    `check=False` makes it pure flavor — no roll and no effects;
    `difficulty` overrides the event DC when set.
    """

    id: str
    text: str
    actions: Tuple[str, ...] = ()
    check: bool = True
    difficulty: int | None = None  # DC override; None = EVENT_DIFFICULTY


#: When an event fires for an action, the engine filters this table by
#: matching `actions` and picks one at random — table order feeds the
#: seeded RNG, so keep content/events.json key order stable. Ids are
#: stable names; per-event effects don't exist yet; `_resolve_event` is
#: the hook point when you add them.
RANDOM_EVENTS: Dict[str, RandomEvent] = {
    key: RandomEvent(
        id=key,
        text=record["text"],
        actions=tuple(record["actions"]),
        check=record["check"],
        difficulty=record.get("difficulty"),
    )
    for key, record in CONTENT.events.items()
}

# --- Balance: progression & events (content/balance.json) ------------------
# Every number below is bound from CONTENT.balance — edit the JSON, not
# this block. validate_content() cross-checks BALANCE_KEYS <-> these names.

#: XP awarded for executing any action, credited to the player.
ACTION_XP = CONTENT.balance["ACTION_XP"]
#: XP awarded to a skilled action's governing skill.
SKILL_XP = CONTENT.balance["SKILL_XP"]
#: Placeholder event-check settings: d20 + summed contributor levels
#: versus this DC; outcomes grant XP and may cost health.
CHECK_DIE = CONTENT.balance["CHECK_DIE"]
EVENT_DIFFICULTY = CONTENT.balance["EVENT_DIFFICULTY"]
#: DC for ordinary skilled actions (gather attempts) — placeholder.
ACTION_DIFFICULTY = CONTENT.balance["ACTION_DIFFICULTY"]
EVENT_XP_SUCCESS = CONTENT.balance["EVENT_XP_SUCCESS"]
EVENT_XP_FAILURE = CONTENT.balance["EVENT_XP_FAILURE"]
EVENT_FAILURE_HEALTH = CONTENT.balance["EVENT_FAILURE_HEALTH"]
#: Chance a random event interrupts a slot (mirrored on GameEngine so
#: tests can override per instance, like ACTION_DIFFICULTY).
EVENT_CHANCE = CONTENT.balance["EVENT_CHANCE"]
#: Lean to passive effect: +10% health/energy recovery, rounded down.
LEAN_TO_RECOVERY_BONUS = CONTENT.balance["LEAN_TO_RECOVERY_BONUS"]

# --- Balance: costs, yields, recovery (content/balance.json) ---------------

#: Gather attempts — effort spent even on failure. Per-kind yields,
#: tool bonuses, and difficulty live in each action's gather block.
GATHER_ENERGY_COST = CONTENT.balance["GATHER_ENERGY_COST"]
GATHER_HUNGER_COST = CONTENT.balance["GATHER_HUNGER_COST"]

#: Resting.
REST_FOOD_HEALTH = CONTENT.balance["REST_FOOD_HEALTH"]
REST_FOOD_ENERGY = CONTENT.balance["REST_FOOD_ENERGY"]
#: eating (-15) offsets time passing (+5)
REST_FOOD_HUNGER_NET = CONTENT.balance["REST_FOOD_HUNGER_NET"]
REST_EMPTY_HEALTH = CONTENT.balance["REST_EMPTY_HEALTH"]
REST_EMPTY_ENERGY = CONTENT.balance["REST_EMPTY_ENERGY"]
REST_EMPTY_HUNGER = CONTENT.balance["REST_EMPTY_HUNGER"]

#: Sleeping.
SLEEP_HUNGER_NIGHT = CONTENT.balance["SLEEP_HUNGER_NIGHT"]
SLEEP_FOOD_HEALTH = CONTENT.balance["SLEEP_FOOD_HEALTH"]
SLEEP_FOOD_ENERGY = CONTENT.balance["SLEEP_FOOD_ENERGY"]
SLEEP_FOOD_HUNGER_NET = CONTENT.balance["SLEEP_FOOD_HUNGER_NET"]
SLEEP_EMPTY_HEALTH = CONTENT.balance["SLEEP_EMPTY_HEALTH"]
SLEEP_EMPTY_ENERGY = CONTENT.balance["SLEEP_EMPTY_ENERGY"]

# --- Items --------------------------------------------------------------
# FOOD_ITEM/WOOD_ITEM are code-side behavior anchors (Rest/Sleep eat any
# item tagged `food`, best tier first — FOOD_ITEM stays the canonical
# starting food); their values are content ids (slugs), checked by
# validate_content().

FOOD_ITEM = "berries"
WOOD_ITEM = "wood"

#: Foods in eating order: best quality tier first; ties keep the
#: content-file order (Batch 5 — a tier drains before downgrading).
FOOD_ITEMS: Tuple[str, ...] = tuple(
    iid for _tier, iid in sorted(
        ((entry["food"], entry["id"]) for entry in CONTENT.items
         if type(entry.get("food")) is int),
        key=lambda pair: -pair[0],  # stable: equal tiers keep file order
    )
)

#: Inventory rendering / accounting order (= content/items.json order).
ITEM_ORDER: Tuple[str, ...] = tuple(entry["id"] for entry in CONTENT.items)

#: Display label per item id (ids are stable save data; names may change).
ITEM_NAMES: Dict[str, str] = {
    entry["id"]: entry["name"] for entry in CONTENT.items
}

#: (snapshot key, display label) for stats shown in change lists.
STAT_LABELS: Tuple[Tuple[str, str], ...] = (
    ("health", "Health"),
    ("energy", "Energy"),
    ("hunger", "Hunger"),
    ("gold", "Gold"),
)

#: A single delta such as ("Berries", 2) or ("Health", -10).
Change = Tuple[str, int]

#: Maximum for health/energy/hunger meters (single source of truth).
MAX_VITAL = CONTENT.balance["MAX_VITAL"]

#: XP needed for the first level-up (placeholder balance).
XP_TO_NEXT = CONTENT.balance["XP_TO_NEXT"]
#: Extra XP each further level costs (placeholder balance).
XP_COST_STEP = CONTENT.balance["XP_COST_STEP"]


def xp_cost_for(level: int) -> int:
    """XP required to advance from `level` to `level + 1`.

    Costs scale with every level gained: 100, 120, 140, …
    """
    return XP_TO_NEXT + XP_COST_STEP * max(0, level - 1)


def clamp(value: int, low: int = 0, high: int = MAX_VITAL) -> int:
    return max(low, min(high, value))


def format_changes(changes: List[Change]) -> str:
    """Render changes as 'Berries +2, Wood +1'."""
    return ", ".join(f"{label} {delta:+d}" for label, delta in changes)


def aggregate_changes(results: List["SlotResult"]) -> List[Change]:
    """Net changes across every slot result, in display order."""
    totals: Dict[str, int] = {}
    for result in results:
        for label, delta in result.changes:
            totals[label] = totals.get(label, 0) + delta
    # Items first (preferred order), then stats, then anything unknown —
    # matching how GameEngine._diff() reports changes.
    known = [ITEM_NAMES.get(item, item) for item in ITEM_ORDER]
    known += [label for _, label in STAT_LABELS]
    ordered: List[Change] = []
    for label in known:
        if totals.get(label):
            ordered.append((label, totals[label]))
    for label, delta in totals.items():
        if delta and label not in known:
            ordered.append((label, delta))
    return ordered


@dataclass
class Progress:
    """A levelled stat or skill with XP progress toward the next level."""

    level: int = 1
    xp: int = 0

    @property
    def xp_next(self) -> int:
        return xp_cost_for(self.level)


@dataclass
class EventResolution:
    """Result of a triggered placeholder event check.

    `check == ''` means no stat/skill applied (e.g. rest), so the event
    was flavor only.
    """

    check: str
    bonus: int  # summed levels of all contributors
    die: int  # die rolled (0 when no check)
    roll: int  # die + bonus
    success: bool
    event_id: str = ""  # RANDOM_EVENTS id, if a named event was drawn
    text: str = ""  # the event's flavor text
    changes: List[Change] = field(default_factory=list)  # display copy
    note: str = ""


@dataclass
class SlotResult:
    """Outcome of one executed time slot."""

    slot_index: int
    action_id: str
    event_triggered: bool
    event: EventResolution | None = None
    success: bool = True  # False when a skilled attempt failed
    changes: List[Change] = field(default_factory=list)
    note: str = ""

    @property
    def slot_name(self) -> str:
        return SLOT_NAMES[self.slot_index]

    @property
    def action_label(self) -> str:
        return ACTION_LABELS[self.action_id]


@dataclass
class SleepReport:
    """Outcome of the end-of-day sleep cycle."""

    changes: List[Change] = field(default_factory=list)
    note: str = ""
    new_day: int = 1
    game_over: bool = False
    game_over_reason: str = ""


class GameEngine:
    """Holds all mutable game state and the day-cycle rules."""

    #: Chance a placeholder random event interrupts a time slot
    #: (mirror of the module constant so tests override per instance).
    EVENT_CHANCE = EVENT_CHANCE
    #: Ordinary skilled-action DC (mirror of the module constant).
    ACTION_DIFFICULTY = ACTION_DIFFICULTY
    #: Event table (mirrored so tests can swap it per instance).
    RANDOM_EVENTS = RANDOM_EVENTS
    #: Stat-XP hook (mirrored for the same reason).
    ACTION_STAT_XP = ACTION_STAT_XP
    #: Mirror of the module-level constant (single source of truth).
    MAX_VITAL = MAX_VITAL

    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

        # Top-bar stats
        self.day = 1
        self.health = self.MAX_VITAL
        self.hunger = 20  # 0 = content, MAX_VITAL = starving
        self.gold = 10

        # Side-panel stats (energy is used by actions)
        self.energy = self.MAX_VITAL
        self.level = 1
        self.xp = 0

        # Levelled stats and skills, each with XP toward the next level.
        # Starting levels come from content/stats.json & content/skills.json.
        self.stats: Dict[str, Progress] = {
            key: Progress(level=record["start_level"])
            for key, record in CONTENT.stats.items()
        }
        self.skills: Dict[str, Progress] = {
            key: Progress(level=record["start_level"])
            for key, record in CONTENT.skills.items()
        }

        # Pattern progress and finished assets.
        # projects: pattern id -> successful attempts so far
        # buildings / tools: pattern id -> count owned (semi-permanent)
        self.projects: Dict[str, int] = {}
        self.buildings: Dict[str, int] = {}

        # Set when the player dies; checked at the end of each day.
        self.game_over = False
        self.game_over_reason = ""

        # Starting inventory from content/items.json ("start" fields).
        self.inventory: Dict[str, int] = {
            entry["id"]: entry["start"] for entry in CONTENT.items
        }

        # The planned action for each of the three time slots.
        self.slot_actions: List[str] = list(DEFAULT_SLOT_ACTIONS)

        self._day_in_progress = False
        self._slot_results: List[SlotResult] = []
        self._day_snapshot: Optional[Dict[str, object]] = None  # abort rewind

    # --- Planning --------------------------------------------------------

    def set_slot_action(self, index: int, action_id: str) -> None:
        if action_id not in ACTION_LABELS:
            raise ValueError(f"Unknown action: {action_id}")
        if not 0 <= index < len(SLOT_NAMES):
            raise IndexError(f"Invalid slot index: {index}")
        if self._day_in_progress:
            raise RuntimeError("Cannot replan while the day is executing")
        self.slot_actions[index] = action_id

    def get_slot_actions(self) -> List[str]:
        return list(self.slot_actions)

    # --- Execution -------------------------------------------------------

    def begin_day(self) -> None:
        if self._day_in_progress:
            raise RuntimeError("Day already in progress")
        # Rewind point for abort_day (Batch 4): full state + rng, taken
        # at plan time. Session-local — never serialized (to_dict and the
        # save identity gate never see it).
        self._day_snapshot = self.to_dict()
        self._slot_results = []
        self._day_in_progress = True

    @property
    def day_in_progress(self) -> bool:
        return self._day_in_progress

    @property
    def slots_executed(self) -> int:
        return len(self._slot_results)

    @property
    def results(self) -> List[SlotResult]:
        return list(self._slot_results)

    def run_slot(self, index: int,
                 pattern_provider: Callable[[str], str | None] | None = None
                 ) -> SlotResult:
        """Run time slot `index` (slots must run in order).

        Rolls the random-event chance, applies the planned action's
        outcome, and returns the recorded result. Build/Craft actions
        call `pattern_provider` (if given) with the action id so the
        caller's UI can ask which pattern to work on; returning None
        skips the slot. A triggered event is only a flag for now; the UI
        pauses the player, and real event content can later modify or
        replace the outcome.
        """
        if not self._day_in_progress:
            raise RuntimeError("Call begin_day() first")
        if index != len(self._slot_results):
            raise RuntimeError("Time slots must run in order")

        action_id = self.slot_actions[index]
        behavior = ACTION_BEHAVIOR[action_id]
        event_triggered = self.rng.random() < self.EVENT_CHANCE

        pattern_id: str | None = None
        if behavior == BUILD_CRAFT and pattern_provider is not None:
            # Like an event, this waits on the caller's UI for input.
            pattern_id = pattern_provider(action_id)

        snapshot = self._snapshot()
        xp_changes: List[Change] = []
        notes: List[str] = []
        attempted = True
        success = True

        if behavior == BUILD_CRAFT:
            if pattern_id is None:
                attempted = False
                notes.append(
                    "no pattern was chosen, so the slot passes quietly."
                )
            else:
                attempted, success = self._apply_build_craft(
                    action_id, pattern_id, xp_changes, notes
                )
        else:
            success, action_note = self._apply_action(action_id)
            notes.append(action_note)

        # Attempts teach even when they fail — skipping teaches nothing.
        if attempted:
            changes, level_note = self.add_xp("player", None, ACTION_XP)
            xp_changes.extend(changes)
            if level_note:
                notes.append(level_note)
            skill = ACTION_SKILL.get(action_id)
            if skill:
                changes, level_note = self.add_xp("skills", skill, SKILL_XP)
                xp_changes.extend(changes)
                if level_note:
                    notes.append(level_note)
            # Optional stat training hook (see ACTION_STAT_XP).
            stat_xp = self.ACTION_STAT_XP.get(action_id)
            if stat_xp:
                changes, level_note = self.add_xp(
                    "stats", stat_xp[0], stat_xp[1]
                )
                xp_changes.extend(changes)
                if level_note:
                    notes.append(level_note)

        event = None
        if event_triggered:
            event = self._resolve_event(action_id, xp_changes, notes)

        result = SlotResult(
            slot_index=index,
            action_id=action_id,
            event_triggered=event_triggered,
            event=event,
            success=success,
            # Item/stat deltas come from the snapshot diff; XP is granted
            # explicitly through add_xp and appended here.
            changes=self._diff(snapshot) + xp_changes,
            note=" ".join(notes),
        )
        self._slot_results.append(result)
        return result

    def build_summary(self) -> Dict[str, object]:
        """Data needed by the end-of-day summary dialog."""
        results = self.results
        return {
            "day": self.day,
            "results": results,
            "totals": aggregate_changes(results),
        }

    def complete_day(self) -> SleepReport:
        """Run the sleep cycle, then roll over to the next day."""
        if not self._day_in_progress:
            raise RuntimeError("No day in progress")
        if len(self._slot_results) != len(SLOT_NAMES):
            raise RuntimeError("All three time slots must run first")

        snapshot = self._snapshot()
        note = self._apply_sleep()
        report = SleepReport(
            changes=self._diff(snapshot),
            note=note,
            new_day=self.day + 1,
        )

        self._day_in_progress = False
        self._slot_results = []

        if self._check_game_over():
            report.game_over = True
            report.game_over_reason = self.game_over_reason
            report.new_day = self.day  # the dead do not see tomorrow
        else:
            self.day += 1
        return report

    def abort_day(self) -> None:
        """Recover from a failed or interrupted day so planning resumes.

        Rewinds to the begin_day() snapshot (state AND rng), so the
        aborted day's partial effects are undone and a re-run replays
        it identically — no double-dipping (review Batch 4). Idempotent:
        with no day in progress it only clears the flags, as before.
        """
        if self._day_in_progress and self._day_snapshot is not None:
            fresh = type(self).from_dict(self._day_snapshot)
            self.__dict__.update(fresh.__dict__)  # full rewind
        self._day_in_progress = False
        self._slot_results = []

    def _check_game_over(self) -> bool:
        """Set the game-over flags if the player has died.

        Death is only evaluated at the end of the day (for now), and the
        thresholds are placeholder balance.
        """
        if not self.game_over:
            if self.hunger >= self.MAX_VITAL:
                self.game_over = True
                self.game_over_reason = "You starved."
            elif self.health <= 0:
                self.game_over = True
                self.game_over_reason = "Your wounds proved fatal."
        if self.game_over and not self.game_over_reason:
            self.game_over_reason = "Your journey has ended."
        return self.game_over


    # --- Progression ------------------------------------------------------

    @property
    def xp_next(self) -> int:
        """XP the player needs to reach the next level (scaling)."""
        return xp_cost_for(self.level)

    def add_xp(self, kind: str, key: str | None,
               amount: int) -> Tuple[List[Change], str]:
        """Grant XP to the player ('player'), a stat, or a skill.

        Levels advance automatically once xp reaches the scaling cost.
        Returns (changes, level_up_note) — the note is '' when no
        level-up happened.
        """
        if amount <= 0:
            return [], ""
        if kind == "player":
            ups = 0
            self.xp += amount
            while self.xp >= xp_cost_for(self.level):
                self.xp -= xp_cost_for(self.level)
                self.level += 1
                ups += 1
            note = f"You reached level {self.level}!" if ups else ""
            return [("XP", amount)], note

        table = self.stats if kind == "stats" else self.skills
        if key is None or key not in table:
            raise KeyError(f"Unknown {kind} entry: {key!r}")
        progress = table[key]
        ups = 0
        progress.xp += amount
        while progress.xp >= xp_cost_for(progress.level):
            progress.xp -= xp_cost_for(progress.level)
            progress.level += 1
            ups += 1
        name = self._display_name(kind, key)
        note = f"{name} reached level {progress.level}!" if ups else ""
        return [(f"{name} XP", amount)], note

    def _level_of(self, kind: str, key: str) -> int:
        if kind == "stats":
            return self.stats[key].level
        if kind == "skills":
            return self.skills[key].level
        return self.level

    def _display_name(self, kind: str, key: str) -> str:
        if kind == "stats":
            return STAT_NAMES.get(key, key.title())
        if kind == "skills":
            return SKILL_NAMES.get(key, key.title())
        return "You"

    # --- Persistence -----------------------------------------------------

    #: Save identity: to_dict stamps both; from_dict refuses anything
    #: else (balance.json can never masquerade as a save — review B3).
    SAVE_GAME_ID = "dayscheduler_rpg"
    SAVE_VERSION = 1

    def to_dict(self) -> Dict[str, object]:
        """JSON-serializable snapshot of the whole game (save between days)."""
        rng_version, rng_state, rng_gauss = self.rng.getstate()
        return {
            "game": self.SAVE_GAME_ID,
            "version": self.SAVE_VERSION,
            "day": self.day,
            "health": self.health,
            "energy": self.energy,
            "hunger": self.hunger,
            "gold": self.gold,
            "level": self.level,
            "xp": self.xp,
            "stats": {
                key: {"level": p.level, "xp": p.xp}
                for key, p in self.stats.items()
            },
            "skills": {
                key: {"level": p.level, "xp": p.xp}
                for key, p in self.skills.items()
            },
            "inventory": dict(self.inventory),
            "projects": dict(self.projects),
            "buildings": dict(self.buildings),
            "slot_actions": list(self.slot_actions),
            "game_over": self.game_over,
            "game_over_reason": self.game_over_reason,
            # RNG state is saved so a loaded save replays the same rolls.
            "rng": {
                "version": rng_version,
                "state": list(rng_state),
                "gauss": rng_gauss,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "GameEngine":
        """Rebuild a game from to_dict() output.

        Missing or invalid fields fall back to defaults so saves stay
        forward-compatible with future versions.
        """

        # Identity gate (review Batch 3): refuse non-saves BEFORE any
        # field work. Wrong shape / wrong game / unsupported version all
        # raise ValueError, which _load_game already reports as a clean
        # "Load failed: ..." status — never a silent fresh Day 1.
        if not isinstance(data, dict):
            raise ValueError(
                "save must be a JSON object "
                f"(got {type(data).__name__})"
            )
        if data.get("game") != cls.SAVE_GAME_ID:
            raise ValueError(
                "not a Day Scheduler RPG save (missing or wrong 'game' tag)"
            )
        version = data.get("version")
        if type(version) is not int or not 1 <= version <= cls.SAVE_VERSION:
            raise ValueError(
                f"unsupported save version {version!r} "
                f"(this build reads 1..{cls.SAVE_VERSION})"
            )

        def as_int(value: object, default: int) -> int:
            try:
                return int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return default

        engine = cls()
        engine.day = max(1, as_int(data.get("day"), engine.day))
        engine.health = clamp(as_int(data.get("health"), engine.health))
        engine.energy = clamp(as_int(data.get("energy"), engine.energy))
        engine.hunger = clamp(as_int(data.get("hunger"), engine.hunger))
        engine.gold = max(0, as_int(data.get("gold"), engine.gold))
        engine.level = max(1, as_int(data.get("level"), engine.level))
        engine.xp = max(0, as_int(data.get("xp"), engine.xp))
        engine.game_over = bool(data.get("game_over", False))
        engine.game_over_reason = str(data.get("game_over_reason", ""))

        inventory = data.get("inventory")
        if isinstance(inventory, dict):
            merged = dict(engine.inventory)
            merged.update(
                {str(k): max(0, as_int(v, 0)) for k, v in inventory.items()}
            )
            engine.inventory = merged

        for kind, table in (("stats", engine.stats), ("skills", engine.skills)):
            saved = data.get(kind)
            if isinstance(saved, dict):
                for key, values in saved.items():
                    if key in table and isinstance(values, dict):
                        table[key] = Progress(
                            level=max(1, as_int(values.get("level"),
                                                 table[key].level)),
                            xp=max(0, as_int(values.get("xp"),
                                             table[key].xp)),
                        )

        for name in ("projects", "buildings"):
            saved = data.get(name)
            if isinstance(saved, dict):
                target: Dict[str, int] = getattr(engine, name)
                target.update(
                    {str(k): max(0, as_int(v, 0)) for k, v in saved.items()}
                )

        # Legacy saves stored tools as a separate table — they are
        # inventory items now; fold them in (older saves stay useful).
        legacy_tools = data.get("tools")
        if isinstance(legacy_tools, dict):
            for tool, count in legacy_tools.items():
                tool = str(tool)
                engine.inventory[tool] = (
                    engine.inventory.get(tool, 0) + max(0, as_int(count, 0))
                )

        actions = data.get("slot_actions")
        if isinstance(actions, list) and len(actions) == len(SLOT_NAMES):
            engine.slot_actions = [
                action if action in ACTION_LABELS else engine.slot_actions[i]
                for i, action in enumerate(actions)
            ]

        rng = data.get("rng")
        if isinstance(rng, dict):
            try:
                engine.rng.setstate(
                    (
                        int(rng["version"]),  # type: ignore[arg-type]
                        tuple(int(v) for v in rng["state"]),  # type: ignore[index]
                        rng.get("gauss"),
                    )
                )
            except (KeyError, TypeError, ValueError):
                pass  # corrupt RNG data: keep the fresh generator
        return engine

    # --- Placeholder events ----------------------------------------------

    def _pick_event(self, action_id: str) -> RandomEvent | None:
        """Draw a table event whose `actions` include this action."""
        eligible = [
            event for event in self.RANDOM_EVENTS.values()
            if not event.actions or action_id in event.actions
        ]
        if not eligible:
            return None
        return self.rng.choice(eligible)

    def _resolve_event(self, action_id: str, xp_changes: List[Change],
                       notes: List[str]) -> EventResolution:
        """Resolve a triggered event.

        A named event is drawn from RANDOM_EVENTS (filtered by which
        actions may trigger it); `check=False` events are pure flavor.
        Otherwise the generic check runs: contributors' levels feed the
        roll, and the outcome feeds XP back (plus health on failure).
        Per-event effects can be added here without touching any UI code.
        """
        chosen = self._pick_event(action_id)
        text = chosen.text if chosen else ""
        event_id = chosen.id if chosen else ""
        contributors = ACTION_CHECKS.get(action_id, ())

        if chosen is not None and not chosen.check:
            note = f"event: {text}"
            notes.append(note)
            return EventResolution(
                check="", bonus=0, die=0, roll=0, success=True,
                event_id=event_id, text=text, note=note,
            )

        if not contributors:
            note = text or "an event passes with no check attached yet."
            notes.append(note)
            return EventResolution(
                check="", bonus=0, die=0, roll=0, success=True,
                event_id=event_id, text=text, note=note,
            )

        labels: List[str] = []
        bonus = 0
        for kind, key in contributors:
            bonus += self._level_of(kind, key)
            labels.append(self._display_name(kind, key))
        die = self.rng.randint(1, CHECK_DIE)
        roll = die + bonus
        dc = (chosen.difficulty if chosen is not None
              and chosen.difficulty is not None else EVENT_DIFFICULTY)
        success = roll >= dc

        award = EVENT_XP_SUCCESS if success else EVENT_XP_FAILURE
        event_changes: List[Change] = []
        for kind, key in contributors:
            changes, level_note = self.add_xp(kind, key, award)
            xp_changes.extend(changes)
            event_changes.extend(changes)
            if level_note:
                notes.append(level_note)
        if not success:
            self.health = clamp(self.health + EVENT_FAILURE_HEALTH)
            event_changes.append(("Health", EVENT_FAILURE_HEALTH))

        check = f"{' + '.join(labels)} vs DC {dc}"
        note = (
            f"event check [{check}]: d20 {die} + {bonus} = {roll} — "
            f"{'success' if success else 'failure'}."
        )
        if text:
            note = f"{text} {note}"
        notes.append(note)
        return EventResolution(
            check=check, bonus=bonus, die=die, roll=roll, success=success,
            event_id=event_id, text=text, changes=event_changes, note=note,
        )

    # --- Action handlers -------------------------------------------------

    def _apply_action(self, action_id: str) -> Tuple[bool, str]:
        """Apply a non-pattern action by dispatching on its behavior.

        Returns (attempt_succeeded, note). Behavior names map to
        GameEngine._apply_<name> methods; validate_content() proves every
        behavior has one before play starts. build_craft routes through
        run_slot (it needs the pattern picker) and is rejected here.
        """
        behavior = ACTION_BEHAVIOR[action_id]
        if behavior == BUILD_CRAFT:
            raise ValueError(
                f"action {action_id!r}: build_craft dispatches in run_slot, "
                "not _apply_action"
            )
        return getattr(self, f"_apply_{behavior}")(action_id)

    def _skill_check(self, skill_key: str,
                     difficulty: int | None = None) -> bool:
        """Roll d20 + skill level against a DC.

        `difficulty` overrides ACTION_DIFFICULTY per call (a gather
        block's optional "difficulty"); tests still force the class
        default via the instance attribute when content sets none.
        """
        skill = self.skills[skill_key]
        die = self.rng.randint(1, CHECK_DIE)
        dc = self.ACTION_DIFFICULTY if difficulty is None else difficulty
        return die + skill.level >= dc

    def _stat_check(self, stat_key: str,
                    difficulty: int | None = None) -> bool:
        """Roll d20 + stat level against a DC.

        Same single draw as _skill_check — used when an action's
        difficulty_target names a stat instead of a skill.
        """
        stat = self.stats[stat_key]
        die = self.rng.randint(1, CHECK_DIE)
        dc = self.ACTION_DIFFICULTY if difficulty is None else difficulty
        return die + stat.level >= dc

    def _recovery(self, amount: int) -> int:
        """Scale a recovery gain; the Lean to adds 10%, rounded down."""
        if amount > 0 and self.buildings.get("lean_to"):
            return int(amount * (1 + LEAN_TO_RECOVERY_BONUS))
        return amount

    def _apply_gather_item(self, action_id: str) -> Tuple[bool, str]:
        """Generic gather: effort cost, skill check, yield on success.

        Kind-specific data comes from the action's gather block (item,
        yield range, messages, optional difficulty); tool bonuses come
        from inventory items whose tool_bonus is tagged with this
        action's id — highest owned amount wins, copies never stack.
        Draw order is the seeded contract: costs before any draw, one
        skill-check draw, one yield draw only on success, tool bonus
        after the yield with no draw.
        """
        cfg = ACTION_GATHER[action_id]
        # The effort is spent whether or not anything is found.
        self.energy = clamp(self.energy - GATHER_ENERGY_COST)
        self.hunger = clamp(self.hunger + GATHER_HUNGER_COST)
        # Aim: explicit difficulty_target, else the action's own skill.
        target = ACTION_TARGETS.get(action_id)
        if target is not None and target[0] == "stats":
            passed = self._stat_check(target[1], cfg.get("difficulty"))
        else:
            key = (target[1] if target is not None
                   else ACTION_SKILL[action_id])
            passed = self._skill_check(key, cfg.get("difficulty"))
        if passed:
            low, high = cfg["yield"]
            amount = self.rng.randint(low, high)
            # Best owned tool tagged for this action wins; copies of the
            # same tool never stack (max over owned, not sum).
            bonus = 0
            for item_id, (tagged, flat) in TOOL_BONUSES.items():
                if tagged == action_id and self.inventory.get(item_id):
                    bonus = max(bonus, flat)
            amount += bonus
            self.inventory[cfg["item"]] += amount
            return True, cfg["success"].format(amount=amount)
        return False, cfg["fail"]

    def _apply_build_craft(self, action_id: str, pattern_id: str,
                           extra_changes: List[Change],
                           notes: List[str]) -> Tuple[bool, bool]:
        """Attempt a build/craft pattern.

        Materials are committed up front and are lost even when the
        attempt fails; run_slot grants XP whenever an attempt happens.
        Returns (attempt_made, success). Completions append their own
        (name, +1) change for the summary display.
        """
        pattern = PATTERNS.get(pattern_id)
        if pattern is None or pattern.kind != action_id:
            notes.append("that pattern does not fit this task.")
            return False, False
        store = self.buildings if action_id == BUILD else self.inventory
        if action_id == BUILD and store.get(pattern.id):
            # Buildings are unique until an upgrade replaces them; crafted
            # tools may repeat (extras land in inventory for later selling).
            notes.append(f"you already have a finished {pattern.name}.")
            return False, False
        skill = self.skills.get(pattern.skill)
        skill_name = SKILL_NAMES.get(pattern.skill, pattern.skill.title())
        if skill is None or skill.level < pattern.skill_req:
            notes.append(
                f"the {pattern.name} needs {skill_name} "
                f"{pattern.skill_req} — you are not there yet."
            )
            return False, False
        missing = [
            f"{qty - self.inventory.get(item, 0)} more "
            f"{ITEM_NAMES.get(item, item)}"
            for item, qty in pattern.materials.items()
            if self.inventory.get(item, 0) < qty
        ]
        if missing:
            notes.append(
                f"not enough materials for the {pattern.name} "
                f"({', '.join(missing)})."
            )
            return False, False

        for item, qty in pattern.materials.items():
            self.inventory[item] -= qty  # surfaces via the slot diff

        if not self._skill_check(pattern.skill, pattern.difficulty):
            notes.append(
                f"your attempt at the {pattern.name} fails — the materials "
                "are spent, but the effort still teaches."
            )
            return True, False

        progress = self.projects.get(pattern.id, 0) + 1
        if progress >= pattern.work:
            self.projects.pop(pattern.id, None)
            store[pattern.id] = store.get(pattern.id, 0) + 1
            extra_changes.append((pattern.name, 1))
            notes.append(
                f"you finish the {pattern.name}! {pattern.description}"
            )
        else:
            self.projects[pattern.id] = progress
            notes.append(
                f"you work on the {pattern.name} "
                f"({progress}/{pattern.work})."
            )
        return True, True

    def patterns_for(self, kind: str) -> List[Pattern]:
        """Patterns of `kind` still worth offering.

        Buildings drop out once owned (a future upgrade tier replaces
        them); tools stay listed so extras can be made for later selling.
        """
        found: List[Pattern] = []
        for pattern in PATTERNS.values():
            if pattern.kind != kind:
                continue
            if kind == BUILD and self.buildings.get(pattern.id):
                continue
            found.append(pattern)
        return found

    def _eat_until_recovered(
        self, health_add: int, energy_add: int, hunger_add: int
    ) -> List[str]:
        """Batch 5: eat best-tier-first until the food-recoverable stats
        are saturated (health/max, energy/max, hunger/0). Each tier is
        drained before downgrading; returns eaten ids in order — empty
        means already satisfied, a bare larder (the shortfall only the
        player's pantry can cause), or gains that can change nothing
        (the progress guard)."""
        eaten: List[str] = []
        for item_id in FOOD_ITEMS:
            while (self.inventory.get(item_id, 0) > 0
                   and not (self.health >= self.MAX_VITAL
                            and self.energy >= self.MAX_VITAL
                            and self.hunger <= 0)):
                # Review guard: a bite that cannot move any target stat
                # toward saturation would drain the pantry one item at a
                # time (validator-legal zero/negative REST/SLEEP_FOOD_*
                # values). The gains are per-behavior — identical for
                # every tier — so refusing here refuses for all of them.
                improves = (
                    (self.health < self.MAX_VITAL and health_add > 0)
                    or (self.energy < self.MAX_VITAL and energy_add > 0)
                    or (self.hunger > 0 and hunger_add < 0)
                )
                if not improves:
                    return eaten
                self.inventory[item_id] -= 1
                eaten.append(item_id)
                self.health = clamp(self.health + self._recovery(health_add))
                self.energy = clamp(self.energy + self._recovery(energy_add))
                self.hunger = clamp(self.hunger + hunger_add)
        return eaten

    def _apply_rest(self, _action_id: str) -> Tuple[bool, str]:
        """Rest never fails; returns (True, note) for the behavior dispatch."""
        if any(self.inventory.get(item, 0) > 0 for item in FOOD_ITEMS):
            eaten = self._eat_until_recovered(
                REST_FOOD_HEALTH, REST_FOOD_ENERGY, REST_FOOD_HUNGER_NET)
            if eaten:
                name = ITEM_NAMES.get(eaten[0], eaten[0]).lower()
                return True, f"you ate {name} and rested properly."
            return True, "you were already rested — supplies untouched."
        self.health = clamp(self.health + self._recovery(REST_EMPTY_HEALTH))
        self.energy = clamp(self.energy + self._recovery(REST_EMPTY_ENERGY))
        self.hunger = clamp(self.hunger + REST_EMPTY_HUNGER)
        return True, "you rested, but an empty stomach limited the recovery."

    def _apply_sleep(self) -> str:
        # The night passes whether or not there is food.
        self.hunger = clamp(self.hunger + SLEEP_HUNGER_NIGHT)
        if any(self.inventory.get(item, 0) > 0 for item in FOOD_ITEMS):
            eaten = self._eat_until_recovered(
                SLEEP_FOOD_HEALTH, SLEEP_FOOD_ENERGY, SLEEP_FOOD_HUNGER_NET)
            if eaten:
                return "you ate before bed and slept soundly."
            return "you slept soundly — no food needed."
        self.health = clamp(self.health + self._recovery(SLEEP_EMPTY_HEALTH))
        self.energy = clamp(self.energy + self._recovery(SLEEP_EMPTY_ENERGY))
        return "you slept on an empty stomach and woke up weak."

    # --- Change bookkeeping ----------------------------------------------

    def _snapshot(self) -> Dict[str, Dict[str, int]]:
        """Capture items and stats separately so `_diff()` can tell them
        apart and pick up items that are not in ITEM_ORDER."""
        return {
            "items": dict(self.inventory),
            "stats": {key: getattr(self, key) for key, _label in STAT_LABELS},
        }

    def _diff(self, snapshot: Dict[str, Dict[str, int]]) -> List[Change]:
        changes: List[Change] = []
        # Items: union of current and snapshotted keys, ITEM_ORDER first.
        old_items = snapshot["items"]
        items = [
            item for item in ITEM_ORDER
            if item in self.inventory or item in old_items
        ]
        items += [item for item in self.inventory if item not in items]
        items += [item for item in old_items if item not in items]
        for item in items:
            delta = self.inventory.get(item, 0) - old_items.get(item, 0)
            if delta:
                changes.append((ITEM_NAMES.get(item, item), delta))
        for key, label in STAT_LABELS:
            delta = getattr(self, key) - snapshot["stats"][key]
            if delta:
                changes.append((label, delta))
        return changes


def validate_content() -> List[Problem]:
    """Content + engine contract checks; [] means all consistent.

    The engine-free half (schema, cross-references, balance key set) is
    content.validate_bundle — it already ran inside the strict import
    load, and re-running it here keeps one entry point for callers. The
    checks below are the ones only game code can make:

    - the fresh-game default plan exists in content;
    - code-side item anchors (FOOD_ITEM/WOOD_ITEM) exist in content;
    - every BEHAVIOR_HANDLERS name has a GameEngine._apply_<name> method;
    - STAT_LABELS keys are engine attributes (the vitals-only rule);
    - every BALANCE_KEYS name is bound to a number in this module.

    Called by test_smoke.py and check_live.py — fix anything it reports
    before playtesting.
    """
    problems: List[str] = list(validate_bundle(CONTENT))
    engine = GameEngine()

    for action_id in DEFAULT_SLOT_ACTIONS:
        if action_id not in ACTION_LABELS:
            problems.append(
                f"actions.json: missing default slot action {action_id!r}"
            )

    item_ids = {entry["id"] for entry in CONTENT.items}
    for item_id in (FOOD_ITEM, WOOD_ITEM):
        if item_id not in item_ids:
            problems.append(
                f"items.json: missing code-required item {item_id!r}"
            )

    # Shared behavior vocabulary (content.py BEHAVIOR_HANDLERS is what the
    # content editor reads) must match real, callable handler methods.
    for behavior in BEHAVIOR_HANDLERS:
        if not callable(getattr(GameEngine, f"_apply_{behavior}", None)):
            problems.append(
                f"content.py BEHAVIOR_HANDLERS: no GameEngine._apply_{behavior}()"
            )

    for key, _label in STAT_LABELS:
        if not hasattr(engine, key):
            problems.append(
                f"STAT_LABELS: {key!r} is not a direct engine attribute "
                "(vitals only — stats live in engine.stats)"
            )

    # balance.json keys and the CONTENT.balance[...] bindings above must
    # cover each other: a key added to content.py's BALANCE_KEYS without
    # a matching line here (or vice versa) is reported.
    module_globals = globals()
    for key in BALANCE_KEYS:
        value = module_globals.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            problems.append(
                f"game_core: balance key {key!r} is not bound to a number — "
                "add CONTENT.balance[...] line or fix content.py BALANCE_KEYS"
            )

    # One conversion point: engine-appended plain strings join the
    # Problems from validate_bundle (text unchanged, structure parsed).
    return [Problem(p) for p in problems]
