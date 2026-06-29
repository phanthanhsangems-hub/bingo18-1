"""
train_lstm_full.py
==================
Phase 1  - Load ALL ~60k draws from Supabase
Phase 2  - Train improved LSTM (multiset-class, 56 outputs)
Phase 3  - Backtest LSTM vs FWBR on the same last 1,000 draws

Architecture choice: 56-class softmax (one class per legal Bingo18 multiset).
This lets the model learn the full joint distribution of the 3 numbers,
including repeat draws like [1,1,4], rather than treating each position
independently.

Run:  python train_lstm_full.py [--skip-train]
  --skip-train  skips training, loads existing model and runs backtest only
"""

import argparse
import json
import os
import statistics
import sys
import time
from collections import Counter
from itertools import combinations_with_replacement
from typing import List, Tuple

import numpy as np
from dotenv import load_dotenv
load_dotenv()

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
# Keep oneDNN enabled (critical for Intel CPU speed -- disabling it causes ~20x slowdown)

import psycopg2

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

SEQ_LEN    = 20        # input window (draws)
EPOCHS     = 60
BATCH      = 1024     # larger batch -> fewer kernel launches -> faster CPU training
TEST_N     = 1_000     # last N draws for backtest (same as FWBR test)
MODEL_PATH = "models/lstm_full_bingo18.keras"
RANDOM_MS  = 1 / 56   # ~ 1.786 %
FWBR_MS    = 0.042    # FWBR (rw=0.5) benchmark from previous backtest

# All 56 legal multisets of 3 numbers from {1..6}
MULTISETS: List[Tuple[int, int, int]] = list(combinations_with_replacement(range(1, 7), 3))
MS_IDX   = {ms: i for i, ms in enumerate(MULTISETS)}   # (1,1,1) -> 0, ...


# -----------------------------------------------------------------------------
# Data loading
# -----------------------------------------------------------------------------

def fetch_draws() -> List[List[int]]:
    print("Connecting to Supabase...", flush=True)
    conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=15)
    cur  = conn.cursor()
    cur.execute("SELECT draw_number, numbers FROM draw_history ORDER BY draw_number ASC")
    rows = cur.fetchall()
    conn.close()

    draws = []
    for _, raw in rows:
        if raw is None:
            continue
        if isinstance(raw, list):
            nums = [int(x) for x in raw]
        elif isinstance(raw, str):
            try:
                nums = [int(x) for x in json.loads(raw)]
            except Exception:
                try:
                    nums = [int(x.strip()) for x in raw.strip("[]").split(",")]
                except Exception:
                    continue
        else:
            continue
        if len(nums) == 3 and all(1 <= n <= 6 for n in nums):
            draws.append(nums)

    print(f"Loaded {len(draws):,} draws.", flush=True)
    return draws


# -----------------------------------------------------------------------------
# Encoding
# -----------------------------------------------------------------------------

def encode_draw(nums: List[int]) -> np.ndarray:
    """Draw -> 6-dim frequency vector (normalised to sum=1)."""
    v = np.zeros(6, dtype=np.float32)
    for n in nums:
        if 1 <= n <= 6:
            v[n - 1] += 1.0
    return v / 3.0   # always sums to 1


def draw_to_class(nums: List[int]) -> int:
    return MS_IDX[tuple(sorted(nums))]


def class_to_draw(cls: int) -> List[int]:
    return list(MULTISETS[cls])


def build_sequences(draws: List[List[int]]):
    """Return (X, y) numpy arrays for LSTM training."""
    enc = [encode_draw(d) for d in draws]
    X, y = [], []
    for i in range(len(enc) - SEQ_LEN):
        X.append(enc[i : i + SEQ_LEN])
        y.append(draw_to_class(draws[i + SEQ_LEN]))
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.int32)


# -----------------------------------------------------------------------------
# Model
# -----------------------------------------------------------------------------

def get_tf():
    try:
        import tensorflow_intel as tf
        _ = tf.keras
        return tf
    except (ImportError, AttributeError):
        import tensorflow as tf
        return tf


