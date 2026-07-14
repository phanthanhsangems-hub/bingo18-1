"""
Bingo 18 – Model Classes
Numbers: 1-6, draw 3 (with replacement). Win = ≥1 match.

Classes:
    MarkovModel        – order-2 Markov chain transition predictor
    ColdNumberModel    – absence-based frequency predictor
    MLEnsembleModel    – Random Forest + feature engineering
    HybridModel        – weighted ensemble of all sub-models
    ModelSelector      – picks best model by DB win-rate stats
"""

import json
import logging
import os
import pickle
import random
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _nested_defaultdict_float():
    """Module-level factory cho defaultdict — picklable (lambda không pickle được)."""
    return defaultdict(float)

NUMBERS = list(range(1, 7))   # [1, 2, 3, 4, 5, 6]
DRAW_SIZE = 3                  # 3 numbers per draw (with replacement)


# ── Helpers ───────────────────────────────────────────────────

def _parse_numbers(val) -> List[int]:
    if isinstance(val, list):
        return [int(x) for x in val]
    if isinstance(val, str):
        try:
            return [int(x) for x in json.loads(val)]
        except Exception:
            return []
    return []


def _random_predict() -> Tuple[List[int], float]:
    nums = sorted(random.choices(NUMBERS, k=DRAW_SIZE))
    return nums, 0.20


# ═══════════════════════════════════════════════════════════════
# 1. MarkovModel
# ═══════════════════════════════════════════════════════════════

class MarkovModel:
    """
    Order-N Markov chain on sorted draw tuples.
    State = tuple of last `order` draws.
    """

    def __init__(self, order: int = 2, decay_rate: float = 0.005):
        self.order      = order
        self.decay_rate = decay_rate
        self.name       = f"markov_order_{order}"
        # transitions[state_key][next_state] = weighted count
        self._transitions: Dict[str, Dict[str, float]] = defaultdict(_nested_defaultdict_float)
        self._trained = False

    # ── Training ─────────────────────────────────────────────

    def train(self, df: pd.DataFrame):
        self._transitions = defaultdict(_nested_defaultdict_float)
        draws = [tuple(sorted(_parse_numbers(r))) for r in df.sort_values('draw_number')['numbers']]
        n = len(draws)

        for i in range(self.order, n):
            age    = n - 1 - i                      # 0 = newest transition
            weight = np.exp(-self.decay_rate * age)
            state     = json.dumps(list(draws[i - self.order : i]))
            next_draw = str(draws[i])
            self._transitions[state][next_draw] += weight

        self._trained = True
        logger.info("%s trained on %d draws (%d states)",
                    self.name, len(draws), len(self._transitions))

    # ── DB-based state rebuild (lightweight) ─────────────────

    def _load_from_db_transitions(self, transitions: Dict[str, Dict[str, float]]):
        """Called by HybridModel after loading DB markov_transitions."""
        self._db_transitions = transitions

    # ── Prediction ───────────────────────────────────────────

    def predict(self, recent_draws, next_draw: int = None) -> List[Tuple[List[int], float]]:
        draws = [tuple(sorted(_parse_numbers(d))) if not isinstance(d, tuple) else d
                 for d in recent_draws]

        if len(draws) < self.order:
            return [_random_predict()]

        state = json.dumps(list(draws[-self.order:]))

        # Try in-memory transitions first
        if self._trained and state in self._transitions:
            counter  = self._transitions[state]
            total    = sum(counter.values())
            best_key = max(counter, key=lambda k: counter[k])
            cnt      = counter[best_key]
            try:
                nums = list(json.loads(best_key.replace('(','[').replace(')',']')))
                conf = cnt / total
                return [(sorted([int(n) for n in nums]), conf)]
            except Exception:
                pass

        # Fallback: frequency of recent draws
        freq = Counter()
        for d in draws[-20:]:
            freq.update(list(d))
        top = [n for n, _ in freq.most_common(3)]
        if len(top) < 3:
            top = sorted(random.choices(NUMBERS, k=3 - len(top))) + top
        return [(sorted(top[:3]), 0.25)]


# ═══════════════════════════════════════════════════════════════
# 2. ColdNumberModel
# ═══════════════════════════════════════════════════════════════

