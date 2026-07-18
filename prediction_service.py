"""
Prediction Service
- Được gọi bởi /api/trigger-prediction (Cloud Scheduler)
- Được gọi bởi admin_interface khi submit kết quả
Stateless: không giữ state giữa các request (Cloud Run)
"""

import json
import logging
import os
import traceback
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

import config
from database import DatabaseManager, USE_POSTGRES
from models import HybridModel, MarkovModel, ColdNumberModel, FWBRModel, MLEnsembleModel, ModelSelector, SizePredictor, ComboColdModel
from ensemble_model import VotingEnsemble
from regime_detector import SizeRegimeDetector
from hedge_voter import load_hedge_weights, update_hedge_from_draw, _HEDGE_WARMUP
from conformal import get_conformal_quantile, get_prediction_set
from lstm_model import BingoPredictor, FullLSTMPredictor
from telegram_bot import TelegramBot
from calibration import get_calibrator, invalidate_calibrator

logger = logging.getLogger(__name__)

MODEL_SAVE_PATH = os.path.join(config.MODELS_PATH, "hybrid_model.pkl")
ALL_MODEL_NAMES = [
    'markov_order_2', 'cold_number_window_30', 'fwbr_w30', 'fwbr_w60',
    'ml_ensemble', 'hybrid_model', 'lstm', 'voting_ensemble', 'majority_vote',
]

# ── Lazy singleton (tồn tại trong 1 container instance) ──────
_model_cache = None
_model_cache_lock = threading.Lock()  # FIX: thread-safe access
_last_retrain_time: Optional[datetime] = None
_retrain_failure_count: int = 0

def invalidate_model_cache():
    """Gọi sau khi retrain để force reload model mới lên RAM"""
    global _model_cache
    with _model_cache_lock:
        _model_cache = None
    logger.info("🔄 Đã xóa cache model. Các request tiếp theo sẽ load model mới.")

def _background_retrain():
    """Retrain HybridModel + VotingEnsemble + SizePredictor từ 500 kỳ gần nhất, chạy ngầm."""
    global _model_cache, _last_retrain_time, _retrain_failure_count
    try:
        logger.info("Auto-Retrain: bắt đầu...")
        db = DatabaseManager()
        df = db.get_recent_draws(500)

        if len(df) < 50:
            logger.warning("Auto-Retrain: không đủ data (%d rows).", len(df))
            return

        hybrid = HybridModel()
        hybrid.train(df)
        hybrid.save(MODEL_SAVE_PATH)

        ensemble = VotingEnsemble()
        ensemble.train(df)
        ensemble.update_weights_from_db(db)

        size_pred = SizePredictor(decay_rate=0.005)
        size_pred.train(df)

        # Rebuild selector with fresh model instances; preserve LSTM voters from old cache
        fwbr_r   = FWBRModel(window_size=30, recency_weight=0.5)
        fwbr60_r = FWBRModel(window_size=60, recency_weight=0.5)
        new_selector = ModelSelector(db)
        for m in [hybrid.markov_model, hybrid.cold_model,
                  fwbr_r, fwbr60_r, hybrid.ml_model, hybrid, ensemble]:
            new_selector.add_model(m)

        # Ghi trực tiếp vào cache thay vì invalidate → tránh reload toàn bộ
        with _model_cache_lock:
            if _model_cache is not None:
                old = _model_cache
                for name, m in old[1]._models.items():
                    if name not in new_selector._models:
                        new_selector.add_model(m)
                _model_cache = (hybrid, new_selector, old[2], ensemble, size_pred)
            else:
                _model_cache = (hybrid, new_selector, None, ensemble, size_pred)
            _last_retrain_time = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))

        with _model_cache_lock:
            _retrain_failure_count = 0
        logger.info("Auto-Retrain: hoàn tất (df=%d rows, ensemble+ML retrained).", len(df))
    except Exception as e:
        with _model_cache_lock:
            _retrain_failure_count += 1
        logger.error("Auto-Retrain error (attempt %d): %s", _retrain_failure_count, e)
        traceback.print_exc()

def _get_models(db):
    global _model_cache
    # Fast path: no lock needed for read
    if _model_cache is not None:
        return _model_cache

    # Slow path: acquire lock to init
    with _model_cache_lock:
        if _model_cache is not None:  # double-check after lock
            return _model_cache

        hybrid   = HybridModel()
        fwbr     = FWBRModel(window_size=30, recency_weight=0.5)
        fwbr60   = FWBRModel(window_size=60, recency_weight=0.5)
        ensemble = VotingEnsemble()
        os.makedirs(config.MODELS_PATH, exist_ok=True)

        loaded = hybrid.load(MODEL_SAVE_PATH)
        df     = db.get_recent_draws(500)
        if not loaded and len(df) >= 50:
            hybrid.train(df)
            hybrid.save(MODEL_SAVE_PATH)

        if len(df) >= 50:
            ensemble.train(df)

        ensemble.update_weights_from_db(db)

        # LSTM voters only added when TensorFlow is available; otherwise skip
        # to avoid fallback-mode dead weight in selector
        lstm_voters = []
        try:
            lstm      = BingoPredictor()
            lstm_full = FullLSTMPredictor()
            lstm.load()
            lstm_full.load()
            if getattr(lstm, 'model', None) is not None:
                lstm_voters.append(lstm)
            if getattr(lstm_full, 'model', None) is not None:
                lstm_voters.append(lstm_full)
        except Exception as _le:
            logger.debug("LSTM not loaded (TF unavailable): %s", _le)

        selector = ModelSelector(db)
        for m in [hybrid.markov_model, hybrid.cold_model,
                  fwbr, fwbr60, hybrid.ml_model, hybrid, *lstm_voters, ensemble]:
            selector.add_model(m)

        size_pred = SizePredictor(decay_rate=0.005)
        if len(df) >= 30:
            size_pred.train(df)

        # Pre-warm transition cache so first prediction has full signal
        try:
            if len(df) > 0:
                _ensure_transition_cache(db, int(df.iloc[0]['draw_number']))
        except Exception:
            pass

        _model_cache = (hybrid, selector, fwbr, ensemble, size_pred)
        return _model_cache

# ── Ban-list diversity ────────────────────────────────────────
BAN_WINDOW = 8    # số kỳ gần nhất không được lặp combo

# P151/P152: Only predict from 20 distinct-number combos (3 different numbers).
# Analysis of 67k draws: distinct=1.56× expected, pair=0.78×, triple=0.26×.
# Machine structurally favors distinct combos — pairs/triples are permanently suppressed.
# 20 distinct combos cover 55.6% of actual draws; cold score now works without structural bias.
_STRUCTURAL_BANS: frozenset = frozenset({
    # 6 triples
    (1,1,1),(2,2,2),(3,3,3),(4,4,4),(5,5,5),(6,6,6),
    # 30 pairs (one repeated digit + one different)
    (1,1,2),(1,1,3),(1,1,4),(1,1,5),(1,1,6),
    (1,2,2),(2,2,3),(2,2,4),(2,2,5),(2,2,6),
    (1,3,3),(2,3,3),(3,3,4),(3,3,5),(3,3,6),
    (1,4,4),(2,4,4),(3,4,4),(4,4,5),(4,4,6),
    (1,5,5),(2,5,5),(3,5,5),(4,5,5),(5,5,6),
    (1,6,6),(2,6,6),(3,6,6),(4,6,6),(5,6,6),
})

def _get_banned_combos(db: DatabaseManager) -> set:
    """Trả về set các combo (tuple sorted) đã predict trong BAN_WINDOW kỳ gần nhất."""
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT predicted_numbers FROM predictions ORDER BY draw_number DESC LIMIT {BAN_WINDOW}"
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    banned = set(_STRUCTURAL_BANS)  # always ban pairs + triples (structural bias)
    for (nums,) in rows:
        parsed = json.loads(nums) if isinstance(nums, str) else nums
        banned.add(tuple(sorted(int(x) for x in parsed)))
    return banned


def get_diverse_prediction(history: List[List[int]], banned: set,
                           window: int = 30) -> List[int]:
    """
    Tìm combo lạnh nhất (số 1-6 chọn 3 có lặp) không nằm trong banned.
    Score = tổng tần suất của 3 số trong window kỳ gần nhất (thấp = lạnh hơn).
    """
    freq: Counter = Counter()
    for draw in history[-window:]:
        for n in draw:
            freq[n] += 1

    all_combos = [
        (i, j, k)
        for i in range(1, 7)
        for j in range(i, 7)
        for k in range(j, 7)
    ]  # 56 combos

    # Primary: tổng frequency thấp = lạnh hơn
    # Secondary: nhiều số khác nhau = any-match tốt hơn (unique > pair > triple)
    scored = sorted(all_combos, key=lambda c: (
        freq[c[0]] + freq[c[1]] + freq[c[2]],
        -(len(set(c)))
    ))

    for combo in scored:
        if combo not in banned:
            return list(combo)

    # Tất cả đều bị ban (không thể xảy ra với BAN_WINDOW≤56) → trả coldest
    return list(scored[0])


# ── Blended cold score for combo selection ──────────────────
def _build_recent_freq(df, window: int = 30):
    """Returns (combo_freq, num_freq, sum_freq) from last `window` draws."""
    from models import _parse_numbers as _pn
    combo_freq: Counter = Counter()
    num_freq: Counter   = Counter()
    sum_freq: Counter   = Counter()
    for row in df.head(window).itertuples():
        nums = [int(x) for x in _pn(row.numbers)]
        combo_freq[tuple(sorted(nums))] += 1
        for n in nums:
            num_freq[n] += 1
        sum_freq[sum(nums)] += 1
    return combo_freq, num_freq, sum_freq


def _cold_score(combo: tuple, combo_freq: Counter, num_freq: Counter,
                sum_freq: Counter = None,
                pred_num_freq: Counter = None,
                multi_freq: dict = None) -> float:
    """Lower = colder = better prediction target.
    Blends combo-level, number-level, sum-level recency, plus prediction diversity penalty.
    multi_freq: {window: Counter} for B multi-window cold score.
    pred_num_freq: số lần mỗi number đã được predict gần đây — penalize over-predicted.
    """
    c = combo_freq.get(combo, 0)
    n = sum(num_freq.get(x, 0) for x in combo) / 3.0
    s = (sum_freq.get(sum(combo), 0) / 1.5) if sum_freq else 0.0
    p = (sum(pred_num_freq.get(x, 0) for x in combo) / 3.0 * 0.40) if pred_num_freq else 0.0

    # B: multi-window cold — combo cold across 60+100 kỳ is "truly cold", not just noise
    # Normalized by expected random freq (window/56). Small weight to not override recency signal.
    m = 0.0
    if multi_freq:
        for w, wt in ((60, 0.08), (100, 0.05)):
            freq_w = multi_freq.get(w)
            if freq_w is not None:
                m += (freq_w.get(combo, 0) / (w / 56.0)) * wt

    return c + 0.25 * n + 0.10 * s + p + m


def _build_multi_window_combo_freq(df, windows=(60, 100)) -> dict:
    """Returns {window: Counter} of combo frequencies for B multi-window cold score."""
    from models import _parse_numbers as _pn_mw
    result = {}
    rows = list(df.head(max(windows)).itertuples())
    for w in windows:
        freq: Counter = Counter()
        for row in rows[:w]:
            freq[tuple(sorted(int(x) for x in _pn_mw(row.numbers)))] += 1
        result[w] = freq
    return result


# ── Prediction diversity tracker (B) ────────────────────────
_pred_diversity_window = 15          # số kỳ gần nhất theo dõi
_recent_pred_history: list  = []     # list[tuple[int,...]] newest ở cuối
_recent_pred_nums:  Counter = Counter()  # num → tổng lần xuất hiện trong window
_pred_diversity_lock = __import__('threading').Lock()

def _update_pred_diversity(numbers: list) -> None:
    """Cập nhật counter sau mỗi prediction để track over-predicted numbers."""
    global _recent_pred_history, _recent_pred_nums
    with _pred_diversity_lock:
        _recent_pred_history.append(tuple(numbers))
        if len(_recent_pred_history) > _pred_diversity_window:
            removed = _recent_pred_history.pop(0)
            for n in removed:
                _recent_pred_nums[n] -= 1
                if _recent_pred_nums[n] <= 0:
                    _recent_pred_nums.pop(n, None)
        for n in numbers:
            _recent_pred_nums[n] += 1


# ── Dynamic voter weight cache ───────────────────────────────
_voter_weight_cache: dict = {}
_voter_weight_ts: int = 0
_bocpd_cache: dict = {}        # {draw_number: {NHO: float, HOA: float, LON: float}}
_last_bocpd_regime: str = ''   # tracks last alerted regime to avoid alert spam
_last_triple_alert_draw: int = 0  # cooldown: don't re-alert within 8 draws
_TRIPLE_DROUGHT_THRESH = 25       # alert when ≥25 draws without a triple (near expected 36; fire early)
_TRIPLE_ALERT_COOLDOWN = 8        # draws between repeated triple drought alerts
# Gap analysis over 2,039 historical triple gaps: 26.2% of gaps ≤10 draws vs 19.7%
# expected under a memoryless geometric (mean 46) — triples cluster. After a fresh
# triple, the next ~10 draws carry ~33% elevated triple probability.
_last_triple_cluster_draw: int = 0  # last draw a cluster-window alert was sent
_TRIPLE_CLUSTER_WINDOW = 10         # draws of elevated triple probability after a fresh triple
_last_pair_alert_draw: int = 0    # cooldown for pair drought alert
_PAIR_DROUGHT_THRESH = 10         # alert when ≥10 draws without any pair (~1.1× expected 9.3)
_PAIR_ALERT_COOLDOWN = 5          # draws between repeated pair drought alerts
_VOTER_WEIGHT_MIN_SAMPLES = 20   # per-voter minimum before applying multiplier
_VOTER_WEIGHT_REFRESH_EVERY = 15  # draws between refreshes (low while building data)
_voter_decay_cache: dict = {}    # {voter_name: {'streak': int, 'decay': float}}

# ── P75: Voter decay auto-reset ──────────────────────────────
# P145: WR threshold lowered 0.35→0.20 — all Bingo18 voters naturally sit at
# 31-36% (random lottery ceiling ~37%), so 0.35 was resetting everyone on a
# long-streak, defeating the penalty system. Only truly broken voters (<20%) reset.
_DECAY_RESET_STREAK_MIN = 7    # streak >= 7 → decay at floor 0.55×
_DECAY_RESET_WR_MAX     = 0.20 # WR must also be below this to qualify (was 0.35)
_DECAY_RESET_MIN_DRAWS  = 30   # need at least 30 draws in window before resetting
_reset_alerted_voters: set = set()  # P77: track voters already alerted this reset session

# ── P102: Alert manager ──────────────────────────────────────
import time as _time_module

