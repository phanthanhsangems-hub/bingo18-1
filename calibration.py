"""
calibration.py — Honest confidence calibration for Bingo18 predictions.

Raw model confidence is meaningless (model reports 87%, actual win = 6%).
This module replaces it with historical win probability from real prediction data.

Calibration strategy: weighted rolling win rate
  - 50% weight on last 50 predictions  (most recent, most relevant)
  - 30% weight on last 100 predictions (medium term)
  - 20% weight on all-time             (stable floor)
  Falls back to random baseline (1.79%) if insufficient data.
"""

import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

RANDOM_BASELINE = 0.0179   # fallback only (n<20); is_win is SIZE win, not multiset match
MIN_SAMPLES     = 20       # need at least this many evaluated predictions


class ConfidenceCalibrator:
    """
    Reads actual win rates from prediction_results and produces
    a calibrated P(win) for each model.
    """

    def __init__(self):
        self._rates: Dict[str, Dict[str, float]] = {}
        self._counts: Dict[str, Dict[str, int]]  = {}

    def fit(self, db) -> None:
        """Pull win rates from DB for all models. Call once per prediction cycle."""
        try:
            conn = db.get_connection()
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT p.model_name, pr.is_win
                    FROM predictions p
                    JOIN prediction_results pr ON pr.prediction_id = p.id
                    WHERE pr.actual_numbers IS NOT NULL
                    ORDER BY p.draw_number DESC
                """)
                rows = cur.fetchall()
            finally:
                conn.close()

            from collections import defaultdict
            by_model: Dict[str, list] = defaultdict(list)
            for model_name, is_win in rows:
                by_model[model_name].append(bool(is_win))

            for model_name, wins_list in by_model.items():
                def _wr(lst):
                    return sum(lst) / len(lst) if lst else None

                wr50  = _wr(wins_list[:50])
                wr100 = _wr(wins_list[:100])
                wr_all = _wr(wins_list)

                self._rates[model_name] = {
                    "last_50":  wr50,
                    "last_100": wr100,
                    "all_time": wr_all,
                }
                self._counts[model_name] = {
                    "last_50":  min(len(wins_list), 50),
                    "last_100": min(len(wins_list), 100),
                    "all_time": len(wins_list),
                }

            logger.info("Calibrator fitted: %d models", len(self._rates))

        except Exception as e:
            logger.warning("ConfidenceCalibrator.fit error: %s", e)

    def calibrate(self, model_name: str, raw_confidence: float) -> Tuple[float, dict]:
        """
        Returns (calibrated_probability, metadata_dict).

        calibrated_probability: honest P(win) based on historical data.
        metadata_dict: breakdown for display on dashboard.
        """
        rates  = self._rates.get(model_name, {})
        counts = self._counts.get(model_name, {})

        n_all = counts.get("all_time", 0)

        if n_all < MIN_SAMPLES:
            # Not enough data → return baseline
            return RANDOM_BASELINE, {
                "source":    "baseline",
                "n_samples": n_all,
                "message":   f"Chua du du lieu ({n_all} ky)",
            }

        wr50  = rates.get("last_50")
        wr100 = rates.get("last_100")
        wr_all = rates.get("all_time")

        # Weighted blend: more weight to recent if we have enough data
        if counts.get("last_50", 0) >= MIN_SAMPLES and wr50 is not None:
            calibrated = 0.50 * wr50 + 0.30 * (wr100 or wr_all) + 0.20 * wr_all
            source = "weighted_50_100_all"
        elif counts.get("last_100", 0) >= MIN_SAMPLES and wr100 is not None:
            calibrated = 0.60 * wr100 + 0.40 * wr_all
            source = "weighted_100_all"
        else:
            calibrated = wr_all
            source = "all_time"

        # Clamp to reasonable range [0.05, 0.60]
        # Lower bound: avoid showing 0% confidence; upper bound: SIZE prediction
        # theoretical max is ~60% for a near-perfect predictor (baseline ≈ 37.5%)
        calibrated = max(0.05, min(calibrated, 0.60))

        return calibrated, {
            "source":      source,
            "n_samples":   n_all,
            "win_rate_50":  f"{100*(wr50 or 0):.1f}%",
            "win_rate_100": f"{100*(wr100 or 0):.1f}%",
            "win_rate_all": f"{100*wr_all:.1f}%",
            "raw_model_conf": f"{100*raw_confidence:.1f}%",
        }

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
