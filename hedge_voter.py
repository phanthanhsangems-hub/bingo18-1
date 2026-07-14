"""Hedge (Exponential Weights / Multiplicative Weights) online voter weighting.

Regret bound: E[R_T] ≤ sqrt(T · ln(K) / 2) — Freund & Schapire (1997) —
where K = number of voters, T = rounds. Replaces the ad-hoc WR-multiplier +
EMA-smoother + streak-decay + auto-reset heuristics with a single principled
update rule and one tunable parameter (η).

Update rule (standard Hedge / Exponentiated Gradient):
    log_w[v] -= η · loss(v)     (loss = 1 if wrong, 0 if correct)
⇒  w[v] *= exp(-η)             on each mistake (weights only fall, never grow)

Multipliers are the softmax probabilities re-scaled relative to the uniform
distribution, so uniform → all multipliers = 1.0, good voter → > 1.0, bad → < 1.0.
"""
import json
import logging
import math
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

_HEDGE_CONFIG_KEY = 'hedge_log_weights'
_DEFAULT_ETA = 0.05         # learning rate; 0.05 → slower decay, prevents single-voter dominance
_HEDGE_WARMUP = 20          # minimum draw updates before Hedge takes effect
_HEDGE_MULT_MIN = 0.5       # clamp floor — raised from 0.3 to preserve diversity among active voters
_HEDGE_MULT_MAX = 3.0       # clamp ceiling
_PRUNE_LOG_W_FLOOR = -100.0 # voters below this are unrecoverable; pruned during backfill

_hedge_cache: Optional['HedgeWeights'] = None  # module-level singleton; reset on update


class HedgeWeights:
    """Log-weight vector over voter names with online Hedge updates."""

    def __init__(self, eta: float = _DEFAULT_ETA):
        self.eta = eta
        self.log_weights: Dict[str, float] = {}
        self.n_updates: int = 0

    def update(self, voter_losses: Dict[str, float]) -> None:
        """Apply one round of Hedge update.
        voter_losses = {voter_name: 0.0 (correct) or 1.0 (wrong)}
        """
        for voter, loss in voter_losses.items():
            if loss > 0:
                self.log_weights[voter] = self.log_weights.get(voter, 0.0) - self.eta * loss
        # Voters not seen yet start at 0.0 (uniform) on first appearance
        for voter in voter_losses:
            if voter not in self.log_weights:
                self.log_weights[voter] = 0.0
        self.n_updates += 1

    def get_multipliers(self) -> Dict[str, float]:
        """Softmax of log-weights, re-scaled to multipliers relative to uniform.

        multiplier_v = softmax_v * n   (so uniform → all 1.0)
        Clamped to [_HEDGE_MULT_MIN, _HEDGE_MULT_MAX].
        """
        if not self.log_weights:
            return {}
        n = len(self.log_weights)
        # Numerically stable softmax: subtract max before exp
        max_lw = max(self.log_weights.values())
        raw = {v: math.exp(lw - max_lw) for v, lw in self.log_weights.items()}
        total = sum(raw.values()) or 1.0
        normalized = {v: w / total for v, w in raw.items()}
        return {v: round(max(_HEDGE_MULT_MIN, min(p * n, _HEDGE_MULT_MAX)), 3)
                for v, p in normalized.items()}

    def to_dict(self) -> dict:
        return {'eta': self.eta, 'log_weights': self.log_weights, 'n_updates': self.n_updates}

    @classmethod
    def from_dict(cls, d: dict) -> 'HedgeWeights':
        obj = cls(eta=d.get('eta', _DEFAULT_ETA))
        obj.log_weights = {k: float(v) for k, v in d.get('log_weights', {}).items()}
        obj.n_updates = int(d.get('n_updates', 0))
        return obj


# ── DB persistence (system_config table) ─────────────────────────────────────

def _use_postgres() -> bool:
    return bool(getattr(config, 'DATABASE_URL', None))


