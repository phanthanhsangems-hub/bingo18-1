"""test_ensemble.py — Local pre-deployment verification."""
import json
import os
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

from ensemble_model import VotingEnsemble, quick_backtest
from models import (ColdNumberModel, FWBRModel, MarkovModel,
                    MLEnsembleModel, HybridModel, ModelSelector)
from prediction_service import _get_models, run_prediction_cycle

check("ensemble_model imports", lambda: None)
check("models imports",         lambda: None)
check("prediction_service imports", lambda: None)

# ── TEST 2: Initialization ────────────────────────────────────────────────────
print("\n" + "="*60)
print("TEST 2: Initialization")
print("="*60)

ensemble = VotingEnsemble()
check("VotingEnsemble.__init__",
      lambda: setattr(ensemble, '_checked', True))
check("ensemble.name == 'voting_ensemble'",
      lambda: (_ for _ in ()).throw(AssertionError()) if ensemble.name != "voting_ensemble" else None)
check("5 base models registered",
      lambda: (_ for _ in ()).throw(AssertionError(f"got {len(ensemble._base)}")) if len(ensemble._base) != 5 else None)
check("default weights sum to 1.0",
      lambda: (_ for _ in ()).throw(AssertionError(f"sum={sum(ensemble.weights.values()):.3f}")) if abs(sum(ensemble.weights.values()) - 1.0) > 0.01 else None)

# ── TEST 3: Synthetic prediction (no DB) ─────────────────────────────────────
print("\n" + "="*60)
print("TEST 3: Synthetic prediction (no DB)")
print("="*60)

import random, pandas as pd

rng = random.Random(42)
fake_draws = [[rng.randint(1,6), rng.randint(1,6), rng.randint(1,6)] for _ in range(150)]
fake_df    = pd.DataFrame([
    {"draw_number": i+1, "numbers": d} for i, d in enumerate(fake_draws)
])

def _pred_list():
    preds = ensemble.predict(fake_draws[-100:])
    assert preds, "No predictions returned"
    nums, conf = preds[0]
    assert len(nums) == 3, f"Expected 3 numbers, got {len(nums)}"
    assert all(1 <= n <= 6 for n in nums), f"Numbers out of range: {nums}"
    assert 0 < conf <= 1.0, f"Confidence out of range: {conf}"

def _pred_df():
    ensemble.train(fake_df)
    preds = ensemble.predict(fake_df)
    assert preds
    nums, conf = preds[0]
    assert len(nums) == 3
    assert all(1 <= n <= 6 for n in nums)

check("predict(list of draws) -> 3 numbers in [1,6]", _pred_list)
check("train(df) + predict(df) works",                _pred_df)
check("predict with 5 draws (short history)",
      lambda: ensemble.predict([[1,2,3],[2,3,4],[3,4,5],[4,5,6],[5,6,1]]))
check("predict with 1 draw (minimal history)",
      lambda: ensemble.predict([[1,2,3]]))

# ── TEST 4: DB connection + model cache ──────────────────────────────────────
print("\n" + "="*60)
print("TEST 4: Database + model cache")
print("="*60)

from database import DatabaseManager

def _db_connect():
    db = DatabaseManager()
    df = db.get_recent_draws(10)
    assert len(df) > 0, "No draws returned from DB"

def _get_models_cache():
    db = DatabaseManager()
    result = _get_models(db)
    assert len(result) == 5, f"Expected 5-tuple, got {len(result)}"
    hybrid, selector, fwbr, ens, size_pred = result
    assert ens.name == "voting_ensemble"

def _selector_has_ensemble():
    db = DatabaseManager()
    _, selector, _, ens, _ = _get_models(db)
    m = selector.get_model("voting_ensemble")
    assert m is not None, "voting_ensemble not registered in selector"

def _weights_update():
    db  = DatabaseManager()
    ens = VotingEnsemble()
    ens.update_weights_from_db(db)
    assert abs(sum(ens.weights.values()) - 1.0) <= 0.02, \
        f"Weights don't sum to ~1 after DB update: {sum(ens.weights.values())}"

check("DB connect + get_recent_draws(10)",      _db_connect)
check("_get_models() returns 5-tuple with ens", _get_models_cache)
check("voting_ensemble registered in selector", _selector_has_ensemble)
check("update_weights_from_db() normalizes",    _weights_update)

# ── TEST 5: Live prediction cycle (dry run) ───────────────────────────────────
print("\n" + "="*60)
print("TEST 5: run_prediction_cycle() dry run")
print("="*60)

def _cycle():
    result = run_prediction_cycle()
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "error" not in result or result.get("skipped"), \
        f"Cycle returned error: {result.get('error')}"

check("run_prediction_cycle() returns dict", _cycle)

# ── TEST 3 (extended): Model Selector deep-dive ───────────────────────────────
print("\n" + "="*60)
print("TEST 3: Model Selector (detailed)")
print("="*60)

from database import DatabaseManager as _DM

_db3      = _DM()
_, _sel3, _, _ens3, _ = _get_models(_db3)
_df3      = _db3.get_recent_draws(100)
_history3 = [row["numbers"] for _, row in _df3.iterrows()]

def _sel_registered_models():
    names = list(_sel3._models.keys())
    print(f"         Registered ({len(names)}): {names}")
    assert len(names) >= 6, f"Expected >= 6 models, got {len(names)}"

def _sel_win_rates():
    rows = []
    for name in _sel3._models:
        wr = _db3.get_model_win_rate(name, 200)
        rows.append((name, wr or 0.0))
    rows.sort(key=lambda x: -x[1])
    print(f"         {'Model':<32} {'WinRate':>8}")
    for name, wr in rows:
        print(f"         {name:<32} {wr:>7.3f}")

