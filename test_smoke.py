"""Smoke test for game_core + the tkinter day flow. Run: python test_smoke.py"""

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# --- Pin the suite to the frozen fixture BEFORE game_core imports ----------
# game_core loads content/*.json at its own import time. Engine and seeded
# tests must never shift because live content was edited; live content gets
# its own gates below (direct validation + spawned check_live.py).
_ROOT = Path(__file__).resolve().parent
_FIXTURE = _ROOT / "tests" / "fixtures" / "content"
os.environ["DAY_SCHEDULER_CONTENT_DIR"] = str(_FIXTURE)

import content  # noqa: E402
from check_live import run_live_check  # noqa: E402
from game_core import (  # noqa: E402
    ACTION_LABELS,
    ACTION_ORDER,
    ACTION_XP,
    BUILD,
    CONTENT,
    CRAFT,
    EVENT_CHANCE,
    EVENT_XP_FAILURE,
    EVENT_XP_SUCCESS,
    FOOD_ITEM,
    GATHER_FOOD,
    GATHER_WOOD,
    ITEM_NAMES,
    ITEM_ORDER,
    MAX_VITAL,
    PATTERNS,
    RANDOM_EVENTS,
    REST,
    SKILL_NAMES,
    SKILL_XP,
    STAT_NAMES,
    WOOD_ITEM,
    GameEngine,
    RandomEvent,
    format_changes,
    validate_content,
    xp_cost_for,
)

# --- Content tables must be internally consistent --------------------------
problems = validate_content()
assert problems == [], problems
print("Content validation OK")

# --- Fixture pinning proof + env override mechanics -------------------------
assert CONTENT.source == _FIXTURE, CONTENT.source   # game_core read the pin
assert content.content_dir() == _FIXTURE            # env override honored
os.environ["DAY_SCHEDULER_CONTENT_DIR"] = str(_ROOT / "content")
assert content.content_dir() == _ROOT / "content"   # variable is live
os.environ["DAY_SCHEDULER_CONTENT_DIR"] = str(_FIXTURE)  # restore the pin

# --- Fixture goldens: order-sensitive identity (sort_keys tripwire) ---------
# Key/array order in content files feeds planner order and the seeded RNG
# (_pick_event, patterns_for, the fuzz plan pool). If these fire after an
# edit, the JSON was reordered (e.g. sort_keys=True) — restore file order,
# or update these goldens DELIBERATELY together with a fixture re-pin
# (see DEV_GUIDE "Testing workflow").
assert ACTION_ORDER == (GATHER_FOOD, GATHER_WOOD, REST, BUILD, CRAFT)
assert ITEM_ORDER == ("berries", "wood", "herbs", "stone")
assert tuple(PATTERNS) == ("lean_to", "wood_axe")
assert tuple(RANDOM_EVENTS) == (
    "wandering_thoughts", "stray_berry_bush", "howling_wind", "quiet_moment",
)
assert tuple(STAT_NAMES) == ("strength", "defense")
assert tuple(SKILL_NAMES) == (
    "foraging", "woodcutting", "carpentry", "carving",
)
# Balance spot-values: identical to the pre-content literals.
assert (MAX_VITAL, EVENT_CHANCE, ACTION_XP, SKILL_XP) == (100, 0.1, 5, 10)
print("Fixture goldens OK")

# --- Live content validates too (the fixture only pins the engine tests) ----
live_bundle, live_problems = content.try_load_content(_ROOT / "content")
assert live_problems == [], live_problems
assert live_bundle is not None
print("Live content (engine-free) OK")

