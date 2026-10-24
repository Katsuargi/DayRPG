"""Live-content gate for Day Scheduler RPG.
Run: python check_live.py [content_dir]

When run as a script it forces DAY_SCHEDULER_CONTENT_DIR *before*
anything imports game_core: an explicit directory argument wins — the
editor's Run-check button (2e) checks the directory it has open —
else this project's content/ (the test suite pins that variable to its
fixture and spawns this file as a child; the variable travels, so we
overwrite it).

Exits 1 listing every problem when:
- content/*.json fails the strict load (ContentError names file+field), or
- game_core.validate_content() finds an engine-contract break, or
- a few seeded days crash or leave the vitals/inventory invariants.

main.py runs run_live_check() at startup and refuses to launch (with a
dialog) when it reports problems; test_smoke.py spawns this script so
the pre-commit suite also gates the live content.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import List

# Force the content directory before game_core can be imported
# (game_core loads content at its own import time). Argv wins so the
# editor can check any opened directory; default stays the live files.
if __name__ == "__main__":
    import os

    os.environ["DAY_SCHEDULER_CONTENT_DIR"] = str(
        Path(sys.argv[1]).resolve() if len(sys.argv) > 1
        else Path(__file__).resolve().parent / "content"
    )

from content import ContentError


def run_live_check() -> List[str]:
    """Validate whatever content game_core loaded, then play seeded days.

    In normal runs game_core loaded the live content/; the test suite
    pins the fixture instead — either way this gates *the content the
    game would actually run*. [] means shipshape.
    """
    try:
        from game_core import (
            ACTION_ORDER,
            BUILD,
            CRAFT,
            GameEngine,
            validate_content,
        )

        problems = list(validate_content())
    except ContentError as exc:
        return list(exc.problems)
    if problems:
        return problems  # don't simulate content the game already rejects

    rng = random.Random(20261021)
    for seed in (7, 21, 99):
        try:
            engine = GameEngine(seed=seed)
            for _ in range(3):
                if engine.game_over:
                    break
                for slot in range(3):
                    engine.set_slot_action(slot, rng.choice(ACTION_ORDER))
                engine.begin_day()
                for slot in range(3):
                    action = engine.slot_actions[slot]
                    provider = None
                    if action in (BUILD, CRAFT):
                        options = engine.patterns_for(action)
                        if options:
                            provider = (lambda kind: options[0].id)
                    engine.run_slot(slot, pattern_provider=provider)
                    _assert_invariants(engine, seed)
                engine.complete_day()
                _assert_invariants(engine, seed)
        except Exception as exc:  # any crash on valid-looking content
            problems.append(f"seeded smoke (seed {seed}) crashed: {exc!r}")
    return problems


def _assert_invariants(engine, seed: int) -> None:
    for name, value in (
        ("health", engine.health),
        ("energy", engine.energy),
        ("hunger", engine.hunger),
    ):
        if not 0 <= value <= engine.MAX_VITAL:
            raise AssertionError(
                f"seed {seed}: {name}={value} outside 0..{engine.MAX_VITAL}"
            )
    counts = list(engine.inventory.values())
    counts += list(engine.buildings.values())
    if any(count < 0 for count in counts):
        raise AssertionError(f"seed {seed}: negative count in stores: {counts}")
    if engine.xp < 0 or engine.level < 1:
        raise AssertionError(
            f"seed {seed}: xp={engine.xp} level={engine.level}"
        )


if __name__ == "__main__":
    found = run_live_check()
    if found:
        print("Live content check FAILED:")
        for problem in found:
            print(f"  - {problem}")
        raise SystemExit(1)
    print("Live content check OK")
