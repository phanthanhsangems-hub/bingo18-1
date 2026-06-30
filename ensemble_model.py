"""
ensemble_model.py — Voting Ensemble for Bingo18

Combines 5 base models via per-number weighted voting:
  • ColdNumber(w=30)  — current best: ~6.27% win rate
  • FWBR(w=30)        — backtest: ~4.2%
  • FWBR(w=60)        — wider window variant
  • Markov(order=2)   — sequential pattern
  • MLEnsemble        — random forest on features

Voting mechanism:
  For each number 1-6, score = Σ weight_m × confidence_m  (if n in pred_m)
  Pick top 3 numbers by score. Ties broken by number value.

Online learning:
  update_weights_from_db() pulls last-N win rates per model from DB,
  renormalizes weights so better models get more vote mass.

Win condition (Bingo18): predicted SIZE category (NHO/HOA/LON) matches actual SIZE
Baseline P(win) ≈ 37.5% — same definition as prediction_results.is_win_size in production.
"""

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import pandas as pd

from models import (
    ColdNumberModel, FWBRModel, MarkovModel, MLEnsembleModel, SizePredictor,
    _parse_numbers, _random_predict, NUMBERS, DRAW_SIZE,
)

logger = logging.getLogger(__name__)


class VotingEnsemble:
    """
    Number-level voting ensemble.
    All base models vote; votes are weighted by model weight × prediction confidence.
    """

    name = "voting_ensemble"

    # Initial weights reflecting known backtest performance.
    # Will be overwritten by update_weights_from_db() once DB data accumulates.
    _DEFAULT_WEIGHTS: Dict[str, float] = {
        "cold_number_window_30": 0.40,
        "fwbr_w30":              0.30,
        "fwbr_w60":              0.15,
        "markov_order_2":        0.10,
        "ml_ensemble":           0.05,
    }

    def __init__(self):
        self.cold30 = ColdNumberModel(window_size=30)
        self.fwbr30 = FWBRModel(window_size=30, recency_weight=0.5)
        self.fwbr60 = FWBRModel(window_size=60, recency_weight=0.5)
        self.markov = MarkovModel(order=2)
        self.ml     = MLEnsembleModel()

        self.weights: Dict[str, float] = dict(self._DEFAULT_WEIGHTS)

        self._base: Dict[str, object] = {
            "cold_number_window_30": self.cold30,
            "fwbr_w30":             self.fwbr30,
            "fwbr_w60":             self.fwbr60,
            "markov_order_2":       self.markov,
            "ml_ensemble":          self.ml,
        }

    # ── Training ──────────────────────────────────────────────────────

    def train(self, df: pd.DataFrame):
        self.cold30.train(df)
        self.markov.train(df)
        if len(df) >= 50:
            self.ml.train(df)
        # FWBR is stateless

    # ── Weight update from DB win rates ───────────────────────────────

    def update_weights_from_db(self, db, window: int = 200):
        """
        Pull recent win rates for each base model from prediction_results.
        Models with higher win rate get proportionally more vote mass.
        Falls back to default weights if data is insufficient.
        """
        raw: Dict[str, float] = {}
        for name in self._base:
            try:
                wr = db.get_model_win_rate(name, window)
                if wr and wr > 0:
                    raw[name] = wr
            except Exception as e:
                logger.debug("update_weights_from_db: %s → %s", name, e)

        if len(raw) < 2:
            logger.debug("VotingEnsemble: insufficient DB data, keeping default weights")
            return

        # Merge: models with DB data use win rate; others keep default weight
        merged = dict(self._DEFAULT_WEIGHTS)
        merged.update(raw)

        # Normalize so weights sum to 1.0
        total = sum(merged.values())
        if total > 0:
            self.weights = {k: v / total for k, v in merged.items()}

        logger.info("VotingEnsemble weights updated: %s",
                    {k: f"{v:.3f}" for k, v in self.weights.items()})

    # ── Prediction ────────────────────────────────────────────────────

    def predict(
        self,
        df_or_draws,
        next_draw: int = None,
    ) -> List[Tuple[List[int], float]]:

        if isinstance(df_or_draws, pd.DataFrame):
            df    = df_or_draws.sort_values("draw_number", ascending=False)
            draws = [_parse_numbers(r)
                     for r in reversed(df.head(100)["numbers"].tolist())]
        else:
            draws = [
                d if isinstance(d, list) else _parse_numbers(d)
                for d in df_or_draws
            ]

        num_scores: Dict[int, float] = defaultdict(float)
        model_debug: Dict[str, dict] = {}

        for model_name, model in self._base.items():
            weight = self.weights.get(model_name, 0.0)
            if weight < 1e-9:
                continue
            try:
                if isinstance(df_or_draws, pd.DataFrame) and hasattr(model, "markov_model"):
                    preds = model.predict(df_or_draws, next_draw)
                else:
                    preds = model.predict(draws, next_draw)

                if preds:
                    nums, conf = preds[0]
                    vote = weight * max(conf, 0.1)
                    for n in nums:
                        num_scores[n] += vote
                    model_debug[model_name] = {"nums": nums, "conf": round(conf, 3), "weight": round(weight, 3)}

            except Exception as e:
                logger.warning("VotingEnsemble: %s error: %s", model_name, e)

        if not num_scores:
            return [_random_predict()]

        ranked     = sorted(num_scores, key=lambda x: num_scores[x], reverse=True)
        top3       = sorted(ranked[:DRAW_SIZE])
        total_score = sum(num_scores.values())
        conf        = sum(num_scores[n] for n in top3) / total_score if total_score > 0 else 0.30
        conf        = min(conf, 0.95)

        logger.debug("VotingEnsemble: scores=%s → %s (conf=%.3f) [%s]",
                     dict(num_scores), top3, conf, model_debug)

        return [(top3, conf)]