# --- Loader fails loudly: file+line context, never a silent fallback --------
_tmp = Path(tempfile.mkdtemp(prefix="content_test_"))
try:
    # (a) missing files: no bundle, every file named
    bundle, probs = content.try_load_content(_tmp)
    assert bundle is None and len(probs) == len(content.CONTENT_FILES)
    assert any(p.startswith("items.json:") for p in probs), probs
    # (b) strict load raises, message names the files
    try:
        content.load_content(_tmp)
        raise AssertionError("strict load must raise ContentError")
    except content.ContentError as exc:
        assert "items.json" in str(exc), str(exc)

    for src in _FIXTURE.glob("*.json"):
        shutil.copy(src, _tmp / src.name)

    # (c) malformed JSON: file + line/column, still no bundle
    (_tmp / "actions.json").write_text("{ not json", encoding="utf-8")
    bundle, probs = content.try_load_content(_tmp)
    assert bundle is None and any(
        p.startswith("actions.json: line") for p in probs
    ), probs

    # (d) broken reference: usable bundle + named problem (editor repair path)
    shutil.copy(_FIXTURE / "actions.json", _tmp / "actions.json")
    patterns = json.loads(
        (_tmp / "patterns.json").read_text(encoding="utf-8")
    )
    patterns["lean_to"]["skill"] = "carpentery"  # typo'd reference
    (_tmp / "patterns.json").write_text(
        json.dumps(patterns, indent=2), encoding="utf-8"
    )
    bundle, probs = content.try_load_content(_tmp)
    assert bundle is not None, "parseable content must stay loadable"
    assert any("carpentery" in p for p in probs), probs
    try:
        content.load_content(_tmp)
        raise AssertionError("strict load must reject the bad reference")
    except content.ContentError as exc:
        assert "carpentery" in str(exc), str(exc)

    # (e) typo'd balance key: rejected loudly (would otherwise be ignored)
    shutil.copy(_FIXTURE / "patterns.json", _tmp / "patterns.json")
    balance = json.loads(
        (_tmp / "balance.json").read_text(encoding="utf-8")
    )
    balance["EVENT_CHANE"] = 0.1  # typo
    (_tmp / "balance.json").write_text(
        json.dumps(balance, indent=2), encoding="utf-8"
    )
    bundle, probs = content.try_load_content(_tmp)
    assert any("EVENT_CHANE" in p for p in probs), probs

    # (f) non-slug item id: named file + exact id + the rule, both loaders
    shutil.copy(_FIXTURE / "balance.json", _tmp / "balance.json")
    items = json.loads((_tmp / "items.json").read_text(encoding="utf-8"))
    items[0]["id"] = "Berries"  # display text crept back into the id
    (_tmp / "items.json").write_text(
        json.dumps(items, indent=2), encoding="utf-8"
    )
    bundle, probs = content.try_load_content(_tmp)
    assert bundle is not None, "parseable content must stay loadable"
    assert any(
        p.startswith("items.json: 'Berries'") and "slug" in p for p in probs
    ), probs
    try:
        content.load_content(_tmp)
        raise AssertionError("strict load must reject the non-slug id")
    except content.ContentError as exc:
        assert "'Berries'" in str(exc) and "slug" in str(exc), str(exc)

    # (g) unknown action behavior: named file + id + the vocabulary
    shutil.copy(_FIXTURE / "items.json", _tmp / "items.json")
    actions = json.loads((_tmp / "actions.json").read_text(encoding="utf-8"))
    actions[0]["behavior"] = "gather"  # not in BEHAVIOR_HANDLERS
    (_tmp / "actions.json").write_text(
        json.dumps(actions, indent=2), encoding="utf-8"
    )
    bundle, probs = content.try_load_content(_tmp)
    assert bundle is not None, "parseable content must stay loadable"
    assert any(
        p.startswith("actions.json: 'gather_food'") and "behavior" in p
        for p in probs
    ), probs

    # (h) broken gather block: named fields, ranges, templates, tool refs
    shutil.copy(_FIXTURE / "actions.json", _tmp / "actions.json")
    actions = json.loads((_tmp / "actions.json").read_text(encoding="utf-8"))
    gather = actions[0]["gather"]
    gather["yield"] = [5, 2]                  # min > max (randint crash)
    gather["tool_bonus"] = ["silver_sword", 2]  # not a tool pattern
    gather["success"] = "you dig {amount holes"  # broken template
    (_tmp / "actions.json").write_text(
        json.dumps(actions, indent=2), encoding="utf-8"
    )
    bundle, probs = content.try_load_content(_tmp)
    assert bundle is not None, "parseable content must stay loadable"
    gprefix = "actions.json: 'gather_food': 'gather'"
    assert any(p.startswith(gprefix) for p in probs), probs
    assert any("'yield'" in p for p in probs), probs
    assert any("'tool_bonus'" in p for p in probs), probs
    assert any("'success'" in p and "template" in p for p in probs), probs
    # 2a-0 structured problems: file/record/field parse off the shape
    typed = next(p for p in probs if p.startswith(gprefix))
    assert isinstance(typed, content.Problem)
    assert typed.file == "actions.json", typed.file
    assert typed.record_id == "gather_food", typed.record_id
    assert typed.field == "gather", typed.field

    # (i) duplicate JSON key: refuses the file, names file + key (D8)
    shutil.copy(_FIXTURE / "actions.json", _tmp / "actions.json")
    shutil.copy(_FIXTURE / "items.json", _tmp / "items.json")
    text = (_tmp / "items.json").read_text(encoding="utf-8")
    assert '"name": "Berries",' in text, "fixture shape changed"
    (_tmp / "items.json").write_text(
        text.replace(
            '"name": "Berries",',
            '"name": "Berries",\n    "id": "berries",',
            1,
        ),
        encoding="utf-8",
    )
    bundle, probs = content.try_load_content(_tmp)
    assert bundle is None, "duplicate keys must refuse the file"
    assert any(
        p.startswith("items.json: duplicate key 'id'") for p in probs
    ), probs

    # (j) non-finite numbers: NaN is not JSON — refuses, names file+value
    shutil.copy(_FIXTURE / "items.json", _tmp / "items.json")
    balance = json.loads((_tmp / "balance.json").read_text(encoding="utf-8"))
    balance["EVENT_CHANCE"] = float("nan")
    (_tmp / "balance.json").write_text(
        json.dumps(balance, indent=2), encoding="utf-8"
    )
    bundle, probs = content.try_load_content(_tmp)
    assert bundle is None, "NaN must refuse the file"
    assert any(
        p.startswith("balance.json: non-finite number 'NaN'") for p in probs
    ), probs

    # (j continued) overflow spelling 1e400 → inf: parse_float refuses
    # the same class (dumps would spell it "Infinity" — wrong hook).
    shutil.copy(_FIXTURE / "balance.json", _tmp / "balance.json")
    btext = (_tmp / "balance.json").read_text(encoding="utf-8")
    assert '"EVENT_CHANCE": 0.1' in btext, "fixture shape changed"
    (_tmp / "balance.json").write_text(
        btext.replace('"EVENT_CHANCE": 0.1', '"EVENT_CHANCE": 1e400', 1),
        encoding="utf-8",
    )
    bundle, probs = content.try_load_content(_tmp)
    assert bundle is None, "overflow floats must refuse the file"
    assert any(
        p.startswith("balance.json: non-finite number '1e400'") for p in probs
    ), probs

    # (k) UTF-8 BOM: tolerated on read (utf-8-sig) — loads clean (D10)
    shutil.copy(_FIXTURE / "balance.json", _tmp / "balance.json")
    items_path = _tmp / "items.json"
    items_path.write_bytes(b"\xef\xbb\xbf" + items_path.read_bytes())
    bundle, probs = content.try_load_content(_tmp)
    assert bundle is not None and probs == [], (bundle, probs)
