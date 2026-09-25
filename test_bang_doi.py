"""P226: bảng "bộ 2 số trùng nhau" — một số ra ÍT NHẤT 2 lần trong kỳ.

Định nghĩa đã chốt bằng chính bảng người dùng gửi, không phải đoán:
    ít nhất 2 lần (kể cả bộ ba) -> 16/216 = 7,41%, TB 216/16 = 13,5 -> 13  KHỚP
    đúng 2 lần (loại bộ ba)     -> 15/216 = 6,94%, TB 216/15 = 14,4 -> 14  LỆCH
Bảng đối chiếu ghi 13 ở cả sáu dòng, nên là "ít nhất 2 lần".
"""
import os, sys
from itertools import product
from unittest import mock

os.environ.setdefault('DATABASE_URL', '')
os.environ.pop('APP_USER', None)

import app as A

DAT = HONG = 0
def kiem(ten, dk, ct=''):
    global DAT, HONG
    if dk: DAT += 1; print(f"  DAT  {ten}")
    else:  HONG += 1; print(f"  HONG {ten}" + (f"  -> {ct}" if ct else ''))

print("=== 1. DINH NGHIA: doi chieu voi 216 ket qua ===")
tat_ca = list(product(range(1, 7), repeat=3))
def co_doi(d):
    a, b, c = d
    return a if (a == b or a == c) else (b if b == c else None)

so_cach = sum(1 for d in tat_ca if co_doi(d) == 1)
kiem("so 1 ra it nhat 2 lan: 16/216", so_cach == 16, str(so_cach))
kiem("TB ly thuyet = 13,5", abs(216 / 16 - 13.5) < 1e-9)
kiem("bo ba 1-1-1 PHAI duoc tinh la co doi", co_doi((1, 1, 1)) == 1)
kiem("1-1-5 co doi so 1", co_doi((1, 1, 5)) == 1)
kiem("5-1-1 co doi so 1 (vi tri khac nhau)", co_doi((5, 1, 1)) == 1)
kiem("1-5-1 co doi so 1", co_doi((1, 5, 1)) == 1)
kiem("1-2-3 KHONG co doi", co_doi((1, 2, 3)) is None)

# Toi da MOT so thoa -> 6 bien co loai tru nhau
chong = [d for d in tat_ca
         if sum(1 for n in range(1, 7) if d.count(n) >= 2) > 1]
kiem("khong ket qua nao co HAI so cung lap", not chong, str(chong[:3]))
tong_cach = sum(1 for d in tat_ca if co_doi(d) is not None)
kiem("tong 6 bo = 96/216 (4/9)", tong_cach == 96, str(tong_cach))

print("\n=== 2. TINH TREN DU LIEU DUNG SAN ===")
# Ky:      1        2        3        4        5        6        7
# numbers: 1,1,5    1,2,3    2,2,2    1,1,1    4,5,6    3,3,1    2,2,4
ky = [(101, [1,1,5]), (102, [1,2,3]), (103, [2,2,2]), (104, [1,1,1]),
      (105, [4,5,6]), (106, [3,3,1]), (107, [2,2,4])]

class GiaCur:
    def __init__(s): s.buoc = 0
    def execute(s, sql, *a):
        s.sql = sql; s.buoc += 1
    def fetchone(s):
        return (len(ky), max(d for d, _ in ky))
    def fetchall(s):
        q = s.sql
        if 'GROUP BY sum_value' in q:
            return []
        if 'ROW_NUMBER' in q or 'rn' in q:
            return []
        if 'numbers' in q:
            return [(d, str(n)) for d, n in ky]
        return []
    def close(s): pass
class GiaConn:
    def cursor(s): return GiaCur()
    def close(s): pass

with mock.patch.object(A.db, 'get_connection', return_value=GiaConn()), \
     mock.patch.object(A, '_trung_vi_theo_tong', return_value={}):
    kq = A._tinh_thong_ke()

doi = {r['combo']: r for r in kq['pairs']}
kiem("co du 6 dong 11..66", sorted(doi) == ['11','22','33','44','55','66'], str(sorted(doi)))

# '11' xuat hien o ky 101 (1,1,5) va 104 (1,1,1) -> 2 lan
kiem("11: dem = 2 (co ky 1-1-1)", doi['11']['count'] == 2, str(doi['11']['count']))
kiem("11: lan cuoi = ky 104", doi['11']['last_draw'] == 104, str(doi['11']['last_draw']))
kiem("11: chuoi khoang cach = [3] (104-101)", doi['11']['gaps'] == [3], str(doi['11']['gaps']))
kiem("11: chua ve = 107-104 = 3", doi['11']['current_gap'] == 3, str(doi['11']['current_gap']))

# '22' o ky 103 (2,2,2) va 107 (2,2,4) -> 2 lan
kiem("22: dem = 2", doi['22']['count'] == 2, str(doi['22']['count']))
kiem("22: chua ve = 0 (vua ra ky moi nhat)", doi['22']['current_gap'] == 0,
     str(doi['22']['current_gap']))
# '33' o ky 106 -> 1 lan
kiem("33: dem = 1", doi['33']['count'] == 1, str(doi['33']['count']))
kiem("33: prev_gap = None (moi ve dung 1 lan)", doi['33']['prev_gap'] is None)
# '44','55','66' khong xuat hien
for c in ('44','55','66'):
    kiem(f"{c}: dem = 0, chua ve = None", doi[c]['count'] == 0 and doi[c]['current_gap'] is None)

