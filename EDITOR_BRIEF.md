# EDITOR BRIEF — Phase 2 planning (draft for multi-model review)

Status: draft v3 — adds round-2 inputs (D9–D13 definitions and a
required-coverage list) after a second external pass. Answers and
takes from either round are deliberately NOT included, to keep your
plan independent. Purpose: paste this whole file into 1–2 other
models and ask for *their own* plan and D-decision list — not a
review of this draft. Bring the outputs back;
disagreements get reconciled with stated reasons before implementation
(same method that worked for the content-design rounds).

## Goal

A tkinter content editor for `content/*.json`: browse, edit, validate,
and save content without hand-editing JSON — including files the game
refuses to load (repair mode).

## Settled constraints (do not relitigate — four review rounds decided these)

Round-2 uncontested amendments, adopted: constraint 1's last sentence
is now "open and diagnose any file, and repair whatever parses" (raw
repair deferred); constraint 4 additionally covers key order *within*
records. One challenge remains open — see D13.

1. Editor imports `content.py` ONLY — never `game_core.py`. It must
   open and diagnose any file, and repair whatever parses.
2. Schema-driven forms — field lists drive widgets, not per-file hand
   layout.
3. Validation blocks save — reuse `content.validate_bundle()` /
   `try_load_content()` messages verbatim; never write a file that
   fails validation.
4. JSON writes never sort keys, never reorder arrays, and never
   reorder keys within a record — planner order, event draw order,
   and the seeded RNG read file order (fixture goldens are the
   tripwire), and record key order keeps git diffs to one line.
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
  one-time churn across every content file). Whichever you pick: pin
  it with a `.gitattributes` entry for the content files (this repo
  runs `core.autocrlf=true`) so git can't move the goalposts, and
  handle newlines explicitly in read/write — the `\r\r\n` bug comes
  from mixing translated and untranslated newline handling.
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
2. D1–D8 decisions with reasons; add D9+ if you see missed decisions.
3. Risks or tripwires this draft missed.
4. Any "settled constraint" you'd challenge — flag it explicitly; a
   challenge reopens a decided question and needs a reason.

## Round-1 checklist (required coverage — from an external first pass)

Address each; use D-numbered answers where they open forks:

- **Atomic writes:** temp file in the *same directory* as the target
  (cross-volume replace fails), flush + fsync before `os.replace`; on
  Windows `os.replace` can raise PermissionError while antivirus or
  another editor holds the file — brief retry, then fail loudly;
  delete the temp file on every failure path.
- **Multi-file edits:** stage every affected file, validate the whole
  bundle in memory, only then replace — never leave a half-applied
  set.
- **Duplicate JSON keys:** `json.loads` silently keeps the last one —
  detect with `object_pairs_hook` and fail naming file + key (a
  hand-edit data-loss vector; the game's own loader has the same gap
  today).
- **Encoding:** pin `ensure_ascii=False` explicitly (measured:
  required for byte stability — `items.json` contains an em-dash) and
  UTF-8 end-to-end; include a non-ASCII value in the tests.
- **Float formatting:** `json.dumps` canonicalizes (`0.10` → `0.1`) —
  live content round-trips byte-identical today; decide how the
  byte-stable guarantee is stated for hand-edited non-canonical
  floats.
- **No silent override:** under settled constraint 3, save stays
  blocked on validation errors. If your plan proposes a WIP override,
  that reopens constraint 3 (output format item 4) — and must state
  how the editor warns that the game will refuse to launch.

## New decisions opened by round 1

- **D7 — Item-id rename policy.** Ids are save data (hard rule 4), but
  pre-release saves were explicitly judged expendable (the 0b
  decision). Options: (a) refuse id edits on existing records; (b)
  allow with type-to-confirm, cross-file staging (see checklist), and
  whole-bundle validation; (c) allow with a loud warning. Also state
  how *new* records differ (id editable until first save?).
- **D8 — Duplicate-key detection placement.** Decide *where* it lands:
  a separate pre-2a loader fix (it is a live gap in the game loader,
  in the spirit of hard rule 2), inside 2a's viewer, or in the 2b
  write layer — not *whether*.

## Round-2 additions — definitions only (answer them in your plan)

- **D9 — Save granularity.** What is the unit of save and of
  atomicity: per-file, or Save-All (stage dirty files, validation,
  temp-then-replace, compensation on partial failure)? State exactly
  what is atomic, what is not, and what the safety net is.
- **D10 — Canonical form on save.** Serialization pins (ensure_ascii,
  UTF-8, no NaN/Infinity) and what happens when canonical bytes would
  differ from disk (CRLF, `0.10`, odd indentation): reformat, warn,
  or leave untouched files alone? BOM policy?
- **D11 — Stale-write guard.** The repo may be edited (hand, agent)
  while the editor is open. Detect disk changes since load; define
  save behavior when the buffer and disk have both moved.
- **D12 — Reference sources.** Dropdowns and used-by lists resolve
  from the in-memory bundle or from disk? Is a record added this
  session selectable immediately?
- **D13 — Save-gate granularity (round-2 challenges settled
  constraint 3; still open).** Original rule: bundle-wide
  all-or-nothing gate. Challenge: with problems across several files,
  one-at-a-time repair can never persist progress. Proposed rule: a
  file may be written only when it has no problems of its own; a save
  must never increase the bundle's total problem count; other files'
  problems are listed but do not block; the editor must say plainly
  that the game will not launch until all problems are fixed. Choose,
  reason, and reconcile your choice with your D9 answer.

## Round-2 required coverage (risks)

- Structured problems: file/record/field metadata alongside each
  message, **str-compatible with today's exact message format** (the
  existing suite asserts on substrings of raw problem entries).
- Record key order preserved: edit fields in place, append new keys
  in schema order; acceptance = change one field, save, git diff is
  one line.
- `type(x) is int` discipline (bool is an int) in schema and form
  coercion; empty string vs null vs missing distinguished in forms.
- Viewer and forms render invalid data without crashing (per
  failure-type fixtures in 2a's acceptance).
- Stale temp files: cleaned on start, pattern gitignored.
- Show the target directory in the title bar; make the fixtures
  directory visually distinct.
