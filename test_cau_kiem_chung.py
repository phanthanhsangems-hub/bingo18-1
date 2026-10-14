"""P265: kiem chung cau tren lich su — tinh tay tren du lieu nho."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cau_kiem_chung as C
DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))
# 123 ra o #1, #111 ra o #2 (cau trung). 123 ra #5, #111 khong ra #6 (cau truot).
# 111 ra #10 khong co 123 truoc (trip ngoai cau). 1-2-3 o #1..#9 chi 2 lan.
ky = [(1,(1,2,3)),(2,(1,1,1)),(3,(4,5,6)),(4,(2,2,6)),(5,(1,2,3)),(6,(4,4,5)),
      (7,(3,3,6)),(8,(5,5,6)),(9,(2,4,6)),(10,(1,1,1)),(11,(4,5,5))]
r = C.kiem_chung(ky, {'123': [('111', 9)]})
c = r['cap'][0]
kiem("cau 123 co 2 lan kich hoat (#1, #5)", c['n_kich_hoat'] == 2, c)
kiem("1 lan trung (#2 = 111)", c['trung_cau'] == 1, c)
kiem("ty le cau = 1/2", c['ty_le_cau'] == 0.5, c)
kiem("khong co cau: dich 111 ra sau cac ky khac (#10 khong sau 123)",
     r['tong_hop']['111']['khong_cau'] == 1, r['tong_hop'])
kiem("tong lan 111 ra = 2 (#2 va #10)", r['tong_hop']['111']['tong_lan_dich'] == 2, r['tong_hop'])
kiem("sau cau = 1", r['tong_hop']['111']['sau_cau'] == 1)
kiem("nen cua mot dich cu the = 1/216", r['nen_1_216'] == round(1/216, 5))
kiem("it mau -> khong co y nghia", c['co_y_nghia'] is False)
# khoang Wilson
lo, hi = C.wilson(0, 0)
kiem("n=0 khong chia 0", (lo, hi) == (0.0, 1.0))
lo, hi = C.wilson(50, 100)
kiem("Wilson 50/100 ~ 0.40..0.60", 0.39 < lo < 0.41 and 0.59 < hi < 0.61, (lo, hi))
# cau khong co ky tiep lien tuc (ky bi thieu) -> bo qua
gap = [(1,(1,2,3)),(3,(1,1,1))]
r2 = C.kiem_chung(gap, {'123': [('111', 1)]})
kiem("ky thieu lien ke -> khong dem", r2['cap'][0]['n_kich_hoat'] == 0 and r2['so_ky_co_truoc'] == 0, r2)
# hieu ung that: cau co ti le cao hon nen -> co y nghia khi mau du lon
big = []
for i in range(1, 4001):
    big.append((i, (1,2,3) if i % 2 else (4,5,6)))
    big[-1] = big[-1]
big = [(d, (1,2,3) if d % 2 == 1 else (4,5,6)) for d in range(1, 4001)]
# 111 ra ngay sau 123 trong 60% lan (de kiem tra co y nghia), con lai thi khong
ex = []
for d in range(1, 4001):
    b = (1,2,3) if d % 5 == 0 else (4,5,6)
    ex.append((d, b))
ex = [(d, (1,1,1)) if (d - 1) % 5 == 0 and d > 1 else (d, b) for d, b in ex]
rr = C.kiem_chung(ex, {'123': [('111', 0)]})
kiem("cau 123 trung 111 o moi lan co 123 truoc -> ty le 1.0 va co y nghia",
     rr['cap'][0]['ty_le_cau'] == 1.0 and rr['cap'][0]['co_y_nghia'] is True, rr['cap'][0])
print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
