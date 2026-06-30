"""test_prediction_service.py — Local pre-deployment verification for the
predict + online-learning flow in prediction_service.py.

Complements test_ensemble.py (which covers model/ensemble wiring) by
exercising run_prediction_cycle()'s end-to-end behaviour (including
idempotency) and the online-learning hooks _update_markov_online() /
process_actual_result().

Safety notes (important if run against a real production DATABASE_URL):
  - The Markov-online sub-test never calls db.update_markov_transition()
    for real — it monkeypatches it to a capturing stub so no transition
    counts are mutated.
  - The process_actual_result() sub-test only runs against a prediction
    that is ALREADY genuinely pending (no prediction_results row yet) and
    whose actual draw is already known in draw_history. It never
    fabricates draw numbers or actual results, so it cannot collide with
    or double-count real production data. If no such pending prediction
    exists, the sub-test is skipped (not failed).
"""
import json
import sys

from dotenv import load_dotenv
load_dotenv()

PASS = "OK"
FAIL = "FAIL"
results = []

def check(label, fn):
    try:
        fn()
        print(f"  [{PASS}] {label}")
        results.append((label, True, None))
    except Exception as e:
        print(f"  [{FAIL}] {label}: {e}")
        results.append((label, False, str(e)))

# ── TEST 1: Imports ───────────────────────────────────────────────────────────
print("\n" + "="*60)
print("TEST 1: Imports")
print("="*60)

from prediction_service import (run_prediction_cycle, process_actual_result,
                                 _update_markov_online, _get_models)
from database import DatabaseManager

check("prediction_service imports", lambda: None)

# ── TEST 2: run_prediction_cycle() shape + idempotency ───────────────────────
print("\n" + "="*60)
print("TEST 2: run_prediction_cycle()")
print("="*60)

_cycle_result_1 = {}
_cycle_result_2 = {}

def _cycle_first_call():
    global _cycle_result_1
    _cycle_result_1 = run_prediction_cycle()
    assert isinstance(_cycle_result_1, dict), f"Expected dict, got {type(_cycle_result_1)}"
    assert "error" not in _cycle_result_1 or _cycle_result_1.get("skipped"), \
        f"Cycle returned error: {_cycle_result_1.get('error')}"

def _cycle_result_shape():
    if _cycle_result_1.get("skipped"):
        assert "draw_number" in _cycle_result_1
        print(f"         first call already skipped (draw #{_cycle_result_1.get('draw_number')} predicted ahead)")
        return
    for key in ("draw_number", "predicted_numbers", "confidence", "model", "prediction_id"):
        assert key in _cycle_result_1, f"Missing key '{key}' in result: {_cycle_result_1}"
    nums = _cycle_result_1["predicted_numbers"]
    assert len(nums) == 3 and all(1 <= n <= 6 for n in nums), f"Bad numbers: {nums}"
    conf = _cycle_result_1["confidence"]
    assert 0 < conf <= 1.0, f"Confidence out of range: {conf}"
    print(f"         draw #{_cycle_result_1['draw_number']}  {nums}  "
          f"conf={conf:.1%}  model={_cycle_result_1['model']}")

def _cycle_idempotent():
    global _cycle_result_2
    _cycle_result_2 = run_prediction_cycle()
    assert isinstance(_cycle_result_2, dict)
    assert _cycle_result_2.get("skipped") is True, \
        f"Second call within same draw window should be skipped, got: {_cycle_result_2}"
    print(f"         second call -> skipped=True (draw #{_cycle_result_2.get('draw_number')})")

check("run_prediction_cycle() #1 returns dict",      _cycle_first_call)
check("result shape valid (predict or skip)",        _cycle_result_shape)
check("run_prediction_cycle() #2 is idempotent (skipped)", _cycle_idempotent)

# ── TEST 3: _update_markov_online() — no real DB mutation ────────────────────
print("\n" + "="*60)
print("TEST 3: _update_markov_online() (monkeypatched, no DB writes)")
print("="*60)

def _markov_online_calls_update():
    db = DatabaseManager()
    captured = []
    original = db.update_markov_transition
    db.update_markov_transition = lambda from_state, to_state: captured.append((from_state, to_state))
    try:
        df = db.get_recent_draws(4)
        assert len(df) >= 3, "Need >= 3 recent draws to exercise online update"
        _update_markov_online(db, current_draw=999999, actual_numbers=[1, 2, 3])
    finally:
        db.update_markov_transition = original
    assert len(captured) == 1, f"Expected exactly 1 transition update, got {len(captured)}"
    from_state, to_state = captured[0]
    assert isinstance(from_state, str) and from_state, "from_state should be a non-empty string"
    assert to_state == str((1, 2, 3)), f"Unexpected to_state: {to_state}"
    print(f"         from_state={from_state}  to_state={to_state}")

def _markov_online_short_history_noop():
    db = DatabaseManager()
    captured = []
    original = db.update_markov_transition
    db.update_markov_transition = lambda from_state, to_state: captured.append((from_state, to_state))

    class _EmptyDB:
        def get_recent_draws(self, limit):
            import pandas as pd
            return pd.DataFrame([])
    try:
        _update_markov_online(_EmptyDB(), current_draw=1, actual_numbers=[1, 2, 3])
    finally:
        db.update_markov_transition = original
    assert captured == [], "Should not call update_markov_transition with < 3 recent draws"

check("_update_markov_online() derives from_state/to_state correctly", _markov_online_calls_update)
check("_update_markov_online() no-ops gracefully on short history",    _markov_online_short_history_noop)

# ── TEST 4: process_actual_result() — only on a genuinely pending draw ───────
print("\n" + "="*60)
print("TEST 4: process_actual_result()")
print("="*60)

def _find_pending_prediction(db):
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT p.id, p.draw_number FROM predictions p
            LEFT JOIN prediction_results pr ON pr.prediction_id = p.id
            INNER JOIN draw_history dh ON dh.draw_number = p.draw_number
            WHERE pr.id IS NULL
            ORDER BY p.draw_number ASC LIMIT 1
        """)
        return cur.fetchone()
    finally:
        conn.close()

def _process_actual_result_pending_only():
    db  = DatabaseManager()
    row = _find_pending_prediction(db)
    if not row:
        print("         no genuinely pending prediction found — skipping (nothing to process)")
        return
    pred_id, draw_number = row
    df = db.get_recent_draws(500)
    match = df[df["draw_number"] == draw_number]
    assert len(match) == 1, f"draw #{draw_number} not found in draw_history despite join"
    actual_numbers = match.iloc[0]["numbers"]

    result_info = process_actual_result(draw_number, actual_numbers)
    assert isinstance(result_info, dict), f"Expected dict, got {type(result_info)}"
    assert "predicted" in result_info and "win" in result_info, f"Unexpected shape: {result_info}"
    assert len(result_info["predicted"]) == 3
    print(f"         draw #{draw_number}: predicted={result_info['predicted']} "
          f"match={result_info['match']} win={result_info['win']}")

check("process_actual_result() on a pending prediction (or skip if none)", _process_actual_result_pending_only)

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "="*60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"RESULTS: {n_pass} passed, {n_fail} failed")
if n_fail:
    print("\nFailed tests:")
    for label, ok, err in results:
        if not ok:
            print(f"  - {label}: {err}")
    sys.exit(1)

print("="*60)
print("ALL TESTS PASSED")
print("="*60)
