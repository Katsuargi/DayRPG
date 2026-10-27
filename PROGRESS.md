# PROGRESS — green checkpoint ledger

Append-only, one line per commit: date | checkpoint | hash | tests.
Written at round-end in a follow-up commit after the work commit (the
hash must exist first). Docs-only commits are listed for continuity.

- 2026-10-22 | Phase 0a full checkpoint | b20a60c | test_smoke + check_live green
- 2026-10-22 | Phase 0b slug item ids | 6eca4bd | test_smoke + check_live green
- 2026-10-22 | content id slug validation | 3c01126 | test_smoke + check_live green
- 2026-10-23 | Phase 1 behavior-keyed dispatch | cb37786 | test_smoke + check_live green
- 2026-10-23 | Phase 1 parameterized gather_item | be2f4c6 | test_smoke + check_live green
- 2026-10-23 | EDITOR_BRIEF v1 (planning) | f5ac534 | docs-only
- 2026-10-23 | EDITOR_BRIEF v2 round-1 checklist | 02b45ed | docs-only
- 2026-10-23 | EDITOR_BRIEF v3 round-2 inputs | 7171566 | docs-only
- 2026-10-23 | EDITOR_BRIEF v4 reconciled, binding | c8c2bcd | docs-only
- 2026-10-23 | Phase 2a-0 loader hardening | 89f0ea2 | test_smoke + check_live green
- 2026-10-23 | Phase 2a-0 coverage (1e400 path) | 29cf24f | test_smoke + check_live green
- 2026-10-23 | lost-response failure mode recorded | 5ff857c | docs-only
- 2026-10-23 | PROGRESS.md ledger created (backfilled) | 53f943b | docs-only
- 2026-10-23 | Phase 2a read-only viewer + SCHEMA + drift tests | 914155a | test_smoke + check_live + test_editor_gui green
- 2026-10-23 | push policy recorded (user-directed pushes) | e8791b0 | docs-only
- 2026-10-23 | nitpick #1: per-record difficulty (patterns + events) | bde78a4 | test_smoke + check_live + test_editor_gui green
- 2026-10-23 | nitpick #2: gather sub-row rendering (difficulty visible) | 06e250a | test_editor_gui + test_smoke green
- 2026-10-23 | nitpick #3: Tunables view + split rule (effects stay with records) | 9f648bd | test_editor_gui + test_smoke + check_live green
- 2026-10-23 | nitpick #4: tools are items (tagged tool_bonus, best-owned scan) | 28ef988 | test_smoke + check_live + test_editor_gui green
- 2026-10-23 | stone_axe probe recorded (zero-Python verified, reverted) | b563941 | docs-only
- 2026-10-23 | nitpick #5: difficulty_target aim (stats or skills) | 96547c2 | test_smoke + check_live + test_editor_gui green
- 2026-10-23 | viewer round: uses/used-by links, click-through, Economy view | e964727 | test_smoke + check_live + test_editor_gui green
- 2026-10-23 | docs: HANDOFF rollover lesson corrected (context-rollover amnesia, not invisible continuation) | f5af4ba | docs-only
- 2026-10-23 | pre-2b housekeeping: edit-arrival wording (2c) + viewer sign-off recorded | f617cbf | test_smoke + test_editor_gui green
- 2026-10-23 | Phase 2b headless write layer: save() D9/D10/D11 + test_content_write.py | 4ba24d3 | test_smoke + check_live + test_editor_gui + test_content_write green
- 2026-10-23 | Phase 2c hybrid forms: RecordForm seam, Save-All/guards, D5/D7 record ops | ddc52db | test_smoke + check_live + test_editor_gui + test_content_write green
- 2026-10-23 | Phase 2d forms: layout flag/pane (D14-D15), nested/list/dict_int editors (D16), model-first tests (D17) | f026678 | test_smoke + check_live + test_editor_gui + test_content_write green
- 2026-10-23 | 2d-ops: dict-file record ops + key identity (D18) + fishing full-pass acceptance (D19) | 21c25ed | test_smoke + check_live + test_editor_gui + test_content_write green
- 2026-10-23 | 2e repair flow (D4): line/column + open-external + Run-check dir arg — Phase 2 complete | 94e0d36 | test_smoke + check_live + test_editor_gui + test_content_write green
- 2026-10-26 | review batch 1: event-DC display + save-dialog/compensation hardening + housekeeping | e05850f | test_smoke + check_live + test_editor_gui + test_content_write green
- 2026-10-26 | review batch 2: balance per-key typing + build_craft id rule; food slice scheduled (Batch 5) | a6b53b3 | test_smoke + check_live + test_editor_gui + test_content_write green