print("\n=== 3. DONG 'BAT KY DOI NAO' ===")
bk = kq['pair_any']
# ky co doi: 101,103,104,106,107 -> 5
kiem("dem = 5 ky co doc nao do", bk['count'] == 5, str(bk['count']))
kiem("tong 6 dong = dong 'bat ky' (6 bien co loai tru nhau)",
     sum(r['count'] for r in kq['pairs']) == bk['count'],
     f"{sum(r['count'] for r in kq['pairs'])} vs {bk['count']}")
kiem("lan cuoi = ky 107", bk['last_draw'] == 107, str(bk['last_draw']))
kiem("last_combo = '22'", bk['last_combo'] == '22', str(bk['last_combo']))

print("\n=== 4. TB LY THUYET: 13,5 chu KHONG phai 14 ===")
# round(13.5) cua Python ra 14 (lam tron ve so chan) -> lech bang doi chieu.
kiem("round(13.5) cua Python that su ra 14", round(13.5) == 14)
kiem("moi dong co avg_gap_ly_thuyet = 13.5",
     all(r['avg_gap_ly_thuyet'] == 13.5 for r in kq['pairs']),
     str([r['avg_gap_ly_thuyet'] for r in kq['pairs']]))
kiem("dong 'bat ky' = 216/96 = 2.25", bk['avg_gap_ly_thuyet'] == 2.25,
     str(bk['avg_gap_ly_thuyet']))

print("\n=== 5. TRIP KHONG BI ANH HUONG khi bo loc sum_value ===")
trip = {r['combo']: r for r in kq['triples']}
kiem("111: dem = 1 (ky 104)", trip['111']['count'] == 1, str(trip['111']['count']))
kiem("222: dem = 1 (ky 103)", trip['222']['count'] == 1, str(trip['222']['count']))
kiem("333: dem = 0", trip['333']['count'] == 0, str(trip['333']['count']))

print("\n=== 6. MO PHONG: TB do duoc phai bam 13,5 ===")
import random
random.seed(20260925)
N = 400_000
lan_cuoi, kc = None, []
for i in range(1, N + 1):
    d = tuple(random.randint(1, 6) for _ in range(3))
    if co_doi(d) == 1:
        if lan_cuoi is not None:
            kc.append(i - lan_cuoi)
        lan_cuoi = i
tb = sum(kc) / len(kc)
kiem(f"mo phong {N:,} ky: TB = {tb:.3f}, lech < 0,15 so voi 13,5",
     abs(tb - 13.5) < 0.15, f"{tb:.3f}")

print("\n=== 7. ENDPOINT /api/pair-stats ===")
A.limiter.enabled = False
with mock.patch.object(A, '_thong_ke', return_value=kq):
    r = A.app.test_client().get('/api/pair-stats')
    j = r.get_json()
kiem("tra 200", r.status_code == 200, str(r.status_code))
kiem("co khoa 'pairs' du 6 dong", len(j.get('pairs', [])) == 6, str(len(j.get('pairs', []))))
kiem("co khoa 'any' (dong bat ky)", j.get('any') is not None)
kiem("'any' la cua DOI, khong phai cua TRIP",
     j['any'].get('last_combo') == '22', str(j['any'].get('last_combo')))
kiem("co max_draw de doi chieu moc ky (P223)", 'max_draw' in j, str(sorted(j)))
kiem("co total_draws", j.get('total_draws') == len(ky))

print("\n=== 8. CAI BAY: board-stats dat ten dong 'any' KHAC ===")
# /api/board-stats tra nguyen _thong_ke(): o do 'any' la dong cua TRIP, con
# dong cua DOI ten la 'pair_any'. Giao dien lay nham d.any se hien dong trip
# vao bang doi. Khoa lai bang test.
with mock.patch.object(A, '_thong_ke', return_value=kq):
    bs = A.app.test_client().get('/api/board-stats').get_json()
kiem("board-stats co CA 'pairs' lan 'pair_any'",
     'pairs' in bs and 'pair_any' in bs, str(sorted(bs)))
kiem("board-stats: 'any' la cua TRIP (nen KHONG duoc dung cho bang doi)",
     bs['any'].get('last_combo') in ('222', '111', None),
     str(bs['any'].get('last_combo')))
kiem("board-stats: 'pair_any' moi la cua DOI",
     bs['pair_any'].get('last_combo') == '22', str(bs['pair_any'].get('last_combo')))
kiem("hai dong do KHAC nhau — day chinh la cho de lay nham",
     bs['any'].get('last_combo') != bs['pair_any'].get('last_combo'))

print("\n=== 9. GIAO DIEN uu tien pair_any ===")
js = open('static/js/dashboard.js', encoding='utf-8').read()
kiem("loadPairStats lay 'd.pair_any || d.any'",
     'd.pair_any || d.any' in js)
kiem("KHONG con cho nao trong loadPairStats lay thang d.any",
     'const a = bk;' in js)
kiem("duoc goi trong cung request voi hai bang kia",
     'await loadPairStats(d);' in js)
html = open('templates/dashboard.html', encoding='utf-8').read()
kiem("the co du 4 id", all(f'id="{i}"' in html for i in ('dd-body','dd-sub','dd-note','dd-table')))
kiem("tieu de dung ten nguoi dung quen", 'Bộ 2 số trùng nhau' in html)

print("\n" + "=" * 52)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