class ColdNumberModel:
    """
    Predicts numbers with the highest absence count (due for return).
    Also blends with moderate frequency to avoid purely cold picks.
    """

    def __init__(self, window_size: int = 30):
        self.window_size = window_size
        self.name        = f"cold_number_window_{window_size}"
        self._absence: Dict[int, int] = {}
        self._trained = False

    def train(self, df: pd.DataFrame):
        recent = df.sort_values('draw_number', ascending=False).head(self.window_size)
        last_seen: Dict[int, int] = {}
        for _, row in recent.iterrows():
            dn   = int(row['draw_number'])
            nums = _parse_numbers(row['numbers'])
            for n in nums:
                if n not in last_seen:
                    last_seen[n] = dn

        max_draw = int(recent.iloc[0]['draw_number']) if len(recent) > 0 else 0
        self._absence = {}
        for n in NUMBERS:
            if n in last_seen:
                self._absence[n] = max_draw - last_seen[n]
            else:
                self._absence[n] = self.window_size

        self._trained = True
        logger.info("%s trained: absence=%s", self.name, self._absence)

    def predict(self, recent_draws, next_draw: int = None) -> List[Tuple[List[int], float]]:
        draws = [_parse_numbers(d) if not isinstance(d, list) else d for d in recent_draws]

        # Compute absence from recent draws if not trained
        if not self._trained or not self._absence:
            last_seen: Dict[int, int] = {}
            for i, d in enumerate(reversed(draws[-self.window_size:])):
                for n in d:
                    if n not in last_seen:
                        last_seen[n] = i
            self._absence = {n: last_seen.get(n, self.window_size) for n in NUMBERS}

        # Score = absence (higher = colder = more likely to appear)
        # Blend: 70% absence, 30% inverse recent frequency
        freq = Counter()
        for d in draws[-20:]:
            freq.update(d)

        scores = {}
        for n in NUMBERS:
            absence_score = self._absence.get(n, 0)
            freq_score    = 1.0 / (1.0 + freq.get(n, 0))
            scores[n]     = 0.7 * absence_score + 0.3 * freq_score * 10

        sorted_nums = sorted(scores, key=lambda x: scores[x], reverse=True)
        top3        = sorted(sorted_nums[:3])

        # Confidence: relative score of top3 vs all
        total = sum(scores.values())
        conf  = sum(scores[n] for n in top3) / total if total > 0 else 0.3
        conf  = min(conf, 0.95)

        return [(top3, conf)]


# ═══════════════════════════════════════════════════════════════
# 3. ComboColdModel
# ═══════════════════════════════════════════════════════════════

class ComboColdModel:
    """
    Tracks frequency of all 56 unordered multiset combos (3-from-6 with replacement).
    Predicts the combo with the lowest occurrence count in the last `window_size` draws.

    Why better than ColdNumberModel:
    - Cold_number picks 3 cold NUMBERS and assembles a combo — that combo might be hot.
    - ComboCold picks the coldest COMBO directly → targets exact-match win more precisely.

    With 61k draws / 56 combos ≈ 1089 average occurrences per combo → enough data.
    """

    ALL_COMBOS: List[Tuple[int, ...]] = [
        (a, b, c)
        for a in NUMBERS
        for b in NUMBERS[NUMBERS.index(a):]
        for c in NUMBERS[NUMBERS.index(b):]
    ]  # 56 sorted multiset combos

    def __init__(self, window_size: int = 30, blend_global: float = 0.3):
        self.window_size  = window_size
        self.blend_global = blend_global   # weight of global cold vs local cold
        self.name         = f"combo_cold_w{window_size}"
        self._freq: Counter = Counter()

    def _combo_key(self, draw) -> Tuple[int, ...]:
        return tuple(sorted(_parse_numbers(draw) if not isinstance(draw, tuple) else draw))

    def train(self, df: pd.DataFrame):
        recent = df.sort_values('draw_number', ascending=False).head(self.window_size)
        self._freq = Counter()
        for _, row in recent.iterrows():
            self._freq[self._combo_key(row['numbers'])] += 1

    def predict(self, recent_draws, next_draw: int = None) -> List[Tuple[List[int], float]]:
        draws = [_parse_numbers(d) if not isinstance(d, (list, tuple)) else list(d)
                 for d in recent_draws]
        window = draws[-self.window_size:] if len(draws) >= self.window_size else draws

        local_freq: Counter = Counter(self._combo_key(d) for d in window)

        # Score = local_freq (lower = colder = predict it)
        # Break ties by global absence (blend_global)
        global_freq: Counter = Counter(self._combo_key(d) for d in draws[-300:]) if len(draws) > 30 else local_freq

        scores: Dict[Tuple, float] = {}
        for combo in self.ALL_COMBOS:
            local_score  = local_freq.get(combo, 0)
            global_score = global_freq.get(combo, 0)
            # Lower score = colder = better prediction target
            scores[combo] = (1 - self.blend_global) * local_score + self.blend_global * global_score

        coldest = min(self.ALL_COMBOS, key=lambda c: scores[c])

        # Confidence: how cold is this combo vs average?
        avg_freq = len(window) / len(self.ALL_COMBOS)  # expected freq per combo
        actual   = local_freq.get(coldest, 0)
        coldness = max(0.0, avg_freq - actual)          # how far below average
        conf     = min(0.5 + coldness / max(avg_freq * 2, 1), 0.95)

        return [(sorted(list(coldest)), conf)]


