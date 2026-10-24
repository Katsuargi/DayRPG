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
  file can still be opened and repaired, then save() (the headless 2b
  write layer: atomic per file, stale-guarded, problem-gated, never
  sorts keys) to write edits back.

Path resolution for load_content(): an explicit `path` argument wins,
else the DAY_SCHEDULER_CONTENT_DIR environment variable (the test
suite pins it to tests/fixtures/content/ before importing game_core),
else `content/` next to this file.

Editor rules: keep JSON key/array order stable — the game reads order
as planner and iteration order (seeded RNG depends on it); never write
these files with sort_keys=True.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

#: The seven content files; all are required.
CONTENT_FILES: Tuple[str, ...] = (
    "items", "skills", "stats", "actions", "patterns", "events", "balance",
)

#: Valid `behavior` values for actions.json entries. game_core implements
#: each as GameEngine._apply_<name> and validates the mapping — this is
#: the shared vocabulary the content editor's dropdown reads (it must
#: never import game_core).
BEHAVIOR_HANDLERS: Dict[str, str] = {
    "gather_item": "Effort cost, skill check, yields a configured item.",
    "rest": "Recovery action; eats food if available.",
    "build_craft": "Pattern attempt: spends materials, skill check, progress.",
}

#: Behavior whose actions carry a `gather` block (item, yield range,
#: messages, optional tool bonus / difficulty) — validated by _check_gather.
GATHER_ITEM: str = "gather_item"

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
    "REST_FOOD_HEALTH", "REST_FOOD_ENERGY", "REST_FOOD_HUNGER_NET",
    "REST_EMPTY_HEALTH", "REST_EMPTY_ENERGY", "REST_EMPTY_HUNGER",
    "SLEEP_HUNGER_NIGHT", "SLEEP_FOOD_HEALTH", "SLEEP_FOOD_ENERGY",
    "SLEEP_FOOD_HUNGER_NET", "SLEEP_EMPTY_HEALTH", "SLEEP_EMPTY_ENERGY",
)

#: Pattern kinds (must match game_core's BUILD/CRAFT constants).
PATTERN_KINDS: Tuple[str, ...] = ("build", "craft")

#: Check contributor kinds (must match game_core's ACTION_CHECKS shape).
CHECK_KINDS: Tuple[str, ...] = ("stats", "skills")

#: Field-spec vocabulary for SCHEMA (D1): the viewer reads it; the
#: validator stays imperative and drift is pinned by test_smoke's
#: mutation loops. Specs: "slug" | "string" | "int" | "bool" | "number";
#: ("opt", T) absent-OK; ("nullable", T) may be null; ("enum", options);
#: ("ref", file) record id; ("dyn_ref", {sibling value: file}) id in the
#: file named by a sibling field; ("list", T); ("pair", T1, T2);
#: ("dict_int", file) ref -> positive-int map; ("nested", fields) block.
#:
#: order_sensitive: file order is meaningful data (planner order, event
#: draw order, golden tuples) — the editor must never sort these files.
SCHEMA: Dict[str, dict] = {
    "items": {
        "kind": "array",
        "order_sensitive": True,
        "fields": {
            "id": "slug",
            "name": "string",
            "start": "int",
            "tooltip": ("opt", "string"),
            "tool_bonus": ("opt", ("pair", ("ref", "actions"), "int")),
        },
    },
    "skills": {
        "kind": "dict",
        "order_sensitive": True,
        "fields": {
            "name": "string",
            "start_level": "int",
            "tooltip": ("opt", "string"),
        },
    },
    "stats": {
        "kind": "dict",
        "order_sensitive": True,
        "fields": {
            "name": "string",
            "start_level": "int",
            "tooltip": ("opt", "string"),
        },
    },
    "actions": {
        "kind": "array",
        "order_sensitive": True,
        "fields": {
            "id": "slug",
            "label": "string",
            "behavior": ("enum", tuple(BEHAVIOR_HANDLERS)),
            "skill": ("nullable", ("ref", "skills")),
            "difficulty_target": (
                "opt", ("pair", ("enum", CHECK_KINDS),
                        ("dyn_ref", {"stats": "stats", "skills": "skills"}))),
            "checks": ("list", ("pair", ("enum", CHECK_KINDS),
                                ("dyn_ref", {"stats": "stats",
                                             "skills": "skills"}))),
            "stat_xp": ("nullable", ("pair", ("ref", "stats"), "int")),
            "gather": ("opt", ("nested", {
                "item": ("ref", "items"),
                "yield": ("pair", "int", "int"),
                "success": "string",
                "fail": "string",
                "difficulty": ("opt", "int"),
            })),
        },
    },
    "patterns": {
        "kind": "dict",
        "order_sensitive": True,
        "fields": {
            "name": "string",
            "kind": ("enum", PATTERN_KINDS),
            "skill": ("ref", "skills"),
            "skill_req": "int",
            "materials": ("dict_int", "items"),
            "work": "int",
            "description": "string",
            "effect": ("opt", "string"),
            "difficulty": ("opt", "int"),
        },
    },
    "events": {
        "kind": "dict",
        "order_sensitive": True,
        "fields": {
            "text": "string",
            "actions": ("list", ("ref", "actions")),
            "check": "bool",
            "difficulty": ("opt", "int"),
        },
    },
    "balance": {
        "kind": "flat",
        "order_sensitive": False,
        "fields": {key: "number" for key in BALANCE_KEYS},
    },
}


