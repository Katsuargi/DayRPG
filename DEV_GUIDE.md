# Day Scheduler RPG — Developer Guide

A practical guide to extending the game: adding actions, stats, skills,
patterns (build/craft), and tuning balance. Written for a JavaScript
developer who hasn't used Python — see the crash course below first.

## Big picture

The code, the data, and the checks:

| File | Role | Rule |
|------|------|------|
| `content/*.json` | **All game content**: items, skills, stats, actions, patterns, events, balance | The single source of truth — edit these to add or rebalance content. Never write them with sorted keys (order feeds the planner and the seeded RNG). |
| `content.py` | Loads and validates those files; shared by game, tests, and (later) the content editor | No game logic, no UI imports. Failures name file + field. |
| `game_core.py` | The game: state, rules, handlers | **No UI imports, ever.** It must stay runnable headless (that's what the tests do). Loads content strictly at import — a broken file fails loudly, no fallback. |
| `main.py` | tkinter interface: renders state, shows dialogs | Never put game rules here — only display and "ask the player" flows. |
| `check_live.py` | Content gate: validates the LIVE content, then plays a few seeded days | `python check_live.py` — also run automatically by `test_smoke.py` and at game startup. |
| `test_smoke.py` | Automated checks: content gates, engine, GUI flow | Run after every change: `python test_smoke.py`. Engine tests pin content to `tests/fixtures/content/`. |

Run the game with `python main.py` from this folder.

### A day, end to end

1. You plan 3 slots (Morning/Midday/Evening) in the dropdowns.
2. `Execute Day` → `DaySchedulerApp.execute_day()` loops the slots and calls
   `GameEngine.run_slot(index, ...)` for each, in order.
3. Inside `run_slot`:
   - 10% event roll (`EVENT_CHANCE`).
   - Build/Craft slots call the GUI's pattern picker (via `pattern_provider`).
   - The action applies (`_apply_action` / `_apply_build_craft`): items and
     vitals change, a skill check may fail, XP is granted.
   - If an event rolled, `_resolve_event` runs a stat/skill check and feeds
     XP (and maybe a health hit) back.
4. GUI shows a summary dialog; Accept → `complete_day()` → sleep eats food,
   applies recovery (with building bonuses), checks for death, next day.

Everything a slot changes is captured two ways: a **snapshot diff**
(items + the vitals listed in `STAT_LABELS`) and **explicit XP changes**
from `add_xp`. Those combine into `result.changes`, which powers the
planner labels, the summary, and the totals line.

## Python crash course (for JS devs)

You'll mostly read simple code, but these differences bite:

- **Indentation replaces braces.** Blocks are `4 spaces`. No `;`, no `{}`.
- **`self` ≈ `this`.** First parameter of every class method.
  `def _apply_rest(self, _action_id):` is called as
  `engine._apply_rest("rest")`.
- **`None` ≈ `null`.** `True`/`False` capitalized. ⚠ Truthiness is **not**
  like JS: Python treats `0`, `""`, `None`, **and empty `{}` / `[]` / `()`**
  as falsy — in JS empty objects and arrays are *truthy*. The code leans
  on Python's rule: `if self.inventory.get("wood_axe"):` means "owns at
  least one" (missing key → `None`, count 0 → falsy).
- **dict `{}` ≈ JS object/Map.** `self.inventory.get("wood", 0)` is
  `obj.wood ?? 0`. `.get()` never throws; it returns the default.
- **tuple `()` ≈ frozen array.** Used for fixed lists like `SLOT_NAMES`.
- **f-strings:** `` f"you found {amount} berries." `` ≈ `` `you found ${amount} berries.` ``
- **Type hints** (`amount: int`, `-> bool`) are decoration for readers —
  Python ignores them at runtime. Safe to copy-paste and adapt. **One
  exception:** inside a `@dataclass`, the annotations *are* the fields —
  a member added without a type hint won't exist as a field. Always
  annotate dataclass members.
- **dataclasses** auto-generate the constructor: the `Pattern` class just
  lists fields; `Pattern(id="lean_to", name="Lean to", ...)` builds one.
- **`//` is integer division**, `/` keeps decimals. `int(x)` truncates.
- Everything is mutable by default; there's no `const`.

Where JS has `class Foo { constructor(){...} }`, Python has:

```python
class Foo:
    def __init__(self, bar: int) -> None:
        self.bar = bar
```

## Feature map — where things live

Content lives in `content/*.json`; `game_core.py` derives its tables from
it at import. The derived names in the middle column still exist — they
just aren't hand-written anymore.

| Feature | Edit here | Derived name / logic |
|---------|-----------|----------------------|
| Action ids, labels, planner order | `content/actions.json` (array order) | `ACTION_LABELS`, `ACTION_ORDER` → dropdowns in `main.py` |
| Governing skill per action | `actions.json` → `skill` field | `ACTION_SKILL` → XP grant inside `run_slot` |
| Event check contributors | `actions.json` → `checks` field | `ACTION_CHECKS` → `_resolve_event` |
| Action stat XP | `actions.json` → `stat_xp` field | `ACTION_STAT_XP` → XP block in `run_slot` |
| Stat/skill names, start levels, tooltips | `content/stats.json`, `content/skills.json` | `STAT_NAMES`, `SKILL_NAMES`, `GameEngine.__init__` |
| Vitals shown in change lists | (code — vitals are engine attributes) | `STAT_LABELS` → `_snapshot` / `_diff` |
| Action dispatch | `content/actions.json` (`behavior` field) | `ACTION_BEHAVIOR` → `_apply_<behavior>` in `_apply_action` / `run_slot` |
| Action behavior + yields | `gather_item` params in the `gather` block of `actions.json` | `_apply_gather_item`, `_apply_rest`, `_apply_sleep` |
| Skilled-action difficulty | `content/balance.json` | `ACTION_DIFFICULTY` → `_skill_check`; per-record `difficulty` overrides (gather block, pattern, event); `difficulty_target` on an action aims its check at a stat or skill |
| Build/craft blueprints | `content/patterns.json` | `PATTERNS` (`Pattern` dataclass) → `_apply_build_craft`, `patterns_for` |
| Building/tool effects | effect *text* in `patterns.json`; effect *math* in code | `_recovery` (Lean to); tool bonuses live on the tool's **item** (`items.json` → `tool_bonus`) and are scanned by `_apply_gather_item` |
| XP costs & level-ups | `balance.json` → `XP_TO_NEXT`, `XP_COST_STEP` | `xp_cost_for`, `add_xp` |
| Death | (code) | `_check_game_over` (end of day only) |
| Random events | `content/events.json` | `RANDOM_EVENTS` (`RandomEvent` dataclass) → `_pick_event` / `_resolve_event` |
| Balance numbers (costs, yields, DCs, chance) | `content/balance.json` | bound at the top of `game_core.py` |
| Save/load | (code — saves engine state, never content) | `to_dict` / `from_dict` |
| UI tooltips | `tooltip` fields in items/skills/stats.json | `*_TOOLTIPS` maps (game_core) + `Tooltip` class in `main.py` |

## Balance knobs (placeholder numbers)

All tunable numbers live in **`content/balance.json`** — keys are the
constant names (`MAX_VITAL`, `EVENT_DIFFICULTY`, `GATHER_ENERGY_COST`, …).
`game_core.py` binds each key to the same-named constant at the top, so
the tables below still describe the code you'll read — but the *values*
are edited in the JSON:

| Constant | Value | What it does |
|----------|-------|--------------|
| `MAX_VITAL` | 100 | Cap for health/energy/hunger. The GUI reads it too. |
| `XP_TO_NEXT` | 100 | XP needed for level 1→2. |
| `XP_COST_STEP` | 20 | Extra XP per further level (100, 120, 140…). Formula: `xp_cost_for(level)`. |
| `ACTION_XP` | 5 | Player XP per attempt — granted even on failure. |
| `SKILL_XP` | 10 | Skill XP per attempt. |
| `ACTION_DIFFICULTY` | 8 | DC for ordinary skill checks: d20 + level ≥ DC. |
| `EVENT_CHANCE` | 0.10 | Per-slot random event chance (class attr on `GameEngine` — tests override it per instance). |
| `EVENT_DIFFICULTY` | 10 | DC for event checks. |
| `CHECK_DIE` | 20 | Die size for all checks. |
| `EVENT_XP_SUCCESS` / `EVENT_XP_FAILURE` | 12 / 6 | XP per event contributor. |
| `EVENT_FAILURE_HEALTH` | -5 | Health lost on a failed event check. |

Every number from `content/balance.json` shows up as a same-named module
constant (`MAX_VITAL = CONTENT.balance["MAX_VITAL"]`), so grep still
finds it and the tables below keep matching the code. **Adding a new
balance number takes three touches:** the JSON key, the same key in
`content.py`'s `BALANCE_KEYS`, and one binding line in `game_core.py` —
`validate_content()` reports any mismatch loudly. The "Balance: costs,
yields, recovery" block covers the action numbers:

| Constant | Value | What it does |
|----------|-------|--------------|
| `GATHER_ENERGY_COST` / `GATHER_HUNGER_COST` | 10 / 5 | Effort per gather (spent even on failure). |
| `REST_FOOD_HEALTH` / `REST_FOOD_ENERGY` | 15 / 25 | Rest gains when eating. |
| `REST_EMPTY_HEALTH/ENERGY/HUNGER` | 5 / 10 / +5 | Rest on an empty stomach. |
| `REST_FOOD_HUNGER_NET` | −10 | Net hunger while eating and resting. |
| `SLEEP_FOOD_HEALTH` / `SLEEP_FOOD_ENERGY` | 20 / 30 | Sleep gains when eating. |
| `SLEEP_EMPTY_HEALTH` / `SLEEP_EMPTY_ENERGY` | 5 / 10 | Sleep on an empty stomach. |
| `SLEEP_HUNGER_NIGHT` | 10 | Hunger added per night. |
| `SLEEP_FOOD_HUNGER_NET` | −30 | Hunger removed per night when eating. |

Every recovery gain routes through `self._recovery(...)` so building
bonuses apply — keep using it for any new healing source. Action failures
never cost health by themselves (only events do, plus lost build/craft
materials).

**Why `eng.ACTION_DIFFICULTY = 0` works in tests:** constants tests may
tune are *mirrored* as class attributes inside `GameEngine`
(`ACTION_DIFFICULTY = ACTION_DIFFICULTY`, `MAX_VITAL = MAX_VITAL`,
`RANDOM_EVENTS = RANDOM_EVENTS`). Assigning on an *instance* shadows the
class value, and the code reads `self.ACTION_DIFFICULTY` — so the
override takes effect. `EVENT_CHANCE` mirrors the module constant the
same way now (its value lives in `balance.json`). Don't edit the
class/module values in tests; override per instance.

### Where a number lives (split rule)

- **`content/balance.json` = global knobs** — values with the same
  meaning everywhere: costs, DCs, XP amounts, event outcomes. The key
  set is gated by `content.py BALANCE_KEYS` (adding a key is a code
  edit by design — `game_core` binds each at import).
- **Intrinsic values live with their record** — a tool's bonus
  (`tool_bonus` on the tool's **item** record: `[action id it serves,
  flat amount]`), a blueprint's `work`/`skill_req`/`materials`,
  per-record `difficulty`. Adding content stays zero-Python, and the
  editor can create it without touching code.
- **Effects live on their record** — the lean-to's `recovery_bonus`
  (E2: `_recovery` sums mults over built buildings, floors once) is the
  first entry of the `EFFECT_TYPES` registry in `content.py`. New
  effect types take three touches: a registry entry, a `LEGAL_EFFECTS`
  pair enabled in the same commit as their applier, and the applier
  itself — validation rejects everything else.
- **Wholesale review:** the viewer's **Tunables** tab aggregates every
  balance-relevant number from all files onto one screen.

## The three check systems (how they interact)

1. **Action check** — every gather and every pattern attempt rolls
   `d20 + level ≥ DC` (`_skill_check` / `_stat_check`). The DC defaults
   to `ACTION_DIFFICULTY` unless a per-record `difficulty` overrides it
   (gather block, pattern, event). A gather's check aims at its
   action's `skill` — or at `difficulty_target: [kind, key]` when the
   action should check a stat (or another skill) instead.
   On failure:
   effort (and build/craft materials) is spent, no yield/progress, but
   **XP is still granted**. Rest never checks.
2. **Event check** — when the 10% fires, `_resolve_event` sums the levels
   of the action's `ACTION_CHECKS` contributors (e.g. Foraging + Strength),
   then rolls `d20 + bonus ≥ EVENT_DIFFICULTY` (an event's optional
   `difficulty` overrides that DC). Success: `EVENT_XP_SUCCESS`
   to each contributor. Failure: `EVENT_XP_FAILURE` each, plus the health
   penalty. `REST: ()` means "no check, flavor only".
3. **Pattern attempt** — materials are checked, consumed (even on
   failure), then a skill check runs; success adds progress, and `work`
   successes complete the pattern.

**XP flow:** `add_xp(kind, key, amount)` where kind is `"player"`,
`"stats"`, or `"skills"`. It returns `(changes, level_up_note)` and
levels advance automatically at the scaling cost. `run_slot` calls it for
the player and the action's `ACTION_SKILL` on every attempt; event and
pattern code call it for their own contributors.

**Snapshot vs explicit:** items and the four vitals in `STAT_LABELS`
(Health/Energy/Hunger/Gold) are diffed automatically. XP is *never*
diffed — it's appended explicitly by `add_xp`. That's why strength XP
appears as a `"Strength XP"` change without living in `STAT_LABELS`.

## Recipe: adding an action (worked example)

Goal: a **Fish** action governed by a new **Fishing** skill.

**1. Declare it in `content/actions.json`** — append to the end of the
array (array order is the planner order, so new actions appear last in
every dropdown):

```json
{ "id": "fish", "label": "Fish", "behavior": "fish",
  "skill": "fishing",
  "checks": [["skills", "fishing"], ["stats", "strength"]],
  "stat_xp": null }
```

`"behavior"` picks the handler (step 3); `"skill": null` makes an
action unskilled (like Rest); `"stat_xp"` may be `null` or
`["strength", 4]` to train a stat per attempt. The `id` is
save data — pick it once and never rename it.

**2. Give it a skill** — add to `content/skills.json`:

```json
"fishing": { "name": "Fishing", "start_level": 1,
             "tooltip": "Governs Fish attempts." }
```

The SKILLS panel row appears on its own; `start_level` feeds
`GameEngine.__init__` automatically and the tooltip comes from the same
record — there is nothing to touch in `main.py`.

**3. Gather actions need no code at all** — an action whose `behavior`
is `gather_item` is pure content. The engine's `_apply_gather_item`
reads the `gather` block you wrote in step 1 (item, yield range,
messages, optional tool bonus / difficulty) and does everything else:
effort cost, skill check on `skill`, yield roll, tool bonus. Adding
"Gather Metal" later is the same shape — a new item, a new skill, and a
new `gather_item` action record — with no new handler.

You only write Python for a genuinely **new behavior** — one that isn't
a gather, rest, or pattern attempt. Then `validate_content()` refuses
the JSON entry until it exists:

1. Claim the name in `content.py`'s `BEHAVIOR_HANDLERS` (also the
   editor's dropdown vocabulary):

```python
"fish": "Effort cost, skill check, yields fish.",
```

2. Implement it, near the other `_apply_*` methods — note it receives
   the `action_id`, so a generic handler can look up per-action config:

```python
def _apply_fish(self, action_id: str) -> Tuple[bool, str]:
    # The effort is spent whether or not anything bites.
    self.energy = clamp(self.energy - 12)
    self.hunger = clamp(self.hunger + 5)
    if self._skill_check("fishing"):
        amount = self.rng.randint(1, 2)
        self.inventory["fish"] += amount
        return True, f"you caught fish at the river ({amount} fish)."
    return False, "you cast all morning, but nothing bit."
```

Return `(success, note)` — returning `False` still grants XP (handled
centrally in `run_slot`); it just means no yield.

**4. If it yields a new item** — append to `content/items.json`:

```json
{ "id": "fish", "name": "Fish", "start": 0, "food": 2,
  "tooltip": "Edible catch — finer fare than berries." }
```

`id` is a lowercase slug — code, saves, and cross-references (pattern
materials, behavior anchors) use it; `name` is the display string the
player sees in the inventory panel and change lists. Display order =
array position (insert before `"stone"` if you care
where it shows up). The inventory panel, change summaries, and
validation pick it up automatically; `start` is how many you begin the
game with. Item ids double as save keys — keep them stable.

`food` (positive int) is the quality tier: Rest and Sleep eat foods
**best-tier-first**, draining each tier before downgrading, until
health, energy, and hunger are fully recovered (hunger 0) — only a bare
larder leaves a character unrecovered, and an already-recovered
character wastes nothing. Ties keep file order. The loop also stops at
the first bite that cannot move health, energy, or hunger toward
saturation, so validator-legal zero gains (`REST/SLEEP_FOOD_*` = 0)
can never drain the pantry. The `tooltip` is
separate, display-only copy shown in-game — write what the item is
genuinely for.

**5. Test it** — append a block to `test_smoke.py`:

```python
fish = GameEngine(seed=41)
fish.EVENT_CHANCE = 0.0
fish.set_slot_action(0, FISH)         # import FISH at the top of the file
fish.begin_day()
caught = fish.run_slot(0)
assert ("XP", ACTION_XP) in caught.changes
assert any(lbl == "Fishing XP" for lbl, _ in caught.changes)
```

Run `python test_smoke.py`. If you assert exact yields from a checkable
action, remember it can now *fail* — either branch on `result.success` or
force `engine.ACTION_DIFFICULTY = 0` (auto-pass) like the peaceful-day
test does.

## Recipe: adding a random event

When the 10% roll fires, the engine filters `RANDOM_EVENTS` (built from
`content/events.json`) by which actions may trigger each event and picks
one at random (`_pick_event`). Entries with `"actions": []` can trigger
for anything — that's the skeleton the adventure system will hang real
content on.

```json
"old_bones": {
  "text": "Half-buried bones poke out of the mud.",
  "actions": ["gather_food", "gather_wood"],
  "check": false
}
```

The key (`old_bones`) is the STABLE event id — pick it once. Entry order
in the file is the draw order among equally-eligible events, so don't
reorder casually (the fixture goldens notice).

- `check: true`: after the text is shown, the normal
  stat/skill check runs and its XP/health outcomes apply — the text is
  prepended to the note and the event dialog.
- `check: false`: nothing mechanical happens. Good for atmosphere, or for
  future choice-based content.
- Per-event *effects* (find gold, take damage, present choices) don't
  exist yet. When you add them, `_resolve_event` is the single hook
  point — the UI already renders whatever `EventResolution` carries, so
  extend that dataclass rather than touching dialog code.
- `validate_content()` checks texts are non-empty and `actions`
  reference real action ids. To test your event
  deterministically, override the table on one engine:
  `eng.RANDOM_EVENTS = {"mine": RandomEvent(...)}` with `EVENT_CHANCE = 1.0`
  (see the "Named events" block in `test_smoke.py`).

## Recipe: adding a stat

Stats are `Progress` objects (level + xp) that `GameEngine.__init__`
builds from `content/stats.json` — one record:

```json
"perception": { "name": "Perception", "start_level": 4,
                "tooltip": "Reserved for future awareness checks." }
```

Then:

1. **Nothing else for display** — name, starting level, and tooltip all
   come from the record; the STATS panel iterates `engine.stats`, so no
   UI work is needed.
2. **Let it influence rolls:** add it as an event contributor in
   `content/actions.json` → `checks`, e.g.
   `["stats", "perception"]` on the Fish action.
   That's the whole wiring — `_resolve_event` sums contributor levels
   automatically, and its XP flows back to the stat.
3. **Give it XP somewhere.** Two routes work today:
   - *Events:* listing it in `checks` (step 2) is enough — event
     outcomes already grant stat XP (12 or 6) to every contributor.
   - *Actions:* use the action's `stat_xp` field —
     `"stat_xp": ["perception", 3]` grants 3 XP on every
     Fishing attempt. You can't call `add_xp` from inside an `_apply_*`
     method (those don't see the slot's change list) — which is exactly
     why this field exists. `validate_content()` checks it.

The STATS panel iterates `engine.stats`, so no UI work is needed. Its
level-up cost shows as `n/180`-style numbers because `xp_cost_for` scales
with the starting level (Strength starts at 5, so it already costs more —
that's intended).

⚠ **Never put a stat key in `STAT_LABELS`.** That list is only for
*vitals* that exist as plain engine attributes (`self.health`, …) so the
snapshot diff can `getattr` them. A stat lives in `self.stats[...]` —
adding it to `STAT_LABELS` crashes `_diff`. Stats get their XP changes
explicitly instead, which is why they still show in summaries.

## Recipe: adding a skill

One record in `content/skills.json`:

```json
"fishing": { "name": "Fishing", "start_level": 1,
             "tooltip": "Governs Fish attempts." }
```

Skills train via any combination of three routes:
- **`actions.json` → `skill` field** — every attempt trains it (+SKILL_XP).
- **`checks` contributors** — event outcomes train it (12 or 6 XP).
- **Patterns** — set `"skill": "fishing"` on a pattern (next section).

The SKILLS panel iterates `engine.skills`, so it appears automatically.

## Recipe: adding a build/craft pattern

Add one entry to `content/patterns.json` — every field:

```json
"wood_fence": {
  "name": "Wood Fence",
  "kind": "build",
  "skill": "carpentry",
  "skill_req": 2,
  "materials": { "wood": 8 },
  "work": 2,
  "description": "A rough fence around a small garden patch.",
  "effect": "+1 berries per Gather Food."
}
```

The key (`wood_fence`) is the STABLE id — it is written to disk in
saves. `kind` must be `"build"` or `"craft"`; `skill` must exist in
`skills.json`; `materials` keys must be real items. A `"craft"`
pattern's key must also be an **item id** — crafting yields that
inventory item (tools are items, so merchants can sell them later).

Almost everything else is automatic: the picker, availability display,
progress tracking, BUILDINGS/TOOLS sections, persistence, and tooltips
all read from `PATTERNS` (`_pattern_tooltip` combines `description` +
`effect`). What you add yourself is the **effect** — either in
`_recovery()` (like the Lean to) or a targeted hook. A garden fence
boosting food belongs in `_apply_gather_food`, right after the skill
check succeeds:

```python
# inside _apply_gather_food, after its foraging check succeeds:
if self.buildings.get("wood_fence"):
    amount += 1
```

Building vs tool semantics: `kind: "build"` patterns are unique (drop out of
the picker once owned, listed under BUILDINGS — future upgrade tiers just
replace the id in `engine.buildings`). `kind: "craft"` patterns can be made
repeatedly (count shown under TOOLS); write their bonuses as either/or so
copies don't stack (see the axe).

Test snippet to copy — note that every slot is planned *before*
`begin_day()` (replanning mid-day raises), and `pattern_provider` is only
consulted for Build/Craft slot actions:

```python
fen = GameEngine(seed=43)
fen.EVENT_CHANCE = 0.0
fen.ACTION_DIFFICULTY = 0        # attempts always succeed
fen.skills["carpentry"].level = 2      # meets skill_req
fen.inventory["wood"] = 16             # work=2 -> two attempts at 8 each
fen.set_slot_action(0, BUILD)
fen.set_slot_action(1, BUILD)
fen.begin_day()
fen.run_slot(0, pattern_provider=lambda _k: "wood_fence")
assert fen.projects["wood_fence"] == 1
fen.run_slot(1, pattern_provider=lambda _k: "wood_fence")
assert fen.buildings["wood_fence"] == 1
```

## Persistence — don't skip this

Any new **state** on the engine must survive saves:

1. Give it a default in `GameEngine.__init__`.
2. Serialize it in `to_dict()`.
3. Restore it in `from_dict()` using the `as_int`/merge style of the
   neighboring blocks — always with a default so old saves still load.

The round-trip test (seed 11 in `test_smoke.py`) is the template: mutate
state, `to_dict → json.dumps → from_dict`, assert everything matches,
then assert both engines roll identical results.

Saves also carry an identity stamp — `game` and `version` (`SAVE_GAME_ID`
/ `SAVE_VERSION`); `from_dict` refuses anything else, so picking a
content file in the Load dialog is a clean "Load failed" status, never a
silent fresh Day 1, and future versions can't load into older builds.
The pinned golden save `tests/fixtures/golden_save.json` must keep
loading (and round-tripping byte-identical): when `to_dict`'s format
legitimately gains a field, re-pin it deliberately with
`python tests/make_golden_save.py` — same discipline as the fixture
goldens.

## Testing workflow

- **Engine tests run on the pinned fixture** (`tests/fixtures/content/`,
  set via `DAY_SCHEDULER_CONTENT_DIR` *before* `game_core` imports).
  Editing live `content/*.json` never moves a seeded test; the suite
  gates live content separately (direct validation + spawned
  `check_live.py`).
- **Re-pin deliberately:** when a content change should affect engine
  tests, copy `content/*.json` → `tests/fixtures/content/` and update
  the fixture goldens (order asserts + balance spot-values) in the same
  change. The goldens are the sort_keys tripwire — never reorder a
  content file "just because".
- One seeded engine per test: `eng = GameEngine(seed=N)`.
- Neutralize randomness you don't care about:
  `eng.EVENT_CHANCE = 0.0`, plus `eng.ACTION_DIFFICULTY = 0` (always
  succeed) or `999` (always fail).
- Slots run in order (0, 1, 2); `begin_day()` first; `complete_day()`
  only after all three.
- Assert on `result.changes` (list of `(label, delta)` pairs),
  `result.success`, `result.note`, and engine state.
  `dict(result.changes)` is a handy label→delta lookup.
- GUI flow tests auto-click dialogs — the *first* button found gets
  clicked, so put the confirm/primary button first in new dialogs.
- Plan every slot before `begin_day()` — replanning mid-day raises, and
  `pattern_provider` is silently ignored for non-Build/Craft slots.
- Prefer membership asserts (`"lean_to" not in [...]`) over exact lists
  (`patterns_for(BUILD) == []`) where the fixture may be re-pinned —
  exact-list asserts then need updating in that same change.
- `test_smoke.py` also runs a **fuzz**: 30 seeded random-planning days
  asserting invariants after every slot (vitals stay clamped, counts and
  XP stay non-negative, project progress stays in range), plus a
  deterministic starvation run proving **death is reachable**. Keep both
  green when you re-pin the fixture.

## Pitfall checklist

- **Engine/UI split** — new rules go in `game_core.py`. If a slot needs
  player input, mirror `pattern_provider`: pass a callback, keep the
  engine UI-free.
- **`STAT_LABELS` is for vitals only** (see the stat recipe's warning).
- **Pattern ids are save data** — renaming one orphans old saves.
- **Ids must be lowercase slugs** (`[a-z][a-z0-9_]*`, all six id
  families) — validation rejects anything else loudly, naming file,
  id, and rule.
- **New state ⇒ `to_dict` + `from_dict`**, with defaults for old saves.
- **Clamp everything** (`clamp(self.health + 20)`), or vitals run away.
- **Route healing through `_recovery()`** so building bonuses keep working.
- **New `randint` calls shift the RNG sequence** — seeded tests may
  change behavior; prefer structural asserts or forced difficulty.
- **`content/*.json` is the source of truth — with no fallback.** A
  missing or broken file fails loudly at import (`ContentError` names
  file and field; the game refuses to launch with a dialog). Roll back
  with your backup/git — never expect old defaults to cover for you.
- **The loader refuses non-standard JSON**: duplicate keys and
  `NaN`/`Infinity` fail loudly at parse (file + offending token named);
  a UTF-8 BOM is tolerated on read. Problems are `Problem`s — a str
  subclass carrying `.file`/`.record_id`/`.field` for the editor.
- **Never write content files with sorted keys** — planner order, event
  draw order, and the seeded RNG all read file order. The fixture
  goldens fail loudly if an editor sorts them.
- **Saving goes through `content.save()`** (the editor write layer): temp
  → `os.replace` per file, refuses any increase in the problem count,
  refuses stale writes when disk changed since load (`StaleWriteError`),
  and emits canonical LF bytes — don't hand-roll JSON writes.
- **`ITEM_ORDER` is derived** from `items.json` order, and `inventory`
  is built from each item's `start` — new items are JSON records, not
  `__init__` edits.
- **Tune-in-test constants are class-attribute mirrors** (`EVENT_CHANCE`,
  `ACTION_DIFFICULTY`, `RANDOM_EVENTS`) — override per instance in tests;
  never edit the class or module values.
- **`python check_fuzz.py`** is the engine-vs-content net: it mutates
  editable fields into the validator-legal space (floats where ints
  belong, extra actions per behavior, empty lists, absent optionals)
  and plays seeded days per variant in fresh child processes — catching
  the "validation passed but the engine can't use it" class that unit
  mutations can't. Guard variants pin known-bad classes as MUST-FAIL.
  The play loop also carries the pantry-drain net: during Rest and the
  sleep cycle, food may only be consumed while some target stat moves
  toward saturation (health/energy up, hunger down).
  Spawned by test_smoke; standalone: `python check_fuzz.py [dir]`.
- **`python check_design.py`** is the *advisory* content lint: prints
  warnings (unobtainable items, untrained skills, missing pattern
  kinds, ambiguous names, pacing heuristics) and **always exits 0** —
  while the design guidelines are still forming, taste informs but
  never fails the build. One rule = one function in `RULES`; findings
  are Problem-shaped for a future editor surface.
- **Run `validate_content()`** (or just `python test_smoke.py`) — the
  schema/reference half lives in `content.py` and runs at every load;
  the engine half checks the default plan, code item anchors, the
  `BEHAVIOR_HANDLERS` ↔ `_apply_*` mapping, `STAT_LABELS`-vitals-only,
  and balance-key bindings.
  `python check_live.py` runs it against the LIVE files plus seeded
  play. Fix its reports before playtesting.
- **Death only checks at day end** (`_check_game_over` in `complete_day`);
  mid-day death needs new plumbing.
- After any change: `python test_smoke.py`, then play one day in
  `python main.py` and hover the new rows to check tooltips.

That's the whole surface area. The adventure, merchant, and NPC systems
will plug into the same seams: engine state, `_apply_*` methods, and
`pattern_provider`-style callbacks wherever they need player input. The
content editor (once built) reads `content.py` only — never
`game_core.py` — so it can open and repair files the game refuses to
load.