finally:
    shutil.rmtree(_tmp, ignore_errors=True)
print("Loader error behavior OK")

# --- Schema drift: SCHEMA must mirror the validator (D1) -------------------
# Coverage: every key of every live record is declared in SCHEMA.
def _records_of(fname: str, bundle) -> list:
    data = getattr(bundle, fname)
    if fname == "balance":
        return [data]
    return data if isinstance(data, list) else list(data.values())


for _fname, _spec in content.SCHEMA.items():
    for _rec in _records_of(_fname, live_bundle):
        _extra = set(_rec) - set(_spec["fields"])
        assert not _extra, (_fname, _extra)

# Wrong-type: every declared field rejects a wrong-typed value.
# (Nested gather sub-fields are covered individually by loader case (h).)
_WRONG = {  # scalar -> what a wrong-typed value looks like
    "slug": 7, "string": 7, "int": "seven", "bool": 7, "number": "seven",
}


def _wrong_value(spec):
    """A value no type in the vocabulary should accept."""
    if isinstance(spec, str):
        return _WRONG.get(spec, 7)
    if spec[0] in ("opt", "nullable"):
        return _wrong_value(spec[1])  # wrong for the INNER type (opt-int: "seven")
    if spec[0] == "enum":
        return "not-an-option"
    return 7  # ref/pair/list/dict_int/nested all reject 7


def _mutated(fname: str, rec: dict) -> dict:
    """The bundle dict with fname's first record replaced by rec."""
    mut = {f: getattr(live_bundle, f) for f in content.CONTENT_FILES}
    if isinstance(mut[fname], list):
        mut[fname] = [rec] + list(mut[fname])[1:]
    elif fname == "balance":
        mut[fname] = rec
    else:  # dict-keyed: replace the value under the first key
        first = next(iter(mut[fname]))
        rest = {k: v for k, v in mut[fname].items() if k != first}
        mut[fname] = {first: rec, **rest}
    return mut


