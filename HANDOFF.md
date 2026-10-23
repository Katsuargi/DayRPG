# HANDOFF — Day Scheduler RPG (session transfer, 0a complete)

This doc captures where the project stands and what's next, for a fresh
session in a new location. **Day-to-day working knowledge lives in
`DEV_GUIDE.md`** — read its file table and feature map first if you're
new to the current architecture. This file is only session memory:
roadmap, pending decisions, and how this collaboration works best.

## Current state

**Phase 0a (content migration) is complete and fully green.** Game
content lives in `content/*.json` (items, skills, stats, actions,
patterns, events, balance) — the single source of truth. `game_core.py`
loads it strictly at import (no fallback: a bad file raises
`ContentError` naming file+field, and `main.py` refuses to launch with
a dialog). Tooltips moved into the data records. Tests pin engine
behavior to `tests/fixtures/content/` via `DAY_SCHEDULER_CONTENT_DIR`.

Verify any fresh checkout/session with:

```
python test_smoke.py    # content gates + goldens + loader errors + engine + GUI
python check_live.py    # LIVE content: full validation + 9 seeded days
python main.py          # startup gate runs check_live's function first
```

All three were green as of the 0a handoff, including failure paths
proven deliberately (corrupted content → exit 1 naming the bad key).

### Moving the folder

Safe: there are **no absolute paths anywhere** (verified — everything
resolves from `Path(__file__)`). Move the folder, run the two commands
above, done. Then, when convenient: `git init` + a private remote
(`.gitignore` already exists: `__pycache__/`, `*.pyc`,
`screenshot.png`). The project previously lived under
`AppData\Local\Cline\` — an app-data folder that a Cline reset could
delete; that's why it's moving.

## Roadmap and pending decisions

Ordered; phases have one concern each (a failure has one suspect).

### Next: 0b — slug item ids (ORDINARY WORK — no stronger model needed)

Rationale for doing soon: item references in the data files are still
minimal; every later content entry adds a rename target.

- Grep pass for hardcoded item strings: `FOOD_ITEM`/`WOOD_ITEM`
  constants, behavior methods, `main.py`, `test_smoke.py`, DEV_GUIDE
  examples (`"Wood"`, `"Berries"`, `"Herbs"`, `"Stone"`).
- `items.json` → slug ids (`"berries"`) + `name` field for display
  (display strings must stay unchanged: change lists, summaries).
- **No legacy save map, no save-format changes at all.** Decision: no
  saves exist worth protecting (pre-release, solo dev). `from_dict`
  already merges with defaults, so a stale save stays loadable-but-
  messy rather than crashing. Real migration machinery gets written at
  the first migration we actually need (trivial then; git history will
  show the format).
- Gates: re-pin fixture (`content/` → `tests/fixtures/content/`), update
  fixture goldens in the same change, full suite + `check_live.py` green.

### Then: Phase 1 — generic `gather_item` handler (own phase; no stronger model)

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
   renamed casually (0b's item rename is the one deliberate exception,
   display names held constant).
5. **New engine state ⇒ `to_dict` + `from_dict` with defaults.**
6. Every content change: `python test_smoke.py` (includes the live
   gate); re-pin the fixture deliberately when engine tests should
   notice the change.

