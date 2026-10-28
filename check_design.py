"""Design lint for content: advisory warnings, never a gate.

Run: python check_design.py [content_dir]   (default: the live content/)

ADVISORY by design (user call, 2026-10-26): prints warnings and ALWAYS
exits 0 — the project is still designing its guidelines, so taste must
never fail the build. Only a crash of the lint itself is nonzero (and
test_smoke asserts that, so code rot can't hide).

To add a guideline later: write a function `(content) -> list[str]` and
append `(name, fn)` to RULES. Findings are Problem-shaped
("file.json: ...") so a future editor surface can display them too.
Rules here are engine-free (content.py only); engine-curve analysis
(XP achievability, DC sanity) is the natural engine-aware upgrade once
the design guidelines firm up.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, List, Tuple

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

from content import (  # noqa: E402
    PATTERN_KINDS,
    collect_references,
    try_load_content,
)

Rule = Callable[[Any], List[str]]  # (bundle) -> warning strings


def _unobtainable_items(bundle: Any) -> List[str]:
    """An item nothing ever grants: no start stock, no gather yield,
    no craft pattern output. (Known placeholders: stone, herbs.)"""
    sources = {rec["id"] for rec in bundle.items
               if isinstance(rec, dict) and isinstance(rec.get("start"), int)
               and rec["start"] > 0}
    sources |= {edge[4] for edge in collect_references(bundle)
                if edge[3] == "items" and edge[2] == "gather.item"}
    sources |= {pid for pid, pat in bundle.patterns.items()
                if isinstance(pat, dict) and pat.get("kind") == "craft"}
    item_ids = [rec["id"] for rec in bundle.items
                if isinstance(rec, dict) and isinstance(rec.get("id"), str)]
    return [
        f"items.json: {iid!r} has no source — no start stock, no gather "
        "yields it, no craft pattern outputs it"
        for iid in item_ids if iid not in sources
    ]


def _untrained_skills(bundle: Any) -> List[str]:
    """A skill no action trains — with its demanders listed, because a
    demanded-but-untrained skill is a real progression dead end."""
    trained = {act.get("skill") for act in bundle.actions
               if isinstance(act, dict) and isinstance(act.get("skill"), str)}
    demanded: dict = {}
    for pid, pat in bundle.patterns.items():
        if isinstance(pat, dict) and isinstance(pat.get("skill"), str):
            demanded.setdefault(pat["skill"], []).append(pid)
    out: List[str] = []
    for sid in bundle.skills:
        if sid in trained:
            continue
        needed = sorted(demanded.get(sid, []))
        if needed:
            out.append(
                f"skills.json: {sid!r} is required by pattern(s) "
                f"{needed} but nothing trains it")
        else:
            out.append(
                f"skills.json: {sid!r} is never trained (no action uses "
                "it) — idle skill")
    return out


def _pattern_kind_coverage(bundle: Any) -> List[str]:
    """Every build/craft kind needs at least one pattern — otherwise the
    matching action can never offer anything (Batch 2's dead-action
    class, seen from the pattern side)."""
    have = {pat.get("kind") for pat in bundle.patterns.values()
            if isinstance(pat, dict)}
    return [
        f"patterns.json: no pattern of kind {kind!r} — the {kind} action "
        "can never offer anything"
        for kind in PATTERN_KINDS if kind not in have
    ]


def _duplicate_display_names(bundle: Any) -> List[str]:
    """Two items (or two skills) sharing a display name confuses the
    player: inventory and change lists become ambiguous."""
    out: List[str] = []
    for fname, records in (("items", bundle.items),
                           ("skills", bundle.skills.values())):
        seen: dict = {}
        for rec in records:
            if not isinstance(rec, dict):
                continue
            name = rec.get("name")
            if isinstance(name, str) and name:
                seen.setdefault(name, []).append(rec.get("id", "?"))
        for name, ids in seen.items():
            if len(ids) > 1:
                out.append(
                    f"{fname}.json: display name {name!r} is shared by "
                    f"{sorted(ids)} — ambiguous in change lists")
    return out


def _event_chance_heuristic(bundle: Any) -> List[str]:
    """(heuristic) Frequent events are a pacing opinion, not an error —
    advisory is exactly where opinions belong until guidelines exist."""
    chance = bundle.balance.get("EVENT_CHANCE")
    if isinstance(chance, (int, float)) and not isinstance(chance, bool) \
            and chance > 0.5:
        return [
            f"balance.json: EVENT_CHANCE={chance} (heuristic) interrupts "
            "more than half of all slots"
        ]
    return []


#: The rule table — append `(name, fn)` entries as guidelines firm up.
RULES: List[Tuple[str, Rule]] = [
    ("unobtainable items", _unobtainable_items),
    ("untrained skills", _untrained_skills),
    ("pattern kind coverage", _pattern_kind_coverage),
    ("duplicate display names", _duplicate_display_names),
    ("event chance pacing", _event_chance_heuristic),
]


def main(argv: List[str]) -> int:
    directory = Path(argv[0]) if argv else _ROOT / "content"
    bundle, problems = try_load_content(directory)
    print(f"design lint (advisory — never fails the build): {directory}")
    if problems:
        print(f"  note: {len(problems)} validation problem(s) — details "
              "via check_live.py")
    if bundle is None:
        print("  content unusable — lint skipped")
        return 0
    warnings: List[str] = []
    for name, rule in RULES:  # a crashing rule is a bug: let it raise
        warnings.extend(rule(bundle))
    for line in warnings:
        print(f"  warning: {line}")
    print(f"  {len(warnings)} warning(s) from {len(RULES)} rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))