def collect_references(content: "Content") -> List[Tuple[str, str, str, str, str]]:
    """(from_file, from_record, field, to_file, to_record) for every
    schema-typed reference in the bundle: the cross-record graph behind the
    viewer's uses/used-by links and item economy view, and the data 2c's
    delete-blocking will need. Schema-driven, so the schema-drift tests keep
    it complete as fields evolve. Field paths descend into nested records
    (e.g. actions gather.item)."""
    edges: List[Tuple[str, str, str, str, str]] = []
    for fname, spec in SCHEMA.items():
        data = getattr(content, fname)
        if spec["kind"] == "flat":
            records: List[Tuple[str, object]] = [("balance", data)]
        elif spec["kind"] == "array":
            records = [(str(rec.get("id", i)) if isinstance(rec, dict) else str(i),
                        rec) for i, rec in enumerate(data)]
        else:  # dict
            records = [(str(k), v) for k, v in data.items()]
        for rec_id, rec in records:
            if isinstance(rec, dict):
                _walk_refs(fname, rec_id, spec["fields"], rec, edges)
    return edges


def _walk_refs(fname: str, rec_id: str, fields: Dict, rec: Dict,
               edges: List) -> None:
    for field, fspec in fields.items():
        _spec_edge(fname, rec_id, field, fspec, rec.get(field), edges)


def _spec_edge(fname: str, rec_id: str, field: str, spec, value,
               edges: List) -> None:
    while isinstance(spec, tuple) and spec[0] in ("opt", "nullable"):
        spec = spec[1]
    if not isinstance(spec, tuple):
        return
    tag = spec[0]
    if tag == "ref":
        if isinstance(value, str):
            edges.append((fname, rec_id, field, spec[1], value))
    elif tag == "list":
        if isinstance(value, list):
            for item in value:
                _spec_edge(fname, rec_id, field, spec[1], item, edges)
    elif tag == "pair":
        t1, t2 = spec[1], spec[2]
        if isinstance(value, (list, tuple)) and len(value) == 2:
            if isinstance(t1, tuple) and t1[0] == "ref" and isinstance(value[0], str):
                edges.append((fname, rec_id, field, t1[1], value[0]))
            if (isinstance(t2, tuple) and t2[0] == "dyn_ref"
                    and isinstance(value[1], str) and isinstance(value[0], str)):
                to_file = t2[1].get(value[0])
                if to_file:
                    edges.append((fname, rec_id, field, to_file, value[1]))
    elif tag == "dict_int":
        if isinstance(value, dict):
            for key in value:
                if isinstance(key, str):
                    edges.append((fname, rec_id, field, spec[1], key))
    elif tag == "nested":
        if isinstance(value, dict) and isinstance(spec[1], dict):
            for sub, sspec in spec[1].items():
                _spec_edge(fname, rec_id, f"{field}.{sub}", sspec, value.get(sub), edges)