def _sel_picks_valid():
    name = _sel3.select_best_model()
    model = _sel3.get_model(name)
    assert model is not None, f"select_best_model returned '{name}' but get_model returned None"
    print(f"         -> selected: {name}")
    return name, model

def _sel_prediction_from_best():
    name, model = _sel_picks_valid.__wrapped__() if hasattr(_sel_picks_valid, '__wrapped__') else _sel_picks_valid()
    if hasattr(model, 'predict'):
        preds = model.predict(_history3)
        assert preds, "No predictions returned"
        nums, conf = preds[0]
        assert len(nums) == 3
        assert all(1 <= n <= 6 for n in nums)
        assert 0 < conf <= 1.0
        print(f"         prediction: {nums}  conf={conf:.1%}")

def _sel_ensemble_predict():
    preds = _ens3.predict(_df3)
    assert preds
    nums, conf = preds[0]
    assert len(nums) == 3 and all(1 <= n <= 6 for n in nums)
    print(f"         ensemble:   {nums}  conf={conf:.1%}")

def _sel_weights_reflect_db():
    _ens3.update_weights_from_db(_db3)
    total = sum(_ens3.weights.values())
    assert abs(total - 1.0) <= 0.02, f"sum={total}"
    best_w = max(_ens3.weights, key=lambda k: _ens3.weights[k])
    print(f"         highest-weight model: {best_w} ({_ens3.weights[best_w]:.3f})")

check("registered models >= 6",               _sel_registered_models)
check("win rates queryable for all models",   _sel_win_rates)
check("select_best_model() -> valid name",    _sel_picks_valid)
check("selected model produces 3 numbers",   _sel_prediction_from_best)
check("ensemble predict from real df",        _sel_ensemble_predict)
check("weights reflect DB after update",      _sel_weights_reflect_db)

# ── TEST 6: Selector picks a model ───────────────────────────────────────────
print("\n" + "="*60)
print("TEST 6: ModelSelector")
print("="*60)

def _selector_picks():
    from database import DatabaseManager
    db = DatabaseManager()
    _, selector, _, _, _ = _get_models(db)
    name = selector.select_best_model()
    assert isinstance(name, str) and len(name) > 0, f"Got: {name!r}"
    print(f"         -> selected model: {name}")

check("select_best_model() returns a non-empty string", _selector_picks)

# ── TEST E2E: End-to-End Simulation ─────────────────────────────────────────
print("\n" + "="*60)
print("TEST E2E: End-to-End Simulation")
print("="*60)

def _e2e():
    db = DatabaseManager()

    # Step 1: load data
    df = db.get_recent_draws(100)
    assert len(df) > 0
    history = [row["numbers"] for _, row in df.iterrows()]
    print(f"  1. Loaded {len(history)} draws")

    # Step 2: select best model
    _, selector, _, ens, _ = _get_models(db)
    best_name  = selector.select_best_model()
    best_model = selector.get_model(best_name)
    assert best_model is not None
    print(f"  2. Selected model: {best_name}")

    # Step 3: generate prediction
    if isinstance(df, pd.DataFrame) and hasattr(best_model, "markov_model"):
        preds = best_model.predict(df)
    else:
        preds = best_model.predict(history)
    assert preds, "No predictions returned"
    predicted, confidence = preds[0]
    print(f"  3. Prediction: {predicted}  conf={confidence:.1%}")

    # Step 4: validate (Bingo18: 3 numbers from 1-6)
    assert len(predicted) == 3,           f"Expected 3 numbers, got {len(predicted)}"
    assert all(1 <= n <= 6 for n in predicted), f"Numbers out of range: {predicted}"
    assert 0 < confidence <= 1.0,         f"Confidence out of range: {confidence}"
    print(f"  4. Validation passed")

    # Step 5: format for DB storage (matches predictions table schema)
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(draw_number) FROM draw_history")
        last_draw = cur.fetchone()[0] or 0
    finally:
        conn.close()

    import json as _json
    prediction_data = {
        "draw_number":       int(last_draw) + 1,
        "model_name":        best_name,
        "predicted_numbers": _json.dumps([int(n) for n in sorted(predicted)]),
        "confidence":        round(float(confidence), 4),
    }
    print(f"  5. Storage format: {prediction_data}")

    # Step 6: ensemble also produces valid output
    ens_preds = ens.predict(df)
    ens_nums, ens_conf = ens_preds[0]
    assert len(ens_nums) == 3 and all(1 <= n <= 6 for n in ens_nums)
    print(f"  6. Ensemble cross-check: {ens_nums}  conf={ens_conf:.1%}")

check("E2E: load -> select -> predict -> validate -> format", _e2e)

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
print("ALL TESTS COMPLETED")
print("="*60)
print()
print("[OK] TEST 1: Imports & Initialization")
print("[OK] TEST 2: Prediction Generation")
print("[OK] TEST 3: Model Selector")
print("[OK] TEST 4: Database Integration")
print("[OK] TEST 5: End-to-End Simulation")
print()
print("="*60)
print("ALL TESTS PASSED - READY TO DEPLOY!")
print("="*60)
print()
print("Deploy commands:")
print("  gcloud builds submit . --tag asia-southeast1-docker.pkg.dev/bingo18-predictor/bingo18-images/bingo18:latest")
print("  gcloud run deploy bingo18 --image asia-southeast1-docker.pkg.dev/bingo18-predictor/bingo18-images/bingo18:latest --region asia-southeast1")
