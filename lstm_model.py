"""
LSTM Model cho Bingo18
- BingoPredictor: class wrapper dùng trong prediction_service
- Chạy train local: python lstm_model.py [--train | --predict | --all]
- Yêu cầu: pip install tensorflow==2.15.0

Model lưu vào multiset_markov/ (không bị dockerignore) → Cloud Run thấy được.
"""

import os
import sys
import json
import logging
import sqlite3

import numpy as np

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'


def _get_tf():
    """
    Windows tensorflow==2.15: 'tensorflow' là stub rỗng, gói thật là 'tensorflow_intel'.
    Hàm này trả về module tensorflow thật có đủ .keras, .compat, v.v.
    """
    try:
        import tensorflow_intel as _tf
        _ = _tf.keras
        return _tf
    except (ImportError, AttributeError):
        pass
    import tensorflow as _tf
    return _tf


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

try:
    import config as _cfg
    _MODELS_PATH = _cfg.MODELS_PATH          # 'multiset_markov'
    _DB_PATH     = _cfg.DB_PATH
except Exception:
    _MODELS_PATH = "multiset_markov"
    _DB_PATH     = os.environ.get("DB_PATH", "data/bingo18.db")

# Save inside MODELS_PATH so Docker COPY picks it up (models/ is dockerignored)
MODEL_PATH = os.path.join(_MODELS_PATH, "lstm_bingo18.keras")

SEQ_LEN = 20    # chuỗi 20 kỳ gần nhất
EPOCHS  = 50
BATCH   = 64
FEATURE_DIM = 12   # 6 (one-hot hiện tại) + 6 (cold gap mỗi số)


# ── Encoding ─────────────────────────────────────────────────────────────────

def _encode_sequence(draws: list) -> np.ndarray:
    """
    Mã hóa chuỗi draws thành ma trận (len, FEATURE_DIM).

    Mỗi timestep t gồm:
    - dims 0-5: tần suất số i+1 trong draw t (raw count / 3, giữ thông tin repeat)
    - dims 6-11: "cold gap" số i+1 = số kỳ kể từ lần cuối xuất hiện trước t, clip(0,10)/10
    """
    n = len(draws)
    result = np.zeros((n, FEATURE_DIM), dtype=np.float32)

    last_seen = [-10] * 6   # lần cuối xuất hiện của mỗi số (kỳ index)

    for t, draw in enumerate(draws):
        # dims 0-5: raw count (chuẩn hóa theo max 3)
        for num in draw:
            if 1 <= num <= 6:
                result[t, num - 1] += 1.0 / 3.0

        # dims 6-11: cold gap (bao lâu rồi số này chưa ra)
        for i in range(6):
            gap = t - last_seen[i]
            result[t, 6 + i] = min(gap, 10) / 10.0

        # cập nhật last_seen sau khi encode
        for num in draw:
            if 1 <= num <= 6:
                last_seen[num - 1] = t

    return result


def _encode_single(draw: list) -> np.ndarray:
    """Encode 1 draw thành 6-dim (dùng cho target y)."""
    v = np.zeros(6, dtype=np.float32)
    for n in draw:
        if 1 <= n <= 6:
            v[n - 1] += 1
    return np.clip(v, 0, 1)   # multi-hot binary (1 nếu số xuất hiện ít nhất 1 lần)


# ── Data loading ──────────────────────────────────────────────────────────────

