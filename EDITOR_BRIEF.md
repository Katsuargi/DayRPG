# EDITOR BRIEF — Phase 2 plan (round-3 reconciled, binding)

Status: v4 — RECONCILED and binding. Two external passes received
(round-1 reaction; round-2 full plan); every decision D1–D13 is
closed in "Round-3 reconciled decisions" below. Definitions and both
rounds' takes remain for provenance; a new external round happens
only if a decision is reopened. For that: paste this whole file into
1–2 other models and ask for *their own* plan and D-decision list —
not a review of this draft. Bring the outputs back;
disagreements get reconciled with stated reasons before implementation
(same method that worked for the content-design rounds).

## Round-3 reconciled decisions (binding)

Two external passes received (round-1 reaction; round-2 full plan).
Verdicts below — the definitions and both rounds' takes above stay for
provenance. **Slicing adopted** (round-2 structure): 2a-0 loader
hardening → 2a viewer + schema table → 2b headless write layer → 2c
items forms (with dirty tracking + unsaved guard, moved from 2e) →
2d remaining files (round-2's four sub-slices; moving events earlier
is execution-time latitude) → 2e shrunk (parse-error line/column,
external-open button, Run-check spawning check_live.py — which gains
a directory argument and runs off the UI thread).

- **D1:** schema table **in `content.py`** (precedent:
  BEHAVIOR_HANDLERS lives there for the editor; constraint 1 keeps its
  letter). Validator not rewritten to consume it — field-mutation
  drift tests in 2a instead (wrong-type/missing per field must make
  the validator complain; every live record must conform). Schema
  carries `order_sensitive` flags and a `ref(file)` type.
- **D2:** LF everywhere. `.gitattributes` `text eol=lf` for content +
  fixtures — index already `i/lf` (verified) ⇒ zero repo churn; the
  working tree flips CRLF→LF once, invisible to git. Writers emit
  bytes explicitly (assert: no `\r` in saved files); readers accept
  CRLF.
- **D3:** standalone `python editor.py`; a later in-game button may
  spawn it as a subprocess but never imports it (a button would be
  unreachable exactly when the editor is needed).
- **D4:** raw pane deferred; parse errors get line/column +
  open-external + reload.
- **D5:** up/down buttons only; new/duplicates append at the end;
  reorder banner names the remedy: "seeded results will shift —
  re-pin the fixture deliberately".
- **D6:** headless `test_content_write.py` + display-skipping
  `test_editor_gui.py`; test_smoke spawns both (check_live pattern).
- **D7:** existing ids immutable in the editor; "Duplicate as new";
  new-record id editable until first save (lowercase slug, unique);
  deletes of referenced records blocked with a used-by list;
  cross-bundle rename deferred to a headless op until actually needed.
- **D8:** duplicate keys ⇒ file unparseable (ambiguity); fixed in the
  shared loader in 2a-0 — the game inherits the fix.
- **D9:** reworded per D13: Save-All stages only dirty files with no
  own problems, validates the in-memory bundle, writes only if the
  total problem count would not increase, then temp→replace per file
  with in-memory-byte compensation on partial failure; untouched
  files never rewritten; stated plainly: not atomic across files —
  git is the safety net.
- **D10:** canonical form on save (`ensure_ascii=False`, UTF-8,
  `allow_nan=False`, int/float types preserved); warn when
  canonicalizing would reformat beyond the edit (`0.10`, odd
  indentation); BOM stripped on load (utf-8-sig, 2a-0) with notice.
- **D11:** per-file hash at load; save refuses if disk changed —
  clean buffer: reload/cancel; dirty buffer: reload-discard /
  overwrite-confirmed / cancel. Check→replace TOCTOU accepted (git is
  the net).
- **D12:** all dropdowns/refs/used-by resolve from the in-memory
  bundle (same-session adds usable immediately).
- **D13:** **challenge upheld** — constraint 3 amended (above).
  Reason: the all-or-nothing gate already exists where it matters —
  `main.py`'s startup gate refuses launch on any problem; save-time
  rules only need to prevent regressions while letting incremental
  repair persist.
- **Problem type:** `class Problem(str)` carrying `file`/`record_id`/
  `field` — messages byte-identical, so existing substring
  assertions, check_live prints, and ContentError need no changes.
