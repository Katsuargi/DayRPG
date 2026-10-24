"""Headless acceptance tests for the 2b write layer (content.save).

Run: python test_content_write.py — no display needed; test_smoke.py
spawns this file (D6). Proves: byte-identical round-trip of all seven
files, the constraint-3 save gate, D11 stale refusal + confirmed
overwrite, D9 untouched-files-never-rewritten + crash compensation,
D10 reformat notices, record/array order preserved (constraint 4),
and that content.py stays tkinter-free (constraint 5).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

import content  # noqa: E402

_FIXTURE = _ROOT / "tests" / "fixtures" / "content"


def _fresh():
    """Copy the fixture set to a temp dir; (content, state, dir, bytes)."""
    tmp = Path(tempfile.mkdtemp(prefix="write_"))
    for file in _FIXTURE.glob("*.json"):
        shutil.copy(file, tmp / file.name)
    bundle, state = content.try_load_content_with_state(tmp)
    assert bundle is not None and state.problems == [], state.problems
    assert set(state.hashes) == set(content.CONTENT_FILES), state.hashes
    return bundle, state, tmp, _bytes(tmp)


def _bytes(directory: Path) -> dict:
    return {name: (directory / f"{name}.json").read_bytes()
            for name in content.CONTENT_FILES}


def _dump(data) -> bytes:
    return (json.dumps(data, ensure_ascii=False, allow_nan=False,
                       indent=2) + "\n").encode("utf-8")


# 1) Acceptance: load -> save is byte-identical for all seven files,
#    idempotent on a second save, and works without an explicit path
#    (falls back to content.source), leaving no temp file behind.
bundle, state, tmp, before = _fresh()
result = content.save(bundle, tmp, state=state)  # dirty defaults to all
assert list(result.written) == list(content.CONTENT_FILES), result
assert result.skipped == [] and result.reformatted == [], result
assert result.problems == [], result.problems
assert _bytes(tmp) == before, "round-trip must not change a byte"
assert sorted(p.name for p in tmp.iterdir()) == sorted(
    f"{n}.json" for n in content.CONTENT_FILES), "stray temp files"
content.save(bundle, state=state)                # path from content.source
assert _bytes(tmp) == before, "default path must write where it loaded"

# 2) Acceptance: a bundle whose problem count increased raises
#    ContentError listing the problems; disk stays untouched (D9 gate).
bundle, state, tmp, before = _fresh()
bundle.items[0]["start"] = "seven"                # wrong type -> problem
try:
    content.save(bundle, tmp, state=state)
    raise SystemExit("save must refuse a regressed bundle")
except content.ContentError as exc:
    assert any("'start'" in p for p in exc.problems), exc.problems
assert _bytes(tmp) == before, "a refused save must not touch disk"

# 3) Acceptance: a crash mid-write leaves every original intact (D9
#    in-memory-byte compensation) and no temp file behind.
bundle, state, tmp, before = _fresh()
bundle.items[0]["tooltip"] = "edited"             # real byte change
_real_replace, calls = content.os.replace, [0]


def _flaky_replace(src, dst):
    calls[0] += 1
    if calls[0] == 3:                             # after items + skills
        raise OSError("simulated disk failure")
    return _real_replace(src, dst)


with mock.patch.object(content.os, "replace", _flaky_replace):
    try:
        content.save(bundle, tmp, state=state)
        raise SystemExit("the injected replace failure must propagate")
    except OSError as exc:
        assert "simulated" in str(exc), exc
assert _bytes(tmp) == before, "compensation must restore replaced files"
assert sorted(p.name for p in tmp.iterdir()) == sorted(
    f"{n}.json" for n in content.CONTENT_FILES), "temp file left behind"

# 4) D11: stale bytes refuse the save naming the file; overwrite_stale
#    confirms it. Staged files only — a stale file that isn't being
#    saved never blocks (D9: untouched files are never rewritten).
bundle, state, tmp, before = _fresh()
external = json.loads(before["items"].decode("utf-8"))
external[0]["tooltip"] = "touched externally"
(tmp / "items.json").write_bytes(_dump(external))
bundle.items[0]["tooltip"] = "mine"
try:
    content.save(bundle, tmp, state=state, dirty=["items"])
    raise SystemExit("a stale write must refuse")
except content.StaleWriteError as exc:
    assert exc.files == ["items"], exc.files
assert b"touched externally" in (tmp / "items.json").read_bytes(), \
    "the refusal must leave the external edit alone"
result = content.save(bundle, tmp, state=state, dirty=["items"],
                      overwrite_stale=True)
assert result.written == ["items"], result
saved = json.loads((tmp / "items.json").read_bytes())
assert saved[0]["tooltip"] == "mine", "confirmed overwrite wins"
bundle, state, tmp, before = _fresh()
(tmp / "balance.json").write_bytes(before["balance"] + b"\n")  # stale
bundle.items[0]["tooltip"] = "mine"
result = content.save(bundle, tmp, state=state, dirty=["items"])
assert result.written == ["items"], result
assert (tmp / "balance.json").read_bytes() == before["balance"] + b"\n", \
    "an unstaged stale file must not block, nor be touched"

# 5) Constraint 3 / D13: incremental repair persists. The set loads
#    with one problem; staying at one is allowed (the count never
#    grows), the broken file is skipped while the clean edit elsewhere
#    writes — then fully fixing it persists too.
bundle, state, tmp, before = _fresh()
broken = json.loads(before["items"].decode("utf-8"))
broken[0]["start"] = "seven"
(tmp / "items.json").write_bytes(_dump(broken))
bundle, state = content.try_load_content_with_state(tmp)
assert bundle is not None and len(state.problems) == 1, state.problems
bundle.items[0]["start"] = "eight"                # still broken: 1 <= 1
bundle.balance["EVENT_CHANCE"] = 0.3              # clean edit elsewhere
result = content.save(bundle, tmp, state=state,
                      dirty=["items", "balance"])
assert result.written == ["balance"], result
assert result.skipped == ["items"], result
assert len(result.problems) == 1, result.problems
assert b'"seven"' in (tmp / "items.json").read_bytes(), \
    "a file with its own problems must not be written"
reloaded, state = content.try_load_content_with_state(tmp)
assert reloaded.balance["EVENT_CHANCE"] == 0.3, "the clean edit persists"
assert reloaded.items[0]["start"] == "seven", "broken file untouched"
bundle.items[0]["start"] = 2                      # fully repaired: 0 <= 1
result = content.save(bundle, tmp, state=state, dirty=["items"])
assert result.written == ["items"] and result.problems == [], result
reloaded, state = content.try_load_content_with_state(tmp)
assert state.problems == [] and reloaded.items[0]["start"] == 2, \
    "a completed repair must persist and clear the set"

# 6) D10: saving a file whose existing bytes aren't canonical (odd
#    indentation + CRLF here) reports it in `reformatted` but still
#    writes; the follow-up save is quiet (now canonical).
bundle, state, tmp, before = _fresh()
weird = json.loads(before["balance"].decode("utf-8"))
weird["EVENT_CHANCE"] = 0.10                      # dumps as 0.1
(tmp / "balance.json").write_bytes(
    json.dumps(weird, ensure_ascii=False, indent=4)
    .replace("\n", "\r\n").encode("utf-8") + b"\r\n")
bundle, state = content.try_load_content_with_state(tmp)
assert state.problems == [], state.problems
result = content.save(bundle, tmp, state=state, dirty=["balance"])
assert result.written == ["balance"] and \
    result.reformatted == ["balance"], result
_, state = content.try_load_content_with_state(tmp)
result = content.save(bundle, tmp, state=state, dirty=["balance"])
assert result.written == ["balance"] and result.reformatted == [], \
    "after canonicalizing, the second save must be quiet"

# 7) Constraint 4: key order within a record and array order survive
#    the save — never sorted, never reordered.
bundle, state, tmp, before = _fresh()
items = json.loads(before["items"].decode("utf-8"))
record = items[1]
items[1] = {k: record[k] for k in ("tooltip", "id", "start", "name")}
(tmp / "items.json").write_bytes(_dump(items))
bundle, state = content.try_load_content_with_state(tmp)
assert state.problems == [], state.problems
content.save(bundle, tmp, state=state, dirty=["items"])
saved = json.loads((tmp / "items.json").read_bytes())
assert list(saved[1]) == ["tooltip", "id", "start", "name"], list(saved[1])
assert [r["id"] for r in saved] == [r["id"] for r in items], "array order"

# 8) An unknown stem is a caller bug, not a disk write.
try:
    content.save(bundle, tmp, state=state, dirty=["nope"])
    raise SystemExit("unknown stems must raise")
except ValueError as exc:
    assert "nope" in str(exc), exc

# 9) Constraint 5: headless — the write layer never pulls in tkinter.
assert "tkinter" not in sys.modules, "content.py must stay display-free"
print("test_content_write.py OK")