# EFFECTS_BRIEF — planning input for the effects layer (DRAFT)

**Status:** draft for external review — NOT binding until reconciled,
unlike EDITOR_BRIEF v4. Written 2026-10-26 by the implementing agent at
the user's direction (Claude's recommended workflow: implementer writes
the prep → a stronger model does the in-depth planning → back to
implementation). Every fact below was verified by reading this repo at
commit 27031a0; file:line citations are current as of that commit
(re-verified after the pantry-guard fix `27031a0` shifted lines
below the eat loop). Exactly one pin: this one.
EDITOR_BRIEF.md's D-numbers (D1–D19) belong to the editor phase; the
D-numbers in *this* brief are scoped here and restart at D1.

## Goal and boundary

A **minimal effects layer** so content records — items, patterns,
events, and later NPCs, merchants, and adventures — can declare
**passive modifiers** (e.g. "+10% recovery while built") and
**triggered ops** (e.g. "on failure: −5 health") as *data*. Effects
modify things; **behaviors** (gather_item, rest, sleep, build_craft —
the `_apply_*` methods) **stay Python**. **No scripting language**: a
closed vocabulary of typed effect entries, validated like everything
else, rendered by the schema-driven editor.

In scope: where effect types are declared, how records carry them, how
the engine applies them, how the editor displays/edits them, and how
they interact with saves/seeds. Out of scope by fiat above: replacing
behaviors with data, user-facing scripting, and any UI beyond what
schema-driven forms already give us.

## Settled constraints (inherited — do not relitigate)

1. **Content is the single source of truth; no fallback values** — a
   bad file fails loudly at load (`content.py` docstring; `load_content`
   raises `ContentError`; `main.py` refuses launch with a dialog).
2. **The editor imports `content.py` only — never `game_core.py`**;
   engine and content modules stay UI-free (HANDOFF "Hard rules" 1–2).
3. **Schema-driven forms**: field lists drive widgets; per-file hand
   layout is banned (EDITOR_BRIEF constraint 2; `content.py SCHEMA`).
4. **File/record/key order is data** (planner order, event draw order,
   seeded RNG); writers never sort keys (EDITOR_BRIEF constraint 4;
   `DEV_GUIDE.md:531`).
5. **The save gate**: a save may list problems but never increase the
   bundle's total count; files with own problems are skipped (D13).
6. **Saves carry identity** (`SAVE_GAME_ID`/`SAVE_VERSION`,
   `game_core.py:726-727`); additive `to_dict` fields keep the version;
   the pinned golden save re-pins deliberately (`DEV_GUIDE.md:478-490`).
7. **Seeded tests and the golden save pin current behavior**; any
   change to draw order, defaults, or serialized shape is a deliberate
   re-pin (`DEV_GUIDE.md:539-540`, `DEV_GUIDE.md:492-524`).
8. **All slices end green + committed**; hard gates (`check_live`,
   `check_fuzz`) must pass, advisory tools (`check_design`) never fail
   the build (exit 0 by design).
9. **Behaviors stay Python; no scripting language** (this brief's
   boundary, above — repeated here because it binds every decision).

## Draft slicing (E1–E5) — DRAFT ONLY, reviewers may re-slice