- **bool/int:** all 9 numeric validator sites already exclude bools
  (verified); `type(x) is int` binds new schema + form code.

### 2d design decisions (round 4 — user-approved after second-opinion review)

- **D14 — Layout per file.** `SCHEMA[file]["layout"]` = `"inline"` |
  `"pane"`. Inline: items, skills, stats, balance, events (deliberate
  exception — its only nested piece is a short ref list, so the rule's
  purpose, "scrolling hides the fields you're editing", cannot trigger
  there). Pane: actions (checks + gather, genuinely tall), patterns
  (materials grows with every item). Browsing stays the stacked
  read-only viewer for every file; the flag switches only the Edit
  mount. Pane v1 = one record at a time (header + Done + form + ref
  rows), NO in-pane record selection — navigation stays the proven
  browse/Edit toggle.
- **D15 — Unsaved-work navigation: visibility, not prompts.** Forms
  write through to the bundle every keystroke (that is why file
  switches never prompt) — the bundle IS the draft, so selection
  changes lose nothing. Rule: no prompt, no per-record drafts, no
  blocking; instead a per-record ● indicator (session set fed by form
  edits, cleared on save/reload) on block and pane headers. Guard
  scope unchanged (Reload/close). Recorded fallback: if pane
  navigation ever feels loose, reuse `_confirm_discard` on selection.
- **D16 — Nested editors are sub-components of RecordForm.** `nested`
  → labeled group + recurse the same dispatcher (gather); `list` →
  rows (member widget per `spec[1]`, e.g. checks = [enum combo,
  dyn_ref combo]) with add/remove/↑↓; `dict_int` → (ref combo, int)
  rows with add/remove ONLY — no reorder, so materials key order is
  written back unchanged (constraint 4). dyn_ref options filter by the
  row's sibling field; nullable fields gain a "(none)" option stored
  as null. Ref options resolve from the in-memory bundle (D12). New
  form handle: `form.rowvars[field] -> list[list[Variable]]`.
- **D17 — Tests against the form model.** Assertions drive
  `form.vars`/`rowvars`, `bundle`, `dirty`, `problems`, and recorded
  dialogs; widgets are asserted only for existence/invariants (e.g.
  zero input widgets before Edit), never for value flow — layout
  changes must not be able to break tests. 2d acceptance per file
  (six files): one edit→save→reload + one blocked-bad-edit,
  model-first.

## Goal

A tkinter content editor for `content/*.json`: browse, edit, validate,
and save content without hand-editing JSON — including files the game
refuses to load (repair mode).

## Settled constraints (do not relitigate — four review rounds decided these)

Round-2 amendments, adopted: constraint 1's last sentence is now
"open and diagnose any file, and repair whatever parses" (raw repair
deferred); constraint 4 additionally covers key order *within*
records; and the D13 challenge was UPHELD — constraint 3 below
carries the amended save rule (reasons in Round-3 decisions).

1. Editor imports `content.py` ONLY — never `game_core.py`. It must
   open and diagnose any file, and repair whatever parses.
2. Schema-driven forms — field lists drive widgets, not per-file hand
   layout.
3. Validation blocks save — reuse `content.validate_bundle()` /
   `try_load_content()` messages verbatim. A file is written only
   when it has no problems of its own; a save must never increase the
   bundle's total problem count (counted on would-be disk state);
   other files' problems are listed but don't block; the editor must
   state plainly that the game won't launch until all problems are
   fixed. (Amended round-3: bundle-wide all-or-nothing was the
   original rule; the round-2 challenge was upheld — see D13.)
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
  → **Decided round-3:** reworded to match D13 — full rule in the
  Round-3 decisions section.
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
- **D13 — Save-gate granularity. DECIDED round-3: challenge upheld.**
  The original bundle-wide all-or-nothing rule lost to the round-2
  challenge: with problems across several files, one-at-a-time repair
  could never persist progress. The amended rule now lives in
  constraint 3 — own-clean per file, never-increase total, others
  listed-not-blocking, launch-warning stated — while bundle-wide
  all-or-nothing remains enforced by the game's startup gate, which
  is where it matters.

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