# ── Backtest ──────────────────────────────────────────────────────────────────

def _win(predicted: List[int], actual: List[int]) -> bool:
    """Bingo18 win: predicted SIZE category == actual SIZE category.
    Matches the production definition (database.py: is_win = is_win_size),
    not a raw number-overlap match."""
    return SizePredictor._cat(sum(int(x) for x in predicted)) == SizePredictor._cat(sum(int(x) for x in actual))


def quick_backtest(
    draws: List[dict],
    test_window: int = 500,
    verbose: bool = True,
) -> dict:
    """
    Walk-forward backtest comparing VotingEnsemble against all base models.

    draws: list of dicts with keys 'draw_number', 'numbers'
           sorted ascending by draw_number.
    """
    split      = max(0, len(draws) - test_window)
    train_data = draws[:split]
    test_data  = draws[split:]
    n          = len(test_data)

    if n < 10 or split < 30:
        print(f"Not enough data (train={split}, test={n})")
        return {}

    ensemble = VotingEnsemble()

    # Build a minimal DataFrame for models that need it
    def _to_df(draw_list):
        import pandas as pd
        return pd.DataFrame([
            {"draw_number": d["draw_number"], "numbers": d["numbers"]}
            for d in draw_list
        ])

    train_df = _to_df(train_data)
    ensemble.train(train_df)

    # Per-model win trackers
    model_names = list(ensemble._base.keys()) + ["voting_ensemble"]
    wins = {m: 0 for m in model_names}

    for i, draw in enumerate(test_data):
        context_draws = train_data + test_data[:i]
        if len(context_draws) < 10:
            continue

        context_df = _to_df(context_draws)
        actual     = _parse_numbers(draw["numbers"])

        # Base models
        for model_name, model in ensemble._base.items():
            try:
                preds = model.predict(list(reversed(context_df.head(100)["numbers"].tolist())), draw["draw_number"])
                if preds and _win([int(x) for x in preds[0][0]], actual):
                    wins[model_name] += 1
            except Exception:
                pass

        # Ensemble
        try:
            preds = ensemble.predict(context_df, draw["draw_number"])
            if preds and _win(preds[0][0], actual):
                wins["voting_ensemble"] += 1
        except Exception:
            pass

    baseline = 37.5
    results  = {}

    if verbose:
        print(f"\n{'='*60}")
        print(f"BINGO18 ENSEMBLE BACKTEST  train={split}  test={n}")
        print(f"{'='*60}")
        print(f"{'Model':<30}  {'Win%':>6}  {'vs Baseline':>12}  {'Signal'}")
        print(f"{'-'*60}")

    for m in model_names:
        wr    = wins[m] / n * 100 if n > 0 else 0
        delta = wr - baseline
        signal = "[SIGNAL]" if delta > 1.5 else "-"
        results[m] = {"win_rate": round(wr, 2), "delta": round(delta, 2)}
        if verbose:
            marker = " <<<" if m == "voting_ensemble" else ""
            print(f"  {m:<28}  {wr:>5.2f}%  {delta:>+10.2f}pp  {signal}{marker}")

    if verbose:
        print(f"\n  Baseline (random): {baseline}%")
        ens_wr = results["voting_ensemble"]["win_rate"]
        best_base = max(
            (m for m in model_names if m != "voting_ensemble"),
            key=lambda m: results[m]["win_rate"]
        )
        print(f"  Best base model  : {best_base} ({results[best_base]['win_rate']:.2f}%)")
        print(f"  Ensemble         : {ens_wr:.2f}%")
        diff = ens_wr - results[best_base]["win_rate"]
        print(f"  Improvement      : {diff:+.2f}pp vs best base")
        print(f"{'='*60}\n")

    return results


if __name__ == "__main__":
    import os
    import sys
    import argparse
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=int, default=500, help="Test window size")
    args = parser.parse_args()

    try:
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        cur  = conn.cursor()
        cur.execute("SELECT draw_number, numbers FROM draw_history ORDER BY draw_number ASC")
        rows = [{"draw_number": r[0], "numbers": r[1]} for r in cur.fetchall()]
        conn.close()
    except Exception as e:
        print(f"DB error: {e}")
        sys.exit(1)

    print(f"Total draws: {len(rows)}")
    if len(rows) < 50:
        print("Not enough data")
        sys.exit(1)

    quick_backtest(rows, test_window=args.window)