class ContentError(Exception):
    """Content failed to load; `.problems` lists 'file: ...' messages."""

    def __init__(self, problems: List[str]) -> None:
        self.problems = list(problems)
        super().__init__(
            "content failed validation — fix content/*.json:\n"
            + "\n".join(f"  - {p}" for p in self.problems)
        )


#: House message shape: '<file>.json: ['<record>': ['<field>': ]...] text'
#: — rule 2 guarantees file+field naming, so structure parses off the
#: message text itself; engine messages ('game_core: ...') match nothing
#: and keep all attributes None.
_PROBLEM_SHAPE = re.compile(
    r"^([A-Za-z0-9_]+\.json)(?:: '([^']+)')?(?:: '([^']+)')?"
)


class Problem(str):
    """A validation message with structure for editors.

    str(message) is byte-identical to what callers always appended, so
    every existing consumer (substring asserts, prints, ContentError)
    is untouched; `.file`, `.record_id`, `.field` are derived from the
    message shape — consumers never re-parse text themselves.
    """

    def __new__(cls, message: str) -> "Problem":
        obj = super().__new__(cls, message)
        match = _PROBLEM_SHAPE.match(message)
        obj.file = match.group(1) if match else None
        obj.record_id = match.group(2) if match else None
        obj.field = match.group(3) if match else None
        return obj


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


def _check_optional_dc(
    where: str, value: Any, problems: List[str]
) -> None:
    """Optional difficulty: absent = use the global DC; else int >= 1."""
    if value is not None and (
        not isinstance(value, int) or isinstance(value, bool) or value < 1
    ):
        problems.append(f"{where}: 'difficulty' must be an integer >= 1")


