# HANDOFF — Day Scheduler RPG (session transfer, Phase 1 complete)

This doc captures where the project stands and what's next, for a fresh
session in a new location. **Day-to-day working knowledge lives in
`DEV_GUIDE.md`** — read its file table and feature map first if you're
new to the current architecture. This file is only session memory:
roadmap, pending decisions, and how this collaboration works best.

## Current state

**Phases 0a, 0b, and 1 are complete and fully green.** Game content lives
in `content/*.json` (items, skills, stats, actions, patterns, events,
balance) — the single source of truth. `game_core.py` loads it
strictly at import (no fallback: a bad file raises
`ContentError` naming file+field, and `main.py` refuses to launch with
a dialog). Tooltips moved into the data records. Tests pin engine
behavior to `tests/fixtures/content/` via `DAY_SCHEDULER_CONTENT_DIR`.

**Phase 1 (behavior dispatch + generic gather) is complete.** Every
action carries a `behavior` field (keys of `content.py`
`BEHAVIOR_HANDLERS`); `game_core` derives `ACTION_BEHAVIOR` and
dispatches on it — `_apply_action` resolves `_apply_<behavior>`
directly (no id ladder), `run_slot` routes `build_craft` (a
`BUILD_CRAFT` constant) through the pattern picker, and `_apply_rest`
now returns `(True, note)` like every handler. `HANDLED_ACTIONS` was
deleted — obsolete once dispatch is behavior-keyed.

Gather is fully parameterized: the `gather_food`/`gather_wood`
behaviors collapsed into one `gather_item` behavior whose handler
(`_apply_gather_item`) reads a per-action `gather` block (item, yield
[min,max], success/fail messages with `{amount}`, optional
`tool_bonus` [tool id, flat] and `difficulty` override). The five
gather balance keys (`FOOD_*`, `WOOD_*`, `AXE_WOOD_BONUS`) moved into
those blocks; shared costs stay in balance.json. **A new gather kind
(Gather Metal) is now pure content** — new item + skill + action
record, zero Python — proven both success and fail paths. Validation
(`_check_gather`) pins every field, cross-refs items and tool
patterns, and rejects malformed `{amount}` templates. RNG order
untouched (costs → one skill check → one yield-on-success → bonus);
seeded outputs byte-identical. No save-format change: the planner
still stores action ids (event `actions` lists still name those ids).

**0b (slug item ids):** item ids are lowercase slugs (`berries`,
`wood`, `herbs`, `stone`); pattern `materials` keys likewise. Player
facing strings come from each item's `name` field through
`game_core.ITEM_NAMES` (same pattern as STAT_NAMES/SKILL_NAMES) —
`_diff()`, `aggregate_changes()`, the inventory panel, and the pattern
picker all map through it, so no display string changed. No save
migration, per decision: `from_dict` merges defaults, so a stale save
loads but keeps old-named stray keys. Fixture re-pinned in the same
change; the item-order golden is now
`("berries", "wood", "herbs", "stone")`. A follow-up check enforces the
slug shape on all six id families — messages name file, id, and rule.

**Git is set up** (the point of the folder move): `origin` =
https://github.com/Katsuargi/DayRPG on branch `main`; commit small and
often. Pre-0b baseline: `b20a60c`.

Verify any fresh checkout/session with:

```
python test_smoke.py    # content gates + goldens + loader errors + engine + GUI
python check_live.py    # LIVE content: full validation + 9 seeded days
python main.py          # startup gate runs check_live's function first
```

All three were green at the 0b handoff, failure paths proven
deliberately (corrupted content → exit 1 naming the bad key). Seeded
values are identical run-to-run; the GUI smoke engine is unseeded by
design, so its inventory line varies per run — that's expected.

## Roadmap and pending decisions

Ordered; phases have one concern each (a failure has one suspect).

### Next: editor (phases 2+), then deferred design work

- **Phase 2 planning lives in `EDITOR_BRIEF.md`** — sliced 2a–2e
  with D1–D13 all decided (round-3 reconciled, binding section at the
  top of the brief; measured facts and both rounds' takes retained for
  provenance). **2a-0 (loader hardening) is done and green**: duplicate
  keys and non-finite numbers refuse at parse (file + token named),
  UTF-8 BOM tolerated, problems are `Problem` (str subclass with
  `.file`/`.record_id`/`.field`), `.gitattributes` pins content to LF
  (zero repo churn — verified by empty diff). **2a is done**: the
  read-only viewer (`python editor.py [dir]`) renders all seven files
  from the `content.py` SCHEMA (`order_sensitive` + ref/dyn_ref
  types), problems click through to records, the fixtures directory
  is flagged, schema drift is pinned by mutation loops in test_smoke,
  and editor.py holds no write code (grep-verified). Next: 2b —
  headless write layer (D9 Save-All, D11 stale guard, D10 canonical
  form, `test_content_write.py`). The user wants to nitpick viewer
  UX before forms build on it.