class AlertManager:
    """Unified per-key cooldown tracker for all automatic alerts."""

    def __init__(self):
        self._last: dict = {}  # {key: last_fired_ts}

    def fire(self, key: str, cooldown_sec: float) -> bool:
        """Return True and stamp the key if cooldown has elapsed; False otherwise."""
        now = _time_module.time()
        if (now - self._last.get(key, 0.0)) >= cooldown_sec:
            self._last[key] = now
            return True
        return False

    def last_fired(self, key: str) -> float:
        return self._last.get(key, 0.0)

    def reset(self, key: str) -> None:
        self._last.pop(key, None)

    def log(self, db, key: str, message: str = '', metadata: dict = None) -> None:
        """Persist a fired alert to alert_log table (best-effort, never raises)."""
        import json as _json
        try:
            conn = db.get_connection()
            try:
                cur  = conn.cursor()
                ph   = '%s' if USE_POSTGRES else '?'
                cur.execute(
                    f"INSERT INTO alert_log (alert_key, message, metadata) VALUES ({ph}, {ph}, {ph})",
                    (key, message or '', _json.dumps(metadata) if metadata else None)
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as _le:
            logger.debug("alert_log write error: %s", _le)

_alert_mgr = AlertManager()

# Alert thresholds
_WR_DROP_THRESHOLD    = 0.30   # rolling WR below this triggers P91 alert
_WR_DROP_COOLDOWN_SEC = 7200
_MOMENTUM_THRESHOLD    = 8     # same-SIZE streak length for P93 alert
_MOMENTUM_COOLDOWN_SEC = 3600  # per-SIZE cooldown
_GAP_THRESHOLD_MIN     = 12    # minutes since last draw for P94 alert
_GAP_COOLDOWN_SEC      = 1800
_VOTER_DRIFT_THRESHOLD    = 0.10  # conf drop (pp) for P98 alert
_VOTER_DRIFT_COOLDOWN_SEC = 7200  # per-voter cooldown

# ── Adaptive SIZE threshold cache ────────────────────────────
_adaptive_thresh_cache: dict = {}
_adaptive_thresh_ts: int = 0
_ADAPTIVE_THRESH_WINDOW = 50     # actual draws to look back
_ADAPTIVE_THRESH_REFRESH = 15    # same cadence as voter weights

# P64: adaptive TUNE_K — track pred_lon_excess across refresh cycles
_lon_excess_history: list = []   # rolling list of (draw_number, excess) per refresh
_TUNE_K_BASE   = 0.40
_TUNE_K_STEP   = 0.15   # per consecutive-excess cycle
_TUNE_K_MAX    = 1.00
_EXCESS_THRESH = 0.05   # min excess to count as "persistently over"

# ── EMA Smoother (#31) ───────────────────────────────────────
_EMA_ALPHA = 0.35          # 0=frozen, 1=no smoothing; 0.35 ≈ 3-draw half-life
_sw_ema: dict = {}         # {NHO, HOA, LON} normalized EMA fractions (0..1)
_SW_EMA_CONFIG_KEY = 'sw_ema_state'


def _load_sw_ema(db) -> None:
    """Load _sw_ema from system_config on cold start so all instances share EMA state."""
    global _sw_ema
    if _sw_ema:
        return
    try:
        conn = db.get_connection()
        try:
            cur = conn.cursor()
            ph = db._ph()
            cur.execute(f"SELECT config_value FROM system_config WHERE config_key={ph}",
                        (_SW_EMA_CONFIG_KEY,))
            row = cur.fetchone()
            if row:
                loaded = json.loads(row[0])
                if all(k in loaded for k in ('NHO', 'HOA', 'LON')):
                    _sw_ema = loaded
                    logger.debug("_sw_ema loaded from DB: %s", _sw_ema)
        finally:
            conn.close()
    except Exception as e:
        logger.debug("_load_sw_ema error: %s", e)


def _save_sw_ema(db) -> None:
    """Persist _sw_ema to system_config so cold-start instances inherit current state."""
    if not _sw_ema:
        return
    try:
        conn = db.get_connection()
        try:
            cur = conn.cursor()
            ph = db._ph()
            val = json.dumps(_sw_ema)
            if USE_POSTGRES:
                cur.execute(f"""
                    INSERT INTO system_config (config_key, config_value, description)
                    VALUES ({ph},{ph},{ph})
                    ON CONFLICT (config_key) DO UPDATE
                      SET config_value = EXCLUDED.config_value, updated_at = NOW()
                """, (_SW_EMA_CONFIG_KEY, val, 'EMA smoother size weights — shared across instances'))
            else:
                cur.execute(
                    f"INSERT OR REPLACE INTO system_config (config_key, config_value, description) "
                    f"VALUES ({ph},{ph},{ph})",
                    (_SW_EMA_CONFIG_KEY, val, 'EMA smoother size weights'))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.debug("_save_sw_ema error: %s", e)


# ── Time-of-day SIZE distribution (static, 10,000 kỳ gần nhất) ──────────────
# Dùng trực tiếp thay vì live DB query → nhanh hơn, ổn định hơn.
# Cập nhật: 2026-07-15 (bias_analysis.py, n≈600-640/giờ). Blend weight = 0.50 cho giờ lệch >2pp, 0.30 cho giờ bình thường.
_TOD_SIZE_STATS: dict = {
    #  h:  {NHO,  HOA,  LON}
    6:  {'NHO': 0.375, 'HOA': 0.293, 'LON': 0.332},  # LON thấp (giữ nguyên, chưa có data mới)
    7:  {'NHO': 0.366, 'HOA': 0.241, 'LON': 0.394},  # LON cao
    8:  {'NHO': 0.400, 'HOA': 0.262, 'LON': 0.338},  # NHO cao, LON thấp
    9:  {'NHO': 0.408, 'HOA': 0.209, 'LON': 0.383},  # NHO cao nhất, HOA thấp
    10: {'NHO': 0.405, 'HOA': 0.228, 'LON': 0.367},  # NHO cao
    11: {'NHO': 0.403, 'HOA': 0.255, 'LON': 0.342},  # NHO cao, LON thấp
    12: {'NHO': 0.361, 'HOA': 0.255, 'LON': 0.384},  # LON cao
    13: {'NHO': 0.367, 'HOA': 0.252, 'LON': 0.381},  # LON cao
    14: {'NHO': 0.368, 'HOA': 0.232, 'LON': 0.400},  # LON cao nhất
    15: {'NHO': 0.361, 'HOA': 0.269, 'LON': 0.370},
    16: {'NHO': 0.400, 'HOA': 0.237, 'LON': 0.363},  # NHO cao
    17: {'NHO': 0.352, 'HOA': 0.250, 'LON': 0.398},  # LON cao
    18: {'NHO': 0.348, 'HOA': 0.261, 'LON': 0.390},  # NHO thấp nhất
    19: {'NHO': 0.373, 'HOA': 0.242, 'LON': 0.385},
    20: {'NHO': 0.363, 'HOA': 0.245, 'LON': 0.392},
    21: {'NHO': 0.379, 'HOA': 0.245, 'LON': 0.376},
    22: {'NHO': 0.364, 'HOA': 0.281, 'LON': 0.355},  # HOA cao bất thường
}

# ── K: Per-voter WR by hour multiplier (3000-kỳ vote_breakdown analysis) ─────
# factor = voter_wr_at_hour / voter_overall_wr. Only entries with |delta| >= 5pp.
# Applied as additional eff multiplier in majority vote alongside existing wr_mult.
_VOTER_HOUR_MULT: dict = {
    'prior_lon': {
        6:  0.84,  # WR 30.1% vs 36.0% overall (n=156, -7.4pp)
        7:  0.94,  # WR 33.7% (n=163, borderline)
    },
    'prior_nho': {
        6:  1.08,  # WR 40.4% vs 37.2% overall (n=156, +3.2pp)
        11: 1.14,  # WR 42.3% (n=189, +5.1pp)
        8:  0.90,  # WR 33.5% (n=167, -3.7pp)
        16: 0.91,  # WR 33.7% (n=190, -3.5pp)
    },
    'markov': {
        6:  0.59,  # WR 20.7% (n=29, -14.9pp) — terrible at 6h
        9:  0.61,  # WR 21.7% (n=46, -13.9pp) — terrible at 9h
        12: 0.75,  # WR 26.5% (n=34, -9.1pp)
        17: 0.68,  # WR 24.1% (n=29, -11.5pp)
    },
}

# ── Time-of-day SIZE prior cache (legacy — giữ cho backward compat) ──────────
_tod_prior_cache: dict = {}
_tod_prior_ts: int = 0
_TOD_PRIOR_REFRESH = 5000
_TOD_MIN_SAMPLES = 500

# ── Order-2 SIZE Markov table (6000 kỳ) ────────────────────────────────────────
# P(NHO|prev2,prev1), P(HOA|...), P(LON|...) — only NHO/LON used (HOA blocked).
# Strongest signal: LON→NHO → P(NHO)=40.7% (+3.2pp, 1.9σ).
_SIZE_MARKOV2: dict = {
    # (prev2, prev1): (P_NHO, P_HOA, P_LON)
    ('HOA', 'HOA'): (0.340, 0.256, 0.404),
    ('HOA', 'LON'): (0.336, 0.284, 0.380),
    ('HOA', 'NHO'): (0.368, 0.257, 0.375),
    ('LON', 'HOA'): (0.368, 0.250, 0.382),
    ('LON', 'LON'): (0.371, 0.285, 0.345),  # NHO > LON
    ('LON', 'NHO'): (0.407, 0.233, 0.360),  # strongest: NHO preferred
    ('NHO', 'HOA'): (0.350, 0.289, 0.361),
    ('NHO', 'LON'): (0.371, 0.260, 0.369),
    ('NHO', 'NHO'): (0.362, 0.268, 0.370),
}

# ── ToD bias correction: nhân hệ số vào prior_lon/prior_nho theo giờ ─────────
# Tính từ 3000 kỳ prediction_results: những giờ hệ thống lệch pred vs actual SIZE nhiều.
# factor < 1.0 = dampen (giảm confidence); > 1.0 = boost.
# Chỉ áp dụng khi lệch >= 10pp (pred - actual SIZE).
# Cập nhật: 2026-06-05.
_TOD_BIAS_CORRECTION: dict = {
    # h: {'lon': factor, 'nho': factor}
    6:  {'lon': 0.75, 'nho': 1.00},  # pred_lon=54.5% vs actual=30.1% → dampen LON mạnh
    7:  {'lon': 0.70, 'nho': 1.00},  # pred_lon=62% vs actual=33.7% → dampen LON mạnh nhất
    9:  {'lon': 1.00, 'nho': 0.90},  # pred_nho=57.5% vs actual=37.9% → dampen NHO nhẹ
    10: {'lon': 1.00, 'nho': 0.85},  # pred_nho=54.9% vs actual=39.1% → dampen NHO
    13: {'lon': 0.85, 'nho': 1.00},  # pred_lon=61.3% vs actual=40.7% → dampen LON
    20: {'lon': 1.00, 'nho': 0.85},  # pred_nho=59% vs actual=40% → dampen NHO
    # Các giờ còn lại: không có lệch đáng kể → factor = 1.0 (không điều chỉnh)
}

# ── Carry-over stats: xác suất số lặp lại từ kỳ trước theo giờ VN (6000-kỳ) ──
_CARRYOVER_STATS: dict = {
    # 6000 kỳ gần nhất, phân theo giờ VN (6h-21h)
    6:  {1: 40.1, 2: 44.4, 3: 39.3, 4: 35.7, 5: 31.5, 6: 45.1},
    7:  {1: 48.0, 2: 43.9, 3: 41.4, 4: 36.4, 5: 44.8, 6: 43.9},
    8:  {1: 40.5, 2: 45.9, 3: 36.5, 4: 44.4, 5: 41.6, 6: 51.9},
    9:  {1: 41.0, 2: 46.0, 3: 46.8, 4: 46.4, 5: 41.6, 6: 47.7},
    10: {1: 48.5, 2: 43.4, 3: 41.0, 4: 39.9, 5: 45.9, 6: 42.9},
    11: {1: 44.3, 2: 38.8, 3: 48.2, 4: 43.9, 5: 43.3, 6: 46.9},
    12: {1: 41.7, 2: 42.3, 3: 52.3, 4: 44.6, 5: 43.3, 6: 43.7},
    13: {1: 33.0, 2: 43.2, 3: 42.6, 4: 42.7, 5: 40.4, 6: 34.5},
    14: {1: 48.9, 2: 45.6, 3: 37.0, 4: 35.4, 5: 37.1, 6: 37.9},
    15: {1: 41.4, 2: 40.4, 3: 46.2, 4: 39.3, 5: 38.6, 6: 35.7},
    16: {1: 42.7, 2: 45.3, 3: 41.0, 4: 47.4, 5: 46.2, 6: 44.3},
    17: {1: 48.0, 2: 41.6, 3: 44.1, 4: 50.3, 5: 47.1, 6: 39.8},
    18: {1: 44.9, 2: 36.7, 3: 40.7, 4: 36.5, 5: 45.0, 6: 34.7},
    19: {1: 43.5, 2: 48.2, 3: 33.7, 4: 43.4, 5: 36.1, 6: 47.1},
    20: {1: 38.6, 2: 38.9, 3: 41.8, 4: 47.4, 5: 35.6, 6: 43.1},
    21: {1: 39.7, 2: 39.3, 3: 40.2, 4: 42.0, 5: 41.4, 6: 37.8},
}
_CARRYOVER_MIN_PCT  = 45.0   # ngưỡng để tính là "hot carry" (trên baseline ~41%)
_CARRYOVER_MAX_CONF = 0.38   # confidence tối đa của carry-over voter

# ── Auto-refresh static stats từ DB ──────────────────────────────────────────
_STATS_REFRESH_EVERY = 2000   # refresh mỗi ~2000 draws (~8 ngày)
_stats_refresh_draw: int = 0  # draw_number lần refresh gần nhất

def _refresh_static_stats(db, current_draw: int) -> None:
    """
    Tự động cập nhật _TOD_SIZE_STATS, _SIZE_MARKOV2, _CARRYOVER_STATS từ DB
    mỗi _STATS_REFRESH_EVERY draws. Fallback về bảng hardcode nếu query lỗi.
    """
    global _TOD_SIZE_STATS, _SIZE_MARKOV2, _CARRYOVER_STATS, _stats_refresh_draw
    if current_draw - _stats_refresh_draw < _STATS_REFRESH_EVERY:
        return
    if not config.DATABASE_URL:
        return
    _stats_refresh_draw = current_draw  # mark attempted upfront; prevents retry storm on DB failure
    conn = None
    try:
        conn = db.get_connection()
        cur  = conn.cursor()

        # ── 1. TOD SIZE distribution (6000 kỳ gần nhất) ──────────────────────
        cur.execute("""
            SELECT
                EXTRACT(HOUR FROM draw_time AT TIME ZONE 'UTC'
                                           AT TIME ZONE 'Asia/Ho_Chi_Minh')::int AS vn_hour,
                COUNT(*) AS total,
                SUM(CASE WHEN size_category = 'NHO' THEN 1 ELSE 0 END) AS nho,
                SUM(CASE WHEN size_category = 'HOA' THEN 1 ELSE 0 END) AS hoa,
                SUM(CASE WHEN size_category = 'LON' THEN 1 ELSE 0 END) AS lon
            FROM (SELECT * FROM draw_history ORDER BY draw_number DESC LIMIT 6000) sub
            WHERE draw_time IS NOT NULL
            GROUP BY vn_hour
            HAVING COUNT(*) >= 200
            ORDER BY vn_hour
        """)
        tod_rows = cur.fetchall()
        if len(tod_rows) >= 8:
            new_tod = {}
            for vn_hour, total, nho, hoa, lon in tod_rows:
                h = int(vn_hour)
                if 6 <= h <= 21:
                    new_tod[h] = {
                        'NHO': round(nho / total, 4),
                        'HOA': round(hoa / total, 4),
                        'LON': round(lon / total, 4),
                    }
            if new_tod:
                _TOD_SIZE_STATS = new_tod
                logger.info("_TOD_SIZE_STATS refreshed: %d hours from DB", len(new_tod))

        # ── 2. Size Markov2 transitions (6000 kỳ gần nhất) ───────────────────
        cur.execute("""
            WITH ordered AS (
                SELECT size_category,
                       LAG(size_category, 1) OVER (ORDER BY draw_number) AS prev1,
                       LAG(size_category, 2) OVER (ORDER BY draw_number) AS prev2
                FROM (SELECT * FROM draw_history ORDER BY draw_number DESC LIMIT 6000) sub
            )
            SELECT prev2, prev1,
                   COUNT(*) AS total,
                   SUM(CASE WHEN size_category = 'NHO' THEN 1 ELSE 0 END) AS nho,
                   SUM(CASE WHEN size_category = 'HOA' THEN 1 ELSE 0 END) AS hoa,
                   SUM(CASE WHEN size_category = 'LON' THEN 1 ELSE 0 END) AS lon
            FROM ordered
            WHERE prev1 IS NOT NULL AND prev2 IS NOT NULL
              AND prev1 IN ('NHO','HOA','LON') AND prev2 IN ('NHO','HOA','LON')
            GROUP BY prev2, prev1
            HAVING COUNT(*) >= 50
        """)
        mk_rows = cur.fetchall()
        if len(mk_rows) >= 7:
            new_mk = {}
            for prev2, prev1, total, nho, hoa, lon in mk_rows:
                new_mk[(prev2, prev1)] = (
                    round(nho / total, 4),
                    round(hoa / total, 4),
                    round(lon / total, 4),
                )
            if new_mk:
                _SIZE_MARKOV2 = new_mk
                logger.info("_SIZE_MARKOV2 refreshed: %d transitions from DB", len(new_mk))

        # ── 3. Carryover stats by VN hour (6000 kỳ gần nhất) ─────────────────
        cur.execute("""
            WITH pairs AS (
                SELECT
                    EXTRACT(HOUR FROM curr.draw_time AT TIME ZONE 'UTC'
                                       AT TIME ZONE 'Asia/Ho_Chi_Minh')::int AS vn_hour,
                    prev_num,
                    (curr.numbers::jsonb @> jsonb_build_array(prev_num)) AS carried
                FROM (
                    SELECT draw_number, draw_time, numbers,
                           LAG(numbers) OVER (ORDER BY draw_number) AS prev_numbers
                    FROM (SELECT * FROM draw_history ORDER BY draw_number DESC LIMIT 6000) t
                ) curr
                CROSS JOIN LATERAL (
                    SELECT value::int AS prev_num
                    FROM jsonb_array_elements_text(curr.prev_numbers::jsonb)
                ) pn
                WHERE curr.prev_numbers IS NOT NULL AND curr.draw_time IS NOT NULL
            )
            SELECT vn_hour, prev_num,
                   ROUND(100.0 * SUM(CASE WHEN carried THEN 1 ELSE 0 END) / COUNT(*), 1) AS carry_pct,
                   COUNT(*) AS n
            FROM pairs
            WHERE vn_hour BETWEEN 6 AND 21
            GROUP BY vn_hour, prev_num
            HAVING COUNT(*) >= 50
            ORDER BY vn_hour, prev_num
        """)
        co_rows = cur.fetchall()
        if co_rows:
            new_co: dict = {}
            for vn_hour, prev_num, carry_pct, _ in co_rows:
                h = int(vn_hour)
                new_co.setdefault(h, {})[int(prev_num)] = float(carry_pct)
            if len(new_co) >= 8:
                _CARRYOVER_STATS = new_co
                logger.info("_CARRYOVER_STATS refreshed: %d hours from DB", len(new_co))

        logger.info("Static stats refresh done at draw #%d", current_draw)
    except Exception as e:
        logger.warning("_refresh_static_stats error: %s", e)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _get_tod_priors(db, current_draw: int) -> dict:
    """
    Returns {hour: {NHO: float, HOA: float, LON: float}} frequency by VN hour.
    Only hours with >= _TOD_MIN_SAMPLES draws are included.
    Cached aggressively (long-run stats change very slowly).
    """
    global _tod_prior_cache, _tod_prior_ts
    if _tod_prior_cache and (current_draw - _tod_prior_ts) < _TOD_PRIOR_REFRESH:
        return _tod_prior_cache
    conn = None
    try:
        conn = db.get_connection()
        cur  = conn.cursor()
        if config.DATABASE_URL:
            cur.execute("""
                SELECT
                    EXTRACT(HOUR FROM draw_time AT TIME ZONE 'UTC'
                                               AT TIME ZONE 'Asia/Ho_Chi_Minh')::int AS vn_hour,
                    COUNT(*) AS total,
                    SUM(CASE WHEN size_category = 'NHO' THEN 1 ELSE 0 END) AS nho_cnt,
                    SUM(CASE WHEN size_category = 'HOA' THEN 1 ELSE 0 END) AS hoa_cnt,
                    SUM(CASE WHEN size_category = 'LON' THEN 1 ELSE 0 END) AS lon_cnt
                FROM (
                    SELECT draw_time, size_category FROM draw_history
                    WHERE draw_time IS NOT NULL
                    ORDER BY draw_number DESC LIMIT 2000
                ) sub
                GROUP BY vn_hour
                ORDER BY vn_hour
            """)
            rows = cur.fetchall()
        else:
            rows = []

        result = {}
        for vn_hour, total, nho_cnt, hoa_cnt, lon_cnt in rows:
            if total >= _TOD_MIN_SAMPLES:
                result[int(vn_hour)] = {
                    'NHO': round(nho_cnt / total, 4),
                    'HOA': round(hoa_cnt / total, 4),
                    'LON': round(lon_cnt / total, 4),
                    'n':   int(total),
                }
        _tod_prior_cache = result
        _tod_prior_ts    = current_draw
        logger.info("ToD priors loaded for %d hours", len(result))
        return result
    except Exception as e:
        logger.warning("ToD prior load error: %s", e)
        return {}
    finally:
        if conn is not None:
            conn.close()


def _get_adaptive_thresholds(db, current_draw: int) -> dict:
    """
    Computes SIZE thresholds from actual SIZE frequencies over the last
    _ADAPTIVE_THRESH_WINDOW draws with confirmed results.

    Returns dict with keys:
      hoa_suppress    — HOA needs this share of total weight (default 0.70)
      nho_share_min   — NHO needs this share to stay as NHO vs LON (default 0.45)
      prior_nho_conf  — confidence for the NHO prior voter (default 0.44)
      prior_lon_conf  — confidence for the LON prior voter (default 0.40)
    """
    global _adaptive_thresh_cache, _adaptive_thresh_ts
    if _adaptive_thresh_cache and (current_draw - _adaptive_thresh_ts) < _ADAPTIVE_THRESH_REFRESH:
        return _adaptive_thresh_cache

    defaults = {
        'hoa_suppress':   0.70,
        'nho_share_min':  0.50,
        'prior_nho_conf': 0.40,  # P70: actual NHO=LON=37.6% → equal priors
        'prior_lon_conf': 0.40,
    }
    conn = None
    try:
        conn = db.get_connection()
        cur  = conn.cursor()

        # Query 1: actual SIZE frequencies in last _ADAPTIVE_THRESH_WINDOW evaluated draws
        if config.DATABASE_URL:
            cur.execute(f"""
                SELECT actual_size, COUNT(*) AS cnt
                FROM (
                    SELECT
                        CASE
                            WHEN (SELECT SUM(v::int)
                                  FROM json_array_elements_text(pr.actual_numbers::json) v) <= 9  THEN 'NHO'
                            WHEN (SELECT SUM(v::int)
                                  FROM json_array_elements_text(pr.actual_numbers::json) v) <= 11 THEN 'HOA'
                            ELSE 'LON'
                        END AS actual_size
                    FROM prediction_results pr
                    JOIN predictions p ON pr.prediction_id = p.id
                    WHERE pr.actual_numbers IS NOT NULL
                    ORDER BY p.draw_number DESC
                    LIMIT {_ADAPTIVE_THRESH_WINDOW}
                ) sub
                GROUP BY actual_size
            """)
            rows = cur.fetchall()
        else:
            rows = []

        freq = {r[0]: r[1] for r in rows}
        total = sum(freq.values()) or 1
        nho_f = freq.get('NHO', 0) / total
        hoa_f = freq.get('HOA', 0) / total
        lon_f = freq.get('LON', 0) / total

        if total < 20:
            return defaults

        # P48/P150: blend recent-50 freq with static ToD table (6000 kỳ)
        # Blend weight = 0.50 khi giờ có tín hiệu rõ (lệch >2pp vs baseline),
        # 0.30 khi giờ bình thường — ưu tiên tín hiệu dài hạn hơn ở giờ biết rõ.
        vn_hour = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).hour
        tod_h = _TOD_SIZE_STATS.get(vn_hour, {})
        if tod_h:
            _deviation = max(
                abs(tod_h['NHO'] - 0.375),
                abs(tod_h['LON'] - 0.375),
            )
            _w = 0.50 if _deviation > 0.02 else 0.30   # giờ rõ tín hiệu → blend mạnh hơn
            nho_f = (1 - _w) * nho_f + _w * tod_h['NHO']
            hoa_f = (1 - _w) * hoa_f + _w * tod_h['HOA']
            lon_f = (1 - _w) * lon_f + _w * tod_h['LON']
            logger.debug("ToD blend h%02d (w=%.0f%%): NHO=%.1f%% HOA=%.1f%% LON=%.1f%%",
                         vn_hour, _w * 100, nho_f * 100, hoa_f * 100, lon_f * 100)

        # hoa_suppress kept for vote_breakdown logging only (P142 blocks HOA regardless)
        hoa_suppress = round(max(0.45, min(0.85, 0.70 - (hoa_f - 0.25) * 1.2)), 3)

        # Prior confidences (before P51 adjustment)
        prior_nho_conf = round(max(0.28, min(0.58, 0.40 * nho_f / 0.376)), 3)
        prior_lon_conf = round(max(0.28, min(0.58, 0.40 * lon_f / 0.376)), 3)
        # P65: prior_hoa removed in P144 — HOA permanently blocked

        # #4 ToD bias correction: giờ nào hệ thống lịch sử over-predict LON/NHO → dampen
        _bias = _TOD_BIAS_CORRECTION.get(vn_hour, {})
        if _bias.get('lon', 1.0) != 1.0:
            prior_lon_conf = round(max(0.20, prior_lon_conf * _bias['lon']), 3)
        if _bias.get('nho', 1.0) != 1.0:
            prior_nho_conf = round(max(0.25, prior_nho_conf * _bias['nho']), 3)
        if _bias:
            logger.info("ToD bias h%02d: lon×%.2f=%.3f nho×%.2f=%.3f",
                        vn_hour, _bias.get('lon',1), prior_lon_conf,
                        _bias.get('nho',1), prior_nho_conf)

        # P51 + P63: Query 2 — predicted SIZE distribution from same cursor (conn still open)
        pred_lon_excess = 0.0
        pred_nho_excess = 0.0
        try:
            cur.execute(f"""
                SELECT
                    SUM(CASE WHEN pred_sum <= 9  THEN 1 ELSE 0 END)::float / COUNT(*) AS pred_nho_f,
                    SUM(CASE WHEN pred_sum >= 12 THEN 1 ELSE 0 END)::float / COUNT(*) AS pred_lon_f,
                    COUNT(*) AS n
                FROM (
                    SELECT (SELECT SUM(v::int)
                            FROM json_array_elements_text(p.predicted_numbers::json) v) AS pred_sum
                    FROM predictions p
                    JOIN prediction_results pr ON pr.prediction_id = p.id
                    WHERE p.model_name = 'majority_vote'
                      AND pr.actual_numbers IS NOT NULL
                    ORDER BY p.draw_number DESC
                    LIMIT {_ADAPTIVE_THRESH_WINDOW}
                ) sub
            """)
            prow = cur.fetchone()
            if prow and prow[2] and prow[2] >= 20:
                p_nho_f, p_lon_f, p_n = float(prow[0] or 0), float(prow[1] or 0), int(prow[2])
                _LON_BASE = 0.375
                _NHO_BASE = 0.375
                pred_lon_excess = p_lon_f - _LON_BASE   # >0 = overpredicting LON vs baseline
                pred_nho_excess = p_nho_f - _NHO_BASE   # <0 = underpredicting NHO vs baseline
                _DEAD = 0.05
                _K    = 1.2
                if pred_lon_excess > _DEAD:
                    lon_corr = max(0.55, 1.0 - (pred_lon_excess - _DEAD) * _K)
                    prior_lon_conf = round(max(0.20, prior_lon_conf * lon_corr), 3)
                if pred_nho_excess < -_DEAD:
                    nho_boost = min(1.45, 1.0 + (-pred_nho_excess - _DEAD) * _K)
                    prior_nho_conf = round(min(0.65, prior_nho_conf * nho_boost), 3)
                logger.info(
                    "P51 DistCorr (n=%d): pred_LON=%.0f%% excess=%.0f%% → prior_lon=%.3f | "
                    "pred_NHO=%.0f%% excess=%.0f%% → prior_nho=%.3f",
                    p_n, p_lon_f * 100, pred_lon_excess * 100, prior_lon_conf,
                    p_nho_f * 100, pred_nho_excess * 100, prior_nho_conf,
                )
        except Exception as _pe:
            logger.debug("P51/P63 DistCorr query failed: %s", _pe)

        # P63 + P64: Auto-tune nho_share_min with adaptive TUNE_K.
        # K escalates when pred_lon_excess stays positive across refresh cycles.
        global _lon_excess_history
        _lon_excess_history.append((current_draw, pred_lon_excess))
        if len(_lon_excess_history) > 10:
            _lon_excess_history = _lon_excess_history[-10:]

        # Count consecutive cycles (most recent first) where excess > threshold
        consecutive = 0
        for _, ex in reversed(_lon_excess_history[:-1]):   # exclude current
            if ex > _EXCESS_THRESH:
                consecutive += 1
            else:
                break
        tune_k = round(min(_TUNE_K_MAX, _TUNE_K_BASE + consecutive * _TUNE_K_STEP), 3)

        nho_share_min_base = max(0.28, min(0.42, 0.32 - (nho_f - lon_f) * 0.5))
        # P143: sign was wrong — excess>0 means LON over-predicted, so LOWER threshold
        # to make NHO easier to keep (was + pred_lon_excess * tune_k, a feedback loop)
        nho_share_min = round(max(0.22, min(0.48, nho_share_min_base - pred_lon_excess * tune_k)), 3)
        logger.info(
            "P63/P64 AutoTune nho_share_min: base=%.3f excess=%.2f%% "
            "consecutive=%d tune_k=%.2f → %.3f",
            nho_share_min_base, pred_lon_excess * 100, consecutive, tune_k, nho_share_min,
        )

        result = {
            'hoa_suppress':       hoa_suppress,
            'nho_share_min':      nho_share_min,
            'prior_nho_conf':     prior_nho_conf,
            'prior_lon_conf':     prior_lon_conf,
            'tod_hour':           vn_hour,
            'pred_lon_excess':    round(pred_lon_excess, 3),
            'pred_nho_excess':    round(pred_nho_excess, 3),
            'tune_k':             tune_k,
            'consecutive_excess': consecutive,
        }
        _adaptive_thresh_cache = result
        _adaptive_thresh_ts    = current_draw
        logger.info(
            "AdaptiveThresh h%02d (n=%d NHO=%.1f%% HOA=%.1f%% LON=%.1f%%): "
            "hoa_sup=%.2f nho_min=%.2f prior_nho=%.3f prior_lon=%.3f",
            vn_hour, total, nho_f * 100, hoa_f * 100, lon_f * 100,
            hoa_suppress, nho_share_min, prior_nho_conf, prior_lon_conf,
        )
        return result
    except Exception as e:
        logger.warning("AdaptiveThresh load error: %s", e)
        return defaults
    finally:
        if conn is not None:
            conn.close()