def build_model(has_gpu: bool = False):
    """
    CPU-tuned: single LSTM(32) to keep per-epoch time < 2 min.
    GPU path: BiLSTM(64)+LSTM(32) for better capacity.
    Both output 56-class softmax (one class per legal Bingo18 multiset).
    """
    tf  = get_tf()
    inp = tf.keras.Input(shape=(SEQ_LEN, 6))

    if has_gpu:
        x = tf.keras.layers.Bidirectional(
                tf.keras.layers.LSTM(64, return_sequences=True))(inp)
        x = tf.keras.layers.Dropout(0.3)(x)
        x = tf.keras.layers.LSTM(32)(x)
    else:
        x = tf.keras.layers.LSTM(32, return_sequences=True)(inp)
        x = tf.keras.layers.Dropout(0.2)(x)
        x = tf.keras.layers.LSTM(16)(x)

    x   = tf.keras.layers.Dropout(0.2)(x)
    x   = tf.keras.layers.Dense(32, activation="relu")(x)
    x   = tf.keras.layers.BatchNormalization()(x)
    out = tf.keras.layers.Dense(56, activation="softmax")(x)
    model = tf.keras.Model(inp, out)
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    model.summary()
    return model


# -----------------------------------------------------------------------------
# Training
# -----------------------------------------------------------------------------

class TimingCallback(object):
    """Print ETA after the first epoch."""
    def __init__(self, total_epochs):
        self.total  = total_epochs
        self.t0     = None
        self.warned = False

    def on_epoch_begin(self, epoch, logs=None):
        if epoch == 0:
            self.t0 = time.time()

    def on_epoch_end(self, epoch, logs=None):
        if epoch == 0 and not self.warned:
            elapsed  = time.time() - self.t0
            eta_mins = elapsed * self.total / 60
            print(f"\n  [timer] 1st epoch took {elapsed:.1f}s -> "
                  f"ETA for full training ~{eta_mins:.0f} min", flush=True)
            self.warned = True


def train(draws: List[List[int]]):
    tf       = get_tf()
    has_gpu  = bool(tf.config.list_physical_devices("GPU"))
    device   = "GPU" if has_gpu else "CPU"
    print(f"\nDevice: {device}", flush=True)

    train_draws = draws[: len(draws) - TEST_N]
    print(f"Building sequences from {len(train_draws):,} training draws...", flush=True)
    X, y = build_sequences(train_draws)
    print(f"  X shape: {X.shape}   y shape: {y.shape}", flush=True)

    # Balanced class weights: rare multisets get upweighted so model can't collapse
    # to the single most-frequent combo.  Formula: n_samples / (n_classes * freq[c])
    n_classes = 56
    freq = Counter(int(c) for c in y)
    n_samples = len(y)
    class_weight = {
        c: n_samples / (n_classes * max(freq.get(c, 1), 1))
        for c in range(n_classes)
    }
    print(f"  Class weights: min={min(class_weight.values()):.3f}  "
          f"max={max(class_weight.values()):.3f}  "
          f"classes_with_data={len(freq)}/56", flush=True)

    model = build_model(has_gpu=has_gpu)

    os.makedirs("models", exist_ok=True)
    timing_cb = TimingCallback(EPOCHS)

    # Keras callback shim so TimingCallback works with model.fit
    class _KCB(tf.keras.callbacks.Callback):
        def on_epoch_begin(self, epoch, logs=None):
            timing_cb.on_epoch_begin(epoch, logs)
        def on_epoch_end(self, epoch, logs=None):
            timing_cb.on_epoch_end(epoch, logs)

    cbs = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=8, restore_best_weights=True, verbose=1
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", patience=4, factor=0.5, min_lr=1e-5, verbose=1
        ),
        tf.keras.callbacks.ModelCheckpoint(
            MODEL_PATH, save_best_only=True, monitor="val_loss", verbose=0
        ),
        _KCB(),
    ]

    t0 = time.time()
    history = model.fit(
        X, y,
        epochs=EPOCHS,
        batch_size=BATCH,
        validation_split=0.15,
        class_weight=class_weight,
        callbacks=cbs,
        verbose=1,
    )
    elapsed = time.time() - t0

    best_val = min(history.history["val_loss"])
    best_ep  = history.history["val_loss"].index(best_val) + 1
    print(f"\nTraining done in {elapsed/60:.1f} min.", flush=True)
    print(f"Best val_loss={best_val:.4f} at epoch {best_ep}.", flush=True)
    return model


