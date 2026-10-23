# HANDOFF — Day Scheduler RPG (session transfer, 0b complete)

This doc captures where the project stands and what's next, for a fresh
session in a new location. **Day-to-day working knowledge lives in
`DEV_GUIDE.md`** — read its file table and feature map first if you're
new to the current architecture. This file is only session memory:
roadmap, pending decisions, and how this collaboration works best.

## Current state

**Phases 0a and 0b are complete and fully green.** Game content lives
in `content/*.json` (items, skills, stats, actions, patterns, events,
balance) — the single source of truth. `game_core.py` loads it
strictly at import (no fallback: a bad file raises
`ContentError` naming file+field, and `main.py` refuses to launch with
a dialog). Tooltips moved into the data records. Tests pin engine
behavior to `tests/fixtures/content/` via `DAY_SCHEDULER_CONTENT_DIR`.

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

### Next: Phase 1 — generic `gather_item` handler (own phase; no stronger model)

The contract is precise; implement exactly this: `actions.json` gains a
`behavior` field (registry vocabulary already in `content.py` →
`BEHAVIOR_HANDLERS`; dispatch still keys on action ids until this phase
switches it). RNG draw order must be byte-identical:

1. costs (energy -, hunger +, clamped) BEFORE any draw;
2. exactly one `randint(1, CHECK_DIE)` skill check per attempt;
3. exactly one yield `randint(min, max)`, only on success;
4. tool bonus applied after yield — no RNG draw.

**Acceptance:** seeded suite passes unchanged (no fixture re-baseline
for this phase) and cost-on-failure semantics preserved — the
starvation test (seed 51, `ACTION_DIFFICULTY=999`) is the guard for
"death is reachable". After Phase 1: optional hand-edit checkpoint —
**the user has explicitly said they WANT the editor**, so treat the
checkpoint as optional and the editor phases as on the roadmap.

### After that: editor (phases 2+), then deferred design work

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