- **Viewer nitpick #1 (completed difficulty):** every check site now
  takes an optional record-level `difficulty` — patterns and events
  gained it (gather already had its block field); the globals in
  balance.json stay the defaults. Content left unchanged, so seeded
  output stays byte-identical (proven by the suite). The viewer shows
  the new fields through SCHEMA with zero viewer code.
- **Viewer nitpick #2 (gather rendering):** opt-wrapped nested specs
  rendered as one raw dict string, hiding the gather sub-rows (incl.
  difficulty). Fixed by unwrapping opt/nullable before the nested
  branch; the GUI test pins the sub-header + difficulty row.
- **Viewer nitpick #3 (effect location — decided):** effects stay with
  their records; balance.json keeps global knobs only (split rule
  documented in DEV_GUIDE). The viewer gained a read-only **Tunables**
  toolbar view aggregating every number across files for wholesale
  balance reviews. Centralizing bonuses into balance was rejected:
  BALANCE_KEYS is code-gated — it would break zero-Python additions
  and editor-only content creation; lean-to's amount defers to the
  effects registry phase.
- **Viewer nitpick #4 (tools are items — decided):** crafted tools now
  live in items.json as inventory records (`wood_axe`), not a separate
  `engine.tools` table (legacy saves fold their tools into inventory
  on load). The bonus moved onto the tool's item —
  `tool_bonus: ["gather_wood", 1]` — and a gather action scans
  inventory for items tagged with its own id, applying the HIGHEST
  amount (copies never stack; tier numbers deferred until merchants
  need pricing). Craft pattern ids must be item ids (validated); the
  GUI tools panel, check_live invariants, and ITEM_ORDER golden
  updated. Seeded outputs stayed byte-identical.
- Editor architecture was reviewed across four multi-model rounds —
  see the DEV_GUIDE closing note (editor reads `content.py` ONLY, never
  `game_core.py`) and these rules: schema-driven forms, validation
  blocks save, JSON writes must never sort keys.
- **Deferred until needed:** effects registry (when merchants/NPCs need
  structured effects), NPC/merchant/adventure systems (new design
  territory — plan when reached), Ren'Py port (planned separately: the
  engine already loads content directly, so only the display layer
  swaps).
- **Stronger-model planning candidates (user's call):** effects
  registry, the Ren'Py port, NPC/merchant system design, and (optional)
  the editor's file-write layer (atomic writes, dirty-state, no-sort
  discipline). Decided NOT needed for 0b or Phase 1.

## How this collaboration works best

- **Timeout lesson:** two prior runs died at ~2435s, both inside single
  huge thinking blocks before any file write. What worked: lean
  thinking, small batched edits (keep tool inputs modest, ~6k chars),
  verify after every step, checkpoint often. Prefer doing over
  deliberating once a design is agreed.
- **Lost-response continuation:** a crashed client mid-turn does NOT
  stop the agent loop — tool calls still execute server-side; only the
  reply is lost. A finished-looking commit nobody remembers making is
  usually this (every commit carries the configured git identity
  either way — authorship proves nothing). After any crash: check
  `git log` / `git status` / reflog and read file state before
  re-running batches — never assume work didn't happen. Pushes are
  user-directed: the agent pushes to origin only when explicitly
  asked (first push: 2026-10-23, user-requested).
- **Round-end ledger:** after every green checkpoint commit, append
  one line to `PROGRESS.md` (date | checkpoint | hash | tests) and
  commit it as `PROGRESS: <checkpoint>` — a follow-up commit, because
  the work's hash must exist before the line can name it. Docs-only
  commits are logged too, marked docs-only.
- **On design forks:** ask with the question tool, 2–3 options, marked
  recommendation — before any long deliberation.
- **Multi-model habit:** the user runs plans by 2–3 models. Best
  artifact for that: have each model produce an *independent artifact
  to diff* (e.g. a migration matrix) rather than "review this plan" —
  disagreement between artifacts is where hidden edge cases live.
- **Review rounds worked** (content design went through 4): design →
  independent critique → reconcile with stated reasons → final plan.
  Keep decisions explicit (D-numbered lists worked well).

## Hard rules (don't regress these)

1. `game_core.py` and `content.py`: **no UI imports, ever** — headless
   tests depend on it; the editor must import `content.py` only.
2. **No fallback on bad content** — loud failure naming file+field.
3. **Never write content JSON with sorted keys** — planner order, event
   draw order, and seeded RNG read file order (goldens are the
   tripwire).
4. **Ids are save data** — pattern/item/event/action ids never get
   renamed casually (the 0b item rename was the one deliberate
   exception; display names were held constant via `ITEM_NAMES`).
   Ids are lowercase slugs (`[a-z][a-z0-9_]*`) — `content.py`
   validation rejects anything else, naming file, id, and rule.
5. **New engine state ⇒ `to_dict` + `from_dict` with defaults.**
6. Every content change: `python test_smoke.py` (includes the live
   gate); re-pin the fixture deliberately when engine tests should
   notice the change.