# -----------------------------------------------------------------------------
# Helpers (same as backtest_strategies.py for fair comparison)
# -----------------------------------------------------------------------------

def size_cat(nums: List[int]) -> str:
    s = sum(nums)
    return "NHO" if s <= 9 else ("HOA" if s <= 11 else "LON")


def win_ms(pred: List[int], actual: List[int]) -> bool:
    return Counter(pred) == Counter(actual)


def win_size(pred: List[int], actual: List[int]) -> bool:
    return size_cat(pred) == size_cat(actual)


# -----------------------------------------------------------------------------
# FWBR (replicated for self-contained comparison)
# -----------------------------------------------------------------------------

def fwbr_predict(ctx: List[List[int]], window: int = 30,
                 rw: float = 0.5) -> List[int]:
    context   = ctx[-window:] if len(ctx) >= window else ctx
    w         = len(context)
    freq      = {n: 0 for n in range(1, 7)}
    last_seen = {}
    for i, d in enumerate(reversed(context)):
        for n in d:
            freq[n] += 1
            if n not in last_seen:
                last_seen[n] = i
    recency = {n: last_seen.get(n, w) for n in range(1, 7)}
    scores  = {n: freq[n] + rw * recency[n] for n in range(1, 7)}
    return sorted(sorted(scores, key=lambda x: scores[x])[:3])


# -----------------------------------------------------------------------------
# Backtest
# -----------------------------------------------------------------------------

