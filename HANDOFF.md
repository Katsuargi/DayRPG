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
  and editor.py holds no write code (grep-verified). **Viewer UX signed
  off (2026-10-23):** click-throughs work, economy tab approved, no
  mechanical adjustments wanted at this stage. **2b is done and
  green**: the headless write layer lives in `content.py` —
  `try_load_content_with_state()` (core loader: one read per file, sha256
  + decode from the same bytes; `try_load_content()` delegates, zero
  ripple) plus `save(content, path, *, state, dirty, overwrite_stale)` →
  `SaveResult(written, skipped, reformatted, problems)`. Constraint
  3/D13 gate: files with own problems are skipped-not-fatal, the total
  problem count may never grow (`ContentError` with the list), so
  incremental repair persists. D11: `StaleWriteError` names changed
  files; `overwrite_stale=True` is the confirmed overwrite. D10:
  canonical bytes-mode writes (LF, no BOM, `ensure_ascii=False`,
  `allow_nan=False`, indent 2 + trailing newline — bytes avoid the
  Windows `newline=` trap); non-canonical originals (CRLF, `0.10`, odd
  indent, BOM) land in `reformatted` as notices. D9: same-dir `.tmp` +
  `os.replace`, pre-save bytes restored on partial failure
  (monkeypatch-proven), untouched files never read for rewrite, not
  atomic across files (git is net). Acceptance: `test_content_write.py`
  9 sections, spawned by test_smoke (D6). Loader side-effect: an
  invalid-UTF-8 file now yields a Problem instead of a crash (completes
  constraint 1's "diagnose any file"). **2c is done and green** — hybrid
  forms per the user's second-opinion round: records render read-only
  by default; Edit mounts `RecordForm` (schema-driven widget mapping —
  scalar/enum/ref/pair; hover-wheel returns "break" so scrolling over a
  readonly Combobox can never change its value; edits write straight
  into the bundle's record dicts, so display == saveable state). Dirty
  = explicit stem set fed by edits → Save-All → `content.save()`;
  unsaved guard on Reload/close ONLY (file switching is safe — edits
  live in memory); D11 dialogs on StaleWriteError (overwrite /
  reload-discard / cancel); live revalidation per keystroke refreshing
  panels only (focus-safe). Record ops for array files: Add (schema
  defaults, auto-opens editing, id slug-editable until first save),
  Duplicate (appends, D5), ↑/↓ (D5 seed banner once per file), Delete
  (D7 — blocked by the INCOMING `collect_references` edges: deletion
  breaks whoever references you, not your own outbound refs). Fixed en
  route: `ALERT_FG` was referenced but never defined (latent NameError)
  and record-pane hover-scroll only bound at build time (rebinds after
  every render now). Acceptance in `test_editor_gui.py` with dialogs
  patched headless: edit→save→reload round-trip, bad edit blocks
  naming the problem (bad start + empty name), fixture goldens
  untouched. Master-detail layout + fat-record editors deferred to
  **2d** — the RecordForm seam makes that a mount-point swap, not a
  rewrite. **2d is done and green** (decisions D14–D17 recorded in
  EDITOR_BRIEF, round 4): per-file `SCHEMA[file]["layout"]` — pane for
  actions/patterns, inline for the rest (events = deliberate
  exception); pane v1 = one record at a time (header + Done + form +
  ref rows), a jump is browse intent that unmounts it, and the
  browsing architecture is unchanged for every file. D15: the ●
  per-record mark (session set, in-place header update, cleared on
  save/reload) replaced navigation prompts — write-through forms make
  selection free, per the approved second-opinion round. D16
  sub-components all live on RecordForm: `nested` → child RecordForm
  in a LabelFrame (absent blocks attach on first edit — opening a form
  never mutates the bundle), `list` → rows with add/remove/↑↓ chrome
  and dyn_ref sibling-filtered dropdowns, `dict_int` → (ref, int) rows
  add/remove only (constraint 4: key order preserved; duplicate keys
  collapse visibly, never silently), nullable → "(none)" ↔ null. New
  handles: `form.rowvars`, `form.groups`. Acceptance ×6 files,
  model-first (D17): bad edit blocks + repair + edit→save→reload + ●
  lifecycle, dialogs patched headless; full suite green. **2d-ops is
  done and green** (D18–D19, brief round 5): all four record ops
  extended to dict-kind files — key = identity, unsaved dict records
  get a synthetic editable id row (order-preserving rename,
  uniqueness-guarded against clobbering, sets/forms/blocks/pane all
  retargeted); `_live_id` + `_record_rename` resolve stale button
  closures after ANY rename, which also fixes the latent array-id gap
  from 2c. Defaults learned by the tests: nullable keys ship `null`
  (the engine reads `entry["stat_xp"]` with `[]`) and required
  containers ship `[]`/`{}` — `checks` must exist. THE acceptance is
  the user's fishing pass verbatim, model-first: add skill `fishing`
  → add item `fish` → add `go_fishing` (behavior `gather_item`,
  same-session skill/item dropdowns, gather child form) → add
  `fishing_rod` with a tool_bonus pair → one Save-All → reload →
  every link and the collect_references edge intact. **2e is done and
  green — Phase 2 (the content editor) is COMPLETE**: per D4 (raw
  pane deliberately deferred — correcting this line's earlier "raw
  text fallback" wording, which contradicted the binding decision) the
  repair flow is: parse errors carry STRUCTURED `.line`/`.column` on
  Problem (derived by regex, message bytes untouched), the unusable
  view lists the selected file's parse problems plus the flow hint,
  **Open external** hands that file to the OS default editor, **Reload**
  picks the fix up, and Save-All re-canonicalizes (D10 notice fires
  for non-canonical external fixes). **Run check** spawns
  check_live.py against the OPENED directory — check_live gained an
  optional dir argument (no-arg default unchanged; the D6 spawn and
  startup gate are unaffected) — waited on a worker thread and
  reported via `root.after`, so the UI never blocks. D3 was already
  decided (standalone; a later in-game button may spawn, never
  import) — nothing else to build there. Acceptance green in
  test_editor_gui: corrupt → structured line/column → open-external
  (patched) → external fix → reload → edit → Save-All canonical →
  `check_live.py <repaired-dir>` exits 0. Roadmap after Phase 2: the
  deferred list above (effects registry, NPCs/merchants, Ren'Py port)
  plus any viewer/editor nitpicks the user raises.
- **Claude review round (2026-10-26):** second-opinion code review
  triaged against source — 3 findings were stale (2e's Run-check had
  landed but not yet pushed), 2 were decided behavior (D13's count
  gate; the stray-save-keys tolerance recorded above), the rest real
  and verified line-by-line. **Batch 1 done (this round):** event-DC
  display now prints the record's own DC (+ regression test),
  editor Save-All catches OSError into a dialog (no traceback),
  save compensation can no longer mask the original failure,
  `.gitignore` covers `saves/` and `.*.json.tmp`, the GUI test skips
  cleanly when tkinter isn't installed, DEV_GUIDE's fish tooltip
  stopped claiming "Food". **Pending batches:** **2** — per-key
  balance int/float typing (validator + SCHEMA ⇒ editor auto-types)
  and the build_craft ⇒ id ∈ PATTERN_KINDS validation rule, with
  mutation tests; **3** — save identity (game/version checks,
  wrong-shape ValueError, negative golden tests + a pinned golden
  save, atomic `_save_game` + PermissionError retry + fsync; ghost-key
  pruning stays declined per the stray-keys decision); **4** —
  `abort_day` snapshot/restore + a double-dip regression test.
  **Batch 2 done (this round):** balance keys typed per-key —
  `BALANCE_TYPES` is the single source (validator refuses floats for
  int keys like CHECK_DIE, message names key + value; SCHEMA reads the
  same table so the balance form auto-types; mutation tests cover both
  the refusal and the legal fractional keys) — plus the build_craft ⇒
  id ∈ PATTERN_KINDS rule (+ test), closing the dead-action bug the
  editor's dropdown used to offer. **Batch 3 done:** save identity —
  `SAVE_GAME_ID`/`SAVE_VERSION` stamped by `to_dict`, `from_dict`
  refuses wrong shape / wrong game / unsupported version (5 refusal
  cases incl. balance-as-save and v99 — each lands as a clean "Load
  failed" status); pinned golden save `tests/fixtures/golden_save.json`
  (loads with spot-field asserts AND round-trips exactly; re-pin
  deliberately via `python tests/make_golden_save.py`); `_save_game`
  is now atomic (temp → fsync → replace with PermissionError retry;
  temp name matches `.gitignore`'s `.*.json.tmp`) — ghost-key pruning
  stays declined per the stray-keys decision. **Batch 4 done:**
  `begin_day` captures a session-local `to_dict` snapshot (never
  serialized — golden save untouched); `abort_day` restores it via
  `from_dict` + `__dict__` update, so partial slot effects are undone
  and the rewound RNG replays the aborted day identically —
  double-dip closed, with state-equality + replay regression tests.
  **Batch 5 done (user-specified rules): generalized eating** — items
  gain an opt `food` quality tier (validated: positive int; ≥1 food
  required set-wide); `game_core.FOOD_ITEMS` orders foods best-tier
  first (ties keep file order); shared `_eat_until_recovered` drains
  each tier before downgrading until health/energy/hunger saturate —
  shortfall only on a bare larder, zero waste when already recovered
  (each edge with its own message; Rest's note is item-driven: "you
  ate berries..."). Berries ships `food: 1` + honest tooltip (live +
  fixture re-pin); the guide's fish recipe ships `food: 2` and the
  mechanics doc replaced the old "never label Food" warning. Tests:
  tier-downgrade/shortfall/no-waste (patched FOOD_ITEMS, restored),
  food-tier validation (k4), and the two state-bound old pins updated
  to rule-shaped ones (peaceful rest now asserts ate-to-recovery
  instead of exactly −1; bok's two-berry rest asserts +32/+50).
  Deferred: content-mutation fuzz (after Batch 2).
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
  updated. Seeded outputs stayed byte-identical. **Zero-Python claim
  verified by a throwaway `stone_axe` probe** (+2 tag): pure JSON gave
  craft → inventory → tagged best-of bonus, plus GUI rows and viewer
  records — zero code touched; probe reverted after the run.
- **Viewer nitpick #5 (difficulty aim):** actions can now declare
  `difficulty_target: ["stats"|"skills", key]` — explicit aim for the
  difficulty check; absent = the action's own skill (unchanged
  default). `_stat_check` mirrors `_skill_check`'s single draw (RNG
  untouched; no content uses it yet → seeded byte-identical).
  Validation requires [kind, key] to resolve and rejects the field on
  behaviors with no direct check (rest, build/craft — pattern checks
  aim at the pattern's skill). Stat-tied gather_item actions (skill:
  null) are now legal when a target is declared. Behavioral proof in
  test_smoke: DC 21 vs strength 0/99 fails/passes deterministically.
- **Viewer round (Claude-suggested, 2026-10-23):** uses/used-by links on
  every record + click-through navigation (`_jump_to`, shared with
  problem rows) + Economy view (per-item sources/sinks; an item nothing
  grants is flagged red). `content.collect_references()` = schema-driven
  reference graph (24 edges on live content) — the same data 2c's
  delete-blocking will need. Sinks are content-declared only; engine
  consumption (Sleep eating food) is NOT modeled in the viewer — the
  recommended design-lint tool (report, not gate; awaiting user go)
  would be engine-aware via the check_live precedent. Economy view
  finding on live content: stone + herbs are unobtainable (expected
  placeholders — their items say "Not used yet").
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

- **Context-rollover amnesia, not a ghost (2026-10-23, corrected):**
  the context window hit cap mid-session (around the tunables turn) and
  rolled over; the committed editor.py/content.py work that post-rollover
  me "didn't remember" was my own pre-rollover work, initially
  mislabeled as an "invisible continuation" rewrite. The user saw NO
  error — that's the tell distinguishing this from the genuine
  lost-response incident (visible client failure) below, whose rule
  still stands. Tell-tale here: the "unexpected" changes were coherent,
  on-plan, convention-matching work. Rule: when committed state
  surprises you, suspect your own lost memory FIRST — ground-truth with
  `git diff HEAD -- <file>` + grep, treat git and the suite as the only
  authorities, and verify rather than theorize (summaries written at a
  rollover boundary may misattribute the work too).
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

