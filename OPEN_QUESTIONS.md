# OPEN_QUESTIONS.md — design questions outside the briefs

Small questions the active brief doesn't decide, each with a suggested
default so work can continue without blocking. The big forks live in
EFFECTS_BRIEF.md's D1–D6 (and EDITOR_BRIEF.md's D1–D19) — this file is
for the rest.

## Effects layer (raised while writing EFFECTS_BRIEF.md, 2026-10-26)

1. **Where does the effect-type registry live, and how does
   validation see it?**
   Suggested default: an `EFFECT_TYPES` table in `content.py` (type
   name → parameter specs reusing the SCHEMA spec vocabulary), with the
   engine binding appliers the way `BEHAVIOR_HANDLERS` ↔ `_apply_*`
   already works. Rationale: the editor may only import content.py
   (constraint 1), schema-driven forms then render effect params for
   free, and validation stays engine-free. Reviewers may relocate it.

2. **When does the editor get editable effect rows?**
   Suggested default: E1 renders them read-only through existing
   machinery (zero editor work beyond SCHEMA); editable rows land in
   E4 via the D16 list machinery — so validation and engine semantics
   are proven before authors can write effects.

3. **JSON key shape for carrying effects on records.**
   Suggested default: a single `effects` list of typed entries
   (`{"type": "...", ...params}`) rather than separate `passive` /
   `trigger` keys — one rendering path, one validation path, D16
   list-rows render it directly. Reviewers may prefer split keys.

4. **Save-version policy for additive effect state.**
   Suggested default: additive `to_dict` fields keep `SAVE_VERSION`
   (current from_dict defaults-merge design reads old saves fine,
   game_core.py:749-752 docstring); bump only on incompatible shape
   change — consistent with the existing identity gate
   (game_core.py:786-790) and the deliberate golden re-pin rule
   (DEV_GUIDE.md:482-490).

## Answers (round-2 reconciliation, 2026-10-28)

1. **Registry location: `content.py`, as suggested** — `TRIGGERS`/
   `VITALS`/`EFFECT_TYPES`/`LEGAL_EFFECTS` next to `BEHAVIOR_HANDLERS`;
   validation in a new `_check_effects` called from `validate_bundle`
   (plan R9 accepted; brief N1 extends it with the legality table).
2. **Editable rows land in slice E5, ordered *before* E4** (brief
   binding section: final order E1→E2→E3→E5→E4) — authoring usability
   before item-system cleanup; E4's own GUI-test step depends on E5.
3. **Single `effects` list of `{"type": ...}` entries kept** — the
   split `passive`/`trigger` alternative was rejected (plan
   constraint-3 challenge ruling: one list, one rendering path, one
   validation path; `when` distinguishes triggers).
4. **Save policy stands; v1 needs no version bump at all** — effects
   are stateless (no new `to_dict` fields, no golden re-pin; brief
   D6).