def load_hedge_weights(db) -> Optional[HedgeWeights]:
    """Load HedgeWeights from system_config. Returns None if not yet stored.
    Uses module-level singleton cache; invalidated by save_hedge_weights."""
    global _hedge_cache
    if _hedge_cache is not None:
        return _hedge_cache
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        ph = db._ph()
        cur.execute(f"SELECT config_value FROM system_config WHERE config_key = {ph}",
                    (_HEDGE_CONFIG_KEY,))
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            _hedge_cache = HedgeWeights.from_dict(json.loads(row[0]))
            return _hedge_cache
    except Exception as e:
        logger.debug("load_hedge_weights error: %s", e)
    return None


def save_hedge_weights(db, hw: HedgeWeights) -> None:
    """Upsert HedgeWeights into system_config. Updates cache only after successful DB write."""
    global _hedge_cache
    try:
        payload = json.dumps(hw.to_dict())
        conn = db.get_connection()
        cur = conn.cursor()
        ph = db._ph()
        if _use_postgres():
            cur.execute(
                f"INSERT INTO system_config (config_key, config_value) VALUES ({ph},{ph}) "
                f"ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value",
                (_HEDGE_CONFIG_KEY, payload)
            )
        else:
            cur.execute(
                f"INSERT OR REPLACE INTO system_config (config_key, config_value) VALUES ({ph},{ph})",
                (_HEDGE_CONFIG_KEY, payload)
            )
        conn.commit()
        conn.close()
        _hedge_cache = hw  # only update cache after DB write succeeded
        logger.debug("HedgeWeights saved (n_updates=%d)", hw.n_updates)
    except Exception as e:
        logger.warning("save_hedge_weights error: %s", e)


def update_hedge_from_draw(db, vote_breakdown: dict, actual_numbers: List[int]) -> Optional[HedgeWeights]:
    """Compute per-voter losses for one completed draw, update Hedge, persist.

    Called from process_actual_result() once the actual result is known.
    Returns updated HedgeWeights or None on error.
    """
    try:
        from models import SizePredictor
        all_votes: dict = (vote_breakdown or {}).get('all_votes', {})
        if not all_votes:
            return None

        actual_size = SizePredictor._cat(sum(int(x) for x in actual_numbers))
        voter_losses = {v: (0.0 if voted == actual_size else 1.0)
                        for v, voted in all_votes.items()}

        hw = load_hedge_weights(db) or HedgeWeights()
        hw.update(voter_losses)
        save_hedge_weights(db, hw)

        if hw.n_updates % 25 == 0:
            logger.info("HedgeWeights n=%d: %s | losses: %s",
                        hw.n_updates,
                        {k: f"{v:.3f}" for k, v in sorted(hw.log_weights.items())},
                        {k: int(v) for k, v in voter_losses.items()})
        return hw
    except Exception as e:
        logger.warning("update_hedge_from_draw error: %s", e)
        return None


# ── CLI: warm-start from historical vote_breakdown data ──────────────────────