for _fname, _spec in content.SCHEMA.items():
    _rec = _records_of(_fname, live_bundle)[0]
    for _field, _fspec in _spec["fields"].items():
        _bad = dict(_rec)
        _bad[_field] = _wrong_value(_fspec)
        _probs = content.validate_bundle(
            content.Content(source=live_bundle.source,
                            **_mutated(_fname, _bad))
        )
        assert any(p.file == f"{_fname}.json" for p in _probs), (
            _fname, _field, _probs)

# Required deletion: removing a required field is rejected
# (opt/nullable fields are exempt — absence must stay legal).
for _fname, _spec in content.SCHEMA.items():
    _rec = _records_of(_fname, live_bundle)[0]
    for _field, _fspec in _spec["fields"].items():
        if isinstance(_fspec, tuple) and _fspec[0] in ("opt", "nullable"):
            continue
        _gone = {k: v for k, v in _rec.items() if k != _field}
        _probs = content.validate_bundle(
            content.Content(source=live_bundle.source,
                            **_mutated(_fname, _gone))
        )
        assert any(p.file == f"{_fname}.json" for p in _probs), (
            _fname, _field, _probs)
print("Schema drift OK")

# --- Startup gate: the exact function main.py runs before opening ----------
gate_problems = run_live_check()
assert gate_problems == [], gate_problems
print("Startup gate OK")

# --- Live engine-aware gate: spawn check_live.py (fresh interpreter) --------
# The child forces the LIVE content path itself, overriding this file's
# fixture pin — so this asserts live content passes engine validation
# AND survives seeded play, not just the fixture.
_spawn = subprocess.run(
    [sys.executable, str(_ROOT / "check_live.py")],
    capture_output=True,
    text=True,
    cwd=str(_ROOT),
)
assert _spawn.returncode == 0, (
    "check_live.py failed:\n" + _spawn.stdout + _spawn.stderr
)
print("check_live.py (live content) OK")


# --- Engine: peaceful day -------------------------------------------------
e = GameEngine(seed=42)
assert e.day == 1 and e.health == 100 and e.inventory[FOOD_ITEM] == 2

e.EVENT_CHANCE = 0.0
e.ACTION_DIFFICULTY = 0              # auto-succeed: asserts guaranteed yields
e.begin_day()
results = [e.run_slot(i) for i in range(3)]
assert all(not r.event_triggered for r in results)

gf = results[0]
assert gf.action_id == "gather_food"
assert any(lbl == "Berries" and 2 <= d <= 4 for lbl, d in gf.changes), gf.changes
gw = results[1]
assert any(lbl == "Wood" and 1 <= d <= 3 for lbl, d in gw.changes), gw.changes
rest = results[2]
assert ("Berries", -1) in rest.changes, rest.changes   # rest ate 1 food
assert any(lbl == "Energy" and d > 0 for lbl, d in rest.changes), rest.changes

summary = e.build_summary()
assert summary["day"] == 1 and len(summary["results"]) == 3
print("Day 1 totals:", format_changes(summary["totals"]))

berries_before = e.inventory[FOOD_ITEM]
report = e.complete_day()
assert e.day == 2 and report.new_day == 2
assert e.inventory[FOOD_ITEM] == berries_before - 1  # sleep ate 1 food
print("Sleep:", report.note, "->", format_changes(report.changes))

# --- Engine: slot ordering is enforced ------------------------------------
e.begin_day()
e.run_slot(0)
try:
    e.run_slot(2)
    raise AssertionError("slots must run in order")
except RuntimeError:
    pass
e.run_slot(1)
e.run_slot(2)
e.complete_day()

# --- Engine: forced events -------------------------------------------------
e.EVENT_CHANCE = 1.0
e.begin_day()
results = [e.run_slot(i) for i in range(3)]
assert all(r.event_triggered for r in results)
e.complete_day()
assert e.day == 4  # day 1 + ordering-test day + forced-event day

# --- Engine: rest without food gives smaller restore -----------------------
e2 = GameEngine(seed=7)
e2.inventory[FOOD_ITEM] = 0
e2.health = 50   # below cap so rest/sleep restores are observable
e2.energy = 50
for i in range(3):
    e2.set_slot_action(i, "rest")
e2.begin_day()
poor_rest = e2.run_slot(0)
assert ("Energy", 10) in poor_rest.changes, poor_rest.changes
assert ("Health", 5) in poor_rest.changes, poor_rest.changes
e2.run_slot(1)
e2.run_slot(2)
poor_sleep = e2.complete_day()
assert ("Energy", 10) in poor_sleep.changes, poor_sleep.changes
# --- Engine: abort_day recovers a failed day ------------------------------
e.begin_day()
e.run_slot(0)
e.abort_day()                       # simulates an exception mid-day
assert not e.day_in_progress
e.begin_day()                       # would raise "Day already in progress"
e.run_slot(0)
e.run_slot(1)
e.run_slot(2)
e.complete_day()

