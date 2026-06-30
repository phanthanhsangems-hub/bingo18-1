"""
calibration.py — Honest confidence calibration for Bingo18 predictions.

Raw model confidence is meaningless (model reports 87%, actual win = 6%).
This module replaces it with historical win probability from real prediction data.

Calibration strategy:
  1. Primary: bucket by vote_share (ensemble consensus strength) and use the
     actual historical win rate of past predictions that fell in the same
     bucket. This is the axis that actually varies between predictions —
     nearly every prediction shares model_name='majority_vote', so per-model
     calibration alone collapses to a single global number regardless of how
     confident/split the vote was.
  2. Fallback: per-model_name weighted rolling win rate (kept for the rare
     non-majority-vote path, e.g. best_name='hybrid_model', and for buckets
     without enough samples yet).
  3. Final fallback: SIZE-win baseline (~37.5%) if neither has enough data.

Weighted rolling win rate (used at both levels):
  - 50% weight on last 50 predictions  (most recent, most relevant)
  - 30% weight on last 100 predictions (medium term)
  - 20% weight on all-time             (stable floor)
"""

import json
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# is_win (see database.py) = is_win_size: predicted SIZE category == actual SIZE.
# NHO/LON baseline ≈37.5% each, HOA ≈25% — 0.375 is the honest "no-signal" floor
# for NHO/LON predictions, used as the fallback when there isn't enough history yet.
SIZE_WIN_BASELINE = 0.375
MIN_SAMPLES        = 20     # need at least this many evaluated predictions to trust a rate

# Consensus-strength buckets over vote_share (0-1: weighted share of the winning SIZE)
VOTE_SHARE_BUCKETS = [
    (0.00, 0.40, "weak"),
    (0.40, 0.50, "low"),
    (0.50, 0.60, "moderate"),
    (0.60, 0.70, "strong"),
    (0.70, 1.01, "dominant"),
]

# A prediction is "confident" when its calibrated P(win) clears the existing
# dashboard/Telegram tier threshold (telegram_bot._conf_tier's "✅" tier).
CONFIDENT_THRESHOLD = 0.44


def _bucket_for(vote_share: float) -> str:
    for lo, hi, label in VOTE_SHARE_BUCKETS:
        if lo <= vote_share < hi:
            return label
    return VOTE_SHARE_BUCKETS[-1][2]


