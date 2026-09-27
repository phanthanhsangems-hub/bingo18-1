"""P237: go lenh cam bo co so lap + chuan hoa _cold_score theo ky vong.

Nguoi dung hoi: "vi sao khong thay he thong du doan tong 4, 5, 15, 16, 17".
Production (200 du doan): tong 3,4,5,16,17,18 = 0 lan; 0/200 du doan co so
lap (ky that 44,4%). Nguyen nhan: _STRUCTURAL_BANS cam 36 bo co so lap, ma
moi cach ghep ra 6 tong do deu co so lap. Ly do dat lenh cam la so sai moc.
"""
import os, sys, random, math
from collections import Counter
from itertools import product
from unittest import mock
os.environ.setdefault('DATABASE_URL', '')
import prediction_service as PS

DAT = HONG = 0
def kiem(ten, dk, ct=''):
    global DAT, HONG
    if dk: DAT += 1; print(f"  DAT  {ten}")
    else:  HONG += 1; print(f"  HONG {ten}" + (f"  -> {ct}" if ct else ''))

cat = lambda s: 'NHO' if s <= 9 else ('HOA' if s <= 11 else 'LON')

print("=== 1. LY DO CU LA SO SAI MOC ===")
W = Counter(tuple(sorted(p)) for p in product(range(1, 7), repeat=3))
loai = lambda c: 3 - len(set(c))          # 0 khac nhau, 1 doi, 2 bo ba
for l, bo, x in ((0, 20, 1.56), (1, 30, 0.78), (2, 6, 0.26)):
    ty = sum(n for c, n in W.items() if loai(c) == l) / 216
    kiem(f"may CONG BANG da cho x{x} (so bo {bo}/56)", abs(ty / (bo / 56) - x) < 0.01, f"{ty/(bo/56):.3f}")
kiem("ky co so lap ly thuyet = 44,4%",
     abs(sum(n for c, n in W.items() if loai(c)) / 216 - 0.4444) < 0.001)
kiem("tong 3,4,5,16,17,18 CHI ghep duoc tu bo co so lap",
     [s for s in range(3, 19) if all(loai(c) for c in W if sum(c) == s)] == [3, 4, 5, 16, 17, 18])

print("\n=== 2. LENH CAM DA GO ===")
kiem("_STRUCTURAL_BANS khong con", not hasattr(PS, '_STRUCTURAL_BANS'))
class C:
    def execute(s, *a): pass
    def fetchall(s): return [('[1, 2, 3]',), ('[4, 5, 6]',)]
class K:
    def cursor(s): return C()
    def close(s): pass
db = mock.MagicMock(); db.get_connection.return_value = K()
ban = PS._get_banned_combos(db)
kiem("chi cam bo vua du doan gan day", ban == {(1, 2, 3), (4, 5, 6)}, str(ban))
kiem("1-1-2, 5-6-6, 1-1-1 KHONG bi cam", not ({(1, 1, 2), (5, 6, 6), (1, 1, 1)} & ban))

print("\n=== 3. BANG XAC SUAT ===")
kiem("_P_COMBO du 56 bo", len(PS._P_COMBO) == 56)
kiem("_P_COMBO cong lai = 1", abs(sum(PS._P_COMBO.values()) - 1) < 1e-12)
kiem("1-2-3 = 6/216, 1-1-2 = 3/216, 1-1-1 = 1/216",
     PS._P_COMBO[(1, 2, 3)] == 6/216 and PS._P_COMBO[(1, 1, 2)] == 3/216 and PS._P_COMBO[(1, 1, 1)] == 1/216)
kiem("_P_SUM[10] = 27/216, _P_SUM[3] = 1/216",
     abs(PS._P_SUM[10] - 27/216) < 1e-12 and abs(PS._P_SUM[3] - 1/216) < 1e-12)

print("\n=== 4. HAM CHAY DUOC (P237 tung quen import math) ===")
try:
    v = PS._cold_score((1, 1, 1), Counter({(1, 2, 3): 1}), Counter({1: 1, 2: 1, 3: 1}),
                       Counter({6: 1}), Counter({1: 2}), {60: Counter(), 100: Counter()})
    kiem("_cold_score tra so thuc, khong NameError", isinstance(v, float) and math.isfinite(v), str(v))