# --- Engine: death is flagged at the end of the day -----------------------
dead = GameEngine(seed=3)
dead.begin_day()
for i in range(3):
    dead.run_slot(i)
dead.health = -50                   # simulate fatal damage during the day
dead.inventory[FOOD_ITEM] = 0       # no food: sleep cannot revive
death = dead.complete_day()
assert death.game_over and "wounds" in death.game_over_reason
assert dead.game_over and dead.day == 1  # the dead do not advance

starve = GameEngine(seed=4)
starve.begin_day()
for i in range(3):
    starve.run_slot(i)
starve.hunger = 95                  # sleep adds +10, no food to offset
starve.inventory[FOOD_ITEM] = 0
assert starve.complete_day().game_over_reason == "You starved."

# --- Engine: save/load round trip replays identical rolls -----------------
a = GameEngine(seed=11)
a.buildings["lean_to"] = 1            # exercise asset persistence too
a.projects["wood_axe"] = 1
a.tools["wood_axe"] = 2
b = GameEngine.from_dict(json.loads(json.dumps(a.to_dict())))  # via JSON
a.begin_day()
b.begin_day()
assert [a.run_slot(i).changes for i in range(3)] == [
    b.run_slot(i).changes for i in range(3)
]
assert b.day == a.day and b.inventory == a.inventory
assert b.slot_actions == a.slot_actions
assert b.stats == a.stats and b.skills == a.skills
assert b.xp_next == a.xp_next
assert b.buildings == a.buildings and b.tools == a.tools
assert b.projects == a.projects

# --- XP: actions train player + skill; level costs scale -------------------
xp_eng = GameEngine(seed=6)
xp_eng.EVENT_CHANCE = 0.0
xp_eng.skills["foraging"].xp = xp_cost_for(1) - 5   # 95/100
xp_eng.begin_day()
trained = xp_eng.run_slot(0)                        # default: Gather Food
assert xp_eng.skills["foraging"].level == 2
assert xp_eng.skills["foraging"].xp == 5            # 95 + 10 - 100
assert xp_cost_for(2) == 120                        # +20 per level
assert "reached level 2" in trained.note
assert ("XP", ACTION_XP) in trained.changes
assert any(lbl == "Foraging XP" for lbl, _ in trained.changes)

# --- Events: stats/skills feed checks; checks feed stats/skills ------------
ev = GameEngine(seed=8)
ev.EVENT_CHANCE = 1.0
# Single wildcard check-event keeps these mechanics assertions deterministic.
ev.RANDOM_EVENTS = {
    "generic": RandomEvent(
        id="generic", text="A test of mettle.", actions=(), check=True,
    ),
}
expected_bonus = ev.skills["foraging"].level + ev.stats["strength"].level
ev.begin_day()
res = ev.run_slot(0)                                # default: Gather Food
assert res.event is not None
assert "Foraging" in res.event.check and "Strength" in res.event.check
assert res.event.bonus == expected_bonus
assert 1 <= res.event.die <= 20
assert res.event.roll == res.event.die + res.event.bonus
if res.event.success:
    assert ("Foraging XP", EVENT_XP_SUCCESS) in res.event.changes
    assert ("Strength XP", EVENT_XP_SUCCESS) in res.event.changes
    expected_foraging = SKILL_XP + EVENT_XP_SUCCESS
else:
    assert ev.health == 95                          # 100 - 5 penalty
    assert ("Health", -5) in res.event.changes
    expected_foraging = SKILL_XP + EVENT_XP_FAILURE
# Action XP + event XP land in the slot totals exactly once each.
assert sum(d for lbl, d in res.changes if lbl == "Foraging XP") == \
    expected_foraging

# rest has no governing skill: flavor-only event, no check, no effects
ev2 = GameEngine(seed=9)
ev2.EVENT_CHANCE = 1.0
ev2.set_slot_action(0, REST)
ev2.begin_day()
rest_res = ev2.run_slot(0)
assert rest_res.event is not None and rest_res.event.check == ""
assert rest_res.event.changes == []