def _get_voter_multipliers(db, current_draw: int) -> dict:
    """
    Returns {voter_name: multiplier} where multiplier = voter_size_accuracy / baseline.
    Multiplier > 1.0 → voter is above baseline → upweight their confidence.
    Only applied if voter has ≥ _VOTER_WEIGHT_MIN_SAMPLES evaluated predictions.
    Falls back to 1.0 per voter when insufficient data.
    """
    global _voter_weight_cache, _voter_weight_ts
    if _voter_weight_cache and (current_draw - _voter_weight_ts) < _VOTER_WEIGHT_REFRESH_EVERY:
        return _voter_weight_cache
    conn = None
    try:
        conn = db.get_connection()
        cur  = conn.cursor()
        ph   = db._ph()
        if config.DATABASE_URL:
            cur.execute("""
                SELECT p.vote_breakdown,
                    CASE
                        WHEN (SELECT SUM(v::int) FROM json_array_elements_text(pr.actual_numbers::json) v) <= 9  THEN 'NHO'
                        WHEN (SELECT SUM(v::int) FROM json_array_elements_text(pr.actual_numbers::json) v) <= 11 THEN 'HOA'
                        ELSE 'LON'
                    END AS actual_size
                FROM predictions p
                JOIN prediction_results pr ON pr.prediction_id = p.id
                WHERE p.vote_breakdown IS NOT NULL
                  AND pr.actual_numbers IS NOT NULL
                ORDER BY p.draw_number DESC LIMIT 200
            """)
        else:
            cur.execute("""
                SELECT p.vote_breakdown, pr.actual_numbers
                FROM predictions p
                JOIN prediction_results pr ON pr.prediction_id = p.id
                WHERE p.vote_breakdown IS NOT NULL AND pr.actual_numbers IS NOT NULL
                ORDER BY p.draw_number DESC LIMIT 200
            """)
        rows = cur.fetchall()

        from collections import defaultdict
        acc = defaultdict(lambda: {'correct': 0, 'total': 0})
        for vb_raw, actual_raw in rows:
            try:
                vb = json.loads(vb_raw) if isinstance(vb_raw, str) else vb_raw
                if config.DATABASE_URL:
                    actual_size = actual_raw
                else:
                    actual_nums = json.loads(actual_raw) if isinstance(actual_raw, str) else actual_raw
                    s = sum(int(x) for x in actual_nums)
                    actual_size = 'NHO' if s <= 9 else ('HOA' if s <= 11 else 'LON')
                all_votes = (vb or {}).get('all_votes')
                if all_votes:
                    for voter_name, voted_size in all_votes.items():
                        acc[voter_name]['total'] += 1
                        if voted_size == actual_size:
                            acc[voter_name]['correct'] += 1
            except Exception:
                continue

        baseline = 0.375
        _EARLY_PUNISH_MIN  = 10     # downweight early if clearly below baseline
        _EARLY_PUNISH_GAP  = 0.08   # must be >8% below baseline to trigger early
        multipliers = {}
        for name, a in acc.items():
            t  = a['total']
            wr = a['correct'] / t
            if t >= _VOTER_WEIGHT_MIN_SAMPLES:
                # Full two-way weighting once enough data
                mult = max(0.4, min(wr / baseline, 2.5))
                multipliers[name] = round(mult, 3)
            elif t >= _EARLY_PUNISH_MIN and wr < baseline - _EARLY_PUNISH_GAP:
                # Early punishment only: confirmed-bad voter gets downweighted before n=20
                mult = max(0.4, wr / baseline)
                multipliers[name] = round(mult, 3)

        # ── Streak-based decay (rows already ordered DESC = most recent first) ──
        streak: dict  = {}       # current loss streak per voter
        streak_done: set = set() # voters whose streak window is closed (hit a win)
        for vb_raw2, actual_size2 in rows:
            try:
                vb2 = json.loads(vb_raw2) if isinstance(vb_raw2, str) else vb_raw2
                av2 = (vb2 or {}).get('all_votes') or {}
                for vname, vsize in av2.items():
                    if vname in streak_done:
                        continue
                    if vsize == actual_size2:
                        streak_done.add(vname)   # win found → streak stops here
                    else:
                        streak[vname] = streak.get(vname, 0) + 1
            except Exception:
                continue

        def _streak_decay(s: int) -> float:
            if s <= 0: return 1.00
            if s <= 2: return 0.90
            if s <= 4: return 0.80
            if s <= 6: return 0.65
            return 0.55

        global _voter_decay_cache
        _voter_decay_cache = {
            name: {'streak': s, 'decay': _streak_decay(s)}
            for name, s in streak.items()
        }
        if any(d['streak'] > 0 for d in _voter_decay_cache.values()):
            logger.info("VoterDecay streaks: %s",
                        {k: f"{v['streak']}L→{v['decay']:.2f}x"
                         for k, v in _voter_decay_cache.items() if v['streak'] > 0})

        # ── P75+P77: Auto-reset voters stuck at decay floor ──────
        global _reset_alerted_voters
        for name, a in acc.items():
            t  = a['total']
            wr = a['correct'] / t if t else 0
            s  = streak.get(name, 0)
            qualifies = (t >= _DECAY_RESET_MIN_DRAWS
                         and s >= _DECAY_RESET_STREAK_MIN
                         and wr < _DECAY_RESET_WR_MAX)
            if qualifies:
                old_mult  = multipliers.get(name, 1.0)
                old_decay = _voter_decay_cache.get(name, {}).get('decay', 1.0)
                multipliers[name] = 1.0
                streak[name] = 0
                _voter_decay_cache[name] = {'streak': 0, 'decay': 1.0}
                logger.warning(
                    "P75 VoterDecayReset: %s was mult=%.2fx decay=%.2fx streak=%d "
                    "WR=%.1f%% (n=%d) → reset to 1.0x",
                    name, old_mult, old_decay, s, wr * 100, t,
                )
                # P77: alert once per reset session
                if name not in _reset_alerted_voters:
                    _reset_alerted_voters.add(name)
                    try:
                        TelegramBot().send_message(
                            f"🔄 <b>Voter Auto-Reset · P77</b>\n"
                            f"Voter <b>{name}</b> bị reset về 1.0×\n"
                            f"Trước: mult={old_mult:.2f}× · decay={old_decay:.2f}× · streak={s}L\n"
                            f"WR gần nhất: <b>{wr*100:.1f}%</b> ({t} kỳ)\n"
                            f"→ Voter sẽ được đánh giá lại từ đầu"
                        )
                    except Exception as _te:
                        logger.debug("P77 alert error: %s", _te)
            else:
                # voter recovered → remove from alerted set so next reset alerts again
                _reset_alerted_voters.discard(name)

        # ── Hedge overlay: replace WR/streak/decay with Hedge weights when warm ──
        # Hedge is more principled (formal regret bound) and self-adapts without
        # manual EMA alpha, streak-decay thresholds, or auto-reset constants.
        # Once it has seen >= _HEDGE_WARMUP draws it takes over as primary multiplier.
        try:
            _hw = load_hedge_weights(db)
            if _hw and _hw.n_updates >= _HEDGE_WARMUP:
                _hedge_mults = _hw.get_multipliers()
                multipliers.update(_hedge_mults)  # Hedge overrides WR-based values
                _voter_decay_cache = {}           # streak-decay not needed; Hedge subsumes it
                logger.info("Hedge active (n=%d η=%.2f): %s",
                            _hw.n_updates, _hw.eta,
                            {k: f"{v:.2f}x" for k, v in sorted(_hedge_mults.items())})
        except Exception as _he:
            logger.debug("Hedge overlay error (fallback to WR): %s", _he)

        # P146: ml_voter_mult_override — hard cap from system_config (0.0 = disable ML)
        try:
            cur_cfg = conn.cursor()
            cur_cfg.execute(
                f"SELECT config_value FROM system_config WHERE config_key = {ph}",
                ('ml_voter_mult_override',)
            )
            row_cfg = cur_cfg.fetchone()
            if row_cfg is not None:
                cap     = float(row_cfg[0])
                current = multipliers.get('ml', 1.0)
                multipliers['ml'] = min(current, cap)
                logger.info("P146 ml_voter_mult_override cap=%.3f → ml mult %.3f→%.3f",
                            cap, current, multipliers['ml'])
        except Exception as _cfg_e:
            logger.debug("ml_voter_mult_override read error: %s", _cfg_e)

        # ── #50 Manual overrides from system_config ──────────────
        try:
            cur_ov = conn.cursor()
            cur_ov.execute(
                f"SELECT config_key, config_value FROM system_config "
                f"WHERE config_key LIKE {ph}",
                ('voter_override_%',)
            )
            for ck, cv in cur_ov.fetchall():
                vname = ck[len('voter_override_'):]
                try:
                    cap = float(cv)
                    if cap != 1.0:
                        prev = multipliers.get(vname, 1.0)
                        multipliers[vname] = round(prev * cap, 3)
                        logger.info("#50 voter_override %s: %.3f × %.2f = %.3f", vname, prev, cap, multipliers[vname])
                except ValueError:
                    pass
        except Exception as _ov_e:
            logger.debug("voter_override read error: %s", _ov_e)

        _voter_weight_cache = multipliers
        _voter_weight_ts    = current_draw
        if multipliers:
            logger.info("VoterWeights (n=%d): %s", len(rows),
                        {k: f"{v:.2f}x" for k, v in sorted(multipliers.items())})
        return multipliers
    except Exception as e:
        logger.warning("VoterWeights load error: %s", e)
        return {}
    finally:
        if conn is not None:
            conn.close()