def _check_gather(
    where: str, gather: Any, item_ids: Set[str],
    problems: List[str],
) -> None:
    """The `gather` block of a gather_item action.

    Required: item (existing id), yield [min, max] (1 <= min <= max —
    randint would crash otherwise), non-empty success/fail messages.
    Optional: difficulty (DC override; the engine default is
    balance.json ACTION_DIFFICULTY). Tool bonuses moved to the tool's
    item record (items.json tool_bonus) — see _check_tool_bonuses.
    """
    gwhere = f"{where}: 'gather'"
    if not isinstance(gather, dict):
        problems.append(
            f"{gwhere} must be an object (item, yield, success, fail)"
        )
        return
    known = {"item", "yield", "success", "fail", "difficulty"}
    for key in gather:
        if key not in known:
            problems.append(f"{gwhere}: unknown key {key!r} (typo?)")
    item = gather.get("item")
    if not isinstance(item, str) or item not in item_ids:
        problems.append(f"{gwhere}: 'item' must be an existing item id")
    span = gather.get("yield")
    if (
        not isinstance(span, (list, tuple))
        or len(span) != 2
        or not all(
            isinstance(v, int) and not isinstance(v, bool) for v in span
        )
        or span[0] < 1
        or span[0] > span[1]
    ):
        problems.append(
            f"{gwhere}: 'yield' must be [min, max] integers with "
            "1 <= min <= max"
        )
    for key in ("success", "fail"):
        if not isinstance(gather.get(key), str) or not gather[key]:
            problems.append(f"{gwhere}: '{key}' must be a non-empty string")
    success = gather.get("success")
    if isinstance(success, str) and success:
        try:
            success.format(amount=0)
        except (KeyError, IndexError, ValueError) as exc:
            problems.append(
                f"{gwhere}: 'success' is not a valid template ({exc})"
            )
    _check_optional_dc(gwhere, gather.get("difficulty"), problems)


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
    actions: Any, skill_ids: Set[str], stat_ids: Set[str],
    item_ids: Set[str], problems: List[str],
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
        behavior = rec.get("behavior")
        gather = rec.get("gather")
        if behavior == GATHER_ITEM:
            _check_gather(where, gather, item_ids, problems)
        elif gather is not None:
            problems.append(
                f"{where}: 'gather' only applies to gather_item behaviors"
            )
        skill = rec.get("skill")
        if skill is not None and skill not in skill_ids:
            problems.append(f"{where}: unknown skill {skill!r}")
        elif (
            behavior == GATHER_ITEM
            and skill not in skill_ids
            and rec.get("difficulty_target") is None
        ):
            problems.append(
                f"{where}: gather_item actions need a valid 'skill' or a "
                "'difficulty_target' to check"
            )
        target = rec.get("difficulty_target")
        if target is not None:
            if (
                not isinstance(target, (list, tuple))
                or len(target) != 2
                or not isinstance(target[0], str)
                or target[0] not in CHECK_KINDS
            ):
                problems.append(
                    f"{where}: 'difficulty_target' must be [kind, key] "
                    f"with kind one of {CHECK_KINDS}"
                )
            else:
                kind, key = target
                pool = stat_ids if kind == "stats" else skill_ids
                if not isinstance(key, str) or key not in pool:
                    # kind[:-1]: "stats" -> stat, "skills" -> skill
                    problems.append(
                        f"{where}: 'difficulty_target' unknown "
                        f"{kind[:-1]} {key!r}"
                    )
            # gather_item is the only behavior with a direct check today;
            # extend when a new behavior gains one
            if behavior != GATHER_ITEM:
                problems.append(
                    f"{where}: 'difficulty_target' does not apply to "
                    f"{behavior} actions"
                )
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
        elif rec.get("kind") == "craft" and pattern_id not in item_ids:
            problems.append(
                f"{where}: craft patterns must match an item id "
                "(the crafted tool is an inventory item)"
            )
        if rec.get("skill") not in skill_ids:
            problems.append(f"{where}: unknown skill {rec.get('skill')!r}")
        for field_name in ("skill_req", "work"):
            value = rec.get(field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                problems.append(
                    f"{where}: '{field_name}' must be an integer >= 1"
                )
        _check_optional_dc(where, rec.get("difficulty"), problems)
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
        _check_optional_dc(where, rec.get("difficulty"), problems)


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
        for key in ("MAX_VITAL", "XP_TO_NEXT", "XP_COST_STEP", "CHECK_DIE")
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
    chance = balance.get("EVENT_CHANCE")
    if _is_number(chance) and not 0 <= chance <= 1:
        problems.append("balance.json: 'EVENT_CHANCE' must be between 0 and 1")


def _check_tool_bonuses(
    items: Any, action_ids: Set[str], problems: List[str]
) -> None:
    """Item tool_bonus: [action id it serves, flat bonus >= 1].

    The action scans inventory for items tagged with its own id and
    applies the highest amount (copies never stack).
    """
    if not isinstance(items, list):
        return  # _check_items already reported the shape problem
    for rec in items:
        if not isinstance(rec, dict):
            continue
        bonus = rec.get("tool_bonus")
        if bonus is None:
            continue
        where = f"items.json: {rec.get('id')!r}"
        if (
            not isinstance(bonus, (list, tuple))
            or len(bonus) != 2
            or not isinstance(bonus[0], str)
            or bonus[0] not in action_ids
            or not isinstance(bonus[1], int)
            or isinstance(bonus[1], bool)
            or bonus[1] < 1
        ):
            problems.append(
                f"{where}: 'tool_bonus' must be [action id, integer >= 1]"
            )


def validate_bundle(content: Content) -> List[Problem]:
    """All engine-free checks; [] means the content set is consistent.

    Game-contract checks (handler methods exist, STAT_LABELS match engine
    attributes, code action ids are implemented) need game_core and live
    in game_core.validate_content() instead.
    """
    problems: List[str] = []
    item_ids = _check_items(content.items, problems)
    skill_ids = _check_level_table(content.skills, "skills", problems)
    stat_ids = _check_level_table(content.stats, "stats", problems)
    action_ids = _check_actions(
        content.actions, skill_ids, stat_ids, item_ids, problems
    )
    _check_tool_bonuses(content.items, action_ids, problems)
    _check_patterns(content.patterns, skill_ids, item_ids, problems)
    _check_events(content.events, action_ids, problems)
    _check_balance(content.balance, problems)
    # One conversion point: messages become Problems (text unchanged)
    # with .file/.record_id/.field parsed from the house message shape.
    return [Problem(p) for p in problems]


# --- Loading ---------------------------------------------------------------

class _NonStandardJson(ValueError):
    """Non-standard JSON the loader refuses at parse time (loud)."""


def _reject_duplicate_keys(
    pairs: List[Tuple[str, Any]],
) -> Dict[str, Any]:
    """object_pairs_hook: a repeated key is ambiguous — refuse the file."""
    seen: Dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _NonStandardJson(
                f"duplicate key {key!r} — which value wins is ambiguous"
            )
        seen[key] = value
    return seen


def _reject_constant(value: str) -> None:
    """parse_constant: NaN/Infinity/-Infinity are not standard JSON.

    Always raises — the constant never becomes a value.
    """
    raise _NonStandardJson(f"non-finite number {value!r} is not allowed")


def _finite_float(value: str) -> float:
    """parse_float: catches overflow spellings like 1e400 (→ inf)."""
    number = float(value)
    if not math.isfinite(number):
        raise _NonStandardJson(
            f"non-finite number {value!r} is not allowed"
        )
    return number


@dataclass
class LoadState:
    """Load-time facts the 2b write layer needs.

    `problems` is constraint 3's baseline: a save may list problems but
    must never increase this count. `hashes` maps each file stem to the
    sha256 of its bytes as loaded — save() re-checks disk against it and
    refuses stale writes (D11).
    """

    problems: List[Problem]
    hashes: Dict[str, str]


def try_load_content_with_state(
    path: Optional[Path] = None,
) -> Tuple[Optional[Content], LoadState]:
    """Core loader: (content_or_None, load state) — see try_load_content.

    Each file is read once (bytes): hashed for D11, then decoded from
    those same bytes so the hash and the parsed content can never refer
    to two different reads of the file.
    """
    directory = Path(path) if path is not None else content_dir()
    problems: List[str] = []
    hashes: Dict[str, str] = {}
    raw: Dict[str, Any] = {}
    for name in CONTENT_FILES:
        file_path = directory / f"{name}.json"
        try:
            data = file_path.read_bytes()
        except OSError as exc:
            problems.append(f"{name}.json: cannot read ({exc})")
            continue
        hashes[name] = hashlib.sha256(data).hexdigest()
        try:
            # utf-8-sig: a BOM is tolerated (stripped), everything else
            # about the bytes is unchanged (D10 keeps saves BOM-free).
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            problems.append(f"{name}.json: not valid UTF-8 ({exc})")
            continue
        try:
            raw[name] = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_constant,
                parse_float=_finite_float,
            )
        except json.JSONDecodeError as exc:
            problems.append(
                f"{name}.json: line {exc.lineno} column {exc.colno}: {exc.msg}"
            )
        except _NonStandardJson as exc:
            problems.append(f"{name}.json: {exc}")
    if problems:
        return None, LoadState(
            problems=[Problem(p) for p in problems], hashes=hashes
        )
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
    return content, LoadState(
        problems=validate_bundle(content), hashes=hashes
    )