*(listed near the end; kept here to mirror EDITOR_BRIEF's section order.)*

## Measured facts (verified 2026-10-26, this repo @ 27031a0)

### Every hardcoded effect-like hook in the engine

| Hook | Location | Data source today | Pinned by |
|---|---|---|---|
| Gather behavior | `game_core.py:996-1031` (`_apply_gather_item`) | balance costs `GATHER_ENERGY_COST`/`GATHER_HUNGER_COST` (`:246-247`, applied `:1009-1010`), gather block per-action (item/yield/messages/difficulty), tool bonuses from item records via `TOOL_BONUSES` (`:95-97`, scan `:1024-1028`), success template `.format(amount=…)` `:1030` | `test_smoke.py:181-193` (validation), `:516` (auto-pass yields), `:805-807` (fail = no yield, still XP), `:879` (1-3 base + axe), `:900` (+1 once, copies don't stack) |
| Rest behavior | `game_core.py:1149-1161` (`_apply_rest`) | balance `REST_FOOD_*`/`REST_EMPTY_*` (`:250-256`); eats via `_eat_until_recovered` | `test_smoke.py:632-634` (empty rest +10/+5), `:527-530` (rest eats to full recovery), `:859-864` (two-berry +10% math) |
| Sleep behavior | `game_core.py:1163-1173` (`_apply_sleep`) | balance `SLEEP_*` (`:259-264`); night hunger `+SLEEP_HUNGER_NIGHT` `:1165` | `test_smoke.py:542` (food sleep recovers fully); death/starve sections (FOOD=0 empty-sleep paths) |
| Generalized eating | `game_core.py:1115-1147` (`_eat_until_recovered`) | `FOOD_ITEMS` order from content `food` tiers (`game_core.py:275-283`); Batch-5 user rule (best-first, eat-to-saturation, downgrade, shortfall only when bare) + the review-fix progress guard (`:1130-1141`: bites that cannot move any stat are refused) | `test_smoke.py:544-578` (tier downgrade, shortfall, no-waste), `:582-602` (pantry guard) |
| Build/craft behavior | `game_core.py:1033-1098` (`_apply_build_craft`) | pattern record (skill_req `:1055`, materials committed up-front `:1074-1075`, work progress `:1084-1097`); completion note embeds `pattern.description` `:1090` | `test_smoke.py:846-864` (completion, description surfaces `:857`), `:866-900` (axe craft→gather chain, stacking) |
| Building passive bonus (THE hardcoded effect) | `game_core.py:990-994` (`_recovery`): `lean_to` branch adds `LEAN_TO_RECOVERY_BONUS` | balance key `LEAN_TO_RECOVERY_BONUS` (`game_core.py:240`; `content/balance.json:14`) | `test_smoke.py:859-864` (+32/+50 = ×1.1) |
| Event resolution | `game_core.py:880-945` (`_resolve_event`) | per-event `difficulty` override `:918-919`; `EVENT_XP_SUCCESS`/`FAILURE` `:922-929` (bound `:233-234`); `EVENT_FAILURE_HEALTH` on fail `:930-932` (bound `:235`) | `test_smoke.py:911-947` (named events), `:776-782` (XP awards, health −5), `:757-783` (check display, record-DC regression) |
| Stat-XP hook | `game_core.py:573-580` (run_slot) from `ACTION_STAT_XP` (`:120-124`, built from actions' `stat_xp`) | action record `stat_xp: [stat, int]` | `test_smoke.py:933-939` |
| Difficulty overrides (per-record) | events `:918-919`; gather `cfg.get("difficulty")` `:1014/:1018`; pattern `:1077`; globals `EVENT_DIFFICULTY`/`ACTION_DIFFICULTY` `:230/:232` | record fields (opt) | `:754-761` (event), `:181-193` (gather validation), `difficulty_target` stat-aim block (~`:933`-adjacent; nitpick #5) |
| **`pattern.effect` is display-only** | read by UI at `main.py:418-419` (tooltip) and `main.py:680-681` (picker); **never read by game_core** (grep: zero engine hits) | the string merely *documents* the hardcoded lean-to mechanic (`content/patterns.json:12` vs code `:992-993`) — drift-prone by construction | description pin `test_smoke.py:835`; `DEV_GUIDE.md:170-172` already defers "unify into records when the effects registry lands" |

### RNG draw order per slot (the seeded contract)

`run_slot` (`game_core.py:513-598`) draws in exactly this order:
1. **Event chance** — `self.rng.random() < self.EVENT_CHANCE` at `:533`
   (first draw of every slot).
2. **Behavior check** (non-build paths): one `_skill_check` die
   `randint(1, CHECK_DIE)` at `:974` or `_stat_check` at `:986`
   (aimed by `difficulty_target`, `:1012-1018`).
3. **Yield draw** — `randint(low, high)` at `:1021`, success only.
4. Build/craft check die at `:1077` (replaces 2–3 for those behaviors).
5. **Event pick** — `rng.choice(eligible)` at `:878` (via `_pick_event`,
   `:890`), then **event check die** at `:916` when contributors exist.

`_apply_gather_item`'s docstring (`:1003-1005`) already pins this as
"the seeded contract": costs before any draw, one check draw, one yield
draw on success, tool bonus after with no draw. Tool bonuses
(`:1024-1028`), XP grants (`:561-580`), materials spend (`:1074-1075`),
eating (`:1115-1134`), and completion (`:1084-1097`) draw nothing.
`abort_day` rewinds to the `begin_day` snapshot incl. RNG state
(`game_core.py:483-486` capture, `:632-641` restore), so aborted days
replay identically (`test_smoke.py:650-670`: state equality + identical
replay). House rule: **a new `randint` shifts every seeded sequence**
(`DEV_GUIDE.md:539-540`).

### Save facts

`SAVE_GAME_ID = "dayscheduler_rpg"`, `SAVE_VERSION = 1`
(`game_core.py:726-727`), stamped by `to_dict` (`:733-734`), gated by
`from_dict` (`:786-790`). Golden save:
`tests/fixtures/golden_save.json`, re-pinned only deliberately via
`python tests/make_golden_save.py` (`DEV_GUIDE.md:482-490`,
`test_smoke.py:733-746`). Any effect state the engine gains must be
serialized per the persistence recipe (`DEV_GUIDE.md:469-477`).

### Review-facts section (2026-10-26 external review; all verified in-repo, post-`27031a0`)

- **Pantry drain (fixed; the class matters for effects).** The eat
  loop used to bite until stats saturated — with validator-legal zero
  `REST/SLEEP_FOOD_*` gains it drained the whole pantry for nothing.
  Fixed by a progress guard (`game_core.py:1130-1141`): a bite that
  cannot move health/energy/hunger toward saturation is refused.
  Nets: unit tests (`test_smoke.py:582-602`) and a fuzz variant plus a
  generic pantry-drain invariant in the fuzz play loop (`check_fuzz.py`:
  food may only be consumed while some stat moves toward saturation;
  the sleep probe allows for `SLEEP_HUNGER_NIGHT`). Lesson for the
  effects design: any effect that can zero, cap, or negate recoveries
  reopens this hazard — D1/D5 semantics should keep a progress-style
  guard, and the fuzz net should extend to new appliers.
- **Change reporting is a second pipeline effect ops must feed.**
  `run_slot` builds its summary from `_diff(snapshot)` for item/stat
  deltas **plus** an explicit `xp_changes` list, and the prose note is
  `" ".join(notes)` (`game_core.py:540-596`); events append to both
  inside `_resolve_event` (`:880-945`). An effect op that grants XP or
  items must touch the same channels or the summary shows unexplained
  deltas — E3 must specify the reporting contract, not just the state
  mutation. (D4 covers effect *text*; this is the *summary* channel.)
- **No discriminated-union spec exists.** SCHEMA's vocabulary is
  string/int/number/`opt`/`pair`/`ref`/`dict_int`/`nested`
  (`content.py:95-115` for items) — effect params vary by type, so
  E1's read-only display and E4's editable rows both need a new typed
  effect-list spec tag plus matching editor branches (the Tunables
  sheet has no `list` branch either, `editor.py:259-284`).


### Which balance entries would move onto records (if numbers relocate)

House split rule today (`DEV_GUIDE.md:159-174`): **balance.json =
global knobs; intrinsic values live with their record** — and
`DEV_GUIDE.md:170-172` already names the lean-to branch as the first
thing the effects registry should absorb. Moving a number is a
four-touch cost chain (verified): remove the balance key
(`content/balance.json`), remove it from `BALANCE_TYPES`/`BALANCE_KEYS`
(`content.py:63-81` — a code edit by design, `DEV_GUIDE.md:163-164`),
remove the engine binding (`game_core.py:224-264` block; cross-checked
by `validate_content` `:1242-1252`), and add the record field + SCHEMA
entry (auto-renders in forms and in **Tunables**, below).

| Balance keys (balance.json lines) | Bound at | Consumed at | Natural owning record |
|---|---|---|---|
| `LEAN_TO_RECOVERY_BONUS` (14) | `game_core.py:240` | `_recovery` `:992-993` | the lean_to *pattern*/building — the canonical first effects migration |
| `GATHER_ENERGY_COST`/`GATHER_HUNGER_COST` (15-16) | `:246-247` | `:1009-1010` | each gather action's block (already holds yield + difficulty per-action — the precedent) |
| `REST_FOOD_HEALTH`/`ENERGY`/`HUNGER_NET`, `REST_EMPTY_*` (17-22) | `:250-256` | `_apply_rest` `:1149-1161` | the `rest` action record |
| `SLEEP_HUNGER_NIGHT`, `SLEEP_FOOD_*`, `SLEEP_EMPTY_*` (23-28) | `:259-264` | `_apply_sleep` `:1163-1173` | **no owner record exists** — sleep runs from `complete_day`, not an action (actions.json = gather_food, gather_wood, rest, build, craft), so D3(b) has no home to move these to without inventing one |
| `EVENT_XP_SUCCESS`/`FAILURE`, `EVENT_FAILURE_HEALTH` (10-12) | `:233-235` | `:922-932` | each event record (per-event `difficulty` `:918-919` is the per-record-numbers precedent) |
| Borderline: `ACTION_XP`/`SKILL_XP` (5-6) | `:224-226` | `:562/:568` | per-action XP could localize; global keeps pacing uniform — a D3 question |
| Stays global (curves/RNG/pacing): `MAX_VITAL`, `XP_TO_NEXT`, `XP_COST_STEP`, `CHECK_DIE`, `EVENT_CHANCE` | `:305/:308-310/:229/:238` | various | engine curves and the RNG contract — see D2 |

Already-moved precedents (proof the model works): `tool_bonus` on item
records (`game_core.py:95-97`, scanned `:1024-1028`), per-record
`difficulty` everywhere, pattern `work`/`skill_req`/`materials`.

**Tunables impact** (the editor's aggregate sheet,
`editor.py:236-284`): it walks SCHEMA and shows every int/number
scalar, pair, and dict_int value, recurses `nested` blocks (`:265-269`),
and renders absent difficulty as "(global)" (`:276-277`). Consequences
for effects: (a) a number moved onto a record appears in Tunables
automatically — zero editor work; (b) **there is no `list` branch** in
`_tune_rows` (`:259-284`), so an `effects: [...]` list stays invisible
to Tunables until a slice adds that branch.

## Draft slicing E1–E5 (DRAFT — reviewers may re-slice, merge, or kill)

- **E1 — Registry + validation, data only.** An `EFFECT_TYPES` table
  (type name → parameter specs reusing the SCHEMA spec vocabulary)
  lives in content.py; records may carry typed effect lists; full
  validation (unknown type, bad params, refs resolve from the
  in-memory bundle). SCHEMA gains a typed effect-list spec tag (none
  exists today — see the review-facts section) → the editor shows
  entries read-only once the tag has a field branch. **Nothing applies
  yet** — zero behavior change; golden save untouched. Tests:
  validation mutations.
- **E2 — First application seam: the lean-to migration.** Replace the
  hardcoded `_recovery` branch (`game_core.py:992-993`) with a passive
  effect read from the pattern record (`DEV_GUIDE.md:170-172`'s stated
  target). Gameplay stays byte-equivalent (the +32/+50 pins at
  `test_smoke.py:859-864` must not flinch); `LEAN_TO_RECOVERY_BONUS`
  retires from balance via the cost chain above.
- **E3 — Triggered ops at documented points.** Op vocabulary (grant XP,
  damage/heal, give/consume item …) applied where events and outcomes
  resolve (`_resolve_event` `:880-945`, completion `:1084-1091`) —
  effects execute AFTER existing draws and draw nothing themselves
  (per D2, whichever way it lands). May convert hardcodes like
  `EVENT_FAILURE_HEALTH` into event-record ops.
- **E4 — Editor + Tunables for effect lists.** Editable rows via the
  D16 list machinery **plus** the new spec tag's widget branch (the
  existing list machinery is pair/dict_int-shaped — see the
  review-facts section); Tunables gains the missing `list` branch
  (`editor.py:259-284`); `check_design` gains registry-aware rules.
- **E5 — Shared-state foundation (placeholder).** Whatever NPC
  relationships/merchant stock need: persistence shape, session-vs-
  content split, save-version impact. Deliberately last and
  under-specified — its answer depends on D6.

Each slice ends green + committed; no slice requires a later one.

## Open decisions (D-numbered *in this brief* — options and trade-offs, NO recommendations)

- **D1 — Stacking and order.** When several effects touch the same
  target: (a) same-type don't stack, max wins (the tool_bonus
  precedent, `game_core.py:1022-1027`); (b) additively sum; (c)
  declaration order with first-wins/last-wins; (d) cap the count.
  Also undecided: whether a passive *replaces* or *multiplies* the base
  number, and how passives compose with `_recovery`'s existing
  ×(1+bonus). Rounding belongs to this decision: `_recovery` floors on
  every application (`int(amount * 1.1)`, `:992-993`), so
  sum-then-floor and floor-then-sum give different totals — the pinned
  +32/+50 lean-to numbers (`test_smoke.py:859-864`) depend on which
  wins. Trade-offs: (a) simplest + precedent, but caps design
  space; (b) enables compounding builds, needs balance guardrails;
  (c) interacts with the order-is-data constraints; (d) arbitrary feel.
- **D2 — RNG contract.** (a) Effects may never draw — the draw order
  (chance `:533` → check → yield → event choice `:878` → event check
  `:916`) stays frozen and effects run deterministically after draws
  (safest for seeds, the golden save, and `abort_day` replay
  `test_smoke.py:650-670`); (b) effects may draw from the main rng
  (expressive, but every seeded sequence shifts — `DEV_GUIDE.md:539`
  — and all pins must be re-derived); (c) effects get a separate seeded
  rng (isolated, but a second state to serialize; save implications).
  Trade-offs: expressiveness vs the pinned-seed discipline the whole
  suite rests on.
- **D3 — Where numbers live.** (a) Extend the existing split rule
  (`DEV_GUIDE.md:159-174`): effect params live on records, global
  curves stay in balance, migrate the table above opportunistically;
  (b) move ALL listed balance keys onto owning records in one pass
  (one honest churn, Tunables follows automatically); (c) hybrid —
  migrate only what the first real effects need (lean-to first, per
  `DEV_GUIDE.md:170-172`). Trade-offs: one big migration vs
  incremental churn vs knobs that stay invisible next to their records.
- **D4 — Generated effect text.** (a) Content-provided template strings
  per effect (the gather precedent, `.format(amount=…)` `:1030`);
  (b) engine-built phrases from type+params (centralized voice, no
  author typos); (c) hybrid — engine default, content override. Directly
  entangled with the measured drift risk: `pattern.effect` strings are
  pure UI text today (`main.py:418-419/:680-681`) documenting code that
  can diverge (`game_core.py:992-993` vs `content/patterns.json:12`) —
  this choice decides whether effect text becomes
  generated-from-mechanics (drift impossible) or stays hand-written
  (drift persists).
- **D5 — Eating policy.** Batch-5 rules are code
  (`game_core.py:1115-1147`: best-tier-first, eat-to-saturation,
  downgrade, shortfall only on a bare pantry, plus the review-fix
  progress guard — bites that cannot move health/energy/hunger toward
  saturation are refused). Options: (a) keep the
  eating loop behavior-Python untouched; effects only ADD, while
  restoration numbers may still move to records via D3; (b) rest/sleep
  gains become per-record effects, so the loop's *targets* are
  effect-driven while the loop stays code; (c) encode the loop's
  semantics as data (largest; smells like scripting; conflicts with the
  boundary constraint). Trade-offs: stability of a just-shipped user
  rule vs declarative purity.
- **D6 — When shared state arrives.** NPC relationships, merchant
  stock, adventure progress: (a) defer ALL of it until an NPC/merchant
  slice needs it (E5 stays a placeholder; effects remain per-session,
  derived from content + engine state); (b) scaffold the persistence
  shape now (save fields, additive-field version policy, one golden
  re-pin) so later systems only add appliers; (c) model stock as
  content-declared tables + session deltas from day one. Trade-offs:
  speculative-design risk (b)/(c) vs rework/migration risk (a), plus
  save-size and golden-drift costs.
- **D7 — Absorb `food`/`tool_bonus`, or coexist?** Items already carry
  three separate mechanics: the `food` quality tier (`content.py:112`,
  validation `:380-387`), `tool_bonus` (`content.py:113`, scan
  `game_core.py:1024-1028`), and (eventually) effects. Options: (a)
  coexist — effects add NEW mechanics only, `food`/`tool_bonus` stay
  bespoke (fastest, but three parallel item systems and three editor
  renderings forever); (b) absorb both into effects (one vocabulary,
  but `FOOD_ITEMS` derives eating order from `food` tiers over
  items-file order — `game_core.py:275-283` — so absorbing the tier
  must re-express that ordering, and every validator rule, tooltip,
  and editor form migrates); (c) absorb gradually — effects subsume
  `tool_bonus` first (already effect-shaped: flat bonus, tagged
  target), `food` stays because its ordering semantics are
  load-bearing. Trade-offs: unification vs the four-touch migration
  cost and golden/editor churn.
- **D8 — Triggers and targets are undefined.** Nothing yet says how an
  event separates success- vs failure-side effect sets, how an item
  separates passive-while-owned from on-use, or what "the same target"
  (D1) even names. Options: (a) an explicit `when` field per effect
  entry (e.g. on_success/on_failure/on_use/always — verbose but
  greppable and order-safe); (b) type-implied triggers (the type
  decides when it fires — terse, but an effect type reused in the
  wrong slot fires silently or never); (c) hybrid — type-implied
  defaults with an optional `when` override. Paired decision: a
  **closed target vocabulary** (e.g. `recovery`, `yield:<action_id>`,
  `health`, …) validated like references (`ref`/`dyn_ref` style in
  `content.py`) so D1's stacking has canonical keys and typos fail at
  load.

## Output format (what we want back)

1. **Your slicing** of E1–E5 — agree / merge / split / reorder, with
   reasons. Every slice must end green + committed.
2. **Your D-decisions (D1–D6 above)** with reasons — this brief gives
   options and trade-offs deliberately and recommends nothing.
3. **Risks this draft missed** — especially around seeded-compat, save
   growth, validation gaps, or editor surface area.
4. **Any settled constraint you would challenge** (the nine items in
   "Settled constraints") — flag it explicitly; reopening one needs a
   reason, per the EDITOR_BRIEF precedent.