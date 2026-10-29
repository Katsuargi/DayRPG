# EFFECTS_PLAN_DEEPSEEK.md — effects layer plan (reviewer)

Scope: read-only planning output. This file is the only artifact. All
file:line citations are against the working tree as of this writing
(2026-10-28); I re-verified the key hooks, the schema table, the editor
branches, and the pins named below by reading the files, and I ran the
lean-to and axe numbers against the real code. Anything I did NOT verify
is marked **[UNVERIFIED]**.

Recommendations are numbered R1..Rn; per-slice implementation steps are
S1..Sn inside each slice. Each recommendation/step is independently
accept/modify/reject-able.

> **STATUS (2026-10-28): reconciled — binding rulings live in
> `EFFECTS_BRIEF.md` §"Binding decisions (round-2 reconciliation)".**
> Ship order changed to **E1 → E2 → E3 → E5 → E4** (E4 optional) — the
> brief's binding section explains why; this plan's §1/R1/R2 and the
> E4/E5 labels keep their original order for citation, but implement in
> the brief's order. Superseded passages (kept here for provenance):
> §2 **D1** headline + §3.2 `recovery_bonus.stack: "max"` (decided:
> **sum** — §4.1/E2-S3's applier text was the right half); §2 **D3**/R4
> (only `LEAN_TO_RECOVERY_BONUS` retires; `EVENT_FAILURE_HEALTH` stays
> as the generic-path penalty — brief N2); §2 **D4** (decided: text is
> **generated** from type+params with an optional `text` override —
> brief D4); §3.2 `VITALS` (hunger **cut** from v1 — brief D8);
> `grant_xp.key` needs a kind-keyed dyn_ref plus imperative rules
> (brief N3); §5 **E3**'s "see R12" is a dangling reference — the real
> reporting contract is brief N4; and the plan lacks a **legality
> table** (record kind × effect type × trigger) that gates every slice
> (brief N1). Everything else stands, including R12–R18 and the
> constraint-3 challenge ruling.

---

## 1. Slicing (my version; the draft E1–E5 is re-sliced)

The draft's E1–E5 (EFFECTS_BRIEF.md:180-209) is close, but I re-slice for
three reasons: (1) read-only display is cheap and belongs in E1, not E4, so
the editor can *see* effects the moment SCHEMA declares them; (2) the
`tool_bonus` absorption is a full four-touch migration of its own and should
not be crammed into the "triggered ops" slice; (3) the shared-state
placeholder (draft E5) is speculative and I cut it entirely (see D6/R7).

Final slices — every one ends **green + committed** (hard gates `check_live`
and `check_fuzz` pass; advisory `check_design` never fails the build per
constraint 8, EFFECTS_BRIEF.md:51-53):

- **E1 — Registry + validation + read-only display (data only, zero behavior
  change).** `EFFECT_TYPES`/`TRIGGERS`/`TARGETS` in content.py; SCHEMA gains
  an optional `effects` list on items/patterns/events; a new engine-free
  `_check_effects`; `_spec_edge` and the editor's `_value_text` gain an
  `effect` branch so entries render read-only and references are discoverable.
  Engine untouched; golden save untouched. Gate: `python test_smoke.py`
  (schema-drift + validation-mutation sections) and `python check_live.py`.
- **E2 — Lean-to passive (first applier).** Data-drive `_recovery`
  (game_core.py:990-994) off the lean_to pattern's `recovery_bonus` effect;
  retire `LEAN_TO_RECOVERY_BONUS` via the four-touch chain (balance.json →
  BALANCE_TYPES/BALANCE_KEYS → game_core binding → engine read). The
  +32/+50 pins (test_smoke.py:859-864) must not move.
- **E3 — Triggered ops at event resolution.** `_resolve_event`
  (game_core.py:880-945) runs success-/failure-side effect sets
  deterministically after the existing draws; add `vital_delta`/`grant_xp`/
  `grant_item`/`consume_item` appliers; convert `EVENT_FAILURE_HEALTH` to a
  per-event `vital_delta` effect and delete the balance key. Summary/reporting
  contract specified (see R12).
- **E4 — Absorb `tool_bonus` into `yield_bonus` effects.** Delete the
  `tool_bonus` field (content.py:113), `_check_tool_bonuses`
  (content.py:740-768), `TOOL_BONUSES` (game_core.py:92-99), and the editor
  economy special-case (editor.py:336-339); `_apply_gather_item`
  (game_core.py:996-1031) reads a max-wins `yield_bonus` applier. `food`
  stays bespoke (R9). Pins test_smoke.py:866-900 unchanged.
- **E5 — Editor edit path + Tunables + design lint.** Editable effect rows
  (a new `_add_effect_list` branch, not a reuse of `_add_list`), a `list`
  branch in Tunables `_tune_rows` (editor.py:259-284), and registry-aware
  `check_design` rules.
- **CUT — shared-state foundation (draft E5).** Deferred wholesale per D6.

### R1 — Order and what I cut
Adopt E1→E5 above. **Cut:** the shared-state placeholder; the D3(b)
relocation of gather/rest/sleep numbers (they stay in balance.json this
phase); any per-event *success XP* migration (EVENT_XP_SUCCESS/FAILURE stay
global for uniform pacing). Confidence: high (90%).

### R2 — Should you stop after E2?
**Do not stop at E2 as the final state.** E1+E2 is a valid *checkpoint*
(proves the registry + one passive seam cheaply), but it leaves the other
half of the brief ("triggered ops") and authoring unproven. Ship through E3
as the minimum viable whole; treat E4 and E5 as separable follow-ons.
Confidence: high (85%). If you must shrink further, ship E1+E2+E3 and drop
E4+E5 — that still gives content authors validated, engine-applied passive
and triggered effects, just without `tool_bonus` unification or editable
forms.

---

## 2. D-decisions (D1–D8)

### D1 — Stacking and order
**Decision:** per-type stacking rule, defaulting to **max-wins** for passives
and **each-applies-once (declaration order)** for triggered ops. This keeps
the one load-bearing pin: copies of the axe must not stack
(test_smoke.py:887-900 asserts +1 once, and the tool_bonus precedent
game_core.py:1022-1027 is max-over-owned). `yield_bonus` and
`recovery_bonus` use max; `vital_delta`/`grant_xp`/`grant_item`/
`consume_item` each fire once per matching trigger, in record order.

**Rounding:** sum multipliers first, then floor once — `int(amount * (1 +
total_mult))` — byte-identical to today's `int(amount * (1 +
LEAN_TO_RECOVERY_BONUS))` (game_core.py:993) when there is one source at
0.1. The +32/+50 pin depends on this (test_smoke.py:859-864).
Confidence: high (90%).

### R3 — Stacking implementation
Make max-vs-sum a key on each EFFECT_TYPES entry (`stack: "max" | "sum"`),
not a global constant, so a future stacking recovery or additive damage is
one data edit. v1 uses `max` only. Do not implement (d) cap-the-count.

### D2 — RNG contract
**Decision:** (a) **effects may never draw.** Appliers run deterministically
after all existing draws (event chance game_core.py:533 → action check → yield
game_core.py:1021 → event draw 878 → event check 916). Any applier touching
`self.rng` breaks `abort_day` replay (test_smoke.py:650-670) and every seeded
pin; forbid it in review. Confidence: near-certain (95%). Cost: no random
effect outcomes in v1 — acceptable, and consistent with constraint 9.

### D3 — Where numbers live
**Decision:** extend the existing split rule only where the owning record
already exists and the four-touch chain is complete. In scope this phase:
`LEAN_TO_RECOVERY_BONUS` (→ lean_to pattern, E2) and `EVENT_FAILURE_HEALTH`
(→ per-event effect, E3). **Out of scope:** gather/rest/sleep gains — sleep
has no owner record (sleep runs from `complete_day`, not an action;
EFFECTS_BRIEF.md:160) and moving rest/sleep numbers risks the just-shipped
eat loop for no effects-layer payoff. Keep `EVENT_XP_SUCCESS`/`FAILURE`,
`ACTION_XP`, `SKILL_XP` global. Confidence: high (85%).

### R4 — D3 scope
Relocate only the two keys above. Everything else in
EFFECTS_BRIEF.md:155-163 stays put. Do not touch `_eat_until_recovered`,
`_apply_rest`, `_apply_sleep`, or the GATHER_*_COST bindings this phase.

### D4 — Effect text
**Decision:** deterministic per-type text template, overridable by an
optional `text` param on each effect entry. Where the entry has no `text`,
render from type+params (e.g. `recovery_bonus` → `"+10% recovery"`). The
pattern's existing `effect` string (content.py:173; patterns.json:12,24)
stays the human tooltip; the `effects` list is the machine data. This keeps
the two sources of truth disjoint (human text vs appliable data) and avoids
migrating every tooltip. Confidence: medium (75%).

### D5 — Eating policy (OWNER CALL)
The eating loop `_eat_until_recovered` (game_core.py:1115-1147) encodes a
just-shipped, fuzz-guarded user rule (best-tier-first, eat-to-saturation,
progress guard game_core.py:1130-1141).

- **(a) keep loop Python; effects only ADD** (my recommendation). The loop's
  targets/gains stay in code + balance; the `recovery_bonus` effect scales
  whatever amount the loop passes to `_recovery`. Cost: rest/sleep food gains
  stay in balance.json; `food` items do not become effects (see R9).
- **(b) loop targets become effect-driven.** More declarative, but the loop
  is the wrong granularity and couples a delicate rule to effect data.
  Cost: high regression risk on the fuzz guard (check_fuzz.py:90-97 sets
  zero-gain keys to prove the guard).
- **(c) encode loop semantics as data.** Largest; smells like scripting;
  conflicts with constraint 9.

### R5 — Eating policy
Adopt (a). Revisit only if a concrete food-effect requirement appears.
Confidence: high (85%).

### D6 — Timing of shared state (OWNER CALL)
NPC relationships, merchant stock, adventure progress.

- **(a) defer all** (my recommendation). v1 effects are stateless — they read
  `self.buildings`/`self.inventory`/`self.projects` at apply time and write
  only vitals/XP/inventory, so no new `to_dict` field and no golden re-pin is
  needed. Shared state is a future system with its own persistence slice.
  Cost: a later NPC/merchant effect will need its own save-shape slice
  (migration risk), but that risk is real work later, not speculative now.
- **(b) scaffold now.** Add save fields + one golden re-pin for systems that
  don't exist yet. Cost: save-size growth + golden drift + speculative shape.
- **(c) model stock as tables+deltas day one.** Over-builds before any
  merchant exists. Cost: most speculative.

### R6 — Shared state
Adopt (a); delete the draft E5 placeholder. Re-pin the golden save only when
a real shared-state slice lands. Confidence: high (85%).

### D7 — Absorb `food`/`tool_bonus`, or coexist?
**Decision:** (c) absorb gradually — `tool_bonus` first (E4), `food` stays.
`tool_bonus` is already effect-shaped (tagged action + flat int, max-wins);
`food` drives `FOOD_ITEMS` ordering (game_core.py:277-283, best-tier-first),
which is load-bearing and would be a four-touch migration with golden/editor
churn for no v1 payoff. Confidence: high (85%).

### R7 — D7 split
Absorb `tool_bonus` in E4; leave `food` as the quality-tier field. Section 4
shows exactly what each field becomes.

### D8 — Triggers and targets
**Decision:** hybrid — type-implied default trigger with an optional `when`
override, plus a **closed target vocabulary** validated imperatively (like
`ref`/`dyn_ref`), so typos fail at load.
- Passive types (`recovery_bonus`, `yield_bonus`) default `when = "always"`.
- Triggered types (`vital_delta`, `grant_xp`, `grant_item`, `consume_item`)
  **require** `when` ∈ {`on_success`, `on_failure`, `on_use`}; omission is a
  validation error, not a silent never-fire.
- Closed targets: `health`, `energy`, `hunger`, `recovery`, `yield`.
  (`gold` exists as a STAT_LABEL, game_core.py:294-299, but has no mechanic —
  excluded from v1.)

### R8 — D8 encoding
`TRIGGERS = ("always","on_success","on_failure","on_use")` and
`TARGETS = ("health","energy","hunger","recovery","yield")` as module
constants in content.py; `when`/`target` are validated imperatively in
`_check_effects`, not via a loose `string` spec.

---

## 3. Op vocabulary v1

### 3.1 Effect entry shape and the new spec tag

Every record that can carry effects gets an optional field:

```
"effects": ("opt", ("list", ("effect", None)))
```

`("effect", None)` is the ONE new spec tag (a discriminated union: the
entry's `type` selects its params). Existing tags cover everything else.
The existing spec vocabulary is documented at content.py:89-95.

An effect entry is `{"type": <slug>, "when": <trigger?>, ...params}`.

### 3.2 The registry (content.py, next to BEHAVIOR_HANDLERS content.py:47-51)

```python
TRIGGERS: Tuple[str, ...] = ("always", "on_success", "on_failure", "on_use")
TARGETS:  Tuple[str, ...] = ("health", "energy", "hunger", "recovery", "yield")
VITALS:   Tuple[str, ...] = ("health", "energy", "hunger")

