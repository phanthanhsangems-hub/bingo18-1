#!/usr/bin/env python3
"""
bias_analysis.py — Statistical bias detection for Bingo18 draws.

Tests:
  1. Digit frequency         — chi-squared across all positions
  2. Position bias           — digit distribution per position (1/2/3)
  3. Sum distribution        — actual vs theoretical (sums 3-18)
  4. Size distribution       — NHO/HOA/LON vs theoretical
  5. Markov transitions      — size → size serial correlation
  6. ACF on sum series       — autocorrelation at lag 1-20
  7. Time-of-day             — size distribution by VN hour
  8. Within-draw repeat rate — unique / one-pair / triple vs theoretical

Usage:
  python bias_analysis.py
  python bias_analysis.py --limit 10000   # last N draws only
  python bias_analysis.py --acf-lags 30
"""

import os, sys, math, json, argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

import numpy as np
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from database import DatabaseManager

VN_TZ   = timezone(timedelta(hours=7))
SIZES   = ['NHO', 'HOA', 'LON']
THEO_SZ = {'NHO': 81/216, 'HOA': 48/216, 'LON': 87/216}


# ── Statistical helpers ───────────────────────────────────────────────────────

def chi2_pvalue(stat: float, df: int) -> float:
    """Wilson-Hilferty normal approximation for chi-squared p-value.
    Accurate to ~4 decimal places for df ≥ 1.
    """
    if df <= 0 or stat < 0:
        return float('nan')
    if stat == 0:
        return 1.0
    z = ((stat / df) ** (1/3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
    return 0.5 * math.erfc(z / math.sqrt(2))


def chi2_gof(observed, expected):
    """Goodness-of-fit chi-squared. Returns (stat, df, p)."""
    obs = np.array(observed, dtype=float)
    exp = np.array(expected, dtype=float)
    mask = exp > 0
    stat = float(np.sum((obs[mask] - exp[mask]) ** 2 / exp[mask]))
    df   = int(mask.sum()) - 1
    return stat, df, chi2_pvalue(stat, df)


def stars(p: float) -> str:
    if p < 0.001: return '***'
    if p < 0.01:  return '** '
    if p < 0.05:  return '*  '
    return '   '


def section(title: str):
    print(f"\n{'='*64}")
    print(f"  {title}")
    print('='*64)


# ── Theoretical distributions ─────────────────────────────────────────────────

def _theo_sum_dist():
    counts = Counter()
    for a in range(1, 7):
        for b in range(1, 7):
            for c in range(1, 7):
                counts[a+b+c] += 1
    return {s: counts[s]/216 for s in range(3, 19)}


THEO_SUM = _theo_sum_dist()
THEO_MEAN_SUM = sum(s * p for s, p in THEO_SUM.items())   # 10.5


def size_of(s: int) -> str:
    if s <= 9:  return 'NHO'
    if s <= 11: return 'HOA'
    return 'LON'


# ── Data loading ──────────────────────────────────────────────────────────────

def fetch_draws(db, limit=None):
    conn = db.get_connection()
    cur  = conn.cursor()
    q    = "SELECT draw_number, numbers, draw_time FROM draw_history ORDER BY draw_number ASC"
    if limit:
        q += f" LIMIT {limit}"
    cur.execute(q)
    rows = cur.fetchall()
    conn.close()

    draws = []
    for draw_number, numbers_raw, draw_time in rows:
        try:
            if isinstance(numbers_raw, str):
                nums = json.loads(numbers_raw)
            else:
                nums = list(numbers_raw)
            nums = [int(x) for x in nums]
            if len(nums) != 3:
                continue
            if isinstance(draw_time, str):
                dt = datetime.fromisoformat(draw_time.replace('Z', '+00:00'))
            else:
                dt = draw_time
            if dt is not None and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            draws.append((draw_number, nums, dt))
        except Exception:
            continue
    return draws


# ── Main analysis ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Bingo18 bias analysis")
    parser.add_argument('--limit',    type=int, default=None, help='Last N draws to analyze')
    parser.add_argument('--acf-lags', type=int, default=20,   help='ACF max lag')
    args = parser.parse_args()

    db = DatabaseManager()
    print("Loading draws from database...")
    draws = fetch_draws(db, limit=args.limit)
    N = len(draws)
    print(f"  {N:,} draws loaded")

    if N < 100:
        print("ERROR: need at least 100 draws for meaningful analysis")
        sys.exit(1)

    all_nums  = [n for _, nums, _ in draws for n in nums]
    pos_nums  = [[nums[p] for _, nums, _ in draws] for p in range(3)]
    sums      = [sum(nums) for _, nums, _ in draws]
    sizes     = [size_of(s) for s in sums]

    # ── 1. Digit frequency ────────────────────────────────────────────────────
    section("1. DIGIT FREQUENCY BIAS  (all 3 positions combined)")
    digit_cnt  = Counter(all_nums)
    total_nums = len(all_nums)
    exp_digit  = total_nums / 6
    print(f"  Expected per digit : {exp_digit:,.1f}  (out of {total_nums:,} draws×3)")
    print(f"  {'Digit':>6} {'Count':>9} {'Freq%':>7} {'Dev':>8} {'Residual':>10}")
    obs_d = []
    for d in range(1, 7):
        c    = digit_cnt[d]
        freq = c / total_nums
        dev  = (freq - 1/6) * 100
        res  = (c - exp_digit) / math.sqrt(exp_digit)
        obs_d.append(c)
        print(f"  {d:>6} {c:>9,} {freq*100:>6.3f}% {dev:>+7.3f}% {res:>+9.2f}σ")

    stat, df, p = chi2_gof(obs_d, [exp_digit]*6)
    print(f"\n  χ²({df}) = {stat:.3f}   p = {p:.5f}  {stars(p)}")
    print("  (p < 0.05 = digit frequencies significantly non-uniform)")

    # ── 2. Position bias ──────────────────────────────────────────────────────
    section("2. POSITION BIAS  (digit frequencies per draw position)")
    print(f"  {'Digit':>6}", end='')
    for pos in range(3):
        print(f"  {'Pos'+str(pos+1):>12}", end='')
    print()
    for d in range(1, 7):
        print(f"  {d:>6}", end='')
        for pos in range(3):
            c    = pos_nums[pos].count(d)
            freq = c / N
            print(f"  {c:>6,} ({freq*100:.2f}%)", end='')
        print()
    print()
    for pos in range(3):
        obs_p  = [pos_nums[pos].count(d) for d in range(1, 7)]
        stat_p, df_p, p_p = chi2_gof(obs_p, [N/6]*6)
        print(f"  Position {pos+1}: χ²({df_p}) = {stat_p:.3f}   p = {p_p:.5f}  {stars(p_p)}")

    # ── 3. Sum distribution ───────────────────────────────────────────────────
    section("3. SUM DISTRIBUTION  (actual vs theoretical, sums 3-18)")
    sum_cnt = Counter(sums)
    print(f"  {'Sum':>5}  {'Theo%':>7}  {'Actual%':>8}  {'Count':>7}  {'Dev':>8}")
    obs_s, exp_s = [], []
    for s in range(3, 19):
        tp = THEO_SUM[s]
        c  = sum_cnt.get(s, 0)
        ap = c / N
        obs_s.append(c);  exp_s.append(tp * N)
        print(f"  {s:>5}  {tp*100:>6.2f}%  {ap*100:>7.2f}%  {c:>7,}  {(ap-tp)*100:>+7.2f}%")

    stat, df, p = chi2_gof(obs_s, exp_s)
    print(f"\n  χ²({df}) = {stat:.3f}   p = {p:.5f}  {stars(p)}")

    # ── 4. Size distribution ──────────────────────────────────────────────────
    section("4. SIZE DISTRIBUTION  (NHO/HOA/LON vs theoretical)")
    size_cnt = Counter(sizes)
    print(f"  {'Size':>6}  {'Theo%':>7}  {'Actual%':>8}  {'Count':>8}  {'Dev':>8}")
    obs_sz, exp_sz = [], []
    for sz in SIZES:
        tp = THEO_SZ[sz]
        c  = size_cnt.get(sz, 0)
        ap = c / N
        obs_sz.append(c);  exp_sz.append(tp * N)
        print(f"  {sz:>6}  {tp*100:>6.2f}%  {ap*100:>7.2f}%  {c:>8,}  {(ap-tp)*100:>+7.2f}%")

    stat, df, p = chi2_gof(obs_sz, exp_sz)
    print(f"\n  χ²({df}) = {stat:.3f}   p = {p:.5f}  {stars(p)}")

    # ── 5. Markov transition matrix ───────────────────────────────────────────
    section("5. SERIAL CORRELATION — Markov transition NHO/HOA/LON → next draw")
    trans = defaultdict(Counter)
    for i in range(1, len(sizes)):
        trans[sizes[i-1]][sizes[i]] += 1

    print(f"\n  {'From \\ To':>10}", end='')
    for to in SIZES:
        print(f"  {to:>10}", end='')
    print("   row_n")

    obs_tr, exp_tr = [], []
    for frm in SIZES:
        row_n = sum(trans[frm].values())
        print(f"  {frm:>10}", end='')
        for to in SIZES:
            c   = trans[frm].get(to, 0)
            pct = c / row_n * 100 if row_n else 0
            e   = size_cnt[frm] * size_cnt[to] / N
            print(f"  {pct:>8.2f}%", end='')
            obs_tr.append(c);  exp_tr.append(e)
        print(f"  {row_n:>6,}")

    print(f"\n  Expected under independence:")
    for frm in SIZES:
        row_n = sum(trans[frm].values())
        print(f"  {frm:>10}", end='')
        for to in SIZES:
            e   = size_cnt[frm] * size_cnt[to] / N
            ep  = e / row_n * 100 if row_n else 0
            print(f"  {ep:>8.2f}%", end='')
        print()

    obs_tr = np.array(obs_tr, dtype=float)
    exp_tr = np.array(exp_tr, dtype=float)
    mask   = exp_tr >= 5
    stat_t = float(np.sum((obs_tr[mask] - exp_tr[mask])**2 / exp_tr[mask]))
    df_t   = (3-1) * (3-1)   # contingency table (3×3)
    p_t    = chi2_pvalue(stat_t, df_t)
    print(f"\n  χ²({df_t}) = {stat_t:.3f}   p = {p_t:.5f}  {stars(p_t)}")
    print("  (p < 0.05 = current size predicts next size — Markov signal exists)")

    # ── 6. ACF on sum series ──────────────────────────────────────────────────
    section(f"6. AUTOCORRELATION of SUM series  (lag 1-{args.acf_lags})")
    sums_arr = np.array(sums, dtype=float)
    mean_s   = sums_arr.mean()
    var_s    = sums_arr.var()
    se_wn    = 1 / math.sqrt(N)          # ±1.96*se_wn = 95% CI for white noise
    ci95     = 1.96 * se_wn

    print(f"  Mean sum  : {mean_s:.4f}  (theoretical: {THEO_MEAN_SUM:.4f})")
    print(f"  Std dev   : {sums_arr.std():.4f}")
    print(f"  95% CI WN : ±{ci95:.4f}  (beyond this → significant correlation)")
    print()

    sig_lags = []
    centered = sums_arr - mean_s
    for lag in range(1, args.acf_lags + 1):
        acf = float(np.mean(centered[lag:] * centered[:-lag]) / var_s)
        bar_len = min(40, int(abs(acf) / ci95 * 10))
        bar = ('█' if acf > 0 else '░') * bar_len
        sig = ' ← SIG' if abs(acf) > ci95 else ''
        print(f"  lag {lag:>2}: {acf:>+7.4f}  {bar:<20}{sig}")
        if abs(acf) > ci95:
            sig_lags.append((lag, acf))

    if sig_lags:
        print(f"\n  Significant lags: {[(l, round(a,4)) for l,a in sig_lags]}")
    else:
        print(f"\n  No significant autocorrelation detected (all within ±{ci95:.4f})")

    # ── 7. Time-of-day size distribution ─────────────────────────────────────
    section("7. TIME-OF-DAY SIZE DISTRIBUTION  (Vietnam hour, 0-23)")
    tod = defaultdict(Counter)
    for _, nums, dt in draws:
        if dt is None:
            continue
        vn_h = dt.astimezone(VN_TZ).hour
        tod[vn_h][size_of(sum(nums))] += 1

    print(f"  {'Hour':>5}  {'N':>6}  {'NHO%':>6}  {'HOA%':>6}  {'LON%':>6}  Notable (dev >4pp from theo)")
    for h in sorted(tod):
        cnt = tod[h]
        tot = sum(cnt.values())
        if tot < 20:
            continue
        nho = cnt['NHO'] / tot
        hoa = cnt['HOA'] / tot
        lon = cnt['LON'] / tot
        notes = []
        if abs(nho - THEO_SZ['NHO']) > 0.04:
            notes.append(f"NHO:{nho*100:.0f}%({(nho-THEO_SZ['NHO'])*100:+.0f}pp)")
        if abs(lon - THEO_SZ['LON']) > 0.04:
            notes.append(f"LON:{lon*100:.0f}%({(lon-THEO_SZ['LON'])*100:+.0f}pp)")
        if abs(hoa - THEO_SZ['HOA']) > 0.04:
            notes.append(f"HOA:{hoa*100:.0f}%({(hoa-THEO_SZ['HOA'])*100:+.0f}pp)")
        print(f"  {h:>5}  {tot:>6,}  {nho*100:>5.1f}%  {hoa*100:>5.1f}%  {lon*100:>5.1f}%  {'  '.join(notes)}")

    # ── 8. Within-draw repeat rate ────────────────────────────────────────────
    section("8. WITHIN-DRAW REPEAT RATE  (pairs / triples vs theoretical)")
    # Theoretical (3 draws with replacement from {1..6}):
    #   all unique  = 6×5×4/216 = 120/216 ≈ 55.56%
    #   exactly pair = 90/216          ≈ 41.67%
    #   triple       = 6/216           ≈  2.78%
    n_triple   = sum(1 for _, nums, _ in draws if nums[0]==nums[1]==nums[2])
    n_any_pair = sum(1 for _, nums, _ in draws
                     if nums[0]==nums[1] or nums[1]==nums[2] or nums[0]==nums[2])
    n_unique   = N - n_any_pair
    n_pair_only = n_any_pair - n_triple

    rows = [
        ('All 3 unique',    n_unique,    120/216),
        ('Exactly one pair',n_pair_only, 90/216),
        ('All 3 same',      n_triple,    6/216),
    ]
    print(f"  {'Category':>22}  {'Theo%':>7}  {'Actual%':>8}  {'Count':>8}  {'Dev':>7}")
    obs_r, exp_r = [], []
    for label, c, tp in rows:
        ap = c / N
        obs_r.append(c);  exp_r.append(tp * N)
        print(f"  {label:>22}  {tp*100:>6.2f}%  {ap*100:>7.2f}%  {c:>8,}  {(ap-tp)*100:>+6.2f}%")

    stat_r, df_r, p_r = chi2_gof(obs_r, exp_r)
    print(f"\n  χ²({df_r}) = {stat_r:.3f}   p = {p_r:.5f}  {stars(p_r)}")

    # ── Summary ───────────────────────────────────────────────────────────────
    section("SUMMARY")
    print(f"  N draws analyzed : {N:,}")
    print(f"  Significance     : * p<0.05   ** p<0.01   *** p<0.001")
    print()
    print("  Key findings to exploit:")
    print("  - Any *** digit bias → update digit voter weights directly")
    print("  - Any *** Markov signal → current Markov model underweighted")
    print("  - Any *** ACF lag → add lag feature as extra voter")
    print("  - TOD rows with large deviations → refine _TOD_SIZE_STATS in prediction_service.py")
    print()


if __name__ == '__main__':
    main()
