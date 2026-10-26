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

# P275: ky ngay truoc tong 4 / tong 7
r2 = [(10,(1,2,3),'2026-09-30'),(11,(1,1,2),'2026-10-01'),(12,(1,2,4),'2026-10-01'),
      (13,(2,2,3),'2026-10-01'),(15,(1,1,2),'2026-10-01'),(16,(4,5,6),'2026-10-01')]  # thieu #14
q = T.truoc_tong(r2, '2026-10', (4, 7))
kiem("tong 4 ra 2 lan (#11,#15)", q['4']['so_lan'] == 2, q['4'])
kiem("#11 truoc la #10 (123, tong 6) du khac thang", q['4']['danh_sach'][0] == {'ky': 11, 'bo': '112', 'bo_truoc': '123', 'tong_truoc': 6})
kiem("#15 truoc thieu (#14) -> None, khong lay #13", q['4']['danh_sach'][1]['bo_truoc'] is None and q['4']['thieu_ky_truoc'] == 1)
kiem("tong 7 ra 2 lan (#12,#13)", [x['ky'] for x in q['7']['danh_sach']] == [12, 13])
kiem("truoc tong 7: 112 va 124 moi bo 1 lan", sorted(x['bo'] for x in q['7']['bo_truoc']) == ['112', '124'])
kiem("tong_truoc du 16 tong 3..18", len(q['7']['tong_truoc']) == 16)
print(f"\nDAT: {DAT}   HONG: {HONG}"); sys.exit(1 if HONG else 0)
