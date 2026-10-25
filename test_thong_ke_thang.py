import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import thong_ke_thang as T
DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))
rows = [(1,(1,1,2),'2026-09-30'),(2,(1,1,1),'2026-09-30'),(3,(5,5,5),'2026-09-30'),(4,(1,1,3),'2026-09-30'),
        (6,(6,6,5),'2026-09-30'),(8,(2,2,2),'2026-10-01')]   # thieu #5 va #7; #8 la thang 10
r = T.thong_ke(rows, '2026-09')
kiem("dem dung 5 ky thang 9 (bo ky thang 10)", r['so_ky'] == 5, r['so_ky'])
kiem("tong 4: (1,1,2) va... = 1 lan", r['tong']['4']['so_lan'] == 1, r['tong'])
kiem("tong 5: (1,1,3) = 1 lan", r['tong']['5']['so_lan'] == 1)
kiem("tong 3 khong nam trong bao cao nhung trip 111 = 1", r['trip']['111']['so_lan'] == 1)
kiem("trip 555 = 1, 222 = 0 (222 la ky thang 10)", r['trip']['555']['so_lan'] == 1 and r['trip']['222']['so_lan'] == 0)
kiem("tong 17: (6,6,5) = 1", r['tong']['17']['so_lan'] == 1)
kiem("ky thieu trong khoang = 1 (#5)", r['so_ky_thieu_trong_khoang'] == 1, r['so_ky_thieu_trong_khoang'])
kiem("ky vong 4 = 3/216 * n", r['tong']['4']['ky_vong'] == round(5 * 3 / 216, 1))
kiem("tong trip = 2", r['tong_trip'] == 2)
print(f"\nDAT: {DAT}   HONG: {HONG}"); sys.exit(1 if HONG else 0)
