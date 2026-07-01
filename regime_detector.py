"""Bayesian Online Changepoint Detection (BOCPD) for the Bingo18 SIZE sequence.

Adams & MacKay (2007), adapted from Gaussian to categorical (Dirichlet-multinomial)
observations over {NHO, HOA, LON}. Maintains a run-length posterior so it can tell
genuine SIZE-bias drift apart from ordinary noise streaks.

P23 found the underlying game is essentially memoryless (max transition signal
~1.4% above base rate), so the hazard rate here is deliberately conservative
(long expected run length ≈120 draws) — the detector should mostly say "no
regime change, stick near base rate" and only react when evidence is strong,
unlike the old fixed-window hot-adjust heuristic that overreacted to short streaks.
"""
from typing import Dict, List, Optional

from models import SizePredictor

CATEGORIES = ('NHO', 'HOA', 'LON')
BASE_RATE = {'NHO': 0.375, 'HOA': 0.25, 'LON': 0.375}

_MAX_RUN_LENGTH = 150  # truncate negligible-mass tail to keep run() ~O(window)


class SizeRegimeDetector:
    def __init__(self, hazard: float = 1 / 120, prior_strength: float = 8.0,
                 base_rate: Optional[Dict[str, float]] = None):
        self.hazard = hazard
        self.base_rate = base_rate or BASE_RATE
        self._prior_counts = {c: self.base_rate[c] * prior_strength for c in CATEGORIES}

    @staticmethod
    def _pred_prob(counts: Dict[str, float], obs: str) -> float:
        total = sum(counts.values())
        return counts[obs] / total if total else 1.0 / len(CATEGORIES)

    def run(self, sequence: List[str]) -> Dict[str, float]:
        """sequence: chronological (oldest→newest) SIZE labels.
        Returns the predictive distribution over CATEGORIES for the next draw."""
        if not sequence:
            return dict(self.base_rate)

        run_probs: List[float] = [1.0]
        run_counts: List[Dict[str, float]] = [dict(self._prior_counts)]

        for obs in sequence:
            if obs not in CATEGORIES:
                continue
            n_r = len(run_probs)
            pred = [self._pred_prob(run_counts[r], obs) for r in range(n_r)]

            growth = [run_probs[r] * pred[r] * (1 - self.hazard) for r in range(n_r)]
            cp_mass = sum(run_probs[r] * pred[r] * self.hazard for r in range(n_r))

            new_run_probs = [cp_mass] + growth
            new_run_counts = [dict(self._prior_counts)]
            for r in range(n_r):
                updated = dict(run_counts[r])
                updated[obs] = updated.get(obs, 0.0) + 1.0
                new_run_counts.append(updated)

            total = sum(new_run_probs) or 1.0
            run_probs = [p / total for p in new_run_probs]
            run_counts = new_run_counts

            if len(run_probs) > _MAX_RUN_LENGTH:
                tail_mass = sum(run_probs[_MAX_RUN_LENGTH:])
                run_probs = run_probs[:_MAX_RUN_LENGTH]
                run_probs[-1] += tail_mass
                run_counts = run_counts[:_MAX_RUN_LENGTH]

        dist = {c: 0.0 for c in CATEGORIES}
        for r, p in enumerate(run_probs):
            if p <= 0:
                continue
            counts = run_counts[r]
            total = sum(counts.values()) or 1.0
            for c in CATEGORIES:
                dist[c] += p * (counts[c] / total)

        s = sum(dist.values()) or 1.0
        return {c: dist[c] / s for c in CATEGORIES}


# ── Backtest ──────────────────────────────────────────────────────────────────

def _win(predicted_size: str, actual: List[int]) -> bool:
    return predicted_size == SizePredictor._cat(sum(int(x) for x in actual))


def quick_backtest(draws: List[dict], test_window: int = 1000, verbose: bool = True,
                    hazard: float = 1 / 120) -> dict:
    """Walk-forward backtest of SizeRegimeDetector vs random baseline.

    draws: list of dicts with keys 'draw_number', 'numbers', sorted ascending
           by draw_number.
    """
    from models import _parse_numbers

    n = len(draws)
    split = max(0, n - test_window)
    if n - split < 10 or split < 30:
        print(f"Not enough data (train={split}, test={n - split})")
        return {}

    history = [
        SizePredictor._cat(sum(int(x) for x in _parse_numbers(d['numbers'])))
        for d in draws[:split]
    ]
    wins = 0
    total = 0
    detector = SizeRegimeDetector(hazard=hazard)

    for d in draws[split:]:
        actual = _parse_numbers(d['numbers'])
        dist = detector.run(history)
        winner = max(dist, key=dist.get)
        if winner != 'HOA' and _win(winner, actual):
            wins += 1
        if winner != 'HOA':
            total += 1
        history.append(SizePredictor._cat(sum(int(x) for x in actual)))

    baseline = 37.5
    wr = wins / total * 100 if total else 0.0
    delta = wr - baseline
    if verbose:
        print(f"\n{'='*60}")
        print(f"REGIME DETECTOR (BOCPD) BACKTEST  train={split}  test={n - split}  hazard={hazard:.5f}")
        print(f"{'='*60}")
        print(f"  Predictions made : {total} (HOA skipped — blocked downstream by P142)")
        print(f"  Win rate         : {wr:.2f}%")
        print(f"  vs Baseline      : {delta:+.2f}pp  ({'SIGNAL' if delta > 1.5 else '-'})")
        print(f"{'='*60}\n")

    return {'win_rate': round(wr, 2), 'delta': round(delta, 2), 'n': total}


if __name__ == "__main__":
    import os
    import sys
    import argparse
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=int, default=1000, help="Test window size")
    parser.add_argument("--hazard", type=float, default=1 / 120, help="Hazard rate (1/expected run length)")
    args = parser.parse_args()

    try:
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        cur = conn.cursor()
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

    quick_backtest(rows, test_window=args.window, hazard=args.hazard)
