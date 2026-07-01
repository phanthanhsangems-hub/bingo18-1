"""Split Conformal Prediction for Bingo18 SIZE categories.

Classic split-conformal (Venn & Papadopoulos 2005, Angelopoulos & Bates 2023):
  calibration nonconformity score: s(x, y) = 1 - f_y(x)
  prediction set at test time:     {y : f_y(x) ≥ 1 - q_hat}
  coverage guarantee:              P(Y ∈ Ĉ(X)) ≥ 1 - α

where f_y(x) = EMA-smoothed normalized vote weight for class y (size_weights_ema
from vote_breakdown), q_hat = ⌈(n+1)(1-α)⌉/n quantile of calibration scores.

With α = 0.20 we target 80% marginal coverage, so the prediction set size
naturally reflects uncertainty: 1 class = confident, 2 = uncertain, 3 = abstain.
HOA is returned in prediction_sets but filtered downstream (P142 still blocks it
from becoming the final prediction — conformal is informational only).
"""
import json
import logging
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

CATEGORIES = ('NHO', 'HOA', 'LON')
_DEFAULT_ALPHA = 0.35          # target miscoverage rate → 65% coverage (more selective sets)
_CALIB_WINDOW = 150            # calibration draws (need ≥ 30 to be meaningful)
_CALIB_CACHE_KEY = 'conformal_quantile'
_MIN_CALIB_DRAWS = 30          # min calibration draws before using conformal


def get_prediction_set(ema_fracs: Dict[str, float], q_hat: float) -> List[str]:
    """Return the set of SIZE categories whose nonconformity score ≤ q_hat.
    Equivalently: include category c if f_c(x) ≥ 1 - q_hat.
    """
    thresh = 1.0 - q_hat
    return [c for c in CATEGORIES if ema_fracs.get(c, 0.0) >= thresh]


def compute_quantile(nonconformity_scores: List[float], alpha: float = _DEFAULT_ALPHA) -> float:
    """Finite-sample corrected quantile: ⌈(n+1)(1-α)⌉/n.
    Equivalent to numpy.quantile(scores, (n+1)(1-α)/n, method='lower').
    """
    n = len(nonconformity_scores)
    if n == 0:
        return 1.0  # fallback: prediction set = all classes
    sorted_scores = sorted(nonconformity_scores)
    # finite-sample corrected level (guarantees ≥ 1-α coverage)
    level = min(1.0, (n + 1) * (1.0 - alpha) / n)
    idx = max(0, int(level * n) - 1)
    return sorted_scores[min(idx, n - 1)]


def compute_calibration_scores(db, limit: int = _CALIB_WINDOW) -> List[float]:
    """Fetch last `limit` evaluated predictions and compute nonconformity scores.

    score = 1 - f_{y_true}(x)   where f_c = size_weights_ema[c] from vote_breakdown.
    Returns list of scores (most recent first, used for the calibration quantile).
    """
    try:
        ph = db._ph()
        if config.DATABASE_URL:
            query = f"""
                SELECT p.vote_breakdown,
                    CASE
                        WHEN (SELECT SUM(v::int) FROM json_array_elements_text(pr.actual_numbers::json) v) <= 9  THEN 'NHO'
                        WHEN (SELECT SUM(v::int) FROM json_array_elements_text(pr.actual_numbers::json) v) <= 11 THEN 'HOA'
                        ELSE 'LON'
                    END AS actual_size
                FROM predictions p
                JOIN prediction_results pr ON pr.prediction_id = p.id
                WHERE p.vote_breakdown IS NOT NULL AND pr.actual_numbers IS NOT NULL
                ORDER BY p.draw_number DESC LIMIT {ph}
            """
        else:
            query = f"""
                SELECT p.vote_breakdown, pr.actual_numbers
                FROM predictions p
                JOIN prediction_results pr ON pr.prediction_id = p.id
                WHERE p.vote_breakdown IS NOT NULL AND pr.actual_numbers IS NOT NULL
                ORDER BY p.draw_number DESC LIMIT {ph}
            """
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute(query, (limit,))
        rows = cur.fetchall()
        conn.close()

        scores = []
        for vb_raw, actual_raw in rows:
            try:
                vb = json.loads(vb_raw) if isinstance(vb_raw, str) else vb_raw
                ema = (vb or {}).get('size_weights_ema', {})
                if not ema:
                    continue
                if config.DATABASE_URL:
                    actual_size = actual_raw
                else:
                    from models import SizePredictor, _parse_numbers
                    nums = json.loads(actual_raw) if isinstance(actual_raw, str) else actual_raw
                    actual_size = SizePredictor._cat(sum(int(x) for x in _parse_numbers(nums)))
                f_true = ema.get(actual_size, 0.0)
                scores.append(1.0 - f_true)
            except Exception:
                continue
        return scores
    except Exception as e:
        logger.debug("conformal calibration error: %s", e)
        return []