def backtest(draws: List[List[int]], model):
    QUARTERS = 4
    test_draws = draws[-TEST_N:]
    q_size     = TEST_N // QUARTERS

    lstm_ms, lstm_sz = [], []
    fwbr_ms, fwbr_sz = [], []
    lstm_combos: Counter = Counter()
    fwbr_combos: Counter = Counter()

    print(f"\nRunning backtest on last {TEST_N:,} draws...", flush=True)
    for i, actual in enumerate(test_draws):
        ctx = draws[: len(draws) - TEST_N + i]

        # -- LSTM prediction ----------------------------------
        if len(ctx) >= SEQ_LEN and model is not None:
            seq   = np.array([encode_draw(d) for d in ctx[-SEQ_LEN:]])[np.newaxis]
            probs = model.predict(seq, verbose=0)[0]
            cls   = int(np.argmax(probs))
            lstm_pred = class_to_draw(cls)
        else:
            lstm_pred = [1, 2, 3]   # fallback

        lstm_ms.append(win_ms(lstm_pred, actual))
        lstm_sz.append(win_size(lstm_pred, actual))
        lstm_combos[tuple(sorted(lstm_pred))] += 1

        # -- FWBR prediction (rw=0.5, window=30) -------------
        fwbr_pred = fwbr_predict(ctx, window=30, rw=0.5) if len(ctx) >= 30 else [1, 2, 3]
        fwbr_ms.append(win_ms(fwbr_pred, actual))
        fwbr_sz.append(win_size(fwbr_pred, actual))
        fwbr_combos[tuple(sorted(fwbr_pred))] += 1

        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{TEST_N} -- LSTM MS={sum(lstm_ms)/(i+1):.3%}  "
                  f"FWBR MS={sum(fwbr_ms)/(i+1):.3%}", flush=True)

    def quarterly(vec):
        rates = [sum(vec[q*q_size:(q+1)*q_size]) / q_size for q in range(QUARTERS)]
        return rates, statistics.stdev(rates) if len(rates) > 1 else 0.0

    lstm_q, lstm_std = quarterly(lstm_ms)
    fwbr_q, fwbr_std = quarterly(fwbr_ms)

    # -- Print report ----------------------------------------------------------
    SEP = "=" * 72

    print(f"\n\n{SEP}")
    print(f"  LSTM vs FWBR BACKTEST -- {TEST_N} most recent draws")
    print(f"  Random baseline:  MS ~ {RANDOM_MS:.3%}  |  FWBR benchmark: {FWBR_MS:.3%}")
    print(SEP)

    hdr = f"  {'Model':<22}  {'MS wins':>8}  {'MS rate':>9}  {'SZ wins':>8}  {'SZ rate':>9}  {'Stability':>10}  {'Unique':>6}"
    print(hdr)
    print("  " + "-" * 68)

    for label, ms_vec, sz_vec, q_rates, std, combos in [
        ("FWBR (rw=0.5, w=30)", fwbr_ms, fwbr_sz, fwbr_q, fwbr_std, fwbr_combos),
        ("LSTM (full data)",     lstm_ms, lstm_sz, lstm_q, lstm_std, lstm_combos),
    ]:
        ms_r = sum(ms_vec) / TEST_N
        sz_r = sum(sz_vec) / TEST_N
        uniq = len(combos)
        delta = ms_r - FWBR_MS
        flag  = " <- FWBR" if "FWBR" in label else (
                " << WINNER" if ms_r > FWBR_MS else "")
        print(f"  {label:<22}  {sum(ms_vec):>8}  {ms_r:>8.3%}  "
              f"{sum(sz_vec):>8}  {sz_r:>8.3%}  +/-{std:>7.3%}  {uniq:>6}{flag}")

    print(f"\n{SEP}")
    print(f"  STABILITY -- win rate per quarter ({q_size} draws each)")
    print(SEP)
    qhdr = f"  {'Model':<22}  {'Q1':>8}  {'Q2':>8}  {'Q3':>8}  {'Q4':>8}  {'Std':>8}"
    print(qhdr)
    print("  " + "-" * 68)
    for label, q_rates, std in [
        ("FWBR (rw=0.5, w=30)", fwbr_q, fwbr_std),
        ("LSTM (full data)",     lstm_q, lstm_std),
    ]:
        qs = "  ".join(f"{r:>7.3%}" for r in q_rates)
        print(f"  {label:<22}  {qs}  +/-{std:>6.3%}")

    print(f"\n{SEP}")
    print(f"  TOP PREDICTED COMBOS")
    print(SEP)
    for label, combos in [("FWBR", fwbr_combos), ("LSTM", lstm_combos)]:
        top = "  |  ".join(f"{list(c)}x{n}" for c, n in combos.most_common(5))
        print(f"  {label}: {top}")

    print(f"\n{SEP}")
    print(f"  RECOMMENDATION")
    print(SEP)
    lstm_r = sum(lstm_ms) / TEST_N
    fwbr_r = sum(fwbr_ms) / TEST_N
    if lstm_r > fwbr_r * 1.05:   # >5% relative improvement
        improve_pct = (lstm_r - fwbr_r) / fwbr_r * 100
        print(f"  [OK] DEPLOY LSTM -- beats FWBR by {improve_pct:.1f}% relative "
              f"({lstm_r:.3%} vs {fwbr_r:.3%})")
        print(f"     Model saved at: {MODEL_PATH}")
        print(f"     Next step: update prediction_service.py -> best_name = 'lstm'")
    elif lstm_r > fwbr_r:
        print(f"  [~] LSTM marginally better ({lstm_r:.3%} vs FWBR {fwbr_r:.3%})")
        print(f"     Difference too small -- keep FWBR (lower complexity, faster inference)")
    else:
        gap = fwbr_r - lstm_r
        print(f"  [NO] KEEP FWBR -- LSTM underperforms by {gap:.3%}")
        print(f"     FWBR: {fwbr_r:.3%}  |  LSTM: {lstm_r:.3%}")
        print(f"     Likely cause: Bingo18 outcomes are near-random; "
              f"deep model overfit to noise.")
    print(SEP)
    print()

    return lstm_r, fwbr_r


# -----------------------------------------------------------------------------
# Entry
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-train", action="store_true",
                        help="Skip training, load existing model for backtest only")
    args = parser.parse_args()

    draws = fetch_draws()
    if len(draws) < TEST_N + SEQ_LEN + 100:
        print(f"ERROR: only {len(draws)} draws -- need at least {TEST_N + SEQ_LEN + 100}")
        sys.exit(1)

    tf = get_tf()

    if args.skip_train and os.path.exists(MODEL_PATH):
        print(f"Loading existing model from {MODEL_PATH}...", flush=True)
        model = tf.keras.models.load_model(MODEL_PATH)
    elif args.skip_train:
        print(f"--skip-train set but {MODEL_PATH} not found -- training from scratch.")
        model = train(draws)
    else:
        model = train(draws)

    backtest(draws, model)


if __name__ == "__main__":
    main()