except Exception as e:
    kiem("_cold_score tra so thuc, khong NameError", False, repr(e))
try:
    kiem("_cold_score voi Counter RONG khong chia 0",
         math.isfinite(PS._cold_score((1, 2, 3), Counter(), Counter(), Counter(), Counter(), {})))
except Exception as e:
    kiem("_cold_score voi Counter RONG khong chia 0", False, repr(e))
try:
    kiem("get_diverse_prediction chay", len(PS.get_diverse_prediction([[1, 2, 3]], set())) == 3)
    kiem("get_diverse_prediction lich su rong", len(PS.get_diverse_prediction([], set())) == 3)
except Exception as e:
    kiem("get_diverse_prediction chay", False, repr(e))

print("\n=== 5. MO PHONG 12.000 KY DOC LAP — PHAN BO PHAI GAN THAT ===")
ALL = sorted(W)
rnd = random.Random(7); lich = []; du = []; pnh = []
ra = {'NHO': Counter(), 'LON': Counter()}; lap = Counter()
for t in range(12000):
    lich.append(tuple(sorted(rnd.randint(1, 6) for _ in range(3))))
    if len(lich) < 100: continue
    size = rnd.choice(['NHO', 'LON'])
    L = lich[::-1]
    cf = Counter(L[:15]); nf = Counter(x for c in L[:15] for x in c); sf = Counter(sum(c) for c in L[:15])
    mf = {60: Counter(L[:60]), 100: Counter(L[:100])}
    pn = Counter(x for c in pnh[-15:] for x in c)
    ung = [c for c in ALL if cat(sum(c)) == size and c not in set(du[-6:])]
    ch = min(ung, key=lambda c: PS._cold_score(c, cf, nf, sf, pn, mf))
    ra[size][sum(ch)] += 1; lap[size] += len(set(ch)) < 3; du.append(ch); pnh.append(ch)
for sz, tong in (('NHO', (4, 5)), ('LON', (16, 17))):
    n = sum(ra[sz].values())
    ptt = {s: sum(p for c, p in PS._P_COMBO.items() if sum(c) == s) for s in range(3, 19) if cat(s) == sz}
    z = sum(ptt.values()); ptt = {s: v / z for s, v in ptt.items()}
    tv = 0.5 * sum(abs(ra[sz].get(s, 0) / n - ptt[s]) for s in ptt)
    kiem(f"{sz}: tong {tong} DA duoc du doan", all(ra[sz].get(s, 0) > 0 for s in tong), str(dict(ra[sz])))
    kiem(f"{sz}: bo co so lap 35-60% (that 48,1%)", 0.35 < lap[sz] / n < 0.60, f"{lap[sz]/n*100:.1f}%")
    kiem(f"{sz}: lech phan bo tong < 12% (cu ~16%, bo cam ma khong sua ~20%)", tv < 0.12, f"{tv*100:.1f}%")
    bo_ba = sum(v for s, v in ra[sz].items() if s in (3, 18)) / n
    kiem(f"{sz}: bo ba KHONG ngap (< 5%)", bo_ba < 0.05, f"{bo_ba*100:.1f}%")

print("\n=== 6. DUONG get_diverse_prediction ===")
rnd = random.Random(11); h = []; du = []; ra2 = Counter(); lap2 = 0; n2 = 0
for t in range(6000):
    h.append([rnd.randint(1, 6) for _ in range(3)])
    if len(h) < 30: continue
    c = tuple(PS.get_diverse_prediction(h[-30:], set(du[-6:]), window=30))
    ra2[sum(c)] += 1; lap2 += len(set(c)) < 3; n2 += 1; du.append(c)
kiem("co du doan bo co so lap (cu: KHONG bao gio)", lap2 > 0)
kiem("ti le so lap 30-65% (that 44,4%)", 0.30 < lap2 / n2 < 0.65, f"{lap2/n2*100:.1f}%")
kiem("bo ba khong ngap (< 5%)", (ra2[3] + ra2[18]) / n2 < 0.05, f"{(ra2[3]+ra2[18])/n2*100:.1f}%")

print("\n" + "=" * 54)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