# --- Skilled action failure still grants XP --------------------------------
fail_eng = GameEngine(seed=31)
fail_eng.EVENT_CHANCE = 0.0
fail_eng.ACTION_DIFFICULTY = 999          # auto-fail every check
fail_eng.begin_day()
miss = fail_eng.run_slot(0)               # default: Gather Food
assert miss.success is False
assert not any(lbl == ITEM_NAMES[FOOD_ITEM] for lbl, _ in miss.changes)  # no yield
assert ("XP", ACTION_XP) in miss.changes  # failure still teaches
assert any(lbl == "Foraging XP" for lbl, _ in miss.changes)

# --- Build: a failed attempt still eats the materials ----------------------
bld = GameEngine(seed=32)
bld.EVENT_CHANCE = 0.0
bld.ACTION_DIFFICULTY = 999
bld.inventory[WOOD_ITEM] = 5
bld.set_slot_action(0, BUILD)
bld.begin_day()
attempt = bld.run_slot(0, pattern_provider=lambda _kind: "lean_to")
assert attempt.success is False
assert bld.inventory[WOOD_ITEM] == 0              # materials wasted
assert any(lbl == "Carpentry XP" for lbl, _ in attempt.changes)
assert "fails" in attempt.note
assert bld.projects.get("lean_to") is None and not bld.buildings

# no materials -> nothing attempted, nothing learned
bld2 = GameEngine(seed=33)
bld2.EVENT_CHANCE = 0.0
bld2.set_slot_action(0, BUILD)
bld2.begin_day()
blocked_try = bld2.run_slot(0, pattern_provider=lambda _kind: "lean_to")
assert "materials" in blocked_try.note
assert bld2.inventory[WOOD_ITEM] == 0
assert not any(lbl == "Carpentry XP" for lbl, _ in blocked_try.changes)

# skill requirement blocks the attempt without consuming anything
req = GameEngine(seed=36)
req.EVENT_CHANCE = 0.0
req.inventory[WOOD_ITEM] = 5
req.skills["carpentry"].level = 0
req.set_slot_action(0, BUILD)
req.begin_day()
blocked = req.run_slot(0, pattern_provider=lambda _kind: "lean_to")
assert req.inventory[WOOD_ITEM] == 5
assert "Carpentry" in blocked.note
assert not any(lbl == "Carpentry XP" for lbl, _ in blocked.changes)

# --- Build success completes the Lean to; bonus feeds recovery -------------
bok = GameEngine(seed=34)
bok.EVENT_CHANCE = 0.0
bok.ACTION_DIFFICULTY = 0                  # auto-succeed
bok.inventory[WOOD_ITEM] = 5
bok.set_slot_action(0, BUILD)
bok.set_slot_action(1, REST)
bok.begin_day()
finished = bok.run_slot(0, pattern_provider=lambda _kind: "lean_to")
assert finished.success is True
assert bok.buildings.get("lean_to") == 1 and bok.projects == {}
assert ("Lean to", 1) in finished.changes
assert "Keeps the weather out" in finished.note   # description surfaces
assert "lean_to" not in [p.id for p in bok.patterns_for(BUILD)]  # owned
bok.health, bok.energy = 50, 50
rested = bok.run_slot(1)                   # rest, 2 berries on hand
assert ("Health", 16) in rested.changes    # 15 * 1.1 -> 16
assert ("Energy", 27) in rested.changes    # 25 * 1.1 -> 27

# --- Wood Axe: craft it, then +1 wood per gather ---------------------------
ax = GameEngine(seed=35)
ax.EVENT_CHANCE = 0.0
ax.ACTION_DIFFICULTY = 0
ax.inventory[WOOD_ITEM] = 3
ax.set_slot_action(0, CRAFT)
ax.set_slot_action(1, GATHER_WOOD)
ax.begin_day()
made = ax.run_slot(0, pattern_provider=lambda _kind: "wood_axe")
assert made.success and ax.tools.get("wood_axe") == 1
assert ax.inventory[WOOD_ITEM] == 0
chop = ax.run_slot(1)
gain = dict(chop.changes).get("Wood")
assert gain is not None and 2 <= gain <= 4       # 1-3 base + 1 axe
# tools stay craftable (extras for later selling); finished buildings drop out
craftable = [p.id for p in ax.patterns_for(CRAFT)]
assert "wood_axe" in craftable
buildable = [p.id for p in ax.patterns_for(BUILD)]
assert "lean_to" in buildable

