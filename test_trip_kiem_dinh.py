"""P274: kiem dinh trip 444/666 ra nhieu bat thuong."""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trip_kiem_dinh as T

DAT = HONG = 0
def kiem(ten, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {ten}" + ('' if ok else f"  -> {ct}"))

print("=== 1. HAM XAC SUAT ===")
kiem("chi2 df5 tai 11.07 ~ 0.05", abs(T.chi2_p(11.07, 5) - 0.05) < 1e-3, T.chi2_p(11.07, 5))
kiem("chi2 df5 tai 0 = 1", T.chi2_p(0, 5) == 1.0)
kiem("Poisson P(X>=5|2) = 0.0527", abs(T.poisson_tren(5, 2.0) - 0.05265) < 1e-4)
kiem("Poisson P(X>=1|1) = 1-e^-1", abs(T.poisson_tren(1, 1.0) - 0.63212) < 1e-4)
kiem("Poisson P(X>=0) = 1", T.poisson_tren(0, 3.0) == 1.0)
kiem("Poisson lam lon (P(X>=330|300))", 0.03 < T.poisson_tren(330, 300.0) < 0.05, T.poisson_tren(330, 300.0))

print("\n=== 2. XUC XAC CONG BANG -> KHONG DANG NGO ===")
r = random.Random(7)
def ve(n, nang=None):
    rows = []
    for i in range(n):
        bo = tuple(sorted(r.choice(nang) if nang and r.random() < 0.5 else r.randint(1, 6) for _ in range(3)))
        rows.append((100000 + i, bo, f"2026-{8 + i * 3 // n:02d}-{1 + i % 28:02d}"))
    return rows
d = T.phan_tich(ve(60000), '2026-08-01')
tb = d['toan_bo']
kiem("so ky", tb['so_ky'] == 60000)
kiem("p mat > 0.001", tb['p_mat'] > 0.001, tb['p_mat'])
kiem("khong qua 1 bo dang ngo", sum(v['dang_ngo'] for v in tb['bo'].values()) <= 1)
kiem("co theo_thang 08,09,10", list(d['theo_thang']) == ['2026-08', '2026-09', '2026-10'], list(d['theo_thang']))
kiem("30_ngay co tu_ngay", '30_ngay' in d and d['30_ngay']['tu_ngay'] <= '2026-10-28')

print("\n=== 3. XUC XAC LECH VE 4 VA 6 -> PHAT HIEN ===")
d2 = T.kiem_dinh_khoang([(dn, bo) for dn, bo, _ in ve(30000, nang=[4, 6])])
kiem("p mat rat nho", d2['p_mat'] < 1e-6, d2['p_mat'])
kiem("444 dang ngo", d2['bo']['444']['dang_ngo'], d2['bo']['444'])
kiem("666 dang ngo", d2['bo']['666']['dang_ngo'], d2['bo']['666'])
kiem("111 khong dang ngo", not d2['bo']['111']['dang_ngo'])

print("\n=== 4. RONG ===")
e = T.kiem_dinh_khoang([])
kiem("rong khong loi", e['so_ky'] == 0 and e['p_mat'] is None)

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
