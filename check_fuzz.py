"""Content mutation fuzz: validator-legal variants must not crash the engine.

The review's closing recommendation — it targets the pattern where
validation ACCEPTS content the engine can't use (CHECK_DIE=20.5 crashed
randint). Mutates editable fields into the weird-but-legal space, then
plays seeded days against each variant.

Run: python check_fuzz.py [base_content_dir]   (default: the live content/)
Guard variants encode known-bad classes and MUST stay blocked — one
escaping means the validator regressed. Every variant runs in a FRESH
child process (game_core binds content at import time):
    child exit 0 = played clean, 1 = validator rejected (blocked),
    2 = engine broke (FINDING, traceback on stderr).
Spawns from test_smoke (D6 family), standalone-runnable like check_live.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

import content  # noqa: E402  (code constant only: BEHAVIOR_HANDLERS)

Mutator = Callable[[Any, Dict[str, Any]], None]  # (own file, all base files)


def _bad_behavior(actions: Any, _files: Dict[str, Any]) -> None:
    actions[0]["behavior"] = "juggling"


def _dead_build(actions: Any, _files: Dict[str, Any]) -> None:
    # Batch 2 rule: a build_craft action not named build/craft is dead
    actions.append({"id": "repair", "label": "Repair",
                    "behavior": "build_craft", "skill": None,
                    "checks": [], "stat_xp": None})


def _big_yield(actions: Any, _files: Dict[str, Any]) -> None:
    for rec in actions:
        if isinstance(rec, dict) and "gather" in rec:
            rec["gather"]["yield"] = [1, 999]


def _unreachable_patterns(patterns: Any, _files: Dict[str, Any]) -> None:
    for rec in patterns.values():
        rec["skill_req"] = 999


def _empty_event_actions(events: Any, _files: Dict[str, Any]) -> None:
    for rec in events.values():
        rec["actions"] = []


def _empty_materials(patterns: Any, _files: Dict[str, Any]) -> None:
    for rec in patterns.values():
        rec["materials"] = {}


def _start_zero(items: Any, _files: Dict[str, Any]) -> None:
    for rec in items:
        rec["start"] = 0


def _strip_opts(actions: Any, _files: Dict[str, Any]) -> None:
    for rec in actions:
        rec.pop("difficulty", None)
        rec.pop("difficulty_target", None)


def _plain_templates(actions: Any, _files: Dict[str, Any]) -> None:
    for rec in actions:
        gather = rec.get("gather")
        if isinstance(gather, dict):
            gather["success"] = "you gathered something."
            gather["fail"] = "you found nothing."


def _skill_null(actions: Any, _files: Dict[str, Any]) -> None:
    actions[0]["skill"] = None  # unskilled gather: legal? the play says


def _extra_per_behavior(actions: Any, files: Dict[str, Any]) -> None:
    """One extra action per behavior (except build_craft — the Batch 2
    rule makes new ones impossible by design)."""
    items = files.get("items") or []
    skills = list((files.get("skills") or {}).keys())
    have = {rec.get("id") for rec in actions if isinstance(rec, dict)}
    for behavior in content.BEHAVIOR_HANDLERS:
        if behavior == "build_craft":
            continue
        new_id = f"test_{behavior}"
        if new_id in have:
            continue
        rec: Dict[str, Any] = {
            "id": new_id, "label": f"Test {behavior}",
            "behavior": behavior,
            "skill": skills[0] if skills else None,
            "checks": [], "stat_xp": None,
        }
        if behavior == "gather_item":
            rec["gather"] = {
                "item": items[0]["id"] if items else "berries",
                "yield": [1, 1],
                "success": "you gathered {amount} test things.",
                "fail": "the test site was empty.",
            }
        actions.append(rec)


#: (name, file, expectation, mutation) — "block" = the validator must
#: refuse it (regression tripwire), "play" = legal-weird, engine must
#: survive seeded days with all invariants intact.
MUTATIONS: List[Tuple[str, str, str, Mutator]] = [
    ("balance CHECK_DIE float", "balance", "block",
     lambda d, _f: d.update(CHECK_DIE=20.5)),
    ("balance MAX_VITAL float", "balance", "block",
     lambda d, _f: d.update(MAX_VITAL=100.0)),
    ("balance EVENT_CHANCE > 1", "balance", "block",
     lambda d, _f: d.update(EVENT_CHANCE=1.5)),
    ("action unknown behavior", "actions", "block", _bad_behavior),
    ("second build_craft action", "actions", "block", _dead_build),
    ("CHECK_DIE = 1", "balance", "play",
     lambda d, _f: d.update(CHECK_DIE=1)),
    ("CHECK_DIE = 10^6", "balance", "play",
     lambda d, _f: d.update(CHECK_DIE=10 ** 6)),
    ("XP turbo (next=1, step=0)", "balance", "play",
     lambda d, _f: d.update(XP_TO_NEXT=1, XP_COST_STEP=0)),
    ("events always fire", "balance", "play",
     lambda d, _f: d.update(EVENT_CHANCE=1.0)),
    ("EVENT_DIFFICULTY = 999", "balance", "play",
     lambda d, _f: d.update(EVENT_DIFFICULTY=999)),
    ("gather yields 1..999", "actions", "play", _big_yield),
    ("patterns unreachable (req 999)", "patterns", "play",
     _unreachable_patterns),
    ("events match any action", "events", "play", _empty_event_actions),
    ("patterns with no materials", "patterns", "play", _empty_materials),
    ("no starting inventory", "items", "play", _start_zero),
    ("optional fields absent", "actions", "play", _strip_opts),
    ("templates without {amount}", "actions", "play", _plain_templates),
    ("gather with skill null", "actions", "play", _skill_null),
    ("one action per behavior", "actions", "play", _extra_per_behavior),
]


def _build_variant(base: Path, fn: Mutator, filename: str) -> Path:
    """Copy the base content into a temp dir and apply one mutation."""
    tmp = Path(tempfile.mkdtemp(prefix="fuzz_"))
    for src in base.glob("*.json"):
        shutil.copy(src, tmp / src.name)
    files: Dict[str, Any] = {}
    for src in tmp.glob("*.json"):
        files[src.stem] = json.loads(src.read_text(encoding="utf-8"))
    fn(files[filename], files)
    target = tmp / f"{filename}.json"
    target.write_bytes(json.dumps(files[filename], ensure_ascii=False,
                                  indent=2).encode("utf-8") + b"\n")
    return tmp


def _play(dirpath: str) -> int:
    """Child mode: bind the variant content, import the engine, play a
    few seeded days, and hold every invariant check_live holds."""
    import os
    os.environ["DAY_SCHEDULER_CONTENT_DIR"] = dirpath  # before game_core
    try:
        from game_core import ACTION_ORDER, BUILD, CRAFT, GameEngine
    except BaseException as exc:  # ContentError = blocked; other = broke
        import content as _c
        if isinstance(exc, _c.ContentError):
            return 1
        import traceback
        traceback.print_exc()
        return 2
    try:
        engine = GameEngine(seed=7)
        for day in range(5):
            if engine.game_over:
                break
            for slot in range(3):  # plan first — replanning mid-day refuses
                engine.set_slot_action(
                    slot, ACTION_ORDER[(day * 3 + slot) % len(ACTION_ORDER)])
            engine.begin_day()
            for slot in range(3):
                action = engine.slot_actions[slot]
                provider = None
                if action in (BUILD, CRAFT):
                    options = engine.patterns_for(action)
                    provider = (
                        lambda _k, opts=options: opts[0].id if opts else None)
                engine.run_slot(slot, pattern_provider=provider)
                assert 0 <= engine.health <= engine.MAX_VITAL, engine.health
                assert 0 <= engine.energy <= engine.MAX_VITAL, engine.energy
                assert 0 <= engine.hunger <= engine.MAX_VITAL, engine.hunger
                assert engine.xp >= 0 and engine.level >= 1
                assert all(c >= 0 for c in engine.inventory.values())
                assert engine.xp_next >= 1, engine.xp_next
            engine.complete_day()
    except BaseException:
        import traceback
        traceback.print_exc()
        return 2
    return 0


def main(argv: List[str]) -> int:
    if argv[:1] == ["--play"]:
        return _play(argv[1])
    base = Path(argv[1]) if len(argv) > 1 else _ROOT / "content"
    played: List[str] = []
    blocked: List[str] = []
    findings: List[str] = []
    for name, filename, expect, fn in MUTATIONS:
        tmp = _build_variant(base, fn, filename)
        try:
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--play",
                 str(tmp)],
                capture_output=True, text=True, cwd=str(_ROOT), timeout=180)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if expect == "block":
            if proc.returncode == 1:
                blocked.append(name)
            else:
                findings.append(
                    f"{name}: expected a validator BLOCK, child exited "
                    f"{proc.returncode}\n{proc.stderr[-1500:]}")
        elif proc.returncode == 0:
            played.append(name)
        elif proc.returncode == 1:
            blocked.append(f"{name} (validator refused)")
        else:
            findings.append(f"{name}: engine broke\n{proc.stderr[-1500:]}")
    print(f"content fuzz: {len(MUTATIONS)} variants — {len(played)} played,"
          f" {len(blocked)} blocked by the validator,"
          f" {len(findings)} FINDINGS")
    for item in findings:
        print(f"\nFINDING: {item}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))