# --- Tool copies are allowed, but bonuses only apply once ------------------
dup = GameEngine(seed=38)
dup.EVENT_CHANCE = 0.0
dup.ACTION_DIFFICULTY = 0
dup.inventory[WOOD_ITEM] = 6
dup.set_slot_action(0, CRAFT)
dup.set_slot_action(1, CRAFT)
dup.set_slot_action(2, GATHER_WOOD)
dup.begin_day()
dup.run_slot(0, pattern_provider=lambda _kind: "wood_axe")
dup.run_slot(1, pattern_provider=lambda _kind: "wood_axe")
assert dup.tools.get("wood_axe") == 2
chopped_twice = dup.run_slot(2)
twice_gain = dict(chopped_twice.changes).get("Wood")
assert twice_gain is not None and 2 <= twice_gain <= 4  # +1 once, not +2

# --- Skipping a build slot: nothing spent, nothing taught -----------------
sk = GameEngine(seed=37)
sk.EVENT_CHANCE = 0.0
sk.set_slot_action(0, BUILD)
sk.begin_day()
skipped = sk.run_slot(0)                    # no provider at all
assert skipped.changes == []
assert "quietly" in skipped.note

# --- Named events: action filtering + flavor-only events -------------------
named = GameEngine(seed=44)
named.EVENT_CHANCE = 1.0
named.RANDOM_EVENTS = {
    "chatter": RandomEvent(
        id="chatter", text="Birds argue loudly overhead.",
        actions=(GATHER_FOOD,), check=False,
    ),
}
named.begin_day()
flavor = named.run_slot(0)                       # default: Gather Food
assert flavor.event is not None
assert flavor.event.event_id == "chatter"
assert flavor.event.check == "" and flavor.event.changes == []
assert "Birds argue loudly" in flavor.note
named.abort_day()
# check-events still run the mechanics, with the text folded in
named.RANDOM_EVENTS = {
    "generic": RandomEvent(
        id="generic", text="A test of mettle.", actions=(), check=True,
    ),
}
named.begin_day()
checked = named.run_slot(0)
assert checked.event.event_id == "generic"
assert checked.event.check != ""                 # gather food has contributors
assert "A test of mettle" in checked.event.note
named.abort_day()

# --- Stat XP hook: actions can train stats (ACTION_STAT_XP) ----------------
hook = GameEngine(seed=45)
hook.EVENT_CHANCE = 0.0
hook.ACTION_STAT_XP = {GATHER_FOOD: ("strength", 4)}
hook.begin_day()
hooked = hook.run_slot(0)
assert ("Strength XP", 4) in hooked.changes

# --- Fuzz: 30 days of random plans, invariants must hold -------------------
fuzz = GameEngine(seed=99)
plan = random.Random(1234)
action_pool = list(ACTION_LABELS)
died = False
for _ in range(30):
    if fuzz.game_over:
        died = True
        break
    for i in range(3):
        fuzz.set_slot_action(i, plan.choice(action_pool))
    fuzz.begin_day()
    for i in range(3):
        action = fuzz.slot_actions[i]
        provider = None
        if action in (BUILD, CRAFT):
            options = [p.id for p in fuzz.patterns_for(action)]
            pick = plan.choice(options) if options else None
            provider = (lambda chosen: (lambda _kind: chosen))(pick)
        fuzz.run_slot(i, pattern_provider=provider)
        # --- invariants after every slot ---
        assert 0 <= fuzz.health <= fuzz.MAX_VITAL
        assert 0 <= fuzz.hunger <= fuzz.MAX_VITAL
        assert 0 <= fuzz.energy <= fuzz.MAX_VITAL
        assert fuzz.xp >= 0 and fuzz.level >= 1
        assert all(count >= 0 for count in fuzz.inventory.values())
        assert all(count >= 0 for count in fuzz.tools.values())
        assert all(count >= 0 for count in fuzz.buildings.values())
        assert all(p.xp >= 0 and p.level >= 1 for p in fuzz.stats.values())
        assert all(p.xp >= 0 and p.level >= 1 for p in fuzz.skills.values())
        for pid, prog in fuzz.projects.items():
            assert 0 < prog < PATTERNS[pid].work
    fuzz.complete_day()
    assert 0 <= fuzz.hunger <= fuzz.MAX_VITAL
assert died or fuzz.day >= 31   # survived all 30 days, or died trying

# --- Death is reachable: starve with failing gathers and no rest -----------
doom = GameEngine(seed=51)
doom.EVENT_CHANCE = 0.0
doom.ACTION_DIFFICULTY = 999        # gathers always fail -> no food ever
for i in range(3):
    doom.set_slot_action(i, GATHER_WOOD)