def try_load_content(
    path: Optional[Path] = None,
) -> Tuple[Optional[Content], List[Problem]]:
    """Load + validate without throwing: (content_or_None, problems).

    content is None only when a file is missing or unparseable (nothing
    trustworthy to build); schema/reference problems come back alongside
    a usable bundle so the editor can display and repair it.
    """
    content, state = try_load_content_with_state(path)
    return content, list(state.problems)


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


# --- Write layer (2b, headless: D9 Save-All, D10 canonical, D11 stale) -------

class StaleWriteError(Exception):
    """Disk changed since load (D11); `.files` lists the changed stems.

    The headless refusal — 2c's UI maps it to the D11 choices (reload /
    discard / confirmed overwrite / cancel).
    """

    def __init__(self, files: List[str]) -> None:
        self.files = list(files)
        super().__init__(
            "changed on disk since load: "
            + ", ".join(f"{f}.json" for f in self.files)
        )


@dataclass
class SaveResult:
    """What one Save-All did (and did not do) — 2c displays this.

    `skipped` files had problems of their own (constraint 3: a file is
    written only when it has none). `reformatted` files' bytes on disk
    weren't canonical, so writing them canonicalizes beyond the edit
    (D10: CRLF, `0.10`, odd indentation, BOM) — reported, not blocked.
    `problems` is the current validation: listed, non-blocking while
    the total count hasn't grown (constraint 3, amended per D13).
    """

    written: List[str]
    skipped: List[str]
    reformatted: List[str]
    problems: List[Problem]


