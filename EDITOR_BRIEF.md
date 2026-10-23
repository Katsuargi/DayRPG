# EDITOR BRIEF — Phase 2 planning (draft for multi-model review)

Status: draft v1, awaiting independent critique. Purpose: paste this
whole file into 1–2 other models and ask for *their own* plan and
D-decision list — not a review of this draft. Bring the outputs back;
disagreements get reconciled with stated reasons before implementation
(same method that worked for the content-design rounds).

## Goal

A tkinter content editor for `content/*.json`: browse, edit, validate,
and save content without hand-editing JSON — including files the game
refuses to load (repair mode).

## Settled constraints (do not relitigate — four review rounds decided these)

1. Editor imports `content.py` ONLY — never `game_core.py`. It must be
   able to open and repair files the game refuses to load.
2. Schema-driven forms — field lists drive widgets, not per-file hand
   layout.
3. Validation blocks save — reuse `content.validate_bundle()` /
   `try_load_content()` messages verbatim; never write a file that
   fails validation.
4. JSON writes never sort keys, never reorder arrays — planner order,
   event draw order, and the seeded RNG read file order (fixture
   goldens are the tripwire).
5. Engine stays headless; editor is display + "ask the user" only.
6. Every slice keeps `python test_smoke.py` and `python check_live.py`
   green.

## Measured facts (verified 2026-10-23, this repo)

- All seven live content files are CRLF-encoded.
- Every file round-trips **byte-identical** through
  `json.dumps(indent=2, ensure_ascii=False)` + trailing newline (after
  CRLF normalization). A load→save of an unedited file can therefore be
  a no-op — the strongest possible write-layer acceptance test.
- `try_load_content()` already returns `(bundle, problems)`: schema
  problems come back alongside a usable bundle; `bundle is None` only
  for missing/unparseable files. Repair UI has a seam to build on.

## Proposed slicing — one concern each

**2a — Read-only viewer.** Open a content dir; browse all seven files;
render records and the validation problem list. No write code exists.
Acceptance: opens live content (0 problems); opens a deliberately
broken copy and shows problems instead of crashing.

**2b — Write layer (headless module).** `save(bundle, dir)`: atomic
(temp file + `os.replace`), byte-stable round-trip, refuses to save a
bundle failing `validate_bundle`, preserves key/array order, defined
line-ending policy (D2). No tkinter. Acceptance: load→save bytes
identical for all seven files; saving a broken bundle raises with the
problem list; a crash mid-write leaves the original intact (monkeypatch
the replace step to prove it).

**2c — Forms for the simplest file (items.json).** Schema-driven record
editor proven on one flat-schema file: list/edit/add/remove/reorder
records (reorder is deliberate UI — order is display + RNG sensitive),
live problem display, save through 2b. Acceptance: edit→save→reload
round-trips; a bad edit (empty name, bad start) blocks save naming the
problem; fixture goldens untouched.

**2d — Extend forms to the remaining six files.** actions (nested
`checks`, `gather` block), patterns (`materials` dict), events,
skills/stats (dict-keyed), balance (flat exact-key set). Mostly widget
mapping; may split per file type if a chunk grows. Acceptance per
file: one edit→save→reload test + one blocked-bad-edit test.

**2e — Repair mode + lifecycle.** Unparseable JSON → raw-text editing
fallback with re-validate; dirty-state tracking and unsaved-changes
guard; optional launch integration from main.py (D3). Acceptance:
corrupt a file by hand → open in editor → fix → save →
`check_live.py` green.

Each slice ends green + committed; no slice depends on a later one.

## Open decisions (attack these — D-numbered answers please)

- **D1 — Schema source for forms.** (a) explicit per-file schema table
  in `content.py` (single source; editor + future tools read it);
  (b) derive field lists from valid sample records; (c) per-file widget
  code in the editor. Trade-offs: (a) is honest shared-layer work but
  grows content.py; (c) violates the schema-driven rule.
- **D2 — Line-ending policy on write.** Preserve each file's existing
  EOLs (byte-stable, zero churn) vs normalize all to LF (cleaner git,
  one-time churn across every content file).
- **D3 — Launch integration.** Standalone `python editor.py` vs a
  button in main.py vs both.
- **D4 — Raw-text repair in the first ship?** 2e's unparseable-file
  fallback could slip later if schema-problem repair (which falls out
  of 2c/2d for free) covers the real-world cases.
- **D5 — Reorder UX.** Up/down buttons vs index field vs drag — order
  is display order AND RNG input; what makes accidental reorder hardest?
- **D6 — Test placement.** Append to test_smoke.py (already ~600
  lines) vs a new `test_editor.py` spawned by test_smoke, mirroring
  how check_live is spawned.

## Non-goals (deferred by the roadmap)

Effects registry, NPC/merchant/adventure content, balance formula
editing (numbers only for now), theming beyond main.py's palette.

## Output format

1. Your slicing of 2a–2e (agree / merge / split — with reasons).
2. D1–D6 decisions with reasons; add D7+ if you see missed decisions.
3. Risks or tripwires this draft missed.
4. Any "settled constraint" you'd challenge — flag it explicitly; a
   challenge reopens a decided question and needs a reason.