# ═══════════════════════════════════════════════════════════════
# 4. FWBRModel  (Frequency-Weighted by Recency)
# ═══════════════════════════════════════════════════════════════

class FWBRModel:
    """
    Picks the 3 numbers with the lowest combined score:
        score[n] = freq_in_window[n]  +  recency_weight × draws_since_last_seen[n]
    Low score = appeared infrequently AND appeared recently ("active-cold").
    Backtest (1 000 draws): 4.2% multiset win rate vs Cold W30 3.0%.
    """

    def __init__(self, window_size: int = 30, recency_weight: float = 0.5):
        self.window_size    = window_size
        self.recency_weight = recency_weight
        self.name           = f"fwbr_w{window_size}"

    def train(self, df: pd.DataFrame):
        pass  # stateless – no training needed

    def predict(self, recent_draws, next_draw: int = None) -> List[Tuple[List[int], float]]:
        draws   = [_parse_numbers(d) if not isinstance(d, list) else d for d in recent_draws]
        context = draws[-self.window_size:] if len(draws) >= self.window_size else draws
        w       = len(context)
        if not context:
            return [_random_predict()]

        freq: Dict[int, int] = {n: 0 for n in NUMBERS}
        last_seen: Dict[int, int] = {}
        for i, d in enumerate(reversed(context)):
            for n in d:
                freq[n] += 1
                if n not in last_seen:
                    last_seen[n] = i   # 0 = most recent draw

        recency = {n: last_seen.get(n, w) for n in NUMBERS}
        scores  = {n: freq[n] + self.recency_weight * recency[n] for n in NUMBERS}

        top3 = sorted(sorted(scores, key=lambda x: scores[x])[:3])

        # Confidence: how much lower are top3 scores relative to the rest
        total      = sum(scores.values())
        bottom_sum = sum(scores[n] for n in top3)
        conf = max(0.30, min(1.0 - (bottom_sum / total), 0.95)) if total > 0 else 0.30

        return [(top3, conf)]


# ═══════════════════════════════════════════════════════════════
# 4. MLEnsembleModel
# ═══════════════════════════════════════════════════════════════

class MLEnsembleModel:
    """
    Random Forest ensemble on hand-crafted features.
    Predicts probability of each number 1-6 appearing.
    """

    name = "ml_ensemble"

    def __init__(self, decay_rate: float = 0.005):
        self.decay_rate = decay_rate
        self._models   = {}   # {num: RandomForestClassifier}
        self._trained  = False
        self._min_rows = 50

    # ── Feature extraction (inline, no dep on FeatureEngineer) ─

    def _extract(self, draws: List[List[int]]) -> np.ndarray:
        feats = []
        for window in [5, 10, 20, 30]:
            recent = draws[-window:] if len(draws) >= window else draws
            cnt    = Counter()
            for d in recent:
                cnt.update(d)
            for n in NUMBERS:
                feats.append(cnt.get(n, 0) / max(len(recent), 1))

        # Absence features
        last_seen = {}
        for i, d in enumerate(reversed(draws[-50:])):
            for n in d:
                if n not in last_seen:
                    last_seen[n] = i
        for n in NUMBERS:
            feats.append(last_seen.get(n, 50))

        # Recent sum stats
        sums = [sum(d) for d in draws[-20:]] if draws else [10]
        feats += [np.mean(sums), np.std(sums)]

        # Last draw one-hot
        last = draws[-1] if draws else []
        for n in NUMBERS:
            feats.append(1.0 if n in last else 0.0)

        return np.array(feats, dtype=np.float32)

    def train(self, df: pd.DataFrame):
        try:
            from sklearn.ensemble import RandomForestClassifier
        except ImportError:
            logger.warning("scikit-learn not available – MLEnsembleModel disabled")
            return

        draws_raw = df.sort_values('draw_number')['numbers'].tolist()
        draws     = [_parse_numbers(d) for d in draws_raw]

        if len(draws) < self._min_rows:
            logger.warning("%s: not enough data (%d rows)", self.name, len(draws))
            return

        X, y = [], {n: [] for n in NUMBERS}
        for i in range(30, len(draws)):
            history = draws[max(0, i - 50):i]
            feat    = self._extract(history)
            X.append(feat)
            for n in NUMBERS:
                y[n].append(1 if n in draws[i] else 0)

        X = np.array(X)
        n_samples = len(X)
        # Recency decay: recent draws get higher weight
        sample_weight = np.exp(self.decay_rate * np.arange(n_samples - 1, -1, -1))

        # SIZE-balance: weight draws toward theoretical priors (NHO 37.5%, HOA 25%, LON 37.5%)
        # using target_freq / actual_freq. This makes gentle corrections that reduce NHO bias
        # without overcorrecting toward HOA/LON.
        _TARGET_SIZE = {'NHO': 0.355, 'HOA': 0.245, 'LON': 0.400}
        def _size_cat(d): s = sum(d); return 'NHO' if s <= 9 else ('HOA' if s <= 11 else 'LON')
        target_draws = draws[30:]
        size_counts = Counter(_size_cat(d) for d in target_draws)
        n_total = max(sum(size_counts.values()), 1)
        size_bal = {
            cat: _TARGET_SIZE[cat] / max(size_counts[cat] / n_total, 1e-6)
            for cat in ('NHO', 'HOA', 'LON')
        }
        size_weight = np.array([size_bal[_size_cat(d)] for d in target_draws], dtype=np.float32)
        sample_weight = sample_weight * size_weight
        sample_weight /= sample_weight.sum()
        logger.info("%s size_counts=%s  size_bal=%s", self.name, dict(size_counts),
                    {k: round(v, 3) for k, v in size_bal.items()})

        self._models = {}
        for n in NUMBERS:
            clf = RandomForestClassifier(n_estimators=50, max_depth=6,
                                          random_state=42, n_jobs=-1)
            clf.fit(X, y[n], sample_weight=sample_weight)
            self._models[n] = clf

        self._trained = True
        logger.info("%s trained on %d samples", self.name, len(X))

    def predict(self, df_or_draws, next_draw: int = None) -> List[Tuple[List[int], float]]:
        if isinstance(df_or_draws, pd.DataFrame):
            draws = [_parse_numbers(r) for r in df_or_draws.sort_values('draw_number', ascending=False).head(50)['numbers']]
            draws = list(reversed(draws))
        else:
            draws = [_parse_numbers(d) for d in df_or_draws]

        if not self._trained or not self._models:
            # Fallback: frequency based
            freq = Counter()
            for d in draws[-30:]:
                freq.update(d)
            top3 = sorted([n for n, _ in freq.most_common(3)])
            if len(top3) < 3:
                top3 = sorted(NUMBERS[:3])
            return [(top3, 0.30)]

        feat   = self._extract(draws).reshape(1, -1)
        probs  = {}
        for n in NUMBERS:
            try:
                probs[n] = float(self._models[n].predict_proba(feat)[0][1])
            except Exception:
                probs[n] = 1.0 / 6

        sorted_nums = sorted(probs, key=lambda x: probs[x], reverse=True)
        top3        = sorted(sorted_nums[:3])
        conf        = sum(probs[n] for n in top3) / 3
        return [(top3, conf)]