def _get_voter_decay() -> dict:
    """Returns cached decay factors {voter_name: {'streak': int, 'decay': float}}.
    Always call _get_voter_multipliers first (it populates the cache).
    """
    return _voter_decay_cache


# ── system_config reader ─────────────────────────────────────
def _get_active_model_from_config(db):
    """Read model_selection_mode and active_model from system_config table."""
    try:
        conn = db.get_connection()
        try:
            cur = conn.cursor()
            ph  = db._ph()
            cur.execute(f"SELECT config_key, config_value FROM system_config WHERE config_key IN ({ph},{ph})",
                        ('model_selection_mode', 'active_model'))
            cfg = dict(cur.fetchall())
        finally:
            conn.close()
        mode   = cfg.get('model_selection_mode', 'auto')
        active = cfg.get('active_model', 'hybrid_model')
        return mode, active
    except Exception as e:
        logger.debug("system_config read error: %s", e)
        return 'auto', 'hybrid_model'


# ── Size predictor adjustment ────────────────────────────────
_SIZE_ADJUST_THRESHOLD = 0.38         # only swap if predictor beats this confidence
_TRANSITION_ADJUST_THRESHOLD = 0.38  # only act when transition signal above NHO/LON baseline (~37%)
_TRANSITION_REFRESH_INTERVAL = 100   # recompute from DB every N new draws (~25 min of game time)

# Static fallback — used when DB query hasn't run yet
_TRANSITION_PROBS = {
    3:  {'NHO': 0.367, 'HOA': 0.262, 'LON': 0.371},
    4:  {'NHO': 0.372, 'HOA': 0.273, 'LON': 0.355},
    5:  {'NHO': 0.349, 'HOA': 0.289, 'LON': 0.362},
    6:  {'NHO': 0.347, 'HOA': 0.283, 'LON': 0.369},
    7:  {'NHO': 0.363, 'HOA': 0.263, 'LON': 0.374},
    8:  {'NHO': 0.369, 'HOA': 0.266, 'LON': 0.365},
    9:  {'NHO': 0.373, 'HOA': 0.262, 'LON': 0.365},
    10: {'NHO': 0.374, 'HOA': 0.264, 'LON': 0.361},
    11: {'NHO': 0.374, 'HOA': 0.265, 'LON': 0.361},
    12: {'NHO': 0.371, 'HOA': 0.271, 'LON': 0.358},
    13: {'NHO': 0.364, 'HOA': 0.261, 'LON': 0.375},
    14: {'NHO': 0.378, 'HOA': 0.257, 'LON': 0.365},
    15: {'NHO': 0.377, 'HOA': 0.250, 'LON': 0.373},
    16: {'NHO': 0.376, 'HOA': 0.266, 'LON': 0.358},
    17: {'NHO': 0.358, 'HOA': 0.273, 'LON': 0.369},
    18: {'NHO': 0.377, 'HOA': 0.242, 'LON': 0.381},
}
_TRANSITION_FALLBACK = {'NHO': 0.370, 'HOA': 0.265, 'LON': 0.365}

# ── Dynamic transition cache ──────────────────────────────────
_transition_cache: dict = {}           # {probs: {...}, top_sums: {...}, loaded_at: int}
_transition_cache_lock = threading.Lock()

