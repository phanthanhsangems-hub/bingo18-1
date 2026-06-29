"""
combo_filter.py — Bộ lọc tổ hợp 2 số & 3 số cho Bingo18
=========================================================
Phân tích lịch sử để tìm:
  • TOP cặp 2 số (pair) xuất hiện nhiều nhất (có thể trùng, vd: 3-3, 5-5)
  • TOP bộ 3 số (triple) xuất hiện nhiều nhất (có thể trùng, vd: 3-3-5)

Dùng để đưa ra dự đoán tổ hợp cho kỳ tiếp theo.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from itertools import combinations_with_replacement
from typing import List, Tuple, Dict

logger = logging.getLogger(__name__)

# Bingo18: mỗi kỳ rút 3 số từ 1-6, số CÓ THỂ trùng nhau
NUMBERS_RANGE = range(1, 7)   # 1..6
DRAW_SIZE     = 3


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _parse_numbers(val) -> List[int]:
    """Parse numbers từ DB (có thể là list hoặc JSON string)."""
    if isinstance(val, list):
        return [int(x) for x in val]
    if isinstance(val, str):
        return [int(x) for x in json.loads(val)]
    return list(val)


def _extract_pairs(numbers: List[int]) -> List[Tuple[int, int]]:
    """Lấy tất cả cặp 2 số (có thứ tự chuẩn, cho phép trùng) từ 1 kỳ."""
    s = sorted(numbers)
    # combinations_with_replacement để bao gồm cả (x, x)
    # nhưng ở đây ta dùng cách đơn giản hơn: lấy tất cả cặp (i, j) với i<=j
    pairs = []
    for i in range(len(s)):
        for j in range(i, len(s)):
            pairs.append((s[i], s[j]))
    return pairs


def _extract_triple(numbers: List[int]) -> Tuple[int, int, int]:
    """Chuẩn hóa bộ 3 số thành tuple tăng dần."""
    s = sorted(numbers)
    return (s[0], s[1], s[2])


# ──────────────────────────────────────────────────────────────
# Phân tích tần suất tổ hợp
# ──────────────────────────────────────────────────────────────

def analyze_combos(
    draws: List[List[int]],
    window: int = 200
) -> Dict:
    """
    Phân tích lịch sử kỳ quay để đếm tần suất các tổ hợp.

    Args:
        draws: List các kỳ gần nhất, mỗi kỳ là list 3 số.
        window: Số kỳ gần nhất cần xét (mặc định 200).

    Returns:
        dict chứa:
            pair_counts  — Counter của cặp 2 số
            triple_counts — Counter của bộ 3 số
            total_draws  — tổng số kỳ phân tích
    """
    recent = draws[-window:] if len(draws) > window else draws
    total  = len(recent)

    pair_counts   = Counter()
    triple_counts = Counter()

    for nums in recent:
        nums_parsed = _parse_numbers(nums)
        for p in _extract_pairs(nums_parsed):
            pair_counts[p] += 1
        triple_counts[_extract_triple(nums_parsed)] += 1

    return {
        "pair_counts":   pair_counts,
        "triple_counts": triple_counts,
        "total_draws":   total,
    }


# ──────────────────────────────────────────────────────────────
# Dự đoán tổ hợp cho kỳ tiếp theo
# ──────────────────────────────────────────────────────────────

def predict_combos(
    draws: List[List[int]],
    top_n_pairs: int   = 10,
    top_n_triples: int = 10,
    window: int        = 200,
    recent_boost: int  = 30,   # kỳ gần nhất được tính thêm
) -> Dict:
    """
    Dự đoán TOP tổ hợp 2 số và 3 số cho kỳ tiếp theo.

    Thuật toán:
      1. Đếm tần suất toàn bộ window kỳ gần nhất (trọng số 1×)
      2. Đếm thêm tần suất recent_boost kỳ gần nhất (trọng số thêm 1× → tổng 2×)
      3. Kết hợp để số mới xuất hiện nhiều gần đây được ưu tiên hơn
      4. Tính confidence = freq_normalized (0..1)

    Args:
        draws: List các kỳ lịch sử (mới nhất ở cuối).
        top_n_pairs: Số cặp 2 số trả về.
        top_n_triples: Số bộ 3 số trả về.
        window: Cửa sổ phân tích dài hạn.
        recent_boost: Cửa sổ gần nhất để boost trọng số.

    Returns:
        dict với keys:
            top_pairs   — list of {combo, count, confidence, label}
            top_triples — list of {combo, count, confidence, label}
            stats       — thống kê tổng quát
    """
    if not draws:
        logger.warning("combo_filter: không có dữ liệu lịch sử")
        return {"top_pairs": [], "top_triples": [], "stats": {}}

    # ── Đếm tần suất dài hạn ──
    long  = analyze_combos(draws, window=window)
    # ── Đếm tần suất gần nhất (boost) ──
    short = analyze_combos(draws, window=recent_boost)

    # ── Kết hợp với trọng số: long × 1 + short × 1 ──
    pair_score   = Counter()
    triple_score = Counter()

    for combo, cnt in long["pair_counts"].items():
        pair_score[combo] += cnt
    for combo, cnt in short["pair_counts"].items():
        pair_score[combo] += cnt  # +1× bonus gần đây

    for combo, cnt in long["triple_counts"].items():
        triple_score[combo] += cnt
    for combo, cnt in short["triple_counts"].items():
        triple_score[combo] += cnt

    # ── Tổng max để normalize ──
    max_pair   = max(pair_score.values(),   default=1)
    max_triple = max(triple_score.values(), default=1)

    # ── TOP pairs ──
    top_pairs = []
    for combo, score in pair_score.most_common(top_n_pairs):
        freq_long  = long["pair_counts"].get(combo, 0)
        confidence = round(score / (max_pair * 1.0), 4)
        top_pairs.append({
            "combo":      list(combo),
            "label":      f"{combo[0]}-{combo[1]}",
            "score":      score,
            "freq_long":  freq_long,
            "confidence": min(confidence, 1.0),
        })

    # ── TOP triples ──
    top_triples = []
    for combo, score in triple_score.most_common(top_n_triples):
        freq_long  = long["triple_counts"].get(combo, 0)
        confidence = round(score / (max_triple * 1.0), 4)
        top_triples.append({
            "combo":      list(combo),
            "label":      f"{combo[0]}-{combo[1]}-{combo[2]}",
            "score":      score,
            "freq_long":  freq_long,
            "confidence": min(confidence, 1.0),
        })

    # ── Stats tổng quát ──
    total_pair_types   = len(pair_score)
    total_triple_types = len(triple_score)
    possible_pairs     = len(list(combinations_with_replacement(NUMBERS_RANGE, 2)))  # 21
    possible_triples   = len(list(combinations_with_replacement(NUMBERS_RANGE, 3)))  # 56

    stats = {
        "analyzed_draws":       long["total_draws"],
        "boost_draws":          short["total_draws"],
        "unique_pairs_seen":    total_pair_types,
        "unique_triples_seen":  total_triple_types,
        "possible_pairs":       possible_pairs,
        "possible_triples":     possible_triples,
        "pair_coverage_pct":    round(total_pair_types / possible_pairs * 100, 1),
        "triple_coverage_pct":  round(total_triple_types / possible_triples * 100, 1),
    }

    logger.info(
        "combo_filter: analyzed %d draws | top_pair=%s (%.0f%%) | top_triple=%s (%.0f%%)",
        long["total_draws"],
        top_pairs[0]["label"] if top_pairs else "N/A",
        top_pairs[0]["confidence"] * 100 if top_pairs else 0,
        top_triples[0]["label"] if top_triples else "N/A",
        top_triples[0]["confidence"] * 100 if top_triples else 0,
    )

    return {
        "top_pairs":   top_pairs,
        "top_triples": top_triples,
        "stats":       stats,
    }


# ──────────────────────────────────────────────────────────────
# Hàm tiện ích: dự đoán cho kỳ tiếp (từ DatabaseManager)
# ──────────────────────────────────────────────────────────────

def run_combo_prediction(db, window: int = 200, top_n: int = 10) -> Dict:
    """
    Lấy lịch sử từ DB và trả về dự đoán tổ hợp 2 số & 3 số.

    Args:
        db: DatabaseManager instance
        window: Số kỳ gần nhất để phân tích
        top_n: Số kết quả trả về mỗi loại

    Returns:
        dict kết quả dự đoán
    """
    try:
        df = db.get_recent_draws(window)
        if df.empty or len(df) < 10:
            return {"error": "Không đủ dữ liệu lịch sử (cần ít nhất 10 kỳ)"}

        draws = [row["numbers"] for _, row in df.iterrows()]

        # Lấy kỳ tiếp theo
        import sqlite3 as _sqlite3
        conn = db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT MAX(draw_number) FROM draw_history")
            last_draw = cur.fetchone()[0] or 0
        finally:
            conn.close()

        next_draw = last_draw + 1
        result    = predict_combos(draws, top_n_pairs=top_n, top_n_triples=top_n, window=window)

        return {
            "next_draw":   next_draw,
            "top_pairs":   result["top_pairs"],
            "top_triples": result["top_triples"],
            "stats":       result["stats"],
            "mode":        "combo_filter",
        }

    except Exception as e:
        logger.error("run_combo_prediction error: %s", e)
        return {"error": str(e)}