class ConfidenceCalibrator:
    """
    Reads actual win rates from prediction_results and produces
    a calibrated P(win) for each model and for each vote_share bucket.
    """

    def __init__(self):
        self._rates: Dict[str, Dict[str, float]] = {}
        self._counts: Dict[str, Dict[str, int]]  = {}
        self._vs_rates: Dict[str, Dict[str, float]] = {}
        self._vs_counts: Dict[str, Dict[str, int]]  = {}

    def fit(self, db) -> None:
        """Pull win rates from DB for all models + vote_share buckets. Call once per prediction cycle."""
        try:
            conn = db.get_connection()
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT p.model_name, p.vote_breakdown, pr.is_win
                    FROM predictions p
                    JOIN prediction_results pr ON pr.prediction_id = p.id
                    WHERE pr.actual_numbers IS NOT NULL
                    ORDER BY p.draw_number DESC
                """)
                rows = cur.fetchall()
            finally:
                conn.close()

            from collections import defaultdict
            by_model:  Dict[str, list] = defaultdict(list)
            by_bucket: Dict[str, list] = defaultdict(list)
            for model_name, vb_raw, is_win in rows:
                by_model[model_name].append(bool(is_win))
                try:
                    vb = json.loads(vb_raw) if isinstance(vb_raw, str) else (vb_raw or {})
                    vote_share = vb.get('vote_share')
                except Exception:
                    vote_share = None
                if vote_share is not None:
                    by_bucket[_bucket_for(float(vote_share))].append(bool(is_win))

            def _wr(lst):
                return sum(lst) / len(lst) if lst else None

            for model_name, wins_list in by_model.items():
                self._rates[model_name] = {
                    "last_50":  _wr(wins_list[:50]),
                    "last_100": _wr(wins_list[:100]),
                    "all_time": _wr(wins_list),
                }
                self._counts[model_name] = {
                    "last_50":  min(len(wins_list), 50),
                    "last_100": min(len(wins_list), 100),
                    "all_time": len(wins_list),
                }

            for bucket, wins_list in by_bucket.items():
                self._vs_rates[bucket] = {
                    "last_50":  _wr(wins_list[:50]),
                    "last_100": _wr(wins_list[:100]),
                    "all_time": _wr(wins_list),
                }
                self._vs_counts[bucket] = {
                    "last_50":  min(len(wins_list), 50),
                    "last_100": min(len(wins_list), 100),
                    "all_time": len(wins_list),
                }

            logger.info("Calibrator fitted: %d models, %d vote_share buckets",
                        len(self._rates), len(self._vs_rates))

        except Exception as e:
            logger.warning("ConfidenceCalibrator.fit error: %s", e)

    @staticmethod
    def _blend(rates: dict, counts: dict) -> Tuple[Optional[float], str]:
        """Weighted blend of last_50/last_100/all_time. Returns (None, 'insufficient') if too few samples."""
        n_all = counts.get("all_time", 0)
        if n_all < MIN_SAMPLES:
            return None, "insufficient"

        wr50, wr100, wr_all = rates.get("last_50"), rates.get("last_100"), rates.get("all_time")
        if counts.get("last_50", 0) >= MIN_SAMPLES and wr50 is not None:
            return 0.50 * wr50 + 0.30 * (wr100 or wr_all) + 0.20 * wr_all, "weighted_50_100_all"
        if counts.get("last_100", 0) >= MIN_SAMPLES and wr100 is not None:
            return 0.60 * wr100 + 0.40 * wr_all, "weighted_100_all"
        return wr_all, "all_time"

    def calibrate(self, model_name: str, raw_confidence: float) -> Tuple[float, dict]:
        """
        Per-model_name calibration (legacy path; used directly by non-majority-vote
        fallback predictions, and as the fallback inside calibrate_by_vote_share()).

        Returns (calibrated_probability, metadata_dict).
        """
        rates  = self._rates.get(model_name, {})
        counts = self._counts.get(model_name, {})
        n_all  = counts.get("all_time", 0)

        calibrated, source = self._blend(rates, counts)
        if calibrated is None:
            return SIZE_WIN_BASELINE, {
                "source":       "baseline",
                "n_samples":    n_all,
                "message":      f"Chua du du lieu ({n_all} ky)",
                "is_confident": False,
            }

        # Clamp to reasonable range [0.05, 0.60]
        # Lower bound: avoid showing 0% confidence; upper bound: SIZE prediction
        # theoretical max is ~60% for a near-perfect predictor (baseline ≈ 37.5%)
        calibrated = max(0.05, min(calibrated, 0.60))

        return calibrated, {
            "source":         source,
            "n_samples":      n_all,
            "win_rate_50":    f"{100*(rates.get('last_50') or 0):.1f}%",
            "win_rate_100":   f"{100*(rates.get('last_100') or 0):.1f}%",
            "win_rate_all":   f"{100*(rates.get('all_time') or 0):.1f}%",
            "raw_model_conf": f"{100*raw_confidence:.1f}%",
            "is_confident":   calibrated >= CONFIDENT_THRESHOLD,
        }

    def calibrate_by_vote_share(self, vote_share: float, model_name: str,
                                 raw_confidence: float) -> Tuple[float, dict]:
        """
        Primary calibration path: honest P(win) bucketed by consensus strength
        (vote_share). Falls back to per-model calibration when the bucket
        doesn't have enough evaluated samples yet.

        Returns (calibrated_probability, metadata_dict) — metadata always
        includes 'is_confident', a bool the caller can surface as an
        abstain/low-confidence signal without skipping the prediction.
        """
        bucket = _bucket_for(vote_share)
        rates  = self._vs_rates.get(bucket, {})
        counts = self._vs_counts.get(bucket, {})

        calibrated, source = self._blend(rates, counts)
        if calibrated is None:
            calibrated_fb, meta_fb = self.calibrate(model_name, raw_confidence)
            meta_fb["vote_share_bucket"] = bucket
            meta_fb["bucket_source"]     = "fallback_model"
            return calibrated_fb, meta_fb

        calibrated = max(0.05, min(calibrated, 0.60))
        meta = {
            "source":            f"vote_share_{source}",
            "vote_share_bucket": bucket,
            "bucket_source":     "vote_share",
            "n_samples":         counts.get("all_time", 0),
            "win_rate_50":       f"{100*(rates.get('last_50') or 0):.1f}%",
            "win_rate_100":      f"{100*(rates.get('last_100') or 0):.1f}%",
            "win_rate_all":      f"{100*(rates.get('all_time') or 0):.1f}%",
            "raw_model_conf":    f"{100*raw_confidence:.1f}%",
            "is_confident":      calibrated >= CONFIDENT_THRESHOLD,
        }
        return calibrated, meta

    def get_display_stats(self, model_name: str) -> dict:
        """Returns human-readable stats for dashboard."""
        counts = self._counts.get(model_name, {})
        rates  = self._rates.get(model_name, {})
        n      = counts.get("all_time", 0)
        wr     = rates.get("all_time")
        wr50   = rates.get("last_50")

        return {
            "total_predictions": n,
            "win_rate_all":    f"{100*wr:.1f}%" if wr else "N/A",
            "win_rate_recent": f"{100*wr50:.1f}%" if wr50 else "N/A",
            "wins_all":        int(round(n * wr)) if wr else 0,
        }


# ── Module-level singleton ────────────────────────────────────
_calibrator: Optional[ConfidenceCalibrator] = None

def get_calibrator(db) -> ConfidenceCalibrator:
    """Lazy singleton — fits once per process start."""
    global _calibrator
    if _calibrator is None:
        _calibrator = ConfidenceCalibrator()
        _calibrator.fit(db)
    return _calibrator

def invalidate_calibrator():
    """Call after new prediction results are saved."""
    global _calibrator
    _calibrator = None