# ═══════════════════════════════════════════════════════════════
# 4. HybridModel
# ═══════════════════════════════════════════════════════════════

class HybridModel:
    """
    Weighted ensemble: Markov + ColdNumber + MLEnsemble.
    Weights are updated dynamically from DB win-rate stats.

    Cải tiến v2: Thay thế argmax deterministic bằng softmax sampling
    + exploration rate để tránh stuck ở cùng một bộ số nhiều kỳ liên tiếp.
    """

    name = "hybrid_model"

    def __init__(self, exploration_rate: float = float(os.environ.get("EXPLORE", "0")),
                 temperature: float = 0.5,
                 decay_rate: float = 0.005, db=None):
        self.markov_model = MarkovModel(order=2, decay_rate=decay_rate)
        self.cold_model   = ColdNumberModel(window_size=30)
        self.ml_model     = MLEnsembleModel(decay_rate=decay_rate)

        # Default weights — sẽ được override từ DB nếu có dữ liệu thực
        self.weights: Dict[str, float] = {
            "markov":  0.15,
            "cold":    0.55,
            "ml":      0.30,
        }
        self.exploration_rate = exploration_rate
        self.temperature = temperature
        self._trained = False

        # Load weights từ DB ngay lúc init nếu có dữ liệu thực
        if db is not None:
            try:
                self.update_weights(db)
            except Exception:
                pass  # giữ default weights nếu DB chưa có data

    # ── Train ────────────────────────────────────────────────

    def train(self, df: pd.DataFrame):
        logger.info("HybridModel: training sub-models...")
        self.markov_model.train(df)
        self.cold_model.train(df)
        if len(df) >= 50:
            self.ml_model.train(df)
        self._trained = True
        logger.info("HybridModel: training complete")

    # ── Persist ──────────────────────────────────────────────

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
        with open(path, 'wb') as f:
            pickle.dump({
                'markov':  self.markov_model,
                'cold':    self.cold_model,
                'ml':      self.ml_model,
                'weights': self.weights,
            }, f)
        logger.info("HybridModel saved → %s", path)

    def load(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        try:
            with open(path, 'rb') as f:
                data = pickle.load(f)
            self.markov_model = data.get('markov', MarkovModel(order=2))
            self.cold_model   = data.get('cold',   ColdNumberModel(window_size=30))
            self.ml_model     = data.get('ml',     MLEnsembleModel())
            self.weights      = data.get('weights', self.weights)
            self._trained     = True
            logger.info("HybridModel loaded from %s  weights=%s", path, self.weights)
            return True
        except Exception as e:
            logger.warning("HybridModel load error: %s — deleting corrupted pkl", e)
            try:
                os.remove(path)
            except OSError:
                pass
            return False

    # ── Weight update from DB ────────────────────────────────

    def update_weights(self, db):
        """Re-balance weights: size_win_rate + 0.3 × sum_win_rate."""
        try:
            def combined(name):
                size_wr = db.get_model_win_rate(name, 50)
                try:
                    sum_wr = db.get_model_sum_win_rate(name, 50)
                except Exception:
                    sum_wr = 0.0
                return size_wr + 0.3 * sum_wr

            scores = {
                'markov': combined(self.markov_model.name),
                'cold':   combined(self.cold_model.name),
                'ml':     combined(self.ml_model.name),
            }
            total = sum(scores.values())
            if total > 0:
                self.weights = {k: v / total for k, v in scores.items()}
            logger.info("Hybrid weights updated (size+sum): %s", self.weights)
        except Exception as e:
            logger.warning("update_weights error: %s", e)

    # ── Predict ──────────────────────────────────────────────

    def predict(self, df_or_draws, next_draw: int = None) -> List[Tuple[List[int], float]]:
        if isinstance(df_or_draws, pd.DataFrame):
            df    = df_or_draws.sort_values('draw_number', ascending=False)
            draws = [_parse_numbers(r) for r in reversed(df.head(50)['numbers'].tolist())]
        else:
            draws = [_parse_numbers(d) for d in df_or_draws]

        # Collect predictions from sub-models
        candidates: List[Tuple[str, List[int], float]] = []

        try:
            preds = self.markov_model.predict(draws, next_draw)
            if preds:
                candidates.append(('markov', preds[0][0], preds[0][1]))
        except Exception as e:
            logger.warning("Markov predict error: %s", e)

        try:
            preds = self.cold_model.predict(draws, next_draw)
            if preds:
                candidates.append(('cold', preds[0][0], preds[0][1]))
        except Exception as e:
            logger.warning("Cold predict error: %s", e)

        try:
            preds = self.ml_model.predict(draws, next_draw)
            if preds:
                candidates.append(('ml', preds[0][0], preds[0][1]))
        except Exception as e:
            logger.warning("ML predict error: %s", e)

        if not candidates:
            return [_random_predict()]

        # Score each number across models
        num_scores: Dict[int, float] = defaultdict(float)
        for model_key, nums, conf in candidates:
            w = self.weights.get(model_key, 1.0 / 3)
            for n in nums:
                num_scores[n] += w * conf

        numbers = list(num_scores.keys())
        scores  = np.array([num_scores[n] for n in numbers], dtype=float)

        # ── EXPLORATION: 10% cơ hội chọn random hoàn toàn ──────────
        if random.random() < self.exploration_rate:
            chosen = random.sample(numbers, min(DRAW_SIZE, len(numbers)))
        else:
            # ── SOFTMAX SAMPLING: xác suất tỉ lệ với score ──────────
            # Tránh stuck vì argmax deterministic khi nhiều số cùng score cao
            temp   = max(self.temperature, 1e-6)
            exp_s  = np.exp((scores - scores.max()) / temp)   # stable softmax
            probs  = exp_s / exp_s.sum()
            chosen = list(np.random.choice(
                numbers,
                size=min(DRAW_SIZE, len(numbers)),
                replace=False,
                p=probs,
            ))

        top3 = sorted(chosen)

        # Weighted confidence
        total_w = sum(self.weights.values())
        conf    = sum(num_scores[n] for n in top3) / max(total_w, 1e-9) / DRAW_SIZE
        conf    = min(conf, 0.95)

        return [(top3, conf)]


# ═══════════════════════════════════════════════════════════════
# 5. MultisetMarkovModel
# ═══════════════════════════════════════════════════════════════

class MultisetMarkovModel:
    """
    Markov 1-step predictor on multisets (sorted draw tuples).
    Predicts the next multiset with highest conditional frequency.
    Fallback: most-frequent overall multiset when current state unseen.
    """
    name = "multiset_markov"

    def __init__(self, decay_rate: float = 0.005):
        self.decay_rate  = decay_rate
        self.transitions: Dict[tuple, Dict[tuple, float]] = {}
        self._freq: Dict[tuple, float] = defaultdict(float)

    def fit(self, history: List[List[int]]):
        self.transitions = {}
        self._freq = defaultdict(float)
        multisets = [tuple(sorted(_parse_numbers(d) if not isinstance(d, list) else d))
                     for d in history]
        n = len(multisets)
        for i, ms in enumerate(multisets):
            age = n - 1 - i
            self._freq[ms] += np.exp(-self.decay_rate * age)

        for i in range(n - 1):
            age  = n - 2 - i                        # 0 = most recent transition
            w    = np.exp(-self.decay_rate * age)
            prev = multisets[i]
            nxt  = multisets[i + 1]
            if prev not in self.transitions:
                self.transitions[prev] = defaultdict(float)
            self.transitions[prev][nxt] += w

    def predict(self, recent_draws, next_draw: int = None) -> List[Tuple[List[int], float]]:
        if not recent_draws:
            return [([1, 2, 3], 0.3)]
        last_raw = recent_draws[-1]
        last = tuple(sorted(_parse_numbers(last_raw) if not isinstance(last_raw, list) else last_raw))
        if last in self.transitions and self.transitions[last]:
            best = max(self.transitions[last], key=lambda k: self.transitions[last][k])
            conf = self.get_confidence(recent_draws)
        elif self._freq:
            best = max(self._freq, key=lambda k: self._freq[k])
            conf = 0.28
        else:
            return [([1, 2, 3], 0.2)]
        return [(sorted(list(best)), conf)]

    def get_confidence(self, recent_draws) -> float:
        if not recent_draws:
            return 0.28
        last_raw = recent_draws[-1]
        last = tuple(sorted(_parse_numbers(last_raw) if not isinstance(last_raw, list) else last_raw))
        cands = self.transitions.get(last)
        if not cands:
            return 0.28
        total = sum(cands.values())
        best_val = max(cands.values())
        return min(best_val / total, 0.95) if total else 0.28


# ═══════════════════════════════════════════════════════════════
# 6. SizePredictor
# ═══════════════════════════════════════════════════════════════

class SizePredictor:
    """
    Predicts the next draw's size category (NHO/HOA/LON) from recent sum/size history.
    Used as a post-processing step to bias number selection toward the predicted size.

    Base rates from combinatorics (3 dice 1-6):
        NHO (sum 3-9)  = 81/216 = 37.5%
        HOA (sum 10-11) = 54/216 = 25.0%
        LON (sum 12-18) = 81/216 = 37.5%
    """

    CATEGORIES = ['NHO', 'HOA', 'LON']
    name = "size_predictor"

    _SIZE_NHO_MAX  = 9
    _SIZE_HOA_MAX  = 11

    def __init__(self, decay_rate: float = 0.005):
        self.decay_rate = decay_rate
        self._clf       = None
        self._trained   = False

    @staticmethod
    def _cat(s: int) -> str:
        if s <= 9:
            return 'NHO'
        if s <= 11:
            return 'HOA'
        return 'LON'

    def _features(self, sums: List[int], sizes: List[str]) -> np.ndarray:
        n = len(sizes)
        feats: List[float] = []

        # Last 5 size one-hot  (15 features)
        for i in range(1, 6):
            idx = n - i
            for cat in self.CATEGORIES:
                feats.append(1.0 if 0 <= idx < n and sizes[idx] == cat else 0.0)

        # Size freq in windows 10 / 20 / 50  (9 features)
        for w in [10, 20, 50]:
            window = sizes[-w:] if n >= w else sizes
            wlen   = max(len(window), 1)
            for cat in self.CATEGORIES:
                feats.append(window.count(cat) / wlen)

        # Streak of same size at tail  (1 feature)
        streak = 0
        if n > 0:
            last_cat = sizes[-1]
            for i in range(n - 1, -1, -1):
                if sizes[i] == last_cat:
                    streak += 1
                else:
                    break
        feats.append(float(streak))

        # Sum mean + std for windows 10 / 20  (4 features)
        for w in [10, 20]:
            ws = sums[-w:] if len(sums) >= w else sums
            feats.append(float(np.mean(ws)) if ws else 10.5)
            feats.append(float(np.std(ws))  if len(ws) > 1 else 3.0)

        # Draws since each size last seen  (3 features)
        for cat in self.CATEGORIES:
            gap = float(n)
            for i in range(n - 1, -1, -1):
                if sizes[i] == cat:
                    gap = float(n - 1 - i)
                    break
            feats.append(gap)

        # Last 2 sums  (2 features)
        feats.append(float(sums[-1]) if sums else 10.5)
        feats.append(float(sums[-2]) if len(sums) >= 2 else 10.5)

        # Sum trend: last sum minus mean of last 10  (1 feature)
        ws10   = sums[-10:] if len(sums) >= 10 else sums
        mean10 = float(np.mean(ws10)) if ws10 else 10.5
        feats.append((float(sums[-1]) if sums else 10.5) - mean10)

        return np.array(feats, dtype=np.float32)  # 35 features

    def train(self, df: pd.DataFrame):
        try:
            from sklearn.linear_model import LogisticRegression
        except ImportError:
            logger.warning("scikit-learn not available – SizePredictor disabled")
            return

        df_s = df.sort_values('draw_number')
        if len(df_s) < 30:
            return

        if 'sum_value' in df_s.columns:
            sums = [int(x) for x in df_s['sum_value'].tolist()]
        else:
            nums_list = [_parse_numbers(r) for r in df_s['numbers']]
            sums = [sum(n) for n in nums_list]
        # Always derive size from sum_value — size_category column has stale/incorrect data
        sizes = [self._cat(s) for s in sums]

        X, y = [], []
        for i in range(20, len(sums)):
            X.append(self._features(sums[:i], sizes[:i]))
            y.append(sizes[i])

        if len(X) < 10:
            return

        X  = np.array(X)
        n  = len(X)
        sw = np.exp(self.decay_rate * np.arange(n))
        sw /= sw.sum()

        clf = LogisticRegression(max_iter=300, random_state=42, class_weight='balanced')
        clf.fit(X, y, sample_weight=sw)
        self._clf     = clf
        self._trained = True
        logger.info("SizePredictor trained on %d samples, classes=%s", n, list(clf.classes_))

    def predict_proba(self, sums: List[int], sizes: List[str]) -> Dict[str, float]:
        """Return probability dict for each size category."""
        if not self._trained or self._clf is None:
            return {'NHO': 0.375, 'HOA': 0.25, 'LON': 0.375}
        feat  = self._features(sums, sizes).reshape(1, -1)
        probs = self._clf.predict_proba(feat)[0]
        return {c: float(p) for c, p in zip(self._clf.classes_, probs)}

    def predict(self, sums: List[int], sizes: List[str]) -> Tuple[str, float]:
        """Return (predicted_category, confidence)."""
        proba = self.predict_proba(sums, sizes)
        best  = max(proba, key=lambda k: proba[k])
        return best, proba[best]


# ═══════════════════════════════════════════════════════════════
# 7. ModelSelector
# ═══════════════════════════════════════════════════════════════

class ModelSelector:
    """
    Picks the best-performing model based on DB win-rate stats.

    Scoring: combined = size_win_rate + SUM_BONUS_WEIGHT × sum_win_rate
    - SIZE baseline = 37.5% (P(NHO) = P(LON) = 37.5%, P(HOA) = 25%)
    - SUM  baseline = 6.25% (1/16 sums in range 3-18)
    - Threshold = 40% size win rate (phải vượt bias luôn chọn NHO/LON)
    - MIN_SAMPLES = 50: cần đủ data để tin win rate
    - EXPLORE_EPSILON = 0.10: 10% chance thử model chưa đủ data
    """

    RANDOM_BASELINE   = 0.375   # P(size đúng) khi đoán NHO/LON ngẫu nhiên
    SUM_BASELINE      = 0.0625  # P(tổng đúng) khi đoán ngẫu nhiên (1/16)
    OUTPERFORM_MARGIN = 0.025   # threshold = 40.0% (phải vượt single-size bias)
    SUM_BONUS_WEIGHT  = 0.30    # trọng số bonus cho sum accuracy
    MIN_SAMPLES       = 50
    EXPLORE_EPSILON   = 0.10    # epsilon-greedy cho model chưa có đủ data
    # Weighted average windows: ưu tiên recent performance hơn
    WINDOW_WEIGHTS    = {30: 0.5, 60: 0.3, 100: 0.2}

    def __init__(self, db):
        self.db      = db
        self._models: Dict[str, object] = {}

    def add_model(self, model):
        if hasattr(model, "name"):
            self._models[model.name] = model
            logger.debug("ModelSelector: registered '%s'", model.name)

    def get_model(self, name: str):
        return self._models.get(name)

    def select_best_model(self, windows: List[int] = None) -> str:
        if windows is None:
            windows = [30, 60, 100]

        threshold = self.RANDOM_BASELINE + self.OUTPERFORM_MARGIN  # 0.400

        scored: List[Tuple[str, float, int]] = []   # (name, avg_wr, total_samples)
        unexplored: List[Tuple[str, int]] = []       # models chưa đủ MIN_SAMPLES

        # Single batched query instead of 27 connections (9 models × 3 windows)
        db_rows: dict = {}
        try:
            conn = self.db.get_connection()
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT model_name,
                        SUM(CASE WHEN rn <= 30  THEN 1 ELSE 0 END) AS n30,
                        SUM(CASE WHEN is_win    AND rn <= 30 THEN 1 ELSE 0 END) AS wins30,
                        SUM(CASE WHEN COALESCE(is_win_sum, FALSE) AND rn <= 30 THEN 1 ELSE 0 END) AS sw30,
                        SUM(CASE WHEN rn <= 60  THEN 1 ELSE 0 END) AS n60,
                        SUM(CASE WHEN is_win    AND rn <= 60 THEN 1 ELSE 0 END) AS wins60,
                        SUM(CASE WHEN COALESCE(is_win_sum, FALSE) AND rn <= 60 THEN 1 ELSE 0 END) AS sw60,
                        COUNT(*) AS n100,
                        SUM(CASE WHEN is_win    THEN 1 ELSE 0 END) AS wins100,
                        SUM(CASE WHEN COALESCE(is_win_sum, FALSE) THEN 1 ELSE 0 END) AS sw100
                    FROM (
                        SELECT p.model_name, pr.is_win, pr.is_win_sum,
                               ROW_NUMBER() OVER (PARTITION BY p.model_name ORDER BY pr.created_at DESC) AS rn
                        FROM prediction_results pr
                        JOIN predictions p ON pr.prediction_id = p.id
                    ) t
                    WHERE rn <= 100
                    GROUP BY model_name
                """)
                db_rows = {row[0]: row for row in cur.fetchall()}
            finally:
                conn.close()
        except Exception as e:
            logger.warning("ModelSelector batch query error: %s", e)

        for name in self._models:
            weighted_size_wr = 0.0
            weighted_sum_wr  = 0.0
            weight_sum       = 0.0
            total_n          = 0

            row = db_rows.get(name)
            if row:
                # (model_name, n30, wins30, sw30, n60, wins60, sw60, n100, wins100, sw100)
                win_data = {
                    30:  (int(row[1] or 0), int(row[2] or 0), int(row[3] or 0)),
                    60:  (int(row[4] or 0), int(row[5] or 0), int(row[6] or 0)),
                    100: (int(row[7] or 0), int(row[8] or 0), int(row[9] or 0)),
                }
                for w in windows:
                    w_coeff = self.WINDOW_WEIGHTS.get(w, 1.0 / len(windows))
                    n, wins, sw = win_data.get(w, (0, 0, 0))
                    if n:
                        size_wr = wins / n
                        sum_wr  = sw   / n
                        weighted_size_wr += size_wr * w_coeff
                        weighted_sum_wr  += sum_wr  * w_coeff
                        weight_sum       += w_coeff
                        total_n           = max(total_n, n)

            avg_size_wr = weighted_size_wr / weight_sum if weight_sum > 0 else 0.0
            avg_sum_wr  = weighted_sum_wr  / weight_sum if weight_sum > 0 else 0.0
            # Combined score: size accuracy là chính, sum accuracy là bonus
            combined = avg_size_wr + self.SUM_BONUS_WEIGHT * avg_sum_wr
            scored.append((name, combined, avg_size_wr, total_n))

            if total_n < self.MIN_SAMPLES:
                unexplored.append((name, total_n))

            logger.debug(
                "ModelSelector: %-30s size_wr=%.3f combined=%.3f (n=%d) vs threshold=%.3f → %s",
                name, avg_size_wr, combined, total_n, threshold,
                "✅ ABOVE" if avg_size_wr >= threshold and total_n >= self.MIN_SAMPLES else "❌ below"
            )

        # Epsilon-greedy: 10% chance khám phá model chưa có đủ data
        if unexplored and random.random() < self.EXPLORE_EPSILON:
            explore_name, explore_n = min(unexplored, key=lambda x: x[1])
            logger.info(
                "ModelSelector: explore → '%s' (n=%d, epsilon=%.0f%%)",
                explore_name, explore_n, self.EXPLORE_EPSILON * 100
            )
            return explore_name

        # Lọc: size_wr vượt threshold VÀ có đủ samples; rank theo combined score
        qualified = [
            (name, comb, size_wr, n) for name, comb, size_wr, n in scored
            if size_wr >= threshold and n >= self.MIN_SAMPLES
        ]

        if qualified:
            best_name, best_comb, best_size_wr, best_n = max(qualified, key=lambda x: x[1])
            logger.info(
                "ModelSelector: selected '%s' (size_wr=%.3f combined=%.3f n=%d, +%.1f%% vs baseline)",
                best_name, best_size_wr, best_comb, best_n,
                (best_size_wr - self.RANDOM_BASELINE) * 100
            )
            return best_name

        # Không model nào vượt threshold → chọn model tốt nhất có đủ samples
        qualified_any = [(name, comb, size_wr, n) for name, comb, size_wr, n in scored if n >= self.MIN_SAMPLES]
        if qualified_any:
            best_name, best_comb, best_size_wr, best_n = max(qualified_any, key=lambda x: x[1])
            logger.warning(
                "ModelSelector: no model beats threshold %.1f%% "
                "(best size_wr=%.1f%% combined=%.3f '%s'). Using best available.",
                threshold * 100, best_size_wr * 100, best_comb, best_name
            )
            return best_name

        fallback = "hybrid_model" if "hybrid_model" in self._models else (
            list(self._models.keys())[0] if self._models else "hybrid_model"
        )
        logger.info("ModelSelector: fallback → '%s'", fallback)
        return fallback