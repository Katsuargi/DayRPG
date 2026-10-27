"""Regenerate tests/fixtures/golden_save.json (deliberate re-pin ONLY).

Deterministic by construction — fixed seed, fixed state — so re-running
produces byte-identical output. Run it when to_dict's format legitimately
gains a field (DEV_GUIDE: Persistence), then let test_smoke's golden
assertion prove the new save still loads.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
# Fixture content, unconditionally: the golden must be reproducible from
# exactly what the test suite pins, whatever the caller's env says.
os.environ["DAY_SCHEDULER_CONTENT_DIR"] = str(
    _ROOT / "tests" / "fixtures" / "content")

from game_core import GameEngine  # noqa: E402


def main() -> int:
    e = GameEngine(seed=11)
    e.day = 4
    e.health, e.energy, e.hunger = 73, 41, 62
    e.gold = 37
    e.level, e.xp = 2, 40
    e.skills["foraging"].level = 3
    e.skills["foraging"].xp = 55
    e.stats["strength"].level = 2
    e.stats["strength"].xp = 30
    e.inventory["berries"] = 3
    e.inventory["wood"] = 7
    e.inventory["wood_axe"] = 1
    e.projects["wood_axe"] = 1
    e.buildings["lean_to"] = 1
    e.slot_actions = ["gather_food", "rest", "gather_wood"]
    out = _ROOT / "tests" / "fixtures" / "golden_save.json"
    out.write_bytes((json.dumps(e.to_dict(), indent=2) + "\n").encode("utf-8"))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())