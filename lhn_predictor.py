"""
lhn_predictor.py
================
Dự đoán Lớn/Hòa/Nhỏ (LHN) cho kỳ Bingo18 tiếp theo.

Logic:
- Bingo18: 3 số, mỗi số 1-6
- Tổng min=3, max=18
- NHO: tổng <= 9  (trung bình ~43% xác suất lý thuyết)
- HOA: tổng 10-11 (trung bình ~14%)
- LON: tổng >= 12 (trung bình ~43%)

Các chiến lược:
1. Markov chain bậc 1 trên chuỗi LHN
2. Markov chain bậc 2 (window 3 kỳ)
3. Anti-streak (sau N kỳ liên tiếp 1 loại)
4. Frequency trong cửa sổ gần nhất
5. Ensemble vote
"""

import json
import logging
from collections import Counter, defaultdict
from typing import Optional

logger = logging.getLogger(__name__)


def _to_lhn(numbers) -> str:
    if isinstance(numbers, str):
        try:
            numbers = json.loads(numbers)
        except:
            numbers = [int(x) for x in numbers.strip('[]').split(',')]
    s = sum(numbers)
    return "NHO" if s <= 9 else ("HOA" if s <= 11 else "LON")


class LHNPredictor:
    """Dự đoán LHN (Lớn/Hòa/Nhỏ) cho kỳ tiếp theo."""

    CATEGORIES = ["LON", "HOA", "NHO"]

    def __init__(self, db=None):
        self.db = db

    def _load_sequence(self, n: int = 200) -> list:
        """Tải chuỗi LHN từ DB, mới nhất trước."""
        if not self.db:
            return []
        try:
            df = self.db.get_recent_draws(n)
            return [_to_lhn(row['numbers']) for _, row in df.iterrows()]
        except Exception as e:
            logger.warning(f"_load_sequence error: {e}")
            return []

    def _markov1(self, seq: list) -> dict:
        """P(next | prev) — Markov bậc 1."""
        trans = defaultdict(Counter)
        for i in range(len(seq) - 1):
            trans[seq[i]][seq[i+1]] += 1
        # Normalize
        result = {}
        for state, counter in trans.items():
            total = sum(counter.values())
            result[state] = {k: v/total for k, v in counter.items()}
        return result

    def _markov2(self, seq: list) -> dict:
        """P(next | prev2, prev1) — Markov bậc 2."""
        trans = defaultdict(Counter)
        for i in range(len(seq) - 2):
            state = (seq[i], seq[i+1])
            trans[state][seq[i+2]] += 1
        result = {}
        for state, counter in trans.items():
            total = sum(counter.values())
            result[state] = {k: v/total for k, v in counter.items()}
        return result

    def predict_next(self, n_history: int = 100) -> dict:
        """
        Dự đoán LHN cho kỳ tiếp theo.
        seq[0] = kỳ mới nhất (DataFrame sorted DESC).
        """
        seq = self._load_sequence(n_history)
        if len(seq) < 10:
            return {
                "prediction":  "HOA",
                "confidence":  33.3,
                "method":      "insufficient_data",
                "next_draw":   0,
            }

        # Để dự đoán kỳ TIẾP THEO, cần predict sau seq[0]
        # Nhưng seq[0] là mới nhất → để dùng Markov cần reverse
        seq_asc = list(reversed(seq))  # cũ → mới

        votes = Counter()
        methods = []

        # ── 1. Markov bậc 1 ──────────────────────────────────
        m1 = self._markov1(seq_asc)
        last1 = seq_asc[-1]
        if last1 in m1:
            best1 = max(m1[last1], key=m1[last1].get)
            conf1 = m1[last1][best1]
            votes[best1] += conf1 * 2  # weight 2
            methods.append(f"markov1→{best1}({conf1:.0%})")

        # ── 2. Markov bậc 2 ──────────────────────────────────
        m2 = self._markov2(seq_asc)
        if len(seq_asc) >= 2:
            last2 = (seq_asc[-2], seq_asc[-1])
            if last2 in m2:
                best2 = max(m2[last2], key=m2[last2].get)
                conf2 = m2[last2][best2]
                votes[best2] += conf2 * 3  # weight 3 (bậc cao hơn)
                methods.append(f"markov2→{best2}({conf2:.0%})")

        # ── 3. Anti-streak ────────────────────────────────────
        streak_len = 1
        for i in range(len(seq) - 1):
            if seq[i] == seq[0]:
                streak_len += 1
            else:
                break

        if streak_len >= 4:
            others = [c for c in self.CATEGORIES if c != seq[0]]
            freq20 = Counter(seq[:20])
            anti   = max(others, key=lambda x: freq20.get(x, 0))
            votes[anti] += 2.5
            methods.append(f"anti_streak_{streak_len}→{anti}")

        # ── 4. Frequency window 30 ────────────────────────────
        freq30 = Counter(seq[:30])
        total30 = sum(freq30.values())
        if total30 > 0:
            # Chọn loại ít xuất hiện nhất gần đây (mean-reversion)
            least = min(self.CATEGORIES, key=lambda x: freq30.get(x, 0))
            freq_conf = 1 - (freq30.get(least, 0) / total30)
            votes[least] += freq_conf * 1.5
            methods.append(f"mean_revert→{least}({freq_conf:.0%})")

        # ── 5. Tổng hợp ───────────────────────────────────────
        if not votes:
            # Fallback: chọn theo tần suất lịch sử tổng thể
            freq_all = Counter(seq)
            total_all = len(seq)
            # Chọn loại có xác suất cao nhất
            best = max(self.CATEGORIES, key=lambda x: freq_all.get(x, 0))
            return {
                "prediction":  best,
                "confidence":  round(freq_all.get(best, 0) / total_all * 100, 1),
                "method":      "frequency_overall",
                "streak":      {"category": seq[0], "length": streak_len},
                "distribution": {k: round(v/total_all*100,1) for k,v in Counter(seq).items()},
            }

        total_votes = sum(votes.values())
        best_cat    = votes.most_common(1)[0][0]
        confidence  = round(votes[best_cat] / total_votes * 100, 1)

        # Distribution gần nhất
        freq50  = Counter(seq[:50])
        total50 = sum(freq50.values())
        dist    = {k: round(freq50.get(k,0)/total50*100,1) for k in self.CATEGORIES} if total50 else {}

        # Lấy next_draw từ DB
        next_draw = 0
        try:
            df1 = self.db.get_recent_draws(1)
            if not df1.empty:
                next_draw = int(df1.iloc[0]['draw_number']) + 1
        except:
            pass

        return {
            "prediction":     best_cat,
            "confidence":     confidence,
            "method":         " + ".join(methods) if methods else "ensemble",
            "next_draw":      next_draw,
            "streak":         {"category": seq[0], "length": streak_len},
            "distribution":   dist,
            "votes":          {k: round(v, 2) for k, v in votes.items()},
            "recent_10":      seq[:10],
        }

    def get_stats(self, windows: list = None) -> dict:
        """Thống kê LHN theo nhiều window."""
        if windows is None:
            windows = [20, 50, 100, 500]

        max_n = max(windows)
        seq = self._load_sequence(max_n)

        if not seq:
            return {"error": "no_data"}

        result = {}
        for w in windows:
            sub  = seq[:w]
            freq = Counter(sub)
            total = len(sub)
            result[f"window_{w}"] = {
                k: {"count": freq.get(k, 0),
                    "pct": round(freq.get(k, 0) / total * 100, 1)}
                for k in self.CATEGORIES
            }

        # Streak hiện tại
        streak_len = 1
        for i in range(1, len(seq)):
            if seq[i] == seq[0]:
                streak_len += 1
            else:
                break

        # Lịch sử 20 kỳ gần nhất với draw_number
        recent_20 = []
        try:
            df = self.db.get_recent_draws(20)
            for _, row in df.iterrows():
                recent_20.append({
                    "draw_number": int(row['draw_number']),
                    "numbers":     row['numbers'] if isinstance(row['numbers'], list)
                                   else json.loads(row['numbers']),
                    "category":    _to_lhn(row['numbers']),
                })
        except:
            pass

        result["current_streak"] = {"category": seq[0], "length": streak_len}
        result["recent_20"]      = recent_20

        return result