def _backfill(db, limit: int = 5000, eta: float = _DEFAULT_ETA,
              prune_threshold: float = _PRUNE_LOG_W_FLOOR) -> HedgeWeights:
    """Replay historical draws in chronological order to warm-start Hedge weights."""
    from models import SizePredictor, _parse_numbers

    if _use_postgres():
        query = """
            SELECT p.vote_breakdown,
                   (SELECT SUM(v::int) FROM json_array_elements_text(pr.actual_numbers::json) v) AS actual_sum
            FROM predictions p
            JOIN prediction_results pr ON pr.prediction_id = p.id
            WHERE p.vote_breakdown IS NOT NULL AND pr.actual_numbers IS NOT NULL
            ORDER BY p.draw_number ASC LIMIT %s
        """
    else:
        query = """
            SELECT p.vote_breakdown, pr.actual_numbers
            FROM predictions p
            JOIN prediction_results pr ON pr.prediction_id = p.id
            WHERE p.vote_breakdown IS NOT NULL AND pr.actual_numbers IS NOT NULL
            ORDER BY p.draw_number ASC LIMIT ?
        """
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(query, (limit,))
    rows = cur.fetchall()
    conn.close()

    hw = HedgeWeights(eta=eta)
    for vb_raw, actual_raw in rows:
        try:
            vb = json.loads(vb_raw) if isinstance(vb_raw, str) else vb_raw
            all_votes = (vb or {}).get('all_votes', {})
            if not all_votes:
                continue
            if _use_postgres():
                actual_size = SizePredictor._cat(int(actual_raw))
            else:
                nums = json.loads(actual_raw) if isinstance(actual_raw, str) else actual_raw
                actual_size = SizePredictor._cat(sum(int(x) for x in _parse_numbers(nums)))
            voter_losses = {v: (0.0 if voted == actual_size else 1.0)
                            for v, voted in all_votes.items()}
            hw.update(voter_losses)
        except Exception:
            continue

    before = len(hw.log_weights)
    hw.log_weights = {v: lw for v, lw in hw.log_weights.items() if lw >= prune_threshold}
    pruned = before - len(hw.log_weights)
    if pruned:
        print(f"  Pruned {pruned} dead voters (log_w < {prune_threshold})")
    return hw


if __name__ == "__main__":
    import os
    import sys
    import argparse
    from dotenv import load_dotenv
    from database import DatabaseManager

    load_dotenv()

    parser = argparse.ArgumentParser(description="Hedge voter weights tool")
    parser.add_argument("--backfill", action="store_true",
                        help="Warm-start weights from all historical vote_breakdown data and save to DB")
    parser.add_argument("--show", action="store_true",
                        help="Show current weights stored in DB")
    parser.add_argument("--limit", type=int, default=5000, help="Max historical rows for backfill")
    parser.add_argument("--eta", type=float, default=_DEFAULT_ETA, help="Learning rate")
    parser.add_argument("--prune-threshold", type=float, default=_PRUNE_LOG_W_FLOOR,
                        help=f"Prune voters with log_w below this after backfill (default: {_PRUNE_LOG_W_FLOOR})")
    args = parser.parse_args()

    db_mgr = DatabaseManager()

    if args.show:
        hw = load_hedge_weights(db_mgr)
        if hw is None:
            print("No Hedge weights stored yet.")
        else:
            print(f"n_updates : {hw.n_updates}  (η={hw.eta})")
            print(f"Warmup    : {'ACTIVE' if hw.n_updates >= _HEDGE_WARMUP else 'COLD (< %d)' % _HEDGE_WARMUP}")
            mults = hw.get_multipliers()
            print(f"\n{'Voter':<28}  {'log_w':>8}  {'mult':>6}")
            print("-" * 50)
            for v in sorted(hw.log_weights, key=hw.log_weights.get, reverse=True):
                print(f"  {v:<26}  {hw.log_weights[v]:>8.4f}  {mults.get(v, 1.0):>5.3f}x")

    if args.backfill:
        print(f"Backfilling from up to {args.limit} historical draws (η={args.eta})…")
        hw = _backfill(db_mgr, limit=args.limit, eta=args.eta, prune_threshold=args.prune_threshold)
        print(f"Processed {hw.n_updates} draws.")
        mults = hw.get_multipliers()
        print(f"\n{'Voter':<28}  {'log_w':>8}  {'mult':>6}")
        print("-" * 50)
        for v in sorted(hw.log_weights, key=hw.log_weights.get, reverse=True):
            print(f"  {v:<26}  {hw.log_weights[v]:>8.4f}  {mults.get(v, 1.0):>5.3f}x")
        save_hedge_weights(db_mgr, hw)
        print("\nSaved to DB.")