days = 0
while not doom.game_over and days < 20:
    doom.begin_day()
    for i in range(3):
        doom.run_slot(i)
    doom.complete_day()
    days += 1
assert doom.game_over and "starved" in doom.game_over_reason

print("Engine tests OK")

# --- GUI: full day flow with auto-clicked dialogs --------------------------
import tkinter as tk  # noqa: E402

from main import DaySchedulerApp  # noqa: E402

root = tk.Tk()
app = DaySchedulerApp(root)
root.update()

def find_buttons(widget):
    found = [widget] if isinstance(widget, tk.Button) else []
    for child in widget.winfo_children():
        found.extend(find_buttons(child))
    return found

auto = {"active": True, "clicked": []}

def auto_click():
    if not auto["active"]:
        return
    try:
        windows = root.winfo_children()
    except tk.TclError:
        return
    for win in windows:
        if isinstance(win, tk.Toplevel):
            buttons = find_buttons(win)
            if buttons:
                auto["clicked"].append(buttons[0]["text"])
                buttons[0].invoke()
                break
    root.after(50, auto_click)

# Plan a Build slot (pattern picker) and Gather Food (foraging training)
app.engine.set_slot_action(0, BUILD)
app.slot_combos[0].set("Build")
app.engine.set_slot_action(1, GATHER_FOOD)
app.slot_combos[1].set("Gather Food")
app.engine.inventory["wood"] = 10

app.engine.EVENT_CHANCE = 1.0   # force event popups to appear
root.after(100, auto_click)
app.execute_day()               # blocks until every dialog is handled
auto["active"] = False

assert app.engine.day == 2, app.engine.day
assert "Advance" in auto["clicked"], auto["clicked"]
assert "Accept" in auto["clicked"], auto["clicked"]
assert "Start" in auto["clicked"], auto["clicked"]      # picker appeared
assert str(app.execute_btn["state"]) == "normal"
assert str(app.slot_combos[0]["state"]) == "readonly"
assert app.engine.inventory[WOOD_ITEM] == 5            # Lean to attempt cost
assert app.skill_vars["carpentry"][1].get() != "0/100"  # new skill trains
# BUILDINGS lists only finished buildings (fills in as they complete)
first_row = app.buildings_list.winfo_children()[0]
if app.engine.buildings.get("lean_to"):
    assert first_row.cget("text") == "Lean to"
else:
    assert "None" in first_row.cget("text")
root.update()

# Energy is labeled and lives in the top bar; stat/skill rows show xp/next
assert app.energy_var.get().startswith("Energy")
assert "/" in app.player_xp_var.get()
assert all("/" in xp.get() for _lv, xp in app.stat_vars.values())
assert all("/" in xp.get() for _lv, xp in app.skill_vars.values())
assert app.skill_vars["foraging"][1].get() != "0/100"  # trained on day 1
assert app.left_canvas.cget("scrollregion")            # panel is scrollable
print("Top bar :", app.day_var.get(), "|", app.health_var.get(), "|",
      app.energy_var.get(), "|", app.hunger_var.get(), "|",
      app.gold_var.get())
print("Skills  :", {k: (lv.get(), xp.get())
                    for k, (lv, xp) in app.skill_vars.items()})
print("Inventory:", {ITEM_NAMES.get(k, k): v.get()
                     for k, v in app.inventory_vars.items()})
print("Status  :", app.status_var.get())

# --- GUI: game-over screen locks the planner; Begin Anew restarts ----------
app.engine.game_over = True
app.engine.game_over_reason = "You fell in battle."
app.execute_day()                              # must refuse to start
assert not app.engine.day_in_progress

auto["active"] = True
auto["clicked"].clear()
root.after(100, auto_click)
app._show_game_over()
auto["active"] = False

assert "Begin Anew" in auto["clicked"], auto["clicked"]
assert app.engine.game_over is False and app.engine.day == 1
assert str(app.slot_combos[0]["state"]) == "readonly"
assert str(app.execute_btn["state"]) == "normal"
assert str(app.save_btn["state"]) == "normal"
root.update()

root.destroy()
print("GUI smoke test OK")

# --- GUI smoke: the read-only viewer (fresh interpreter; skips headless) ----
_spawn = subprocess.run(
    [sys.executable, str(_ROOT / "test_editor_gui.py")],
    capture_output=True,
    text=True,
    cwd=str(_ROOT),
)
assert _spawn.returncode == 0, (
    "test_editor_gui.py failed:\n" + _spawn.stdout + _spawn.stderr
)
print("test_editor_gui.py OK")