EFFECT_TYPES: Dict[str, dict] = {
    "recovery_bonus": {"stack": "max", "when": ("opt", ("enum", TRIGGERS)),
                       "mult": "number"},
    "yield_bonus":    {"stack": "max", "when": ("opt", ("enum", TRIGGERS)),
                       "action": ("ref", "actions"), "add": "int"},
    "vital_delta":    {"stack": "each", "when": ("enum", TRIGGERS),
                       "target": ("enum", VITALS), "amount": "int"},
    "grant_xp":       {"stack": "each", "when": ("enum", TRIGGERS),
                       "kind": ("enum", ("player", "stats", "skills")),
                       "key": ("opt", "string"), "amount": "int"},
    "grant_item":     {"stack": "each", "when": ("enum", TRIGGERS),
                       "item": ("ref", "items"), "count": "int"},
    "consume_item":   {"stack": "each", "when": ("enum", TRIGGERS),
                       "item": ("ref", "items"), "count": "int"},
}
```

`stack` is a per-type rule used by appliers: `"max"` (passives) or `"each"`
(triggered). `when` being `("opt", ...)` marks the passive default; triggered
types use a required `("enum", TRIGGERS)` so omission fails validation.

Semantic defaults live in the appliers, not in content (the "no fallback
values" rule concerns *bad files*, not designed defaults — same as the global
DC fallback at game_core.py:975/987/918-919).

### 3.3 The six types (name → params, trigger, target, text template)

| type | params | default trigger | target | text template (no `text` param) |
|---|---|---|---|---|
| `recovery_bonus` | `mult` number | `always` | `recovery` | `+{mult*100:g}% recovery` |
| `yield_bonus` | `action` ref actions, `add` int ≥1 | `always` | `yield` | `+{add} {action} yield` |
| `vital_delta` | `target` VITALS, `amount` int (signed) | required | `health`/`energy`/`hunger` | `{target} {amount:+d}` |
| `grant_xp` | `kind` player/stats/skills, `key` optional, `amount` int ≥1 | required | `xp` | `+{amount} {kind} XP` |
| `grant_item` | `item` ref items, `count` int ≥1 | required | (inventory) | `+{count} {item}` |
| `consume_item` | `item` ref items, `count` int ≥1 | required | (inventory) | `−{count} {item}` |

`vital_delta.amount` may be negative (damage) or positive (heal); `add`/`count`
and `grant_xp.amount` must be ≥1 (validated; mirrors the ≥1 rules at
content.py:380-383, 762-764).

### R9 — Registry location and validation
Put `TRIGGERS`/`TARGETS`/`VITALS`/`EFFECT_TYPES` in content.py (the editor
imports content.py only, editor.py:24-26). Validate imperatively in a new
`_check_effects(records, item_ids, action_ids, skill_ids, stat_ids, problems)`
called from `validate_bundle` (content.py:771-791) for each effects-capable
file, exactly like `_check_tool_bonuses` is called at content.py:785. The
editor never imports game_core (constraint 2).

### 3.4 Schema/editor changes required for type-varying params

1. **content.py SCHEMA** — add `"effects": ("opt", ("list", ("effect", None)))`
   to `items` (content.py:107-114), `patterns` (165-175), and `events`
   (181-186). Not to `balance`/`skills`/`stats`/`actions` in v1.
2. **content.py `_spec_edge`** (226-258) — add an `elif tag == "effect":`
   branch: read `value["type"]`, look up `EFFECT_TYPES[type]`, and for each
   param call `_spec_edge(fname, rec_id, f"{field}.{type}.{pname}", pspec,
   value.get(pname), edges)`. This makes `yield_bonus.action` and
   `grant_item.item` appear in `collect_references` (197-217).
3. **content.py `_check_effects`** — validates shape, known `type`, required/
   unknown params, `when`/`target` membership, ref resolution, numeric ranges.
4. **editor.py `_value_text`** (1030-1063) — add `if tag == "effect":` branch
   for read-only rendering (E1): render `type` + params via the existing
   per-param `_value_text`.
5. **editor.py `_add_field`** (1097-1147) — E1 renders `effects` read-only via
   a new `("effect", None)` fallthrough label; E5 replaces it with
   `_add_effect_list` (see S-slice E5). Do NOT route `("effect", None)` into
   the existing `_add_list` (1458-1525) — that list editor assumes a single
   fixed member spec and would render a "no editor for this spec" row.
6. **test_smoke.py `_wrong_value`** (393-401) — no change: `("effect", None)`
   already falls through to `return 7` (401), so the mutation test covers it.

### R10 — Keep the `effect` tag narrow
Do not add generic scripting/expression tags. If a future effect needs a new
param, add a new `EFFECT_TYPES` entry or extend one; do not bolt a `expr`
field onto entries.

---

## 4. Worked examples (JSON), verified against the live tree

I ran the current code to confirm the baseline numbers these must reproduce
(`FOOD_ITEMS == ('berries',)`, `TOOL_BONUSES == {'wood_axe': ('gather_wood', 1)}`,
`_recovery(15)==16`, `_recovery(25)==27`, axe gather gain 2..4).

### 4.1 Lean-to passive (→ `recovery_bonus`)

patterns.json `lean_to` gains (key order preserved; do not sort):

```json
"effects": [
  { "type": "recovery_bonus", "mult": 0.1 }
]
```

- `_recovery` (game_core.py:990-994) is rewritten to read active
  `recovery_bonus` effects and compute `int(amount * (1 + total_mult))`. With
  one source at 0.1 this is byte-identical (verified: `_recovery(15)==16`,
  `_recovery(25)==27`), so the two-berry rest pin +32/+50
  (test_smoke.py:859-864) does not move.
- `LEAN_TO_RECOVERY_BONUS` is deleted from balance.json (line 14) and from
  `BALANCE_TYPES`/`BALANCE_KEYS` (content.py:69/81); the game_core binding at
  game_core.py:240 is removed. `validate_content` (game_core.py:1258-1265) then
  has no key to cross-check.

### 4.2 Axe `tool_bonus` (→ `yield_bonus`)

items.json `wood_axe` replaces its `tool_bonus` field with:

```json
"effects": [
  { "type": "yield_bonus", "action": "gather_wood", "add": 1 }
]
```

- `_apply_gather_item` (game_core.py:996-1031) replaces the `TOOL_BONUSES`
  scan (1024-1027) with a max-wins `yield_bonus` applier: for each owned item
  carrying a `yield_bonus` whose `action == action_id`, `bonus = max(bonus, add)`.
  Verified: the axe still adds 2..4 wood (test_smoke.py:879) and copies add +1
  once (test_smoke.py:887-900).
- Removed: `tool_bonus` from items SCHEMA (content.py:113), `_check_tool_bonuses`
  (740-768), its call site (785), `TOOL_BONUSES` (game_core.py:92-99), the
  editor economy special-case (editor.py:336-339), and the `tool_bonus`
  tooltip text in items.json:31 and patterns.json:24 (data edit).

### 4.3 Event failure penalty (→ `vital_delta`)

events.json `wandering_thoughts`, `stray_berry_bush`, and `howling_wind` each
gain (the three check-events; `quiet_moment` is `check:false` flavor):

```json
"effects": [
  { "type": "vital_delta", "when": "on_failure", "target": "health", "amount": -5 }
]
```

- `_resolve_event` (game_core.py:880-945) replaces the hardcoded
  `self.health = clamp(self.health + EVENT_FAILURE_HEALTH)` (930-932) with an
  applier over the chosen event's `on_failure` effects, appending a
  `("Health", -5)` change to `event_changes` (932's exact behavior).
- `EVENT_FAILURE_HEALTH` is deleted from balance.json (line 12), from
  BALANCE_TYPES/BALANCE_KEYS (content.py:68/81), and the binding at
  game_core.py:235 is removed. Seeded/golden behavior is unchanged because the
  number (−5) and order are preserved.

### 4.4 Food item — NOT an effect in v1

berries (items.json:1-8) is **unchanged**:

```json
{ "id": "berries", "name": "Berries", "start": 2, "food": 1, "tooltip": "…" }
```

### R11 — Fate of the existing `food` and `tool_bonus` fields

- **`food`:** stays the quality-tier field (D7c/R7). It drives `FOOD_ITEMS`
  best-tier-first order (game_core.py:277-283) and the validator's
  "at least one food" rule (content.py:384-387). Absorbing it is a four-touch
  migration with golden/editor churn for zero v1 payoff — reject for now.
- **`tool_bonus`:** absorbed into `yield_bonus` effects (E4) and removed.
  This unifies the item system to two mechanics (food tier + effects) instead
  of three, and it is the only bespoke field whose shape already matches the
  effect model. Confidence: high (85%) that absorption is net-positive; the
  main cost is touching editor economy view + item/pattern tooltips + the
  tool_bonus validation tests (test_smoke.py:331-343) + the GUI edit test
  (test_editor_gui.py:659-674), which must be rewritten to set an effect row.

---

## 5. Per-slice acceptance tests and exact implementation steps

Implementer contract: each S-step lists the file, the exact function/signature
or edit, and the gate that proves it. Pins named "MUST NOT MOVE" are the
byte-behavior asserts already in the repo; if one fails, the step is wrong,
not the pin.

### E1 — registry + validation + read-only display (no behavior change)

Steps (in order):
- **S1** `content.py`: after `BEHAVIOR_HANDLERS` (content.py:47-51) add
  `TRIGGERS`, `TARGETS`, `VITALS`, `EFFECT_TYPES` exactly as in §3.2.
- **S2** `content.py` SCHEMA: add `"effects": ("opt", ("list", ("effect", None)))`
  to `items` (107-114), `patterns` (165-175), `events` (181-186). Do not add it
  to balance/skills/stats/actions.
- **S3** `content.py`: add
  `def _check_effects(records, item_ids, action_ids, skill_ids, stat_ids, problems) -> None`
  and call it from `validate_bundle` (content.py:771-791) three times:
  items, patterns, events (mirror the `_check_tool_bonuses` call site at 785).
  Rules: `effects` absent → OK; not a list → problem; entry not a dict →
  problem; `type` not in EFFECT_TYPES → problem; unknown param key → problem
  (typo guard, like `_check_gather` content.py:419-422); required param missing
  → problem; `when`/`target` not in TRIGGERS/TARGETS(VITALS) → problem;
  refs resolve against the passed id sets; numeric ranges per §3.3.
- **S4** `content.py` `_spec_edge` (226-258): add `elif tag == "effect":` branch
  (§3.4.2) so `collect_references` sees `yield_bonus.action`/`grant_item.item`.
- **S5** `editor.py` `_value_text` (1030-1063): add `if tag == "effect":` branch
  rendering `type` + params (§3.4.4).
- **S6** `editor.py` `_add_field` (1097-1147): BEFORE the `list` branch (1131),
  insert the read-only effect-list branch (§3.4.5) so `effects` renders a
  read-only line and never reaches `_add_list`.

Gate E1: `python test_smoke.py` (schema-drift 372-444 and loader mutations must
pass), `python check_live.py` (exit 0), `python test_editor_gui.py` (no crash
rendering items/patterns/events). Add these mutations to test_smoke.py:
unknown effect type, bad `mult` type, `yield_bonus` with unknown action,
`vital_delta` missing `when`, bad `target`. **MUST NOT MOVE:** the golden save
and every seeded pin — E1 changes no engine code and no content.

### E2 — lean-to passive

Steps:
- **S1** `content/patterns.json`: give `lean_to` the effect from §4.1 (keep key
  order; the `effect` string stays for the tooltip).
- **S2** `game_core.py` `Pattern` dataclass (150-163): add
  `effects: Tuple[dict, ...] = ()`; in `PATTERNS` (168-182) add
  `effects=tuple(record.get("effects", ()))`.
- **S3** `game_core.py` `_recovery` (990-994): replace the body with the
  §4.1 version — sum `recovery_bonus.mult` over built buildings, floor once.
  Signature unchanged: `def _recovery(self, amount: int) -> int`.
- **S4** retire `LEAN_TO_RECOVERY_BONUS`: delete balance.json line 14; delete
  the `"LEAN_TO_RECOVERY_BONUS": "number"` entry in `BALANCE_TYPES`
  (content.py:69); delete the binding `LEAN_TO_RECOVERY_BONUS =
  CONTENT.balance["LEAN_TO_RECOVERY_BONUS"]` (game_core.py:240). Nothing else
  references it (verify with a grep).

Gate E2: `python test_smoke.py` — **MUST NOT MOVE** the +32/+50 lean-to rest
pin (859-864) and the build-completes-lean_to section (845-864);
`python check_live.py`; `python check_fuzz.py`. `validate_content`
(game_core.py:1258-1265) must report no balance-key drift.

### E3 — triggered event ops

Steps:
- **S1** `game_core.py` `RandomEvent` dataclass (187-200): add
  `effects: Tuple[dict, ...] = ()`; in `RANDOM_EVENTS` (208-217) add
  `effects=tuple(record.get("effects", ()))`.
- **S2** `game_core.py` add the applier method:
  `def _apply_effect(self, effect: dict, xp_changes: List[Change], notes: List[str]) -> None`
  dispatching on `effect["type"]`:
  - `vital_delta`: `setattr(self, target, clamp(getattr(self, target) + amount))`;
    append `(STAT_LABEL, amount)` to `event_changes` (see S3 signature).
  - `grant_xp`: `changes, lvl = self.add_xp(kind, key, amount)`; extend
    `xp_changes` and `notes` (mirror 924-929).
  - `grant_item`/`consume_item`: `self.inventory[item] += count` / `-= count`
    (clamped at 0); the slot `_diff` (1186-1204) surfaces the delta.
- **S3** `game_core.py` `_resolve_event` (880-945): pass `event_changes` into the
  applier and run the chosen event's effects **after** the existing XP award
  (922-929) and **instead of** the hardcoded failure health (930-932). Replace
  930-932 with: `for eff in chosen.effects: if eff.get("when") == ("on_success" if success else "on_failure"): self._apply_effect(eff, xp_changes, notes)`
  and have `_apply_effect` append vitals/items to `event_changes`. Keep the
  existing XP success/failure award (922-929) untouched.
- **S4** `content/events.json`: add the §4.3 effect to the three check-events;
  delete balance.json line 12, the `EVENT_FAILURE_HEALTH` entry in
  `BALANCE_TYPES` (content.py:68), and the binding (game_core.py:235).
- **S5** `_check_effects` (from E1): for the events file, only allow
  `when ∈ {"on_success","on_failure"}`; reject `always`/`on_use` for events.

Gate E3: `python test_smoke.py` — **MUST NOT MOVE** the named-event sections
(911-953, including the flavor `changes == []` at 924 and the per-event DC
display at 939-952), and any seeded event-outcome asserts; `python check_live.py`;
`python check_fuzz.py`. Add a mutation: an event whose `vital_delta` targets
`gold` (not in VITALS) must fail validation.

### E4 — absorb `tool_bonus` into `yield_bonus`

Steps:
- **S1** `content/items.json`: replace `wood_axe.tool_bonus` with the §4.2
  `effects` list; update items.json:31 and patterns.json:24 tooltip text.
- **S2** `content.py`: delete `"tool_bonus"` from items SCHEMA (113); delete
  `_check_tool_bonuses` (740-768) and its call (785).
- **S3** `game_core.py`: delete `TOOL_BONUSES` (92-99); in `_apply_gather_item`
  (996-1031) replace the 1024-1027 scan with a max-wins applier over owned
  items' `yield_bonus` effects: `bonus = max((eff["add"] for item_id, owned in self.inventory.items() if owned for eff in EFFECTS_OF(item_id) if eff.get("type")=="yield_bonus" and eff.get("action")==action_id), default=0)`
  (add a helper `EFFECTS_OF(item_id)` or an `ITEM_EFFECTS` table derived at
  import like `TOOL_BONUSES` was).
- **S4** `editor.py`: remove the economy special-case at 336-339 (replace with a
  generic "equipment (effects)" tag when an item carries any effect, or drop).
- **S5** update tests: rewrite the `tool_bonus` validation mutation
  (test_smoke.py:331-343) to exercise a bad `yield_bonus`; rewrite the GUI edit
  test (test_editor_gui.py:659-674) to add a `yield_bonus` effect row.

Gate E4: `python test_smoke.py` — **MUST NOT MOVE** the axe gain 2..4 (879) and
copies +1-once (887-900); `python check_live.py`; `python check_fuzz.py`;
`python test_editor_gui.py`.

### E5 — editor edit path + Tunables + design lint

Steps:
- **S1** `editor.py`: add
  `def _add_effect_list(self, row, field, spec, value, was_opt) -> None`:
  one row per entry, a type combobox (from `EFFECT_TYPES`) plus a param subform
  that swaps when the type changes; add/remove/**no reorder** chrome (order is
  data, constraint 4 — mirror `_add_dict_int`'s no-reorder rule at 1527-1531,
  NOT `_add_list`'s ↑↓ at 1506-1513). Store rows in `self.rowvars[field]` and
  write back `self.record[field]` on every edit (D17 pattern).
- **S2** `editor.py` `_add_field`: replace the E1 read-only branch with a call to
  `_add_effect_list`.
- **S3** `editor.py` `_tune_rows` (259-284): add an `elif tag == "list":` branch
  (or effect-specific) that descends into `effects` entries and shows numeric
  params; do not reorder.
- **S4** `check_design.py`: extend `_unobtainable_items` (36-52) so a `grant_item`
  effect counts as a source (via `collect_references` edges), and add an
  `_effect_references` rule if desired.

Gate E5: `python test_editor_gui.py` (add/remove/edit an effect row, save, reload);
`python test_smoke.py`; `python check_live.py`; `python check_design.py`
(exits 0 — advisory).

### Consolidated pins that MUST NOT move (across the whole phase)

- test_smoke.py:859-864 — lean-to rest +32/+50.
- test_smoke.py:866-884 — axe craft + gather 2..4.
- test_smoke.py:887-900 — tool copies +1 once.
- test_smoke.py:632-638 — empty rest +10/+5, empty sleep +10.
- test_smoke.py:650-670 — abort_day rewinds and replays identically (this is
  the RNG-contract canary: any applier rng call breaks it).
- tests/fixtures/golden_save.json and `tests/make_golden_save.py` — save shape
  and identity (game_core.py:726-727) unchanged; no new `to_dict` fields.

---

## 6. Risks the brief missed, and one settled-constraint challenge

### Risks (beyond EFFECTS_BRIEF.md)

- **R12 — Schema-drift test ordering.** test_smoke.py:381-384 asserts every
  live-record key is declared in SCHEMA, and 418-428 asserts every declared
  field rejects a wrong-typed value. Adding `effects` to SCHEMA *and* the
  validator must land in the SAME commit (E1 S2+S3), or the drift loop will
  either flag `effects` as an undeclared key or fail because the validator
  doesn't reject a bad `effects`. A cheap implementer splitting these will get
  a confusing red. Gate E1 with test_smoke.py immediately after S3.
- **R13 — `collect_references`/economy side effects.** `grant_item` becomes a
  new item *source*; `_unobtainable_items` (check_design.py:36-52) and the
  economy view (editor.py:300-341) only recognize `gather.item` and craft
  patterns. Without the §5 E5 S4 fix, a `grant_item`-only item is falsely
  "red/NO source" (advisory only — not a gate — but a visible regression).
- **R14 — `check_fuzz.py` balance assumptions [UNVERIFIED in full].** I read
  `_zero_food_gains` (check_fuzz.py:90-97) but not every mutator. Before
  retiring `LEAN_TO_RECOVERY_BONUS`/`EVENT_FAILURE_HEALTH` (E2/E3 S4), grep
  `check_fuzz.py` and `test_smoke.py` for those literal names; any direct
  reference must be removed in the same commit or the gate breaks.
- **R15 — Float `mult` and tooltip drift.** `mult: "number"` admits 0.33, -0.1,
  5.0; a negative mult silently *reduces* recovery, and an author writing
  `1` (meaning +100%) vs `0.1` (+10%) is a real footgun. Validate
  `0 <= mult <= 1` in `_check_effects` and put the meaning in the type's tooltip.
- **R16 — `when` on passives vs triggered is easy to invert.** If the applier
  defaults a triggered type's missing `when` to `always`, an event `vital_delta`
  fires on both outcomes silently. Make `_check_effects` *require* `when` for
  triggered types (D8), and make the event applier ignore `always`/`on_use`
  (E3 S5) so a mis-authored event fails loud instead of firing wrong.
- **R17 — `_add_list` reorder chrome vs order-is-data.** The reusable list editor
  has ↑↓ (editor.py:1506-1513). Effect entry order is application order, so E5
  must NOT reuse `_add_list`; use a no-reorder editor (R-via-§5 E5 S1).
- **R18 — `on_use` has no engine seam yet.** Items can declare `on_use`, but no
  action/UI consumes it in v1. Keep `on_use` in TRIGGERS for the schema but
  document it as reserved/unused; do not claim item on-use works.

### Settled constraint I would challenge

**I would not reopen any of the nine settled constraints.** The one I would
flag for the record: **constraint 3's "per-file hand layout is banned"** is
compatible with a *new schema tag* only if we read it as "field *specs* drive
widgets," not "widgets are fixed." The `("effect", None)` tag is the first
field whose widget shape depends on a *value* (`type`) rather than the *spec*
alone; that is a schema-driven extension (the `type` enum drives the param
subform), not a hand layout. If the owner disagrees, the fallback is
OPEN_QUESTIONS.md #3's split `passive`/`trigger` keys — but that multiplies
schema/validation/editor surface for no semantic gain, so I recommend keeping
the single `effects` list. Confidence: medium (70%).

### Final answer to "what would you cut"

Ship E1–E3 as the minimum whole (passive + triggered + validated + readable).
Cut: the shared-state placeholder, the D3(b) rest/sleep/gather relocation,
`food` absorption, and `on_use` wiring. Do E4 (tool_bonus unification) and E5
(editable rows) only if the owner wants the item-system cleanup and authoring
now; both are separable and each ends green.

--- end of plan ---







