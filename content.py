"""Content loading and validation for Day Scheduler RPG.

`content/*.json` is the single source of truth for game content: items,
skills, stats, actions, patterns, random events, and every balance
number. This module is UI-free and game-logic-free so three very
different consumers can share it:

- game_core.py calls load_content() at import time (strict: a broken
  file raises ContentError naming file and field — there is no silent
  fallback to built-in values; git/backup is the rollback).
- test_smoke.py / check_live.py re-validate content directly.
- the content editor calls try_load_content() (non-throwing) so a broken
  file can still be opened and repaired.

Path resolution for load_content(): an explicit `path` argument wins,
else the DAY_SCHEDULER_CONTENT_DIR environment variable (the test
suite pins it to tests/fixtures/content/ before importing game_core),
else `content/` next to this file.

Editor rules: keep JSON key/array order stable — the game reads order
as planner and iteration order (seeded RNG depends on it); never write
these files with sort_keys=True.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

#: The seven content files; all are required.
CONTENT_FILES: Tuple[str, ...] = (
    "items", "skills", "stats", "actions", "patterns", "events", "balance",
)

#: Valid `behavior` values for actions.json entries. game_core implements
#: each as GameEngine._apply_<name> and validates the mapping — this is
#: the shared vocabulary the content editor's dropdown reads (it must
#: never import game_core).
BEHAVIOR_HANDLERS: Dict[str, str] = {
    "gather_food": "Effort cost, skill check, yields a food item.",
    "gather_wood": "Effort cost, skill check, yields wood.",
    "rest": "Recovery action; eats food if available.",
    "build_craft": "Pattern attempt: spends materials, skill check, progress.",
}

#: Exact key set balance.json must carry — a missing key would crash the
#: game at import, an unknown key is a typo silently ignored. Both fail
#: validation. Mirrors the balance constants game_core reads.
BALANCE_KEYS: Tuple[str, ...] = (
    "MAX_VITAL", "XP_TO_NEXT", "XP_COST_STEP",
    "ACTION_XP", "SKILL_XP",
    "CHECK_DIE", "EVENT_DIFFICULTY", "ACTION_DIFFICULTY",
    "EVENT_XP_SUCCESS", "EVENT_XP_FAILURE", "EVENT_FAILURE_HEALTH",
    "EVENT_CHANCE", "LEAN_TO_RECOVERY_BONUS",
    "GATHER_ENERGY_COST", "GATHER_HUNGER_COST",
    "FOOD_MIN", "FOOD_MAX", "WOOD_MIN", "WOOD_MAX", "AXE_WOOD_BONUS",
    "REST_FOOD_HEALTH", "REST_FOOD_ENERGY", "REST_FOOD_HUNGER_NET",
    "REST_EMPTY_HEALTH", "REST_EMPTY_ENERGY", "REST_EMPTY_HUNGER",
    "SLEEP_HUNGER_NIGHT", "SLEEP_FOOD_HEALTH", "SLEEP_FOOD_ENERGY",
    "SLEEP_FOOD_HUNGER_NET", "SLEEP_EMPTY_HEALTH", "SLEEP_EMPTY_ENERGY",
)

#: Pattern kinds (must match game_core's BUILD/CRAFT constants).
PATTERN_KINDS: Tuple[str, ...] = ("build", "craft")

#: Check contributor kinds (must match game_core's ACTION_CHECKS shape).
CHECK_KINDS: Tuple[str, ...] = ("stats", "skills")


class ContentError(Exception):
    """Content failed to load; `.problems` lists 'file: ...' messages."""

    def __init__(self, problems: List[str]) -> None:
        self.problems = list(problems)
        super().__init__(
            "content failed validation — fix content/*.json:\n"
            + "\n".join(f"  - {p}" for p in self.problems)
        )


@dataclass
class Content:
    """Raw content parsed from JSON (validated by validate_bundle)."""

    items: List[dict]
    skills: Dict[str, dict]
    stats: Dict[str, dict]
    actions: List[dict]
    patterns: Dict[str, dict]
    events: Dict[str, dict]
    balance: Dict[str, Any]
    source: Path = field(default_factory=Path)


def project_content_dir() -> Path:
    """The shipped content/ next to this file (ignores the env override)."""
    return Path(__file__).resolve().parent / "content"


def content_dir() -> Path:
    """Directory load_content() reads by default (env override aware)."""
    override = os.environ.get("DAY_SCHEDULER_CONTENT_DIR")
    return Path(override) if override else project_content_dir()


# --- Validation (engine-free: schema, cross-references, id slugs, ranges) ---

def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


#: Slug shape every record id must match (items, skills, stats, actions,
#: patterns, events). Ids are save data and code references; display text
#: lives in each record's name/label fields. fullmatch, not match: a bare
#: `$` would let trailing newlines through.
_ID_SLUG = re.compile(r"[a-z][a-z0-9_]*")


def _check_slug(where: str, rec_id: str, problems: List[str]) -> None:
    """Append a problem when a record id is not a lowercase slug."""
    if not _ID_SLUG.fullmatch(rec_id):
        problems.append(
            f"{where}: id must be a lowercase slug (a-z, then a-z/0-9/_)"
        )


def _check_items(items: Any, problems: List[str]) -> Set[str]:
    ids: Set[str] = set()
    if not isinstance(items, list):
        problems.append("items.json: expected a JSON array of item records")
        return ids
    for index, rec in enumerate(items):
        where = f"items.json: entry {index}"
        if not isinstance(rec, dict):
            problems.append(f"{where}: expected an object")
            continue
        item_id = rec.get("id")
        if not isinstance(item_id, str) or not item_id:
            problems.append(f"{where}: missing or empty 'id'")
            continue
        where = f"items.json: {item_id!r}"
        if item_id in ids:
            problems.append(f"{where}: duplicate id")
        ids.add(item_id)
        _check_slug(where, item_id, problems)
        if not isinstance(rec.get("name"), str) or not rec["name"]:
            problems.append(f"{where}: 'name' must be a non-empty string")
        start = rec.get("start")
        if not isinstance(start, int) or isinstance(start, bool) or start < 0:
            problems.append(f"{where}: 'start' must be an integer >= 0")
        if "tooltip" in rec and not isinstance(rec["tooltip"], str):
            problems.append(f"{where}: 'tooltip' must be a string")
    return ids


def _check_level_table(
    records: Any, filename: str, problems: List[str]
) -> Set[str]:
    """skills.json / stats.json: id -> {name, start_level, tooltip?}."""
    ids: Set[str] = set()
    if not isinstance(records, dict):
        problems.append(f"{filename}.json: expected a JSON object keyed by id")
        return ids
    for rec_id, rec in records.items():
        where = f"{filename}.json: {rec_id!r}"
        if not isinstance(rec_id, str) or not rec_id:
            problems.append(f"{filename}.json: ids must be non-empty strings")
            continue
        _check_slug(where, rec_id, problems)
        if not isinstance(rec, dict):
            problems.append(f"{where}: expected an object")
            continue
        if not isinstance(rec.get("name"), str) or not rec["name"]:
            problems.append(f"{where}: 'name' must be a non-empty string")
        level = rec.get("start_level")
        if not isinstance(level, int) or isinstance(level, bool) or level < 1:
            problems.append(f"{where}: 'start_level' must be an integer >= 1")
        if "tooltip" in rec and not isinstance(rec["tooltip"], str):
            problems.append(f"{where}: 'tooltip' must be a string")
        ids.add(rec_id)
    return ids


def _check_actions(
    actions: Any, skill_ids: Set[str], stat_ids: Set[str], problems: List[str]
) -> Set[str]:
    ids: Set[str] = set()
    if not isinstance(actions, list):
        problems.append("actions.json: expected a JSON array of action records")
        return ids
    for index, rec in enumerate(actions):
        where = f"actions.json: entry {index}"
        if not isinstance(rec, dict):
            problems.append(f"{where}: expected an object")
            continue
        action_id = rec.get("id")
        if not isinstance(action_id, str) or not action_id:
            problems.append(f"{where}: missing or empty 'id'")
            continue
        where = f"actions.json: {action_id!r}"
        if action_id in ids:
            problems.append(f"{where}: duplicate id")
        ids.add(action_id)
        _check_slug(where, action_id, problems)
        if not isinstance(rec.get("label"), str) or not rec["label"]:
            problems.append(f"{where}: 'label' must be a non-empty string")
        if rec.get("behavior") not in BEHAVIOR_HANDLERS:
            problems.append(
                f"{where}: 'behavior' must be one of "
                f"{tuple(BEHAVIOR_HANDLERS)}"
            )
        skill = rec.get("skill")
        if skill is not None and skill not in skill_ids:
            problems.append(f"{where}: unknown skill {skill!r}")
        if not isinstance(rec.get("checks"), list):
            problems.append(f"{where}: 'checks' must be a JSON array")
        else:
            for pair_index, pair in enumerate(rec["checks"]):
                pair_where = f"{where}: checks[{pair_index}]"
                if (
                    not isinstance(pair, (list, tuple))
                    or len(pair) != 2
                    or not isinstance(pair[0], str)
                    or not isinstance(pair[1], str)
                ):
                    problems.append(
                        f"{pair_where}: expected [kind, key] string pair"
                    )
                    continue
                kind, key = pair
                if kind not in CHECK_KINDS:
                    problems.append(
                        f"{pair_where}: kind must be one of {CHECK_KINDS}"
                    )
                elif kind == "stats" and key not in stat_ids:
                    problems.append(f"{pair_where}: unknown stat {key!r}")
                elif kind == "skills" and key not in skill_ids:
                    problems.append(f"{pair_where}: unknown skill {key!r}")
        stat_xp = rec.get("stat_xp")
        if stat_xp is not None and (
            not isinstance(stat_xp, (list, tuple))
            or len(stat_xp) != 2
            or stat_xp[0] not in stat_ids
            or not isinstance(stat_xp[1], int)
            or isinstance(stat_xp[1], bool)
            or stat_xp[1] <= 0
        ):
            problems.append(
                f"{where}: 'stat_xp' must be null or [existing stat, "
                "positive integer]"
            )
    return ids


def _check_patterns(
    patterns: Any,
    skill_ids: Set[str],
    item_ids: Set[str],
    problems: List[str],
) -> None:
    if not isinstance(patterns, dict):
        problems.append(
            "patterns.json: expected a JSON object keyed by pattern id"
        )
        return
    for pattern_id, rec in patterns.items():
        where = f"patterns.json: {pattern_id!r}"
        if not isinstance(pattern_id, str) or not pattern_id:
            problems.append("patterns.json: ids must be non-empty strings")
            continue
        _check_slug(where, pattern_id, problems)
        if not isinstance(rec, dict):
            problems.append(f"{where}: expected an object")
            continue
        if not isinstance(rec.get("name"), str) or not rec["name"]:
            problems.append(f"{where}: 'name' must be a non-empty string")
        if rec.get("kind") not in PATTERN_KINDS:
            problems.append(f"{where}: 'kind' must be one of {PATTERN_KINDS}")
        if rec.get("skill") not in skill_ids:
            problems.append(f"{where}: unknown skill {rec.get('skill')!r}")
        for field_name in ("skill_req", "work"):
            value = rec.get(field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                problems.append(
                    f"{where}: '{field_name}' must be an integer >= 1"
                )
        if not isinstance(rec.get("description"), str) or not rec["description"]:
            problems.append(
                f"{where}: 'description' must be a non-empty string"
            )
        if "effect" in rec and not isinstance(rec["effect"], str):
            problems.append(f"{where}: 'effect' must be a string")
        materials = rec.get("materials")
        if not isinstance(materials, dict):
            problems.append(f"{where}: 'materials' must be a JSON object")
            continue
        for item_id, qty in materials.items():
            mat_where = f"{where}: materials[{item_id!r}]"
            if item_id not in item_ids:
                problems.append(f"{mat_where}: unknown item {item_id!r}")
            if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
                problems.append(
                    f"{mat_where}: quantity must be an integer > 0"
                )


def _check_events(
    events: Any, action_ids: Set[str], problems: List[str]
) -> None:
    if not isinstance(events, dict):
        problems.append("events.json: expected a JSON object keyed by event id")
        return
    for event_id, rec in events.items():
        where = f"events.json: {event_id!r}"
        if not isinstance(event_id, str) or not event_id:
            problems.append("events.json: ids must be non-empty strings")
            continue
        _check_slug(where, event_id, problems)
        if not isinstance(rec, dict):
            problems.append(f"{where}: expected an object")
            continue
        if not isinstance(rec.get("text"), str) or not rec["text"]:
            problems.append(f"{where}: 'text' must be a non-empty string")
        actions = rec.get("actions")
        if not isinstance(actions, list):
            problems.append(f"{where}: 'actions' must be a JSON array")
        else:
            for action_id in actions:
                if not isinstance(action_id, str) or action_id not in action_ids:
                    problems.append(
                        f"{where}: unknown action {action_id!r} in 'actions'"
                    )
        if not isinstance(rec.get("check"), bool):
            problems.append(f"{where}: 'check' must be true or false")


def _check_balance(balance: Any, problems: List[str]) -> None:
    if not isinstance(balance, dict):
        problems.append("balance.json: expected a JSON object of numbers")
        return
    for key in BALANCE_KEYS:
        if key not in balance:
            problems.append(f"balance.json: missing key {key!r}")
    for key in balance:
        if key not in BALANCE_KEYS:
            problems.append(
                f"balance.json: unknown key {key!r} (typo? known keys are "
                "listed in content.py BALANCE_KEYS)"
            )
        elif not _is_number(balance[key]):
            problems.append(f"balance.json: {key!r} must be a number")
    # Crash-level sanity only; placeholder balance stays freely tunable.
    ranged = {
        key: balance[key]
        for key in ("MAX_VITAL", "XP_TO_NEXT", "XP_COST_STEP", "CHECK_DIE",
                    "FOOD_MIN", "FOOD_MAX", "WOOD_MIN", "WOOD_MAX")
        if key in balance and _is_number(balance[key])
    }
    if ranged.get("MAX_VITAL", 1) < 1:
        problems.append("balance.json: 'MAX_VITAL' must be >= 1")
    if ranged.get("XP_TO_NEXT", 1) < 1:
        problems.append("balance.json: 'XP_TO_NEXT' must be >= 1")
    if ranged.get("XP_COST_STEP", 0) < 0:
        problems.append("balance.json: 'XP_COST_STEP' must be >= 0")
    if ranged.get("CHECK_DIE", 1) < 1:
        problems.append(
            "balance.json: 'CHECK_DIE' must be >= 1 (randint would crash)"
        )
    if "FOOD_MIN" in ranged and "FOOD_MAX" in ranged:
        if ranged["FOOD_MIN"] > ranged["FOOD_MAX"]:
            problems.append(
                "balance.json: FOOD_MIN must be <= FOOD_MAX (randint crash)"
            )
    if "WOOD_MIN" in ranged and "WOOD_MAX" in ranged:
        if ranged["WOOD_MIN"] > ranged["WOOD_MAX"]:
            problems.append(
                "balance.json: WOOD_MIN must be <= WOOD_MAX (randint crash)"
            )
    chance = balance.get("EVENT_CHANCE")
    if _is_number(chance) and not 0 <= chance <= 1:
        problems.append("balance.json: 'EVENT_CHANCE' must be between 0 and 1")


def validate_bundle(content: Content) -> List[str]:
    """All engine-free checks; [] means the content set is consistent.

    Game-contract checks (handler methods exist, STAT_LABELS match engine
    attributes, code action ids are implemented) need game_core and live
    in game_core.validate_content() instead.
    """
    problems: List[str] = []
    item_ids = _check_items(content.items, problems)
    skill_ids = _check_level_table(content.skills, "skills", problems)
    stat_ids = _check_level_table(content.stats, "stats", problems)
    action_ids = _check_actions(content.actions, skill_ids, stat_ids, problems)
    _check_patterns(content.patterns, skill_ids, item_ids, problems)
    _check_events(content.events, action_ids, problems)
    _check_balance(content.balance, problems)
    return problems


# --- Loading ---------------------------------------------------------------

def try_load_content(
    path: Optional[Path] = None,
) -> Tuple[Optional[Content], List[str]]:
    """Load + validate without throwing: (content_or_None, problems).

    content is None only when a file is missing or unparseable (nothing
    trustworthy to build); schema/reference problems come back alongside
    a usable bundle so the editor can display and repair it.
    """
    directory = Path(path) if path is not None else content_dir()
    problems: List[str] = []
    raw: Dict[str, Any] = {}
    for name in CONTENT_FILES:
        file_path = directory / f"{name}.json"
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append(f"{name}.json: cannot read ({exc})")
            continue
        try:
            raw[name] = json.loads(text)
        except json.JSONDecodeError as exc:
            problems.append(
                f"{name}.json: line {exc.lineno} column {exc.colno}: {exc.msg}"
            )
    if problems:
        return None, problems
    content = Content(
        items=raw["items"],
        skills=raw["skills"],
        stats=raw["stats"],
        actions=raw["actions"],
        patterns=raw["patterns"],
        events=raw["events"],
        balance=raw["balance"],
        source=directory,
    )
    return content, validate_bundle(content)


def load_content(path: Optional[Path] = None) -> Content:
    """Strict load for the game: raise ContentError listing every problem.

    There is deliberately no fallback to built-in values — a bad edit
    fails loudly, at game_core import, naming file and field. Roll back
    with your backup/git, never with stale silent data.
    """
    content, problems = try_load_content(path)
    if problems or content is None:
        raise ContentError(problems or ["content could not be built"])
    return content