def load_draws_from_db(limit: int = 60000) -> list:
    """
    Load từ DatabaseManager (Supabase nếu có DATABASE_URL, SQLite nếu không).
    Trả về list of list[int], cũ nhất trước.
    """
    try:
        from database import DatabaseManager
        db = DatabaseManager()
        df = db.get_recent_draws(limit)
        if df is not None and len(df) > 0:
            draws = [row["numbers"] for _, row in df.iterrows()]
            draws.reverse()   # get_recent_draws trả về mới nhất trước → đảo lại
            logger.info("Loaded %d draws from DatabaseManager", len(draws))
            return draws
    except Exception as e:
        logger.warning("DatabaseManager load failed: %s", e)

    # Fallback SQLite
    if not os.path.exists(_DB_PATH):
        raise FileNotFoundError(f"DB not found: {_DB_PATH}")
    conn = sqlite3.connect(_DB_PATH)
    rows = conn.execute(
        "SELECT numbers FROM draw_history ORDER BY draw_number ASC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    draws = []
    for (raw,) in rows:
        try:
            nums = json.loads(raw) if isinstance(raw, str) else raw
            draws.append([int(n) for n in nums])
        except Exception:
            pass
    logger.info("Loaded %d draws from SQLite fallback", len(draws))
    return draws


# ── Model architecture ────────────────────────────────────────────────────────

def build_model():
    tf = _get_tf()
    model = tf.keras.Sequential([
        tf.keras.layers.LSTM(128, input_shape=(SEQ_LEN, FEATURE_DIM),
                             return_sequences=True),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.LSTM(64),
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.Dense(32, activation='relu'),
        tf.keras.layers.Dense(6, activation='sigmoid'),
    ])
    model.compile(
        optimizer='adam',
        loss='binary_crossentropy',
        metrics=['accuracy'],
    )
    return model


# ── Training ──────────────────────────────────────────────────────────────────

def train(draws: list):
    if len(draws) < SEQ_LEN + 10:
        raise ValueError(f"Can du lieu: can it nhat {SEQ_LEN + 10} ky")

    encoded = _encode_sequence(draws)

    X, y = [], []
    for i in range(len(draws) - SEQ_LEN):
        X.append(encoded[i: i + SEQ_LEN])
        y.append(_encode_single(draws[i + SEQ_LEN]))

    X, y = np.array(X), np.array(y)
    logger.info("Sequences: %s  targets: %s", X.shape, y.shape)

    model = build_model()
    model.summary()

    tf = _get_tf()
    callbacks = [
        tf.keras.callbacks.EarlyStopping(patience=7, restore_best_weights=True,
                                         monitor='val_loss'),
        tf.keras.callbacks.ReduceLROnPlateau(patience=4, factor=0.5,
                                             monitor='val_loss', min_lr=1e-5),
    ]

    history = model.fit(
        X, y,
        epochs=EPOCHS,
        batch_size=BATCH,
        validation_split=0.15,
        callbacks=callbacks,
        verbose=1,
    )

    os.makedirs(_MODELS_PATH, exist_ok=True)
    model.save(MODEL_PATH)
    logger.info("Model saved -> %s", MODEL_PATH)
    return model, history


# ── BingoPredictor wrapper (dùng trong prediction_service) ────────────────────

class BingoPredictor:
    name = "lstm"

    def __init__(self, model_path: str = MODEL_PATH):
        self.model_path = model_path
        self.model      = None
        self.seq_len    = SEQ_LEN

    def load(self) -> bool:
        if not os.path.exists(self.model_path):
            logger.info("LSTM model not found at %s - fallback mode", self.model_path)
            return False
        try:
            tf = _get_tf()
            self.model = tf.keras.models.load_model(self.model_path)
            logger.info("LSTM loaded from %s", self.model_path)
            return True
        except Exception as e:
            logger.warning("LSTM load error: %s", e)
            return False

    def predict(self, df_or_draws, next_draw: int = None):
        import pandas as pd
        if isinstance(df_or_draws, pd.DataFrame):
            recent = [row["numbers"] for _, row in df_or_draws.head(self.seq_len + 10).iterrows()]
        else:
            recent = list(df_or_draws)[: self.seq_len + 10]

        if self.model is None or len(recent) < self.seq_len:
            return self._fallback(recent)

        try:
            recent = recent[:self.seq_len + 10]
            seq = _encode_sequence(recent)[-self.seq_len:]   # (SEQ_LEN, FEATURE_DIM)
            seq = seq[np.newaxis, ...]                        # (1, SEQ_LEN, FEATURE_DIM)
            probs = self.model.predict(seq, verbose=0)[0]    # (6,)

            # Chọn top-3 theo sigmoid score (số có xác suất cao nhất)
            top3_idx = np.argsort(probs)[::-1][:3].tolist()
            nums     = sorted([i + 1 for i in top3_idx])
            conf     = float(np.mean(probs[top3_idx]))
            return [(nums, conf)]
        except Exception as e:
            logger.error("LSTM predict error: %s", e)
            return self._fallback(recent)

    def _fallback(self, recent):
        from collections import Counter
        freq = Counter()
        for draw in recent:
            freq.update(draw)
        top3 = [n for n, _ in freq.most_common(3)]
        if len(top3) < 3:
            top3 = [1, 3, 5]
        return [(sorted(top3), 0.35)]


# ── FullLSTMPredictor (56-class softmax, models/lstm_full_bingo18.keras) ─────

from itertools import combinations_with_replacement as _cwr

_FULL_SEQ_LEN  = 20
_FULL_MODEL_PATH = os.path.join("models", "lstm_full_bingo18.keras")
_MULTISETS     = list(_cwr(range(1, 7), 3))   # 56 sorted multiset combos


class FullLSTMPredictor:
    """
    Wraps models/lstm_full_bingo18.keras (56-class softmax over Bingo18 multisets).
    Size win rate 36.7% in backtest; acts as an additional LON-aware voter.
    """
    name = "lstm_full"

    def __init__(self, model_path: str = _FULL_MODEL_PATH):
        self.model_path = model_path
        self.model      = None
        self.seq_len    = _FULL_SEQ_LEN

    def load(self) -> bool:
        if not os.path.exists(self.model_path):
            logger.info("FullLSTM model not found at %s - skipping", self.model_path)
            return False
        try:
            tf = _get_tf()
            self.model = tf.keras.models.load_model(self.model_path)
            logger.info("FullLSTM loaded from %s", self.model_path)
            return True
        except Exception as e:
            logger.warning("FullLSTM load error: %s", e)
            return False

    @staticmethod
    def _encode(nums) -> np.ndarray:
        v = np.zeros(6, dtype=np.float32)
        for n in nums:
            if 1 <= n <= 6:
                v[n - 1] += 1.0
        return v / 3.0

    def predict(self, df_or_draws, next_draw: int = None):
        import pandas as pd
        if isinstance(df_or_draws, pd.DataFrame):
            recent = [row["numbers"] for _, row in df_or_draws.head(self.seq_len + 10).iterrows()]
        else:
            recent = list(df_or_draws)[: self.seq_len + 10]

        if self.model is None or len(recent) < self.seq_len:
            return self._fallback(recent)

        try:
            seq   = np.array([self._encode(d) for d in recent[-self.seq_len:]])[np.newaxis]
            probs = self.model.predict(seq, verbose=0)[0]   # (56,)
            cls   = int(np.argmax(probs))
            combo = sorted(list(_MULTISETS[cls]))
            conf  = float(probs[cls])
            return [(combo, conf)]
        except Exception as e:
            logger.error("FullLSTM predict error: %s", e)
            return self._fallback(recent)

    def _fallback(self, recent):
        from collections import Counter
        freq = Counter()
        for draw in recent:
            freq.update(draw)
        top3 = [n for n, _ in freq.most_common(3)]
        if len(top3) < 3:
            top3 = [1, 3, 5]
        return [(sorted(top3), 0.35)]


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    mode  = sys.argv[1] if len(sys.argv) > 1 else "--all"
    draws = load_draws_from_db(60000)
    if not draws:
        print("Khong co data!")
        return

    model = None

    if mode in ("--train", "--all"):
        model, history = train(draws)
        val_loss = history.history['val_loss'][-1]
        epochs_run = len(history.history['val_loss'])
        print(f"\n=== DONE ===")
        print(f"Epochs thuc te : {epochs_run}")
        print(f"Val loss       : {val_loss:.4f}")
        print(f"Model luu tai  : {MODEL_PATH}")

    if mode in ("--predict", "--all"):
        bp = BingoPredictor()
        if model:
            bp.model = model
        else:
            bp.load()
        result = bp.predict(draws[-SEQ_LEN - 10:])
        print(f"\nDu doan ky tiep: {result[0][0]}  (conf={result[0][1]:.3f})")


if __name__ == "__main__":
    main()
