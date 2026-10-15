"""P270: phan loai nong/lanh va bo qua ky trip khi dem."""
import os, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ngay_trip as N
DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))
print("=== 1. phan loai ===")
dem = {1: 9, 2: 7, 3: 5, 4: 5, 5: 2, 6: 1}
kiem("so nhieu nhat -> NONG", N.phan_loai(dem, 1) == 'NONG')
kiem("so nhieu thu 2 -> NONG (top 2)", N.phan_loai(dem, 2) == 'NONG')
kiem("so it nhat -> LANH", N.phan_loai(dem, 6) == 'LANH')
kiem("so it thu 2 -> LANH (bottom 2)", N.phan_loai(dem, 5) == 'LANH')
kiem("so o giua -> GIUA", N.phan_loai(dem, 3) == 'GIUA')
print("=== 2. dem bo qua ky trip ===")
# ngay co 40 ky khong trip, moi ky co 1-2-3, va mot trip 5-5-5
ds = [(i, (1, 2, 3), '2026-01-01') for i in range(40)] + [(100, (5, 5, 5), '2026-01-01')]
r = N.phan_tich([(dn, bo, n) for dn, bo, n in ds])
kiem("ngay co 1 trip duoc dem", r['so_ngay_co_trip'] == 1, r)
kiem("trip 5 khong tu lam minh nong (bi bo qua khi dem)", r['trip']['n'] == 1 and r['trip']['nong'] == 0, r['trip'])
print("=== 3. tinh dung tren du lieu ngau nhien (ky vong ~1/3) ===")
rnd = random.Random(1)
rows = []
dn = 0
for d in range(400):
    ngay = f"2026-02-{(d % 28) + 1:02d}" if d < 28 else f"2026-03-{(d % 28) + 1:02d}"
    for _ in range(150):
        dn += 1
        b = tuple(sorted(rnd.randint(1, 6) for _ in range(3)))
        rows.append((dn, b, f"{2026}-{(d // 28) + 1:02d}-{(d % 28) + 1:02d}"))
r = N.phan_tich(rows)
t = r['trip']; dc = r['doi_chung']
kiem("ngau nhien: ty le nong cua trip gan 1/3 (+-0.06)", t['n'] > 100 and abs(t['ty_le_nong'] - 1/3) < 0.06, t)
kiem("ngau nhien: doi chung gan 1/3 (+-0.03)", abs(dc['ty_le_nong'] - 1/3) < 0.03, dc)
print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