# ── Cached quantile (refreshed on same cadence as voter multipliers) ──────────

_conformal_cache: Optional[float] = None
_conformal_ts: int = 0
_CONFORMAL_REFRESH_EVERY = 15  # draws between calibration refreshes


def get_conformal_quantile(db, current_draw: int, alpha: float = _DEFAULT_ALPHA,
                           force: bool = False) -> Optional[float]:
    """Return cached conformal quantile, refreshing every _CONFORMAL_REFRESH_EVERY draws.
    Returns None if not enough calibration data yet.
    """
    global _conformal_cache, _conformal_ts
    if not force and _conformal_cache is not None and (current_draw - _conformal_ts) < _CONFORMAL_REFRESH_EVERY:
        return _conformal_cache

    scores = compute_calibration_scores(db)
    if len(scores) < _MIN_CALIB_DRAWS:
        logger.debug("conformal: only %d calibration draws (need %d)", len(scores), _MIN_CALIB_DRAWS)
        return None

    q = compute_quantile(scores, alpha=alpha)
    _conformal_cache = q
    _conformal_ts = current_draw
    logger.info("ConformalQuantile α=%.2f n=%d q_hat=%.4f (thresh=%.4f, ~%d class avg)",
                alpha, len(scores), q, 1 - q,
                sum(1 for c in CATEGORIES if 0.33 >= 1 - q))
    return q


if __name__ == "__main__":
    import os
    import sys
    import argparse
    from dotenv import load_dotenv
    from database import DatabaseManager

    load_dotenv()

    parser = argparse.ArgumentParser(description="Conformal prediction diagnostics")
    parser.add_argument("--alpha", type=float, default=_DEFAULT_ALPHA, help="Miscoverage rate")
    parser.add_argument("--limit", type=int, default=_CALIB_WINDOW, help="Calibration window")
    args = parser.parse_args()

    db_mgr = DatabaseManager()
    scores = compute_calibration_scores(db_mgr, limit=args.limit)
    if len(scores) < _MIN_CALIB_DRAWS:
        print(f"Not enough calibration data ({len(scores)} draws, need {_MIN_CALIB_DRAWS})")
        sys.exit(1)

    q = compute_quantile(scores, alpha=args.alpha)
    thresh = 1.0 - q

    print(f"\n{'='*55}")
    print(f"SPLIT CONFORMAL PREDICTION  α={args.alpha}  n={len(scores)}")
    print(f"{'='*55}")
    print(f"  q_hat       : {q:.4f}")
    print(f"  f_c ≥ thresh: {thresh:.4f}  (include category if softmax ≥ this)")
    print(f"  Score stats : min={min(scores):.3f}  max={max(scores):.3f}  "
          f"mean={sum(scores)/len(scores):.3f}")
    avg_set_size = sum(
        1 for c in CATEGORIES
        if 0.333 >= thresh  # hypothetical uniform prediction → how many sets of size 3
    )
    print(f"\n  Example prediction sets at threshold {thresh:.3f}:")
    for nho, lon in [(0.5, 0.4), (0.4, 0.45), (0.35, 0.35), (0.6, 0.3)]:
        hoa = round(1.0 - nho - lon, 2)
        fracs = {'NHO': nho, 'HOA': hoa, 'LON': lon}
        ps = get_prediction_set(fracs, q)
        print(f"    NHO={nho:.2f} HOA={hoa:.2f} LON={lon:.2f} → set={ps}")
    print(f"{'='*55}\n")