def _canonical_bytes(data: Any) -> bytes:
    """The bytes save() writes: UTF-8, no BOM, LF, trailing newline.

    ensure_ascii=False keeps text readable; allow_nan=False honors D10
    (non-finite values refuse at write); dict/array order passes
    through untouched — keys are never sorted (constraint 4).
    """
    text = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2)
    return (text + "\n").encode("utf-8")


def _was_canonical(data: bytes) -> bool:
    """Was this file already in exactly our canonical shape? (D10)

    Anything else (CRLF, `0.10`, odd indentation, a BOM) means saving
    reformats beyond the edit — the caller is warned, not blocked.
    """
    try:
        return _canonical_bytes(json.loads(data.decode("utf-8-sig"))) == data
    except (ValueError, UnicodeDecodeError):
        return False  # unparseable/stale bytes being overwritten anyway


def save(
    content: Content,
    path: Optional[Path] = None,
    *,
    state: LoadState,
    dirty: Optional[Iterable[str]] = None,
    overwrite_stale: bool = False,
) -> SaveResult:
    """Stage -> gate -> temp-replace, per constraint 3 / D9 / D10 / D11.

    Raises:
    - ValueError for an unknown file name (caller bug);
    - StaleWriteError when a staged file no longer hashes to
      `state.hashes` — reload, or pass overwrite_stale=True to confirm
      the overwrite (check->replace TOCTOU is accepted; git is the net);
    - ContentError when the save would increase the bundle's total
      problem count, listing every problem verbatim.

    Only files in `dirty` (default: all seven) are ever touched, and
    only those with no problems of their own are written; the rest are
    reported in `skipped`. Each write is a same-directory temp file +
    os.replace; on failure, files already replaced are restored from
    their pre-save bytes — not atomic across files (git is the net).
    """
    directory = Path(path) if path is not None else Path(content.source)
    stems = (
        tuple(CONTENT_FILES) if dirty is None else tuple(dict.fromkeys(dirty))
    )
    unknown = [name for name in stems if name not in CONTENT_FILES]
    if unknown:
        raise ValueError(f"unknown content file(s): {', '.join(unknown)}")

    # Stage: read each staged file's bytes now — the D11 stale check
    # and the compensation copy both come from this single read.
    originals: Dict[str, Optional[bytes]] = {}
    stale: List[str] = []
    for name in stems:
        file_path = directory / f"{name}.json"
        try:
            data = file_path.read_bytes()
        except OSError:
            originals[name] = None
            stale.append(name)  # missing/unreadable = changed since load
            continue
        originals[name] = data
        if hashlib.sha256(data).hexdigest() != state.hashes.get(name):
            stale.append(name)
    if stale and not overwrite_stale:
        raise StaleWriteError(stale)

    # Gate: never increase the bundle's total problem count (would-be
    # disk state: staged files get this in-memory content; unstaged and
    # untouched files keep the load-time problems state.problems counts).
    new_problems = validate_bundle(content)
    if len(new_problems) > len(state.problems):
        raise ContentError(new_problems)
    own_problem = {p.file for p in new_problems if p.file}
    staged = [name for name in stems if f"{name}.json" not in own_problem]
    skipped = [name for name in stems if f"{name}.json" in own_problem]

    payload: Dict[str, bytes] = {}
    reformatted: List[str] = []
    for name in staged:
        payload[name] = _canonical_bytes(getattr(content, name))
        data = originals[name]
        if data is not None and not _was_canonical(data):
            reformatted.append(name)

    replaced: List[str] = []
    try:
        for name in staged:
            target = directory / f"{name}.json"
            tmp = directory / f".{name}.json.tmp"
            with open(tmp, "wb") as handle:  # bytes: no newline translation
                handle.write(payload[name])
            os.replace(tmp, target)
            replaced.append(name)
    except BaseException:
        # D9 compensation: put back the pre-save bytes of everything
        # this call already replaced, then let the failure surface.
        for name in replaced:
            data = originals[name]
            if data is None:
                (directory / f"{name}.json").unlink(missing_ok=True)
            else:
                (directory / f"{name}.json").write_bytes(data)
        for name in stems:
            (directory / f".{name}.json.tmp").unlink(missing_ok=True)
        raise
    return SaveResult(
        written=staged,
        skipped=skipped,
        reformatted=reformatted,
        problems=list(new_problems),
    )