def _query_transition_probs(db) -> tuple:
    """Query DB for P(next_size|prev_sum) and top-3 next sums. Returns (probs, top_sums)."""
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            WITH recent AS (
                SELECT sum_value, draw_number
                FROM draw_history ORDER BY draw_number DESC LIMIT 5000
            ),
            ordered AS (
                SELECT sum_value,
                       LEAD(sum_value) OVER (ORDER BY draw_number) AS next_sum
                FROM recent
            ),
            totals AS (
                SELECT sum_value, COUNT(*) AS total
                FROM ordered WHERE next_sum IS NOT NULL GROUP BY sum_value
            )
            SELECT o.sum_value,
                   CASE WHEN o.next_sum <= 9 THEN 'NHO'
                        WHEN o.next_sum <= 11 THEN 'HOA'
                        ELSE 'LON' END AS next_size,
                   ROUND(COUNT(*) * 100.0 / t.total, 2) AS pct
            FROM ordered o JOIN totals t ON o.sum_value = t.sum_value
            WHERE o.next_sum IS NOT NULL
            GROUP BY o.sum_value,
                     CASE WHEN o.next_sum <= 9 THEN 'NHO'
                          WHEN o.next_sum <= 11 THEN 'HOA'
                          ELSE 'LON' END,
                     t.total
            ORDER BY o.sum_value
        """)
        probs: dict = {}
        for prev_sum, next_size, pct in cur.fetchall():
            if prev_sum not in probs:
                probs[prev_sum] = {'NHO': 0.0, 'HOA': 0.0, 'LON': 0.0}
            probs[prev_sum][next_size] = float(pct) / 100.0  # pct stored as 0-100, normalize to 0-1

        cur.execute("""
            WITH recent AS (
                SELECT sum_value, draw_number
                FROM draw_history ORDER BY draw_number DESC LIMIT 5000
            ),
            ordered AS (
                SELECT sum_value,
                       LEAD(sum_value) OVER (ORDER BY draw_number) AS next_sum
                FROM recent
            ),
            totals AS (
                SELECT sum_value, COUNT(*) AS total
                FROM ordered WHERE next_sum IS NOT NULL GROUP BY sum_value
            ),
            counted AS (
                SELECT o.sum_value, o.next_sum,
                       ROUND(COUNT(*) * 100.0 / t.total, 1) AS pct
                FROM ordered o JOIN totals t ON o.sum_value = t.sum_value
                WHERE o.next_sum IS NOT NULL
                GROUP BY o.sum_value, o.next_sum, t.total
            ),
            ranked AS (
                SELECT sum_value, next_sum, pct,
                       RANK() OVER (PARTITION BY sum_value ORDER BY pct DESC) AS rnk
                FROM counted
            )
            SELECT sum_value, next_sum, pct FROM ranked WHERE rnk <= 3
            ORDER BY sum_value, rnk
        """)
        top_sums: dict = {}
        for prev_sum, next_sum, pct in cur.fetchall():
            top_sums.setdefault(prev_sum, []).append([int(next_sum), float(pct) / 100.0])  # normalize to 0-1

        return probs, top_sums
    finally:
        conn.close()


def _ensure_transition_cache(db, current_draw: int):
    """Refresh _transition_cache if stale (> _TRANSITION_REFRESH_INTERVAL draws since last load)."""
    global _transition_cache
    if (_transition_cache and
            current_draw - _transition_cache.get('loaded_at', 0) < _TRANSITION_REFRESH_INTERVAL):
        return
    with _transition_cache_lock:
        if (_transition_cache and
                current_draw - _transition_cache.get('loaded_at', 0) < _TRANSITION_REFRESH_INTERVAL):
            return
        try:
            probs, top_sums = _query_transition_probs(db)
            _transition_cache = {'probs': probs, 'top_sums': top_sums, 'loaded_at': current_draw}
            logger.info("TransitionCache refreshed at draw #%d (%d sums)", current_draw, len(probs))
        except Exception as e:
            logger.warning("TransitionCache reload failed: %s", e)
            if not _transition_cache:
                _transition_cache = {'probs': _TRANSITION_PROBS, 'top_sums': {}, 'loaded_at': 0}


def _apply_size_prediction(numbers: List[int], df, size_pred, banned: set,
                           prev_sum: Optional[int] = None,
                           loss_streak: int = 0) -> List[int]:
    """
    If SizePredictor is confident about a category that differs from the
    current numbers' size, swap to the coldest combo in the predicted category.
    Returns original numbers if predictor is uncertain or no valid swap found.
    """
    try:
        df_s = df.sort_values('draw_number')
        if 'sum_value' in df_s.columns:
            sums = [int(x) for x in df_s['sum_value'].tolist()]
        else:
            from models import _parse_numbers as _pn
            sums = [sum(_pn(r)) for r in df_s['numbers']]
        sizes = [SizePredictor._cat(s) for s in sums]

        pred_cat, pred_conf = size_pred.predict(sums, sizes)
        current_cat = ('NHO' if sum(numbers) <= 9 else ('HOA' if sum(numbers) <= 11 else 'LON'))

        if current_cat == pred_cat:
            return numbers
        # P149: HOA blocked at SizePredictor level too
        if pred_cat == 'HOA':
            return numbers
        # P146: LON→NHO flip blocked (30.0% WR vs 37.2% baseline)
        if current_cat == 'LON' and pred_cat == 'NHO':
            return numbers
        # P150: NHO→LON flip blocked permanently (18.75% WR over 16 cases on 04/06/2026
        # vs 37.5% baseline — majority vote NHO signal is correct, flip consistently hurts)
        if current_cat == 'NHO' and pred_cat == 'LON':
            return numbers
        if pred_conf < _SIZE_ADJUST_THRESHOLD:
            # SizePredictor uncertain — fallback to transition probability from prev draw
            if prev_sum is not None:
                _tc = _transition_cache
                t_probs = ((_tc['probs'].get(prev_sum) if _tc else None)
                           or _TRANSITION_PROBS.get(prev_sum, _TRANSITION_FALLBACK))
                t_best = max(t_probs, key=t_probs.get)
                if t_best != current_cat and t_probs[t_best] >= _TRANSITION_ADJUST_THRESHOLD:
                    pred_cat, pred_conf = t_best, t_probs[t_best]
                    logger.info("TransitionPredictor: prev_sum=%d → prefer %s (%.1f%%)",
                                prev_sum, pred_cat, pred_conf * 100)
                else:
                    return numbers
            else:
                return numbers

        # P149: HOA blocked — TransitionPredictor may have set pred_cat='HOA' after the early guard
        if pred_cat == 'HOA':
            return numbers

        # Coldest combo in predicted size that is not banned
        combo_freq, num_freq, sum_freq = _build_recent_freq(df, window=30)

        target_combos = [
            c for c in ComboColdModel.ALL_COMBOS
            if SizePredictor._cat(sum(c)) == pred_cat and c not in banned
        ]
        if not target_combos:
            return numbers

        # Narrow to likely next sum from transition cache (improves is_win_sum)
        # Only apply when transition gives clear signal (pct > 8.5% = 35% above uniform baseline 6.25%)
        if prev_sum is not None:
            _tc = _transition_cache
            top_sums = (_tc.get('top_sums', {}).get(prev_sum, []) if _tc else [])
            for next_sum, pct in top_sums[:2]:
                if (SizePredictor._cat(next_sum) == pred_cat and pct > 0.085):
                    sum_filtered = [c for c in target_combos if sum(c) == next_sum]
                    if sum_filtered:
                        target_combos = sum_filtered
                        logger.info("SumAlign: prev=%d → prefer sum=%d (%.1f%%) → %d combos",
                                    prev_sum, next_sum, pct * 100, len(sum_filtered))
                        break

        coldest = min(target_combos, key=lambda c: _cold_score(c, combo_freq, num_freq, sum_freq))
        logger.info("SizePredictor: %s→%s (conf=%.2f) swap %s→%s",
                    current_cat, pred_cat, pred_conf, sorted(numbers), sorted(coldest))
        return list(coldest)
    except Exception as e:
        logger.warning("_apply_size_prediction error: %s", e)
        return numbers


# ── Filter kèo đẹp ───────────────────────────────────────────
def _apply_filter(numbers: List[int], confidence: float, df) -> Optional[Tuple]:
    if confidence < 0.5:
        return None
    s = sorted(numbers)
    if all(s[i+1]-s[i] == 1 for i in range(len(s)-1)):
        return None
    hot = {n for n, _ in Counter(
        num for row in df.head(20)['numbers'] for num in row
    ).most_common(3)}
    if any(n in hot for n in numbers) and any(n not in hot for n in numbers):
        return (numbers, min(1.0, confidence * 1.1))
    return None

# ── Hot-Adjust: chuyển SIZE khi loss streak >= 3 ─────────────────
_HOT_ADJUST_STREAK_THRESHOLD = 3  # kích hoạt khi thua liên tiếp >= N kỳ
_HOT_WINDOW = 20                  # cửa sổ để tính hot numbers
_REGIME_WINDOW = 200               # cửa sổ lịch sử SIZE cho BOCPD regime voter

def _hot_adjust_size(numbers: List[int], df, loss_streak: int,
                     banned: set) -> tuple:
    """Nếu loss_streak >= ngưỡng, điều chỉnh SIZE dựa vào actual SIZE trend gần nhất.
    Returns (numbers, hot_adjust_note) — note được ghép vào prediction message, không gửi riêng."""
    if loss_streak < _HOT_ADJUST_STREAK_THRESHOLD:
        return numbers, None
    try:
        from models import _parse_numbers as _pn
        # Window co giãn theo độ dài streak: streak ngắn → nhìn sát các kỳ vừa thua
        # thay vì pha loãng trong 20 kỳ, vì đó chính là tín hiệu lệch SIZE đang xảy ra.
        streak_window = max(_HOT_ADJUST_STREAK_THRESHOLD, min(loss_streak + 2, _HOT_WINDOW))
        recent = df.head(streak_window)
        # Ngưỡng dominant nâng lên khi window nhỏ để bù biến động tự nhiên.
        dominant_thresh = 0.40 if streak_window >= _HOT_WINDOW else 0.55

        size_count = {'NHO': 0, 'HOA': 0, 'LON': 0}
        for _, row in recent.iterrows():
            nums = _pn(row['numbers'])
            s = sum(int(x) for x in nums if x)
            if s <= 9:
                size_count['NHO'] += 1
            elif s <= 11:
                size_count['HOA'] += 1
            else:
                size_count['LON'] += 1

        total = sum(size_count.values()) or 1
        dominant = max(('NHO', 'LON'), key=lambda sz: size_count[sz])
        if size_count[dominant] / total < dominant_thresh:
            logger.debug("HotAdjust: no clear signal (window=%d thresh=%.2f) NHO=%d HOA=%d LON=%d",
                         streak_window, dominant_thresh,
                         size_count['NHO'], size_count['HOA'], size_count['LON'])
            return numbers, None

        hot_size = dominant
        current_size = 'HOA' if 10 <= sum(numbers) <= 11 else ('NHO' if sum(numbers) <= 9 else 'LON')
        if hot_size == current_size:
            return numbers, None

        combo_freq, num_freq, sum_freq = _build_recent_freq(df, window=30)
        target = [
            c for c in ComboColdModel.ALL_COMBOS
            if SizePredictor._cat(sum(c)) == hot_size and c not in banned
        ]
        if not target:
            return numbers, None
        best = min(target, key=lambda c: combo_freq.get(c, 0))
        new_numbers = list(best)
        note = (f"streak={loss_streak} window={streak_window} NHO={size_count['NHO']} HOA={size_count['HOA']} LON={size_count['LON']}"
                f" dominant={hot_size}({size_count[dominant]/total*100:.0f}%) {current_size}→{hot_size}")
        logger.info("HotAdjust: %s → %s", numbers, new_numbers)
        return new_numbers, note
    except Exception as e:
        logger.debug("HotAdjust error: %s", e)
        return numbers, None


# ── Triple drought helper ──────────────────────────────────────
def _query_triple_drought(db) -> tuple:
    """Return (draws_since_last_triple, last_triple_draw) by scanning prediction_results.
    A triple is any draw where all 3 actual numbers are equal (e.g. [2,2,2]).
    Returns (None, None) on error or if no triple found in history.
    """
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        if config.DATABASE_URL:
            cur.execute("""
                SELECT draw_number FROM prediction_results
                WHERE actual_numbers IS NOT NULL
                  AND (actual_numbers::json->>0) = (actual_numbers::json->>1)
                  AND (actual_numbers::json->>1) = (actual_numbers::json->>2)
                ORDER BY draw_number DESC LIMIT 1
            """)
        else:
            cur.execute("""
                SELECT draw_number FROM prediction_results
                WHERE actual_numbers IS NOT NULL
                  AND json_extract(actual_numbers,'$[0]') = json_extract(actual_numbers,'$[1]')
                  AND json_extract(actual_numbers,'$[1]') = json_extract(actual_numbers,'$[2]')
                ORDER BY draw_number DESC LIMIT 1
            """)
        row = cur.fetchone()
        if not row:
            conn.close()
            return None, None
        last_triple_draw = int(row[0])
        cur.execute(f"SELECT MAX(draw_number) FROM prediction_results WHERE actual_numbers IS NOT NULL")
        latest_row = cur.fetchone()
        conn.close()
        latest = int(latest_row[0]) if latest_row and latest_row[0] else last_triple_draw
        return latest - last_triple_draw, last_triple_draw
    except Exception as e:
        logger.debug("triple drought query error: %s", e)
        return None, None


# ── Pair drought helper ────────────────────────────────────────
def _query_pair_drought(db) -> tuple:
    """Return (draws_since_last_pair, last_pair_draw, cold_doubles)
    where a pair = exactly 2 of 3 numbers equal (not all 3).
    cold_doubles = [(doubled_digit, drought_draws), ...] sorted by drought desc.
    """
    try:
        conn = db.get_connection()
        cur = conn.cursor()

        if config.DATABASE_URL:
            # PostgreSQL: pair condition (not triple)
            cur.execute("""
                SELECT draw_number FROM prediction_results
                WHERE actual_numbers IS NOT NULL
                  AND ((actual_numbers::json->>0) = (actual_numbers::json->>1)
                       OR (actual_numbers::json->>1) = (actual_numbers::json->>2)
                       OR (actual_numbers::json->>0) = (actual_numbers::json->>2))
                  AND NOT ((actual_numbers::json->>0) = (actual_numbers::json->>1)
                           AND (actual_numbers::json->>1) = (actual_numbers::json->>2))
                ORDER BY draw_number DESC LIMIT 1
            """)
            row = cur.fetchone()
            if not row:
                conn.close()
                return None, None, []
            last_pair_draw = int(row[0])
            cur.execute("SELECT MAX(draw_number) FROM prediction_results WHERE actual_numbers IS NOT NULL")
            latest = int(cur.fetchone()[0] or last_pair_draw)
            # Per-doubled-digit drought
            cur.execute("""
                WITH latest_draw AS (
                    SELECT MAX(draw_number) AS max_dn
                    FROM prediction_results WHERE actual_numbers IS NOT NULL
                ),
                pair_draws AS (
                    SELECT draw_number,
                        CASE
                            WHEN (actual_numbers::json->>0) = (actual_numbers::json->>1)
                                THEN (actual_numbers::json->>0)::int
                            WHEN (actual_numbers::json->>1) = (actual_numbers::json->>2)
                                THEN (actual_numbers::json->>1)::int
                            ELSE (actual_numbers::json->>0)::int
                        END AS ddigit
                    FROM prediction_results
                    WHERE actual_numbers IS NOT NULL
                      AND ((actual_numbers::json->>0) = (actual_numbers::json->>1)
                           OR (actual_numbers::json->>1) = (actual_numbers::json->>2)
                           OR (actual_numbers::json->>0) = (actual_numbers::json->>2))
                      AND NOT ((actual_numbers::json->>0) = (actual_numbers::json->>1)
                               AND (actual_numbers::json->>1) = (actual_numbers::json->>2))
                ),
                last_per AS (
                    SELECT ddigit, MAX(draw_number) AS last_dn FROM pair_draws GROUP BY ddigit
                )
                SELECT lp.ddigit, l.max_dn - lp.last_dn AS drought
                FROM last_per lp, latest_draw l
                ORDER BY drought DESC
            """)
            cold_doubles = [(int(r[0]), int(r[1])) for r in cur.fetchall()]
        else:
            # SQLite
            cur.execute("""
                SELECT draw_number FROM prediction_results
                WHERE actual_numbers IS NOT NULL
                  AND (json_extract(actual_numbers,'$[0]') = json_extract(actual_numbers,'$[1]')
                       OR json_extract(actual_numbers,'$[1]') = json_extract(actual_numbers,'$[2]')
                       OR json_extract(actual_numbers,'$[0]') = json_extract(actual_numbers,'$[2]'))
                  AND NOT (json_extract(actual_numbers,'$[0]') = json_extract(actual_numbers,'$[1]')
                           AND json_extract(actual_numbers,'$[1]') = json_extract(actual_numbers,'$[2]'))
                ORDER BY draw_number DESC LIMIT 1
            """)
            row = cur.fetchone()
            if not row:
                conn.close()
                return None, None, []
            last_pair_draw = int(row[0])
            cur.execute("SELECT MAX(draw_number) FROM prediction_results WHERE actual_numbers IS NOT NULL")
            latest = int(cur.fetchone()[0] or last_pair_draw)
            cur.execute("""
                WITH latest_draw AS (
                    SELECT MAX(draw_number) AS max_dn
                    FROM prediction_results WHERE actual_numbers IS NOT NULL
                ),
                pair_draws AS (
                    SELECT draw_number,
                        CASE
                            WHEN json_extract(actual_numbers,'$[0]') = json_extract(actual_numbers,'$[1]')
                                THEN CAST(json_extract(actual_numbers,'$[0]') AS INTEGER)
                            WHEN json_extract(actual_numbers,'$[1]') = json_extract(actual_numbers,'$[2]')
                                THEN CAST(json_extract(actual_numbers,'$[1]') AS INTEGER)
                            ELSE CAST(json_extract(actual_numbers,'$[0]') AS INTEGER)
                        END AS ddigit
                    FROM prediction_results
                    WHERE actual_numbers IS NOT NULL
                      AND (json_extract(actual_numbers,'$[0]') = json_extract(actual_numbers,'$[1]')
                           OR json_extract(actual_numbers,'$[1]') = json_extract(actual_numbers,'$[2]')
                           OR json_extract(actual_numbers,'$[0]') = json_extract(actual_numbers,'$[2]'))
                      AND NOT (json_extract(actual_numbers,'$[0]') = json_extract(actual_numbers,'$[1]')
                               AND json_extract(actual_numbers,'$[1]') = json_extract(actual_numbers,'$[2]'))
                ),
                last_per AS (
                    SELECT ddigit, MAX(draw_number) AS last_dn FROM pair_draws GROUP BY ddigit
                )
                SELECT lp.ddigit, l.max_dn - lp.last_dn AS drought
                FROM last_per lp, latest_draw l
                ORDER BY drought DESC
            """)
            cold_doubles = [(int(r[0]), int(r[1])) for r in cur.fetchall()]

        conn.close()
        return latest - last_pair_draw, last_pair_draw, cold_doubles
    except Exception as e:
        logger.debug("pair drought query error: %s", e)
        return None, None, []


# ── Majority Vote: tất cả ML models bầu SIZE, chọn số đồng thuận ──
def _run_majority_vote(df, next_draw: int, hybrid, selector, fwbr, ensemble,
                       banned: set, prev_sum: Optional[int] = None,
                       voter_multipliers: dict = None,
                       adaptive_thresholds: dict = None):
    """
    Chạy tất cả ML models → mỗi model bầu 1 SIZE (NHO/HOA/LON) →
    SIZE được chọn nhiều nhất thắng → lấy combo được nhiều model đồng ý nhất
    trong SIZE đó.
    Returns (numbers, confidence, vote_summary) hoặc (None, 0, {}) nếu lỗi.
    """
    recent_draws = [row["numbers"] for _, row in df.head(20).iterrows()]  # A: 50→20

    # (name, model, dùng df hay recent_draws)
    # P40: removed cold(29%), ensemble(28.4%), fwbr_w30(25.8%), fwbr_w60(32.3%) —
    # all NHO-biased with negative edge, adding noise not signal.
    # P49: removed hybrid (WR 31.5%, NHO-biased 58%, below baseline — adds noise).
    # P50: removed markov (-40.2 Hedge log_w, 90% fallback rate) and
    #       markov2_size (-42.7), size_freq (-32.5) — all confirmed negative edge.
    # P51: removed ml (WR 34.7%, Hedge log_w -163/η=0.05 over 4994 draws; after Hedge
    #       pruned it from DB, it reset to 0.925x WR-based mult instead of 0.5x floor,
    #       making it more influential than suppressed — negative edge, removed).
    # prior_nho raised 0.36→0.44 to replace hybrid's NHO signal with a cleaner anchor.
    candidates = []

    lstm_voter = selector.get_model('lstm')
    if lstm_voter and getattr(lstm_voter, 'model', None) is not None:
        candidates.append(('lstm', lstm_voter, False))

    lstm_full_voter = selector.get_model('lstm_full')
    if lstm_full_voter and getattr(lstm_full_voter, 'model', None) is not None:
        candidates.append(('lstm_full', lstm_full_voter, False))

    votes = []
    for name, model, use_df in candidates:
        try:
            arg  = df if use_df else recent_draws
            preds = model.predict(arg, next_draw)
            if preds:
                nums, conf = preds[0]
                nums = [int(n) for n in nums]
                if len(nums) == 3:
                    size = SizePredictor._cat(sum(nums))
                    _conf = float(conf)
                    votes.append({'name': name, 'nums': nums, 'size': size, 'conf': _conf})
        except Exception as e:
            logger.debug("MajorityVote skip %s: %s", name, e)

    # ── G: Sum transition voter — P(NHO|prev_sum) vs P(LON|prev_sum) ────────────
    try:
        if prev_sum is not None:
            _tc_g = _transition_cache
            _t_probs_g = ((_tc_g['probs'].get(prev_sum) if _tc_g and 'probs' in _tc_g else None)
                          or _TRANSITION_PROBS.get(prev_sum, _TRANSITION_FALLBACK))
            _p_nho_g = _t_probs_g.get('NHO', 0.375)
            _p_lon_g = _t_probs_g.get('LON', 0.375)
            _st_winner = 'NHO' if _p_nho_g >= _p_lon_g else 'LON'
            _st_edge   = abs(max(_p_nho_g, _p_lon_g) - 0.375)
            if _st_edge > 0.010:  # only vote when edge > 1pp
                _st_conf = round(min(0.32, 0.25 + _st_edge * 5), 3)
                _st_nums = [1, 1, 2] if _st_winner == 'NHO' else [4, 5, 6]
                votes.append({'name': 'sum_transition', 'nums': _st_nums,
                              'size': _st_winner, 'conf': _st_conf})
    except Exception as _ge:
        logger.debug("sum_transition voter error: %s", _ge)

    # ── BOCPD regime voter — Bayesian Online Changepoint Detection over the
    # SIZE sequence. Conservative hazard (expected run ~120 draws) so it mostly
    # tracks the base rate and only shifts when a streak is statistically
    # unlikely under "no change" — designed to avoid the same overreaction to
    # ordinary noise that the old fixed-window hot-adjust heuristic had. ──────
    _bocpd_dist = None
    try:
        if len(df) >= 20:
            from models import _parse_numbers as _pn_bc
            _bc_window = min(len(df), _REGIME_WINDOW)
            _bc_sizes = [
                SizePredictor._cat(sum(int(x) for x in _pn_bc(row.numbers)))
                for row in df.head(_bc_window).itertuples()
            ]
            _bc_sizes.reverse()  # df is most-recent-first; detector needs chronological order
            if next_draw in _bocpd_cache:
                _bc_dist = _bocpd_cache[next_draw]
            else:
                _bc_dist = SizeRegimeDetector().run(_bc_sizes)
                if len(_bocpd_cache) >= 200:
                    _bocpd_cache.pop(next(iter(_bocpd_cache)))
                _bocpd_cache[next_draw] = _bc_dist
            _bocpd_dist = {k: round(v, 3) for k, v in _bc_dist.items()}
            _bc_winner = max(_bc_dist, key=_bc_dist.get)
            if _bc_winner != 'HOA':
                _bc_conf = round(min(0.32, max(0.22, _bc_dist[_bc_winner])), 3)
                _bc_nums = [1, 1, 1] if _bc_winner == 'NHO' else [4, 5, 6]
                votes.append({'name': 'regime_bocpd', 'nums': _bc_nums,
                              'size': _bc_winner, 'conf': _bc_conf})
                logger.debug("regime_bocpd: dist=%s → %s conf=%.3f", _bc_dist, _bc_winner, _bc_conf)
    except Exception as _bce:
        logger.debug("regime_bocpd voter error: %s", _bce)

    # ── Anti-streak voter ─────────────────────────────────────────────────────
    # If same SIZE appears 4+ consecutive times, mean-reversion signal → vote opposite.
    try:
        from models import _parse_numbers as _pn_as
        _as_sizes = [
            SizePredictor._cat(sum(int(x) for x in _pn_as(row.numbers)))
            for row in df.head(10).itertuples(index=False)
        ]
        if _as_sizes:
            _as_last, _as_streak = _as_sizes[0], 1
            for _s in _as_sizes[1:]:
                if _s == _as_last:
                    _as_streak += 1
                else:
                    break
            if _as_streak >= 4 and _as_last != 'HOA':
                _as_anti = 'LON' if _as_last == 'NHO' else 'NHO'
                _as_conf = round(min(0.34, 0.22 + (_as_streak - 4) * 0.03), 3)
                _as_nums = [1, 1, 2] if _as_anti == 'NHO' else [4, 5, 6]
                votes.append({'name': 'anti_streak', 'nums': _as_nums,
                              'size': _as_anti, 'conf': _as_conf})
                logger.debug("anti_streak: %s×%d → vote %s conf=%.3f", _as_last, _as_streak, _as_anti, _as_conf)
    except Exception as _ase:
        logger.debug("anti_streak voter error: %s", _ase)

    # ── Number absence voter ──────────────────────────────────────────────────
    # Track individual number (1-6) absence. When a number is absent 15+ draws,
    # bias towards combos containing it and vote for the resulting SIZE.
    try:
        from models import _parse_numbers as _pn_na
        _na_last_seen: dict = {}
        for _i, row in enumerate(df.head(30).itertuples(index=False)):
            for _n in _pn_na(row.numbers):
                if _n not in _na_last_seen:
                    _na_last_seen[int(_n)] = _i
        _na_absence = {n: _na_last_seen.get(n, 30) for n in range(1, 7)}
        _na_coldest3 = sorted(_na_absence, key=lambda x: -_na_absence[x])[:3]
        _na_max_abs = _na_absence[_na_coldest3[0]]
        if _na_max_abs >= 15:
            _na_sorted = sorted(_na_coldest3)
            _na_sum = sum(_na_sorted)
            _na_size = 'NHO' if _na_sum <= 9 else ('HOA' if _na_sum <= 11 else 'LON')
            if _na_size == 'HOA':
                _na_size = 'NHO' if _na_sum <= 10 else 'LON'
            _na_conf = round(min(0.32, 0.20 + (_na_max_abs - 15) * 0.012), 3)
            votes.append({'name': 'num_absence', 'nums': _na_sorted,
                          'size': _na_size, 'conf': _na_conf})
            logger.debug("num_absence: coldest3=%s abs=%d → %s conf=%.3f", _na_sorted, _na_max_abs, _na_size, _na_conf)
    except Exception as _nae:
        logger.debug("num_absence voter error: %s", _nae)

    # ── Pair co-occurrence voter ──────────────────────────────────────────────
    # Find the pair (a,b) most frequently appearing together in last 50 draws.
    # If significantly above expected frequency, build a combo and vote its SIZE.
    try:
        from models import _parse_numbers as _pn_pc
        _pc_draws = [_pn_pc(row.numbers) for row in df.head(50).itertuples(index=False)]
        _pc_pair_cnt: Counter = Counter()
        for _d in _pc_draws:
            _uniq = sorted(set(int(x) for x in _d))
            for _pi in range(len(_uniq)):
                for _pj in range(_pi + 1, len(_uniq)):
                    _pc_pair_cnt[(_uniq[_pi], _uniq[_pj])] += 1
        if _pc_pair_cnt:
            (_pc_pair, _pc_cnt) = _pc_pair_cnt.most_common(1)[0]
            _pc_expected = len(_pc_draws) * 0.12  # ~expected pair co-occurrence freq
            if _pc_cnt > _pc_expected * 1.5:      # only fire if 50% above expected
                _pc_in_pair = set(_pc_pair)
                _pc_ls: dict = {}
                for _i, _d in enumerate(_pc_draws):
                    for _n in _d:
                        if int(_n) not in _pc_ls:
                            _pc_ls[int(_n)] = _i
                _pc_absence = {n: _pc_ls.get(n, 50) for n in range(1, 7) if n not in _pc_in_pair}
                _pc_cold3rd = max(_pc_absence, key=_pc_absence.get)
                _pc_combo = sorted(list(_pc_pair) + [_pc_cold3rd])
                _pc_sum = sum(_pc_combo)
                _pc_size = 'NHO' if _pc_sum <= 9 else ('HOA' if _pc_sum <= 11 else 'LON')
                if _pc_size == 'HOA':
                    _pc_size = 'NHO' if _pc_sum <= 10 else 'LON'
                _pc_conf = round(min(0.30, 0.18 + (_pc_cnt / max(_pc_expected, 1) - 1.5) * 0.04), 3)
                votes.append({'name': 'pair_cooc', 'nums': _pc_combo,
                              'size': _pc_size, 'conf': _pc_conf})
                logger.debug("pair_cooc: pair=%s cnt=%d → combo=%s %s conf=%.3f",
                             _pc_pair, _pc_cnt, _pc_combo, _pc_size, _pc_conf)
    except Exception as _pce:
        logger.debug("pair_cooc voter error: %s", _pce)

    # ── LLM voter (OpenRouter/Groq/Gemini) ────────────────────────────────────
    # Chỉ kích hoạt khi có ít nhất 1 API key. Timeout 8s để không block cycle.
    # Kết quả được cache theo draw_number — không gọi LLM 2 lần cho cùng kỳ.
    try:
        from ai_predictor import get_llm_vote as _get_llm_vote
        from models import _parse_numbers as _pn_llm
        _llm_draws = [
            {
                'draw_number': int(row.draw_number),
                'numbers':     [int(x) for x in _pn_llm(row.numbers)],
                'size_category': getattr(row, 'size_category', ''),
                'sum_value':   int(row.sum_value) if hasattr(row, 'sum_value') else 0,
            }
            for row in df.head(30).itertuples(index=False)
        ]
        _llm_draws.reverse()  # chronological order (oldest first)
        _llm_vote = _get_llm_vote(_llm_draws)
        if _llm_vote and _llm_vote.get('size') != 'HOA':
            votes.append(_llm_vote)
            logger.debug("llm voter: %s conf=%.3f", _llm_vote['size'], _llm_vote['conf'])
    except Exception as _llme:
        logger.debug("llm voter error: %s", _llme)

    # P45/P71: prior voters added BEFORE empty check — they are always present to anchor
    # the vote so _run_majority_vote never returns None even when all optional voters fail.
    _at = adaptive_thresholds or {}
    _prior_lon_conf = _at.get('prior_lon_conf', 0.40)
    _prior_nho_conf = _at.get('prior_nho_conf', 0.44)
    # P144: prior_hoa removed — HOA is permanently blocked by P142, so the voter
    # only adds HOA weight that always falls to runner-up, contributing noise.
    votes.append({'name': 'prior_lon', 'nums': [1, 2, 6], 'size': 'LON', 'conf': _prior_lon_conf})
    votes.append({'name': 'prior_nho', 'nums': [1, 1, 1], 'size': 'NHO', 'conf': _prior_nho_conf})

    if not votes:  # unreachable (prior voters always added), kept as safety net
        return None, 0.0, {}

    # D: Calibration cap — raw model confidence > 0.45 has no added WR signal
    # (30k-draw analysis: conf 0.45-0.80 all give WR 31-39%, same as conf 0.25)
    # Cap prevents high-conf voters from dominating with spurious confidence scores.
    _CONF_CAP = 0.45
    for _v in votes:
        if _v['conf'] > _CONF_CAP and _v['name'] not in ('prior_nho', 'prior_lon'):
            _v['conf'] = _CONF_CAP

    # NOTE: Transition voter removed (P23). DB analysis shows max transition signal is
    # only ~1.4% above base rate (game is essentially memoryless). Adding it introduced
    # NHO bias with zero predictive value. Transition logic kept in _apply_size_prediction.

    # P-CARRYOVER: voter dựa trên xác suất lặp số theo giờ VN
    _vn_hour = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).hour
    try:
        from models import _parse_numbers as _pn
        _co_stats = _CARRYOVER_STATS.get(_vn_hour, {})
        if _co_stats and len(df) > 0:
            _prev_nums = [int(x) for x in _pn(df.iloc[0]['numbers']) if x]
            if _prev_nums:
                _hot_carry = [(n, _co_stats[n]) for n in _prev_nums if _co_stats.get(n, 0) >= _CARRYOVER_MIN_PCT]
                if _hot_carry:
                    _proposed = [n for n, _ in _hot_carry]
                    _fill_order = sorted(range(1, 7), key=lambda x: _co_stats.get(x, 40.0), reverse=True)
                    for _fc in _fill_order:
                        if len(_proposed) >= 3:
                            break
                        _proposed.append(_fc)
                    _proposed = _proposed[:3]
                    _s = sum(_proposed)
                    _co_size = 'NHO' if _s <= 9 else ('HOA' if _s <= 11 else 'LON')
                    if _co_size == 'HOA':
                        _co_size = 'NHO' if _s <= 10 else 'LON'
                    _avg_carry = sum(p for _, p in _hot_carry) / len(_hot_carry)
                    _co_conf = round(min(_CARRYOVER_MAX_CONF, max(0.15, (_avg_carry - 40.0) / 50.0)), 3)
                    votes.append({'name': 'carryover', 'nums': _proposed, 'size': _co_size, 'conf': _co_conf})
                    logger.debug("CarryoverVoter h%02d: prev=%s hot=%s → size=%s conf=%.3f",
                                 _vn_hour, _prev_nums, _hot_carry, _co_size, _co_conf)
    except Exception as _ce:
        logger.debug("CarryoverVoter error: %s", _ce)

    # Bầu SIZE: confidence × accuracy-multiplier × streak-decay
    # P147: prior_lon stays fixed (eff=1.0) as LON anchor.
    # prior_nho now WR-penalized so NHO doesn't dominate when actual LON > NHO.
    _FIXED_VOTERS = {'prior_lon'}
    _mults  = voter_multipliers or {}
    _decay  = _get_voter_decay()   # populated by _get_voter_multipliers call above
    _eff_mults: dict = {}          # final effective multiplier per voter (for detail logging)
    size_weights: dict = {'NHO': 0.0, 'HOA': 0.0, 'LON': 0.0}
    for v in votes:
        if v['name'] in _FIXED_VOTERS:
            eff = 1.0
        else:
            wr_mult    = _mults.get(v['name'], 1.0)
            decay_mult = _decay.get(v['name'], {}).get('decay', 1.0)
            # K: per-voter hourly adjustment (3000-kỳ per-hour WR analysis)
            hour_adj   = _VOTER_HOUR_MULT.get(v['name'], {}).get(_vn_hour, 1.0)
            eff = max(0.3, wr_mult * decay_mult * hour_adj)
        _eff_mults[v['name']] = eff
        size_weights[v['size']] += v['conf'] * eff
    size_tally = Counter(v['size'] for v in votes)  # kept for logging

    # ── EMA Smoother (#31): blend normalized size_weights with running EMA ──
    global _sw_ema
    _raw_total = sum(size_weights.values()) or 1.0
    _raw_fracs = {s: size_weights[s] / _raw_total for s in ('NHO', 'HOA', 'LON')}
    if _sw_ema:
        _ema_fracs = {s: _EMA_ALPHA * _raw_fracs[s] + (1 - _EMA_ALPHA) * _sw_ema.get(s, _raw_fracs[s])
                      for s in ('NHO', 'HOA', 'LON')}
    else:
        _ema_fracs = _raw_fracs.copy()
    _sw_ema = _ema_fracs.copy()
    # Re-scale EMA fractions back to original weight magnitude for downstream code
    _ema_weights = {s: _ema_fracs[s] * _raw_total for s in ('NHO', 'HOA', 'LON')}
    _raw_majority = max(size_weights, key=size_weights.get)
    majority_size = max(_ema_weights, key=_ema_weights.get)
    if majority_size != _raw_majority:
        logger.info("EMA smoothed: raw=%s → ema=%s (NHO:%.2f HOA:%.2f LON:%.2f)",
                    _raw_majority, majority_size,
                    _ema_fracs['NHO'], _ema_fracs['HOA'], _ema_fracs['LON'])
    size_weights = _ema_weights  # use EMA weights for all downstream logic

    total_weight = sum(size_weights.values()) or 1.0

    # Anomaly guard: single voter dominates with >60% of weight = confidence scale bug
    # Threshold is 60% (not 40%) because with 3 active voters ~42% per voter is normal.
    for _v in votes:
        _vw = _v['conf'] * _eff_mults.get(_v['name'], 1.0)
        if _vw / total_weight > 0.60:
            logger.warning("WEIGHT_ANOMALY voter='%s' conf=%.4f share=%.0f%% "
                           "(>60%% of total weight — possible conf scale bug)", _v['name'], _v['conf'], _vw / total_weight * 100)

    # P142: HOA precision 18.4% < 25.8% baseline (n=147, 30d) → block entirely.
    # 90d reanalysis (n=226 HOA-intended): precision=24.3% vs fallback WR=36.7% — block confirmed.
    # 16h/17h exceptions NOT warranted: 16h fallback WR=36.8% > HOA precision=31.6%.
    _hoa_suppress = _at.get('hoa_suppress', 0.70)  # kept for logging/vote_breakdown
    if majority_size == 'HOA':
        majority_size = 'LON' if size_weights['LON'] >= size_weights['NHO'] else 'NHO'
        logger.info("HOA blocked P142 (share=%.1f%%) → fallback to %s",
                    size_weights['HOA'] / total_weight * 100, majority_size)

    # P45: NHO share min is adaptive (default 0.45, lower when NHO outpaces LON recently).
    elif majority_size == 'NHO':
        _nho_share_min = _at.get('nho_share_min', 0.45)
        nho_share = size_weights['NHO'] / total_weight
        if size_weights['LON'] > 0 and nho_share < _nho_share_min:
            majority_size = 'LON'
            logger.debug("LON preference: NHO_share=%.0f%% < %.0f%% → LON",
                         nho_share * 100, _nho_share_min * 100)

    majority_count = size_tally[majority_size]
    majority_votes = [v for v in votes if v['size'] == majority_size]

    # Combo được nhiều model đồng ý nhất trong majority SIZE
    combo_tally = Counter(tuple(sorted(v['nums'])) for v in majority_votes)
    _top = combo_tally.most_common(1)
    best_combo, best_count = _top[0] if _top else (None, 0)

    combo_freq, num_freq, sum_freq = _build_recent_freq(df, window=15)
    with _pred_diversity_lock:
        # dict copy — list(Counter) chỉ lấy keys, làm _cold_score crash (.get trên list)
        _pnf = dict(_recent_pred_nums) if _recent_pred_nums else None
    _mfreq = _build_multi_window_combo_freq(df, windows=(60, 100))  # B: multi-window cold

    # Mode sum within each SIZE (highest base probability by combinatorics)
    if best_count >= 2:
        numbers = list(best_combo)
    else:
        # No exact-combo consensus → pick coldest combo across ALL combos in majority SIZE
        all_size_combos = [c for c in ComboColdModel.ALL_COMBOS
                           if SizePredictor._cat(sum(c)) == majority_size and c not in banned]
        if all_size_combos:
            numbers = list(min(all_size_combos,
                               key=lambda c: _cold_score(c, combo_freq, num_freq, sum_freq, _pnf, _mfreq)))
        else:
            best_vote = max(majority_votes, key=lambda v: v['conf'])
            numbers = best_vote['nums']

    # Kiểm tra ban-list; nếu bị ban → coldest combo trong majority SIZE
    current_combo = tuple(sorted(numbers))
    if current_combo in banned:
        target = [c for c in ComboColdModel.ALL_COMBOS
                  if SizePredictor._cat(sum(c)) == majority_size and c not in banned]
        if target:
            numbers = list(min(target,
                               key=lambda c: _cold_score(c, combo_freq, num_freq, sum_freq, _pnf, _mfreq)))

    vote_share = size_weights[majority_size] / total_weight  # 0-1: consensus strength

    # Build per-voter detail for dashboard display (P46/P47)
    _detail = {}
    for v in votes:
        _eff = v['conf'] * _eff_mults.get(v['name'], 1.0)
        _dk  = _decay.get(v['name'], {})
        _detail[v['name']] = {
            'size':       v['size'],
            'conf':       round(v['conf'], 3),
            'mult':       round(_eff_mults.get(v['name'], 1.0), 3),
            'eff_w_pct':  round(_eff / total_weight * 100, 1),
            'winner':     v['size'] == majority_size,
            'streak':     _dk.get('streak', 0),
            'decay':      round(_dk.get('decay', 1.0), 2),
        }

    vote_summary = {
        'total_models':    len(votes),
        'size_tally':      dict(size_tally),
        'size_weights':    {k: round(v, 3) for k, v in size_weights.items()},
        'size_weights_raw':{k: round(_raw_fracs[k], 3) for k in ('NHO','HOA','LON')},
        'size_weights_ema':{k: round(_ema_fracs[k], 3) for k in ('NHO','HOA','LON')},
        'ema_flipped':     majority_size != _raw_majority,
        'majority_size':   majority_size,
        'majority_count':  majority_count,
        'vote_share':      round(vote_share, 3),
        'voters':          [v['name'] for v in majority_votes],
        'all_votes':       {v['name']: v['size'] for v in votes},
        'all_votes_detail':  _detail,
        'adaptive':          {k: round(v, 3) for k, v in (_at or {}).items()},
        'bocpd_dist':        _bocpd_dist,
    }
    logger.info("MajorityVote: %d/%d → SIZE=%s share=%.0f%% tally=%s weights={NHO:%.3f HOA:%.3f LON:%.3f} → %s",
                majority_count, len(votes), majority_size, vote_share * 100, dict(size_tally),
                size_weights['NHO'], size_weights['HOA'], size_weights['LON'], sorted(numbers))
    return numbers, vote_share, vote_summary


# ── P85: Auto-explain helper ─────────────────────────────────
def _send_explain_breakdown(db, telegram, draw_number: int):
    """Fetch prediction vote_breakdown for draw_number and send to Telegram."""
    import json as _json, ast as _ast
    try:
        conn = db.get_connection()
        cur  = conn.cursor()
        ph = '%s' if USE_POSTGRES else '?'
        cur.execute(f"""
            SELECT p.draw_number, p.predicted_numbers, p.confidence,
                   p.vote_breakdown, pr.is_win, pr.actual_numbers
            FROM predictions p
            LEFT JOIN prediction_results pr ON pr.prediction_id = p.id
            WHERE p.draw_number = {ph}
            LIMIT 1
        """, (draw_number,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return
        dn, pred_nums, conf, vb_raw, is_win, actual = row
        try:
            vb = _json.loads(vb_raw) if isinstance(vb_raw, str) else (vb_raw or {})
        except Exception:
            vb = {}
        if isinstance(pred_nums, str):
            pred_nums = _ast.literal_eval(pred_nums)

        pred_sum   = sum(pred_nums)
        majority   = vb.get('majority_size') or ('NHO' if pred_sum <= 9 else ('HOA' if pred_sum <= 11 else 'LON'))
        SIZE_EMJ   = {'NHO': '🔵', 'HOA': '🟡', 'LON': '🔴'}
        SIZE_VI    = {'NHO': 'NHỎ 🔵', 'HOA': 'HÒA 🟡', 'LON': 'LỚN 🔴'}
        conf_str   = f"{conf:.1%}" if conf else "N/A"
        vote_share = vb.get('vote_share', 0)
        size_w     = vb.get('size_weights', {})
        sw_total   = sum(size_w.values()) or 1
        detail     = vb.get('all_votes_detail', {})

        voter_lines = []
        for vname in ['prior_nho', 'prior_lon', 'sum_transition', 'regime_bocpd']:
            d = detail.get(vname)
            if d is None:
                continue
            sz      = d.get('size', '?')
            c       = d.get('conf', 0)
            mult    = d.get('mult', 1.0)
            eff_pct = d.get('eff_w_pct', 0)
            decay   = d.get('decay', 1.0)
            sk      = d.get('streak', 0)
            won     = d.get('winner', False)
            decay_str  = f" decay {decay:.2f}×" if decay < 1.0 else ""
            streak_str = f" {sk}L" if sk > 0 else ""
            voter_lines.append(
                f"{'✅' if won else '❌'} <b>{vname}</b>: {SIZE_EMJ.get(sz,'⚪')}{sz} "
                f"conf {c:.0%}  ×{mult:.2f}{decay_str}{streak_str}  → {eff_pct:.1f}%"
            )

        sw_parts = [
            f"{SIZE_EMJ.get(sz,'')}{sz} {round(size_w.get(sz,0)/sw_total*100)}%"
            for sz in ['NHO', 'HOA', 'LON']
        ]

        adaptive  = vb.get('adaptive', {})
        adapt_parts = []
        for k in ('tune_k', 'nho_share_min', 'hoa_suppress', 'consecutive_excess'):
            if k in adaptive:
                v = adaptive[k]
                adapt_parts.append(f"{k}={int(v)}" if k == 'consecutive_excess' else f"{k}={v:.2f}")

        msg_parts = [
            f"🔍 <b>AUTO-EXPLAIN KỲ #{dn}</b> (thua liên tiếp)",
            "━━━━━━━━━━━━━━━━━━",
            f"{SIZE_EMJ.get(majority,'⚪')} Dự đoán: <b>{SIZE_VI.get(majority, majority)}</b>  "
            f"conf <b>{conf_str}</b>  consensus <b>{vote_share:.0%}</b>",
            f"📊 Weights: {' · '.join(sw_parts)}",
            "",
            "🗳 Voters:",
        ] + [f"  {l}" for l in voter_lines]

        if adapt_parts:
            msg_parts.append(f"\n⚙️ Adaptive: {' · '.join(adapt_parts)}")

        telegram.send_message("\n".join(msg_parts))
    except Exception as ex:
        logger.debug("Auto-explain error: %s", ex)


# ── Main: 1 chu kỳ dự đoán ───────────────────────────────────
def run_prediction_cycle() -> dict:
    import time as _time
    db       = DatabaseManager()
    telegram = TelegramBot()

    # ── P94: Prediction gap alert — check at cycle start ─────
    try:
        vn_hour = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).hour
        if 6 <= vn_hour < 22:  # active hours only
            if _alert_mgr.fire('gap', _GAP_COOLDOWN_SEC):
                conn_g = db.get_connection()
                try:
                    cur_g  = conn_g.cursor()
                    if config.DATABASE_URL:
                        cur_g.execute("""
                            SELECT draw_time FROM draw_history
                            ORDER BY draw_number DESC LIMIT 1
                        """)
                        row_g = cur_g.fetchone()
                        if row_g and row_g[0]:
                            last_draw_time = row_g[0]
                            if hasattr(last_draw_time, 'tzinfo') and last_draw_time.tzinfo is None:
                                last_draw_time = last_draw_time.replace(tzinfo=timezone.utc)
                            age_min = (datetime.now(timezone.utc) - last_draw_time.astimezone(timezone.utc)).total_seconds() / 60
                            if age_min > _GAP_THRESHOLD_MIN:
                                telegram.send_message(
                                    f"⏰ <b>PREDICTION GAP ALERT · P94</b>\n"
                                    f"━━━━━━━━━━━━━━━━\n"
                                    f"Kỳ cuối cách đây <b>{age_min:.0f} phút</b> (ngưỡng {_GAP_THRESHOLD_MIN}p)\n"
                                    f"Giờ VN: {vn_hour}h — đang trong active hours\n"
                                    f"━━━━━━━━━━━━━━━━\n"
                                    f"⚠️ Sync có thể bị lỗi. Kiểm tra sync_to_supabase.py.\n"
                                    f"🔕 Alert tắt 30 phút."
                                )
                                _alert_mgr.log(db, 'gap', f"gap={age_min:.0f}min", {'gap_min': round(age_min, 1), 'vn_hour': vn_hour})
                                logger.warning("P94 gap alert: last draw %.0f min ago", age_min)
                            else:
                                _alert_mgr.reset('gap')  # didn't actually fire — allow retry sooner
                finally:
                    conn_g.close()
    except Exception as _ge:
        logger.debug("P94 gap alert error: %s", _ge)

    # ── Bước 1: Auto-process các kết quả còn pending ─────────
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        ph  = db._ph()
        cur.execute(f"""
            SELECT p.id, p.draw_number, p.predicted_numbers, p.model_name
            FROM predictions p
            WHERE NOT EXISTS (
                SELECT 1 FROM prediction_results pr
                WHERE pr.prediction_id = p.id
            )
            AND EXISTS (
                SELECT 1 FROM draw_history dh
                WHERE dh.draw_number = p.draw_number
            )
            ORDER BY p.draw_number ASC
            LIMIT 20
        """)
        pending = cur.fetchall()
    finally:
        conn.close()

    processed_results = []
    _last_result_info: dict = {}  # kết quả kỳ gần nhất — ghép vào tin dự đoán
    for pred_id, draw_number, pred_json, model_name in pending:
        try:
            conn2 = db.get_connection()
            try:
                cur2 = conn2.cursor()
                cur2.execute(f"SELECT numbers FROM draw_history WHERE draw_number={ph}", (draw_number,))
                row = cur2.fetchone()
            finally:
                conn2.close()

            if not row:
                continue

            actual_numbers = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            predicted      = json.loads(pred_json)

            db.update_prediction_result(pred_id, draw_number, actual_numbers)
            db.update_cold_numbers(draw_number, actual_numbers)
            _update_markov_online(db, draw_number, actual_numbers)

            match_count = len(set(predicted) & set(actual_numbers))
            is_win     = (db.get_size_category(predicted) == db.get_size_category(actual_numbers)) if len(predicted) == 3 and len(actual_numbers) == 3 else False
            is_win_sum = (sum(int(x) for x in predicted) == sum(int(x) for x in actual_numbers)) if len(predicted) == 3 and len(actual_numbers) == 3 else False

            # Fetch last 7 resolved results for W/L trail (exclude current draw)
            recent_wl: list = []
            try:
                conn_wl = db.get_connection()
                try:
                    cur_wl  = conn_wl.cursor()
                    ph_wl   = db._ph()
                    cur_wl.execute(
                        f"SELECT is_win FROM prediction_results WHERE draw_number < {ph_wl} "
                        f"ORDER BY draw_number DESC LIMIT 7",
                        (draw_number,)
                    )
                    recent_wl = [bool(r[0]) for r in reversed(cur_wl.fetchall())]
                finally:
                    conn_wl.close()
            except Exception:
                pass

            _is_last_pending = (pred_id == pending[-1][0])
            if _is_last_pending:
                # Gộp vào tin dự đoán — không gửi riêng để tránh 2 tin/cycle
                _last_result_info = {
                    'draw_number':    draw_number,
                    'actual_numbers': actual_numbers,
                    'predicted':      predicted,
                    'match_count':    match_count,
                    'is_win':         is_win,
                    'is_win_sum':     is_win_sum,
                    'recent_wl':      recent_wl,
                    'model_name':     model_name,
                }
            else:
                telegram.send_result(draw_number, actual_numbers, predicted,
                                     model_name, match_count, is_win, is_win_sum, recent_wl)

            processed_results.append({
                "draw_number": draw_number,
                "match":       match_count,
                "win":         is_win
            })
            logger.info("Auto-processed draw #%d: match=%d win=%s", draw_number, match_count, is_win)

            # P59: streak alerts — fire at 5, 10, 15... consecutive wins or losses
            try:
                trail = recent_wl + [is_win]   # oldest→newest, current is last
                streak = 1
                for r in reversed(trail[:-1]):
                    if r == is_win:
                        streak += 1
                    else:
                        break
                if streak >= 5 and streak % 5 == 0:
                    if is_win:
                        telegram.send_message(
                            f"🔥 <b>STREAK THẮNG {streak} KỸ!</b>\n"
                            f"━━━━━━━━━━━━━━━━\n"
                            f"🎯 {streak} kỳ thắng liên tiếp đến kỳ #{draw_number}\n"
                            f"💡 Duy trì cặp lời — ngưỡng cao!"
                        )
                    else:
                        telegram.send_message(
                            f"❄️ <b>STREAK THUA {streak} KỸ!</b>\n"
                            f"━━━━━━━━━━━━━━━━\n"
                            f"⚠️ {streak} kỳ thua liên tiếp đến kỳ #{draw_number}\n"
                            f"💡 Hãy giảm cặp hoặc dừng lại để bảo toàn vốn"
                        )
            except Exception as _se:
                logger.debug("Streak alert error: %s", _se)

        except Exception as e:
            logger.warning("Auto-process error draw #%d: %s", draw_number, e)

    if processed_results:
        db.refresh_model_stats(ALL_MODEL_NAMES)
        invalidate_calibrator()  # new results → recalibrate next cycle
        try:
            hybrid, _, __, ensemble, _sz = _get_models(db)
            hybrid.update_weights(db)
            ensemble.update_weights_from_db(db)
        except Exception:
            pass

        # Streak + win rate alerts
        try:
            conn_s = db.get_connection()
            try:
                cur_s  = conn_s.cursor()
                cur_s.execute(
                    "SELECT COALESCE(is_win_size, is_win, FALSE) FROM prediction_results "
                    "ORDER BY draw_number DESC LIMIT 50"
                )
                streak_seq = [r[0] for r in cur_s.fetchall()]
            finally:
                conn_s.close()

            win_streak = loss_streak = 0
            for w in streak_seq:
                if w:
                    if loss_streak > 0:
                        break
                    win_streak += 1
                else:
                    if win_streak > 0:
                        break
                    loss_streak += 1

            # Win milestone
            if win_streak in (5, 10, 20, 30, 50):
                telegram.send_message(
                    f"🏆 <b>WIN STREAK {win_streak} KỲ!</b>\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"Đang đoán đúng SIZE <b>{win_streak} kỳ liên tiếp</b> 🎯"
                )
                logger.info("Win streak milestone: %d", win_streak)

            # Loss streak alert (5, 8, 10)
            if loss_streak in (5, 8, 10):
                wr20 = sum(1 for w in streak_seq[:20] if w) / min(20, len(streak_seq))
                telegram.send_message(
                    f"❄️ <b>CẢNH BÁO: THUA {loss_streak} KỲ LIÊN TIẾP</b>\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"Win rate 20 kỳ gần nhất: <b>{wr20*100:.0f}%</b>\n"
                    f"Hệ thống đang trong chuỗi thua. Theo dõi thêm."
                )
                logger.warning("Loss streak alert: %d in a row", loss_streak)
                # P85: auto-explain at first trigger (loss_streak == 5) to debug
                if loss_streak == 5:
                    latest_dn = max(r['draw_number'] for r in processed_results)
                    _send_explain_breakdown(db, telegram, latest_dn)

            # Low win rate alert (last 20 < 20%)
            if len(streak_seq) >= 20:
                wr20 = sum(1 for w in streak_seq[:20] if w) / 20
                if wr20 < 0.20 and loss_streak >= 3:
                    telegram.send_message(
                        f"🚨 <b>WIN RATE THẤP BẤT THƯỜNG</b>\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"20 kỳ gần nhất: <b>{wr20*100:.0f}%</b> (baseline 37.5%)\n"
                        f"Đang thua {loss_streak} kỳ liên tiếp."
                    )
                    logger.warning("Low WR alert: %.0f%% last 20", wr20 * 100)

            # P91: WR drop alert — rolling 50-draw WR < 30%, cooldown 2h
            if len(streak_seq) >= 20:
                wr50 = sum(1 for w in streak_seq if w) / len(streak_seq)
                if wr50 < _WR_DROP_THRESHOLD and _alert_mgr.fire('wr_drop', _WR_DROP_COOLDOWN_SEC):
                    deficit = round((_WR_DROP_THRESHOLD - wr50) * 100, 1)
                    wr20_str = f"{sum(1 for w in streak_seq[:20] if w) / 20 * 100:.0f}%"
                    telegram.send_message(
                        f"📉 <b>WR DROP ALERT · P91</b>\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"Rolling {len(streak_seq)} kỳ: <b>{wr50*100:.1f}%</b> "
                        f"(ngưỡng {_WR_DROP_THRESHOLD*100:.0f}%  −{deficit}%)\n"
                        f"WR 20 kỳ gần nhất: <b>{wr20_str}</b>\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"⚠️ Hệ thống underperform nghiêm trọng. Dùng /health và /explain để debug.\n"
                        f"🔕 Alert tắt 2h."
                    )
                    _alert_mgr.log(db, 'wr_drop', f"WR50={wr50:.1%}", {'wr50': round(wr50, 4), 'n': len(streak_seq)})
                    logger.warning("P91 WR drop alert: %.1f%% over last %d draws",
                                   wr50 * 100, len(streak_seq))
        except Exception as e:
            logger.debug("Streak alert error: %s", e)

        # Trigger retrain khi có đủ results mới — không chờ milestone draw_number
        if len(processed_results) >= 5:
            logger.info("Batch %d results → trigger background retrain", len(processed_results))
            threading.Thread(target=_background_retrain, daemon=True).start()

    # ── Bước 2: Xác định kỳ tiếp theo để dự đoán ─────────────
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(draw_number) FROM draw_history")
        last = cur.fetchone()[0] or 0
        cur.execute("SELECT MAX(draw_number) FROM predictions")
        last_pred = cur.fetchone()[0] or 0
    finally:
        conn.close()

    # Predict cho last+2: buffer 1 kỳ bù sync lag ~6 phút
    # Nếu đã predict >= last+2 → đủ rồi, skip
    next_draw = last + 2

    if last_pred >= next_draw:
        logger.info("Draw #%d already predicted ahead – skip", next_draw)
        return {"skipped": True, "draw_number": next_draw, "processed": processed_results}

    _ensure_transition_cache(db, last)
    _refresh_static_stats(db, last)  # auto-refresh TOD/Markov2/Carryover tables từ DB

    df = db.get_recent_draws(300)
    if len(df) < 20:
        logger.warning("Not enough history for prediction")
        return {"error": "not_enough_data"}

    # ── Hot-adjust: get current loss streak for adaptive correction ────────
    _current_loss_streak = 0
    try:
        conn_ls = db.get_connection()
        try:
            cur_ls  = conn_ls.cursor()
            cur_ls.execute(
                "SELECT COALESCE(is_win_size, FALSE) FROM prediction_results "
                "ORDER BY draw_number DESC LIMIT 20"
            )
            _ls_rows = [r[0] for r in cur_ls.fetchall()]
        finally:
            conn_ls.close()
        for _w in _ls_rows:
            if not _w:
                _current_loss_streak += 1
            else:
                break
    except Exception:
        pass

    hybrid, selector, fwbr, ensemble, size_pred = _get_models(db)

    mode, active_name = _get_active_model_from_config(db)
    logger.info("system_config: mode=%s active=%s", mode, active_name)

    banned = _get_banned_combos(db)
    skip_size_adjust = False
    prev_sum = None  # computed below; initialized here for _tg_signal scope safety
    _vote_info = None  # set only in majority_vote mode; stored in predictions.vote_breakdown
    adaptive_thres = {}  # P70: default; populated in majority_vote path
    try:
        if 'sum_value' in df.columns and len(df) > 0:
            prev_sum = int(df.iloc[0]['sum_value'])
    except Exception:
        pass

    if mode == 'forced':
        best_name  = active_name
        best_model = selector.get_model(best_name)
        if best_model is None:
            best_name  = 'cold_number_window_30'
            best_model = selector.get_model(best_name) or hybrid.cold_model
            logger.warning("Fallback to cold_number_window_30")
        try:
            if hasattr(best_model, "markov_model") or best_name in ["ml_ensemble", "hybrid_model", "lstm"]:
                preds = best_model.predict(df, next_draw)
            else:
                recent_draws = [row["numbers"] for _, row in df.head(50).iterrows()]
                preds = best_model.predict(recent_draws, next_draw)
        except Exception as e:
            logger.error("Predict error: %s", e)
            traceback.print_exc()
            return {"error": str(e)}
        if not preds:
            return {"error": "no_prediction"}
        numbers, confidence = preds[0]
        filtered = _apply_filter(numbers, confidence, df)
        if filtered:
            numbers, confidence = filtered
        current_combo = tuple(sorted(int(x) for x in numbers))
        if current_combo in banned:
            recent_draws_raw = [row["numbers"] for _, row in df.head(60).iterrows()]
            numbers = get_diverse_prediction(recent_draws_raw, banned, window=30)
            logger.warning("Ban-list hit %s → diversified to %s", current_combo, numbers)

    elif mode == 'ensemble':
        best_name  = 'voting_ensemble'
        try:
            preds = ensemble.predict(df, next_draw)
        except Exception as e:
            logger.error("Ensemble predict error: %s", e)
            traceback.print_exc()
            return {"error": str(e)}
        if not preds:
            return {"error": "no_prediction"}
        numbers, confidence = preds[0]
        current_combo = tuple(sorted(int(x) for x in numbers))
        if current_combo in banned:
            recent_draws_raw = [row["numbers"] for _, row in df.head(60).iterrows()]
            numbers = get_diverse_prediction(recent_draws_raw, banned, window=30)
            logger.warning("Ban-list hit %s → diversified to %s", current_combo, numbers)

    else:  # auto → majority vote
        voter_mults     = _get_voter_multipliers(db, next_draw)
        adaptive_thres  = _get_adaptive_thresholds(db, next_draw)
        _conformal_q    = get_conformal_quantile(db, next_draw)
        _load_sw_ema(db)  # restore EMA state on cold start so instances share history
        # P-FIX2: loss streak boost — tăng LON anchor, giảm NHO khi thua >= 7 liên tiếp
        if _current_loss_streak >= 7:
            _boost = min(1.5, 1.0 + (_current_loss_streak - 6) * 0.08)
            adaptive_thres = dict(adaptive_thres)  # copy, không mutate cache
            adaptive_thres['prior_lon_conf'] = round(min(0.70, adaptive_thres.get('prior_lon_conf', 0.40) * _boost), 3)
            adaptive_thres['prior_nho_conf'] = round(max(0.20, adaptive_thres.get('prior_nho_conf', 0.40) / _boost), 3)
            adaptive_thres['streak_boost']   = _current_loss_streak
            logger.info("StreakBoost: streak=%d factor=%.2f → prior_lon=%.3f prior_nho=%.3f",
                        _current_loss_streak, _boost,
                        adaptive_thres['prior_lon_conf'], adaptive_thres['prior_nho_conf'])
        numbers, confidence, _vote_info = _run_majority_vote(
            df, next_draw, hybrid, selector, fwbr, ensemble, banned, prev_sum,
            voter_multipliers=voter_mults,
            adaptive_thresholds=adaptive_thres)
        _save_sw_ema(db)  # persist updated EMA so next cold-start picks up current state
        # Conformal prediction set (informational — P142 still blocks HOA from being chosen)
        if _vote_info and _conformal_q is not None:
            _ema_fracs = _vote_info.get('size_weights_ema', {})
            _pred_set = get_prediction_set(_ema_fracs, _conformal_q)
            _vote_info['conformal_q'] = round(_conformal_q, 4)
            _vote_info['prediction_set'] = _pred_set
            _vote_info['conformal_uncertain'] = len(_pred_set) >= 2
            logger.debug("ConformalSet: q=%.3f thresh=%.3f → %s", _conformal_q, 1 - _conformal_q, _pred_set)
        best_name = 'majority_vote'
        skip_size_adjust = False  # allow SizePredictor to correct SIZE bias
        if numbers is None:
            logger.warning("MajorityVote: tất cả models lỗi → fallback hybrid")
            preds = hybrid.predict(df, next_draw)
            if not preds:
                return {"error": "no_prediction"}
            numbers, confidence = preds[0]
            best_name = 'hybrid_model'
            skip_size_adjust = False

    # Size predictor chạy cho tất cả modes khi skip_size_adjust=False
    if not skip_size_adjust:
        numbers = _apply_size_prediction(numbers, df, size_pred, banned, prev_sum,
                                         loss_streak=_current_loss_streak)

    # Hot-Adjust: khi loss streak >= 3, điều chỉnh SIZE theo hot numbers
    numbers, _hot_adjust_note = _hot_adjust_size(numbers, df, _current_loss_streak, banned)

    # P148: log final SIZE after SizePredictor for post-checkpoint flip analysis
    if _vote_info is not None:
        _final_size = SizePredictor._cat(sum(numbers))
        _vote_info['final_size'] = _final_size
        _majority = _vote_info.get('majority_size')
        if _majority and _final_size != _majority:
            _vote_info['size_flipped'] = f"{_majority}→{_final_size}"

    # Calibrate confidence: replace raw model score with honest historical win rate,
    # bucketed by vote_share (consensus strength) since model_name alone is nearly
    # always 'majority_vote' and carries no per-prediction signal.
    calibrator = get_calibrator(db)
    _vote_share_for_cal = (_vote_info or {}).get('vote_share', 0.5)
    win_prob, cal_meta = calibrator.calibrate_by_vote_share(_vote_share_for_cal, best_name, confidence)
    is_confident = cal_meta.get('is_confident', False)

    # Build transition signal line for Telegram ("SIZE P% từ tổng X → tổng Y P%")
    _tg_signal = ""
    try:
        _tc = _transition_cache
        if _tc and prev_sum is not None:
            t_probs = _tc['probs'].get(prev_sum) or {}
            pred_size_final = SizePredictor._cat(sum(numbers))
            size_pct = t_probs.get(pred_size_final, 0)
            top_sums = _tc.get('top_sums', {}).get(prev_sum, [])
            next_sum_val = sum(numbers)
            # Find the pct for the predicted sum
            sum_pct = next((pct for ns, pct in top_sums if ns == next_sum_val), None)
            size_label = {'NHO': 'NHỎ', 'HOA': 'HÒA', 'LON': 'LỚN'}.get(pred_size_final, pred_size_final)
            if sum_pct is not None:
                _tg_signal = (f"Tổng trước: {prev_sum} → {size_label} {size_pct:.0%} "
                              f"| Tổng {next_sum_val}: {sum_pct:.1%}")
            elif size_pct:
                _tg_signal = f"Tổng trước: {prev_sum} → {size_label} {size_pct:.0%}"
    except Exception:
        pass

    # Pass weighted vote share (%) rather than raw count — weights determine the winner
    _sw = (_vote_info or {}).get('size_weights', {})
    _sw_total = sum(_sw.values()) or 1
    _tg_vote_tally = {k: round(v / _sw_total * 100) for k, v in _sw.items()} if _sw else (_vote_info or {}).get('size_tally')
    pred_id, _is_new_pred = db.insert_prediction(next_draw, best_name, numbers, confidence, _vote_info)
    _update_pred_diversity(numbers)  # B: cập nhật diversity tracker

    if not _is_new_pred:
        logger.info("Draw #%d prediction already sent — skip Telegram (duplicate cycle)", next_draw)
        return {"skipped": True, "draw_number": next_draw, "reason": "duplicate_prediction",
                "processed": processed_results}

    # Build reason_info: absence per number + combo rank within SIZE
    _reason_info: dict = {'loss_streak': _current_loss_streak,
                          'hot_adjust': _hot_adjust_note}
    try:
        from models import _parse_numbers as _pn_ri
        _abs_map: dict = {}
        for _ri, _row in enumerate(df.itertuples()):
            _ns = [int(x) for x in _pn_ri(_row.numbers)]
            for _n in _ns:
                if _n not in _abs_map:
                    _abs_map[_n] = _ri   # 0 = most recent draw
        for _n in range(1, 7):
            if _n not in _abs_map:
                _abs_map[_n] = len(df)
        _reason_info['absence'] = {n: _abs_map.get(n, 0) for n in numbers}

        _final_sz = SizePredictor._cat(sum(numbers))
        _cfr2, _nfr2, _sfr2 = _build_recent_freq(df, window=30)
        _pnf2 = _recent_pred_nums if _recent_pred_nums else None
        _same_sz = [c for c in ComboColdModel.ALL_COMBOS
                    if SizePredictor._cat(sum(c)) == _final_sz]
        _ranked2 = sorted(_same_sz, key=lambda c: _cold_score(c, _cfr2, _nfr2, _sfr2, _pnf2))
        _pred_combo_ri = tuple(sorted(int(x) for x in numbers))
        _reason_info['combo_rank']  = next((i + 1 for i, c in enumerate(_ranked2) if c == _pred_combo_ri), None)
        _reason_info['combo_total'] = len(_same_sz)
    except Exception as _rie:
        logger.debug("reason_info build error: %s", _rie)

    # BOCPD regime change alert — only fires when dominant category deviates
    # significantly from base rate (NHO/LON > 55%, HOA > 45%) and the regime
    # has changed since the last alert, to avoid spam on stable runs.
    try:
        global _last_bocpd_regime
        _bd = (_vote_info or {}).get('bocpd_dist') or {}
        if _bd:
            _BASE = {'NHO': 0.375, 'HOA': 0.25, 'LON': 0.375}
            _THRESH = {'NHO': 0.55, 'HOA': 0.45, 'LON': 0.55}
            _SLV = {'NHO': 'NHỎ', 'HOA': 'HÒA', 'LON': 'LỚN'}
            _dom = max(_bd, key=_bd.get)
            if _bd[_dom] >= _THRESH[_dom] and _dom != _last_bocpd_regime:
                _delta = _bd[_dom] - _BASE[_dom]
                _msg = (
                    f"📡 <b>BOCPD Regime Shift</b>\n"
                    f"Chuỗi SIZE đang lệch mạnh về <b>{_SLV[_dom]}</b> "
                    f"({_bd[_dom]*100:.0f}% vs baseline {_BASE[_dom]*100:.0f}%, "
                    f"Δ+{_delta*100:.0f}pp)\n"
                    f"NHỎ {_bd.get('NHO',0)*100:.0f}% · "
                    f"HÒA {_bd.get('HOA',0)*100:.0f}% · "
                    f"LỚN {_bd.get('LON',0)*100:.0f}%\n"
                    f"<i>Kỳ #{next_draw} · BOCPD hazard=1/120</i>"
                )
                telegram.send_message(_msg)
                _alert_mgr.log(db, 'bocpd_regime',
                               f"Chuỗi SIZE lệch mạnh về {_SLV[_dom]}: {_bd[_dom]*100:.0f}% "
                               f"vs baseline {_BASE[_dom]*100:.0f}% (Δ+{_delta*100:.0f}pp)",
                               {'regime': _dom, 'prob': round(_bd[_dom], 4), 'draw': next_draw})
                _last_bocpd_regime = _dom
                logger.info("BOCPD regime alert sent: %s %.0f%%", _dom, _bd[_dom] * 100)
            elif _bd.get(_last_bocpd_regime, 0) < _THRESH.get(_last_bocpd_regime, 1):
                _last_bocpd_regime = ''  # reset when regime normalises
    except Exception as _bae:
        logger.debug("bocpd alert error: %s", _bae)

    # Triple alerts — cluster window after a fresh triple + drought watch
    try:
        global _last_triple_alert_draw, _last_triple_cluster_draw
        _drought, _last_triple = _query_triple_drought(db)
        if _drought is not None:
            if (_drought == 0
                    and next_draw - _last_triple_cluster_draw >= _TRIPLE_CLUSTER_WINDOW):
                # Latest result IS a triple → open the 10-draw cluster window
                _msg = (
                    f"🔥 <b>TRIPLE CLUSTER · vừa ra triple kỳ #{_last_triple}</b>\n"
                    f"Triple có xu hướng ra theo cụm: 26% cụm lịch sử có "
                    f"triple tiếp trong ≤10 kỳ (vs ~20% nếu ngẫu nhiên, +33%)\n"
                    f"➡️ Cửa sổ theo dõi: kỳ #{_last_triple + 1}–#{_last_triple + _TRIPLE_CLUSTER_WINDOW}\n"
                    f"📌 Chú ý khả năng có triple nữa trong 10 kỳ tới!"
                )
                telegram.send_message(_msg)
                _alert_mgr.log(db, 'triple_cluster',
                               f"Vừa ra triple kỳ #{_last_triple} — cửa sổ cụm 10 kỳ "
                               f"(#{_last_triple + 1}–#{_last_triple + _TRIPLE_CLUSTER_WINDOW}), "
                               f"26% cụm lịch sử có triple tiếp trong ≤10 kỳ",
                               {'triple_draw': _last_triple, 'window': _TRIPLE_CLUSTER_WINDOW})
                _last_triple_cluster_draw = next_draw
                logger.info("Triple cluster alert: triple at #%d, window %d draws",
                            _last_triple, _TRIPLE_CLUSTER_WINDOW)
            elif (_drought >= _TRIPLE_DROUGHT_THRESH
                    and next_draw - _last_triple_alert_draw >= _TRIPLE_ALERT_COOLDOWN):
                _p_next5  = round((1 - (1 - 6/216) ** 5) * 100, 1)
                _p_next10 = round((1 - (1 - 6/216) ** 10) * 100, 1)
                _msg = (
                    f"⚡ <b>WATCH TRIPLE · {_drought} kỳ chưa có</b>\n"
                    f"Kỳ gần nhất: #{_last_triple} · Trung bình 36 kỳ/1 lần\n"
                    f"➡️ P(triple trong 5 kỳ tới): <b>{_p_next5}%</b>\n"
                    f"➡️ P(triple trong 10 kỳ tới): <b>{_p_next10}%</b>\n"
                    f"📌 Triple có khả năng xuất hiện sớm — chú ý theo dõi!"
                )
                telegram.send_message(_msg)
                _alert_mgr.log(db, 'triple_drought',
                               f"{_drought} kỳ chưa có triple (trung bình 36 kỳ/lần) — "
                               f"kỳ triple gần nhất #{_last_triple}",
                               {'drought': _drought, 'last_triple': _last_triple})
                _last_triple_alert_draw = next_draw
                logger.info("Triple drought alert: %d draws since #%d", _drought, _last_triple)
    except Exception as _tae:
        logger.debug("triple alert error: %s", _tae)

    # Pair drought alert — fires when no pair for ≥ _PAIR_DROUGHT_THRESH draws
    try:
        global _last_pair_alert_draw
        if next_draw - _last_pair_alert_draw >= _PAIR_ALERT_COOLDOWN:
            _pd, _lp_draw, _cold_dbls = _query_pair_drought(db)
            if _pd is not None and _pd >= _PAIR_DROUGHT_THRESH:
                _pp5  = round((1 - (1 - 30/216) ** 5)  * 100, 1)
                _pp10 = round((1 - (1 - 30/216) ** 10) * 100, 1)
                _cold_lines = '\n'.join(
                    f"  • Đôi <b>{d}</b> ({d},{d},?): <b>{dr} kỳ</b> chưa ra"
                    for d, dr in _cold_dbls[:3]
                )
                _pmsg = (
                    f"🎯 <b>WATCH CẶP ĐÔI · {_pd} kỳ chưa có</b>\n"
                    f"Kỳ gần nhất: #{_lp_draw} · TB ~9 kỳ/lần\n"
                    f"➡️ P(cặp đôi trong 5 kỳ tới): <b>{_pp5}%</b>\n"
                    f"➡️ P(cặp đôi trong 10 kỳ tới): <b>{_pp10}%</b>\n"
                )
                if _cold_lines:
                    _pmsg += f"🧊 Đôi lạnh nhất:\n{_cold_lines}\n"
                _pmsg += f"📌 Cặp đôi sắp xuất hiện — chú ý theo dõi!"
                telegram.send_message(_pmsg)
                _alert_mgr.log(db, 'pair_drought',
                               f"{_pd} kỳ chưa có cặp đôi (trung bình ~9 kỳ/lần) — "
                               f"kỳ gần nhất #{_lp_draw}",
                               {'drought': _pd, 'last_pair': _lp_draw})
                _last_pair_alert_draw = next_draw
                logger.info("Pair drought alert: %d draws since #%d, cold=%s",
                            _pd, _lp_draw, _cold_dbls[:3])
    except Exception as _pae:
        logger.debug("pair alert error: %s", _pae)

    telegram.send_prediction(next_draw, best_name, numbers, win_prob,
                             signal=_tg_signal, vote_tally=_tg_vote_tally,
                             vote_info=_vote_info, reason_info=_reason_info,
                             last_result=_last_result_info or None,
                             is_confident=is_confident)

    logger.info("Predicted draw #%d: %s (model=%s raw_conf=%.1f%% calibrated=%.2f%%)",
                next_draw, sorted(numbers), best_name, confidence * 100, win_prob * 100)

    # P98: Voter confidence drift alert
    try:
        import json as _json
        _conn_d = db.get_connection()
        try:
            _cur_d  = _conn_d.cursor()
            _cur_d.execute(
                "SELECT vote_breakdown FROM predictions "
                "WHERE vote_breakdown IS NOT NULL ORDER BY draw_number DESC LIMIT 50"
            )
            _vb_rows = _cur_d.fetchall()
        finally:
            _conn_d.close()

        from collections import defaultdict as _dd
        _vc: dict = _dd(lambda: [[], []])  # {voter: [[recent_25_confs], [prior_25_confs]]}
        for _idx, (_vb_raw,) in enumerate(_vb_rows):
            try:
                _vb = _json.loads(_vb_raw) if isinstance(_vb_raw, str) else _vb_raw
                _detail = _vb.get('all_votes_detail', {})
                _bucket = 0 if _idx < 25 else 1
                for _vname, _vinfo in _detail.items():
                    _c = _vinfo.get('conf', 0)
                    if _c:
                        _vc[_vname][_bucket].append(float(_c))
            except Exception:
                pass

        for _voter, (_rec, _pri) in _vc.items():
            if len(_rec) < 10 or len(_pri) < 10:
                continue
            _rec_avg = sum(_rec) / len(_rec)
            _pri_avg = sum(_pri) / len(_pri)
            _drop    = _pri_avg - _rec_avg
            if _drop >= _VOTER_DRIFT_THRESHOLD and _alert_mgr.fire(f'voter_drift_{_voter}', _VOTER_DRIFT_COOLDOWN_SEC):
                _badge = '🔴' if _rec_avg < 0.45 else '🟡'
                telegram.send_message(
                    f"📉 <b>VOTER DRIFT · P98</b>\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"{_badge} Voter <b>{_voter}</b> conf giảm mạnh:\n"
                    f"  25 kỳ trước: <b>{_pri_avg*100:.1f}%</b>\n"
                    f"  25 kỳ gần:   <b>{_rec_avg*100:.1f}%</b>\n"
                    f"  Giảm: <b>−{_drop*100:.1f}pp</b>\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"⚠️ Voter đang mất tin tưởng — kiểm tra /health\n"
                    f"🔕 Alert tắt 2h."
                )
                _alert_mgr.log(db, f'voter_drift_{_voter}',
                               f"{_voter} conf {_pri_avg:.1%}→{_rec_avg:.1%} (−{_drop:.1%})",
                               {'voter': _voter, 'prior': round(_pri_avg, 4), 'recent': round(_rec_avg, 4), 'drop': round(_drop, 4)})
                logger.warning("P98 Voter drift: %s conf %.1f%%→%.1f%% (−%.1fpp)",
                               _voter, _pri_avg * 100, _rec_avg * 100, _drop * 100)
    except Exception as _de:
        logger.debug("P98 voter drift check error: %s", _de)

    # P93: Same-SIZE momentum bias alert
    try:
        _check_n = _MOMENTUM_THRESHOLD + 2  # fetch a few extra to be safe
        _conn_m  = db.get_connection()
        try:
            _cur_m   = _conn_m.cursor()
            _ph_m    = '%s' if USE_POSTGRES else '?'
            _cur_m.execute(f"""
                SELECT (SELECT SUM(v::int) FROM json_array_elements_text(predicted_numbers::json) v)
                FROM predictions
                WHERE predicted_numbers IS NOT NULL
                ORDER BY draw_number DESC LIMIT {_ph_m}
            """ if USE_POSTGRES else f"""
                SELECT (SELECT SUM(value) FROM json_each(predicted_numbers))
                FROM predictions WHERE predicted_numbers IS NOT NULL
                ORDER BY draw_number DESC LIMIT {_ph_m}
            """, (_check_n,))
            _sums = [row[0] for row in _cur_m.fetchall() if row[0] is not None]
        finally:
            _conn_m.close()

        def _sz(s): return 'NHO' if s <= 9 else ('HOA' if s <= 11 else 'LON')
        _sizes = [_sz(int(s)) for s in _sums]

        if len(_sizes) >= _MOMENTUM_THRESHOLD:
            _streak_sz  = _sizes[0]
            _streak_len = sum(1 for s in _sizes if s == _streak_sz)
            # Only count leading streak
            _streak_len = 0
            for _s in _sizes:
                if _s == _streak_sz: _streak_len += 1
                else: break

            if _streak_len >= _MOMENTUM_THRESHOLD and _alert_mgr.fire(f'momentum_{_streak_sz}', _MOMENTUM_COOLDOWN_SEC):
                _sz_vi = {'NHO': 'NHỎ 🔵', 'HOA': 'HÒA 🟡', 'LON': 'LỚN 🔴'}
                telegram.send_message(
                    f"🔄 <b>MOMENTUM BIAS · P93</b>\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"Model đang predict <b>{_sz_vi.get(_streak_sz, _streak_sz)}</b> "
                    f"liên tiếp <b>{_streak_len} kỳ</b>!\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"⚠️ Có thể bị bias — kiểm tra /explain và /health.\n"
                    f"🔕 Alert tắt 1h."
                )
                _alert_mgr.log(db, f'momentum_{_streak_sz}',
                               f"{_streak_sz} x{_streak_len} streak",
                               {'size': _streak_sz, 'streak_len': _streak_len})
                logger.warning("P93 Momentum bias: %s repeated %d times", _streak_sz, _streak_len)
    except Exception as _me:
        logger.debug("P93 momentum check error: %s", _me)

    return {
        "draw_number":        next_draw,
        "predicted_numbers":  sorted(numbers),
        "confidence":         win_prob,          # calibrated — honest P(win)
        "raw_confidence":     confidence,         # model's internal score
        "calibration":        cal_meta,
        "is_confident":       is_confident,        # honest-low-confidence signal (not skipped, just flagged)
        "model":              best_name,
        "prediction_id":      int(pred_id),
        "processed":          processed_results,
        "adaptive_thresholds": adaptive_thres,   # P70: expose consecutive_excess for alert
    }

# ── Xử lý kết quả (gọi từ admin submit) ─────────────────────
def process_actual_result(draw_number: int, actual_numbers: List[int]) -> dict:
    db       = DatabaseManager()
    telegram = TelegramBot()

    db.update_cold_numbers(draw_number, actual_numbers)
    _update_markov_online(db, draw_number, actual_numbers)

    conn = db.get_connection()
    try:
        cur = conn.cursor()
        ph = db._ph()
        cur.execute(f"""
            SELECT id, predicted_numbers, model_name, vote_breakdown FROM predictions
            WHERE draw_number={ph} ORDER BY prediction_time DESC LIMIT 1
        """, (draw_number,))
        row = cur.fetchone()
    finally:
        conn.close()

    result_info = {}
    if row:
        pred_id, pred_json, model_name, vb_raw = row
        predicted = json.loads(pred_json)
        db.update_prediction_result(pred_id, draw_number, actual_numbers)

        # Update Hedge voter weights online with this draw's result
        try:
            vb = json.loads(vb_raw) if isinstance(vb_raw, str) else (vb_raw or {})
            update_hedge_from_draw(db, vb, actual_numbers)
        except Exception as _he:
            logger.debug("hedge update error: %s", _he)

        match_count = len(set(predicted) & set(actual_numbers))
        is_win     = (db.get_size_category(predicted) == db.get_size_category(actual_numbers)) if len(predicted) == 3 and len(actual_numbers) == 3 else False
        is_win_sum = (sum(int(x) for x in predicted) == sum(int(x) for x in actual_numbers)) if len(predicted) == 3 and len(actual_numbers) == 3 else False

        recent_wl: list = []
        try:
            conn_wl = db.get_connection()
            try:
                cur_wl  = conn_wl.cursor()
                ph_wl   = db._ph()
                cur_wl.execute(
                    f"SELECT is_win FROM prediction_results WHERE draw_number < {ph_wl} "
                    f"ORDER BY draw_number DESC LIMIT 7",
                    (draw_number,)
                )
                recent_wl = [bool(r[0]) for r in reversed(cur_wl.fetchall())]
            finally:
                conn_wl.close()
        except Exception:
            pass

        telegram.send_result(draw_number, actual_numbers, predicted,
                             model_name, match_count, is_win, is_win_sum, recent_wl)

        result_info = {
            "predicted": predicted,
            "model":     model_name,
            "match":     match_count,
            "win":       is_win
        }
        logger.info("Draw #%d result processed: match=%d win=%s", draw_number, match_count, is_win)

    db.refresh_model_stats(ALL_MODEL_NAMES)
    invalidate_calibrator()  # new result saved → stale calibration
    try:
        hybrid, _, __, ensemble, _sz = _get_models(db)
        hybrid.update_weights(db)
        ensemble.update_weights_from_db(db)
    except Exception as e:
        logger.warning(f"Không thể update hybrid weights: {e}")

    # ── Logic Auto Retrain chạy ngầm ──
    if draw_number > 0 and draw_number % getattr(config, 'AUTO_RETRAIN_INTERVAL', 500) == 0:
        logger.info(f"🔄 Đã đạt mốc {draw_number} kỳ. Bắt đầu tự động Retrain model ở background...")
        threading.Thread(target=_background_retrain, daemon=True).start()

    return result_info

def _update_markov_online(db: DatabaseManager, current_draw: int, actual_numbers: List[int]):
    try:
        df = db.get_recent_draws(4)
        if len(df) < 3:
            return
        seqs       = [tuple(sorted(r['numbers'])) for _, r in df.iterrows()]
        from_state = json.dumps(list(seqs[1:3]))
        to_state   = str(tuple(sorted(actual_numbers)))
        db.update_markov_transition(from_state, to_state)
    except Exception as e:
        logger.warning("Markov online update error: %s", e)
