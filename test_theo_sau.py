"""P227: bảng "bộ nào hay ra NGAY SAU bộ này".

Hai điều bộ test này tồn tại để giữ, vì thiếu chúng thì bảng nói dối:

1. CHỈ đếm khi hai kỳ LIÊN TIẾP THẬT SỰ. Dữ liệu từng thủng nhiều lần trong
   tháng 9 (mất 11 kỳ #187690-#187700). Bỏ qua điều kiện này thì một lỗ hổng
   sẽ nối liền hai kỳ cách nhau rất xa và sinh ra một cặp "theo sau" giả.

2. Cột "lẽ ra" và phép kiểm chi bình phương. Kỳ quay độc lập nên phân bố bộ
   theo sau phải bám p = số cách/216. Với ~2.574 lần 2-3-5 xuất hiện, một bộ
   3 số khác nhau lẽ ra ra ~71,5 lần, độ lệch chuẩn ~8,3 — đỉnh cao nhất có
   thể lên ~92 lần THUẦN do ngẫu nhiên. Chỉ đưa cột "số lần" là biến nhiễu
   thành cầu giả.
"""
import os, sys, random
from unittest import mock

os.environ.setdefault('DATABASE_URL', '')
os.environ.pop('APP_USER', None)

import app as A
A.limiter.enabled = False

DAT = HONG = 0
def kiem(ten, dk, ct=''):
    global DAT, HONG
    if dk: DAT += 1; print(f"  DAT  {ten}")
    else:  HONG += 1; print(f"  HONG {ten}" + (f"  -> {ct}" if ct else ''))

print("=== 1. BANG SO CACH ===")
kiem("du 56 bo", len(A._SO_CACH_BO) == 56, str(len(A._SO_CACH_BO)))
kiem("tong so cach = 216", sum(A._SO_CACH_BO.values()) == 216)
kiem("2-3-5 (3 so khac nhau) = 6 cach", A._SO_CACH_BO[(2,3,5)] == 6)
kiem("3-3-5 (co doi) = 3 cach", A._SO_CACH_BO[(3,3,5)] == 3)
kiem("4-4-4 (bo ba) = 1 cach", A._SO_CACH_BO[(4,4,4)] == 1)

print("\n=== 2. XAP XI CHI BINH PHUONG (doi chieu scipy) ===")
try:
    from scipy.stats import chi2 as _sc
    co_scipy = True
except Exception:
    co_scipy = False
if co_scipy:
    xau = []
    for df in (10, 30, 55, 100):
        for q in (0.001, 0.01, 0.05, 0.10, 0.50):
            x = _sc.isf(q, df)
            ta = A._p_chi2(x, df)
            if abs(ta - q) > 0.006:
                xau.append((df, q, round(ta, 4)))
    kiem("sai so < 0,006 tren moi df/p da thu", not xau, str(xau[:4]))
    kiem("df=55, p=0,05 khop", abs(A._p_chi2(_sc.isf(0.05, 55), 55) - 0.05) < 0.005,
         str(round(A._p_chi2(_sc.isf(0.05, 55), 55), 4)))
else:
    print("  (khong co scipy — bo qua doi chieu)")
kiem("chi2=0 -> p=1", abs(A._p_chi2(0, 55) - 1.0) < 0.02, str(A._p_chi2(0, 55)))
kiem("chi2 rat lon -> p ~ 0", A._p_chi2(500, 55) < 1e-6)
kiem("df=0 -> khong chia cho 0", A._p_chi2(10, 0) == 1.0)

print("\n=== 3. CHI DEM KY LIEN TIEP THAT SU ===")
def chay(ky):
    class C:
        def __init__(s): s.sql = ''
        def execute(s, q, *a): s.sql = q
        def fetchone(s): return (len(ky), max(d for d, _ in ky))
        def fetchall(s):
            q = s.sql
            if 'GROUP BY sum_value' in q: return []
            if 'ROW_NUMBER' in q or ' rn ' in q: return []
            if 'numbers' in q: return [(d, str(n)) for d, n in ky]
            return []
        def close(s): pass
    class K:
        def cursor(s): return C()
        def close(s): pass
    with mock.patch.object(A.db, 'get_connection', return_value=K()), \
         mock.patch.object(A, '_trung_vi_theo_tong', return_value={}):
        return A._tinh_thong_ke()

# #101 2-3-5, #102 1-4-6  -> lien tiep, DEM
# #102 -> #105: CACH 2 KY (thieu #103, #104) -> KHONG duoc dem
# #105 3-3-5, #106 2-3-5  -> lien tiep, DEM
ky = [(101, [2,3,5]), (102, [1,4,6]), (105, [6,6,6]), (106, [2,3,5])]
kq = chay(ky)
ts = kq['theo_sau']
kiem("cap lien tiep 235 -> 146 duoc dem",
     ts.get((2,3,5), {}).get((1,4,6)) == 1, str(ts.get((2,3,5))))
kiem("cap VAT QUA LO HONG (146 -> 666) KHONG duoc dem",
     (6,6,6) not in ts.get((1,4,6), {}), str(ts.get((1,4,6))))
kiem("cap lien tiep 666 -> 235 duoc dem",
     ts.get((6,6,6), {}).get((2,3,5)) == 1, str(ts.get((6,6,6))))
tong_cap = sum(sum(v.values()) for v in ts.values())
kiem("tong so cap = 2 (4 ky nhung co mot lo hong)", tong_cap == 2, str(tong_cap))

print("\n=== 4. ENDPOINT ===")
with mock.patch.object(A, '_thong_ke', return_value=kq):
    r = A.app.test_client().get('/api/theo-sau?combo=235')
    j = r.get_json()
kiem("tra 200", r.status_code == 200, str(r.status_code))
kiem("combo = '235'", j.get('combo') == '235', str(j.get('combo')))
kiem("du 56 dong", len(j.get('rows', [])) == 56, str(len(j.get('rows', []))))
kiem("total_after = 1", j.get('total_after') == 1, str(j.get('total_after')))
kiem("dong dau la 146 (nhieu lan nhat)", j['rows'][0]['combo'] == '146', j['rows'][0]['combo'])
kiem("moi dong co 'expected'", all('expected' in x for x in j['rows']))
kiem("co chi2/df/p", all(k in j for k in ('chi2', 'df', 'p')))
kiem("df = 55", j.get('df') == 55, str(j.get('df')))

for dv in ('2-3-5', '2,3,5', '235', ' 235 '):
    with mock.patch.object(A, '_thong_ke', return_value=kq):
        jj = A.app.test_client().get(f'/api/theo-sau?combo={dv}').get_json()
    kiem(f"nhan dinh dang {dv!r}", jj.get('combo') == '235', str(jj.get('combo')))

print("\n=== 5. DAU VAO XAU -> KHONG CHET ===")
class C2:
    def execute(s, *a, **k): pass
    def fetchone(s): return ('[1, 2, 3]',)
    def close(s): pass
class K2:
    def cursor(s): return C2()
    def close(s): pass
for dv in ('', 'abc', '999', '12', '1234', '0'):
    with mock.patch.object(A, '_thong_ke', return_value=kq), \
         mock.patch.object(A.db, 'get_connection', return_value=K2()):
        rr = A.app.test_client().get(f'/api/theo-sau?combo={dv}')
    kiem(f"combo={dv!r} -> 200, roi ve ky moi nhat", rr.status_code == 200,
         str(rr.status_code))

print("\n=== 6. BOARD-STATS KHONG duoc keo theo ma tran nang ===")
with mock.patch.object(A, '_thong_ke', return_value=kq):
    bs = A.app.test_client().get('/api/board-stats').get_json()
kiem("board-stats KHONG co 'theo_sau'", 'theo_sau' not in bs, str(sorted(bs)))
kiem("nhung van du cac khoa dashboard can",
     all(k in bs for k in ('sums', 'triples', 'pairs', 'any', 'pair_any')))
kiem("_thong_ke goc VAN con 'theo_sau' (khong bi xoa nham)", 'theo_sau' in kq)

print("\n=== 7. DU LIEU NGAU NHIEN -> PHAI KET LUAN 'KHONG CO CAU' ===")
# Day la phep kiem quan trong nhat: sinh ky doc lap that su, roi doi hoi
# endpoint noi 'lech khong co y nghia'. Neu no bao co cau tren du lieu ngau
# nhien thi bang nay vo dung va nguy hiem.
random.seed(20260927)
N = 60_000
ky2, dn = [], 100_000
for _ in range(N):
    dn += 1
    ky2.append((dn, sorted(random.randint(1, 6) for _ in range(3))))
kq2 = chay(ky2)
bao_cau = []
for muc in ((2,3,5), (1,4,6), (3,3,5), (4,4,4)):
    with mock.patch.object(A, '_thong_ke', return_value=kq2):
        jj = A.app.test_client().get(
            f"/api/theo-sau?combo={''.join(map(str,muc))}").get_json()
    dinh = jj['rows'][0]
    print(f"  {jj['combo']}: n={jj['total_after']:5d}  dinh={dinh['combo']}"
          f" {dinh['count']:4d} lan (le ra {dinh['expected']})"
          f"  chi2={jj['chi2']:.1f} p={jj['p']:.3f}"
          f"  -> {'BAO CO CAU' if jj['lech_co_y_nghia'] else 'khong co cau'}")
    if jj['lech_co_y_nghia']:
        bao_cau.append(jj['combo'])
kiem("khong bo nao bi bao 'co cau' tren du lieu ngau nhien", not bao_cau, str(bao_cau))

print("\n=== 8. GIAO DIEN phai co cot 'le ra' va cau chot ===")
html = open('templates/dashboard.html', encoding='utf-8').read()
js   = open('static/js/dashboard.js', encoding='utf-8').read()
for i in ('ts-body', 'ts-chon', 'ts-sub', 'ts-verdict', 'ts-note'):
    kiem(f"the co id {i}", f'id="{i}"' in html)
kiem("bang co cot 'Le ra'", 'Lẽ ra' in html)
kiem("JS ve cot expected", 'r.expected' in js)
# Quan trong nhat: phai NOI THANG khi khong co cau.
kiem("JS noi thang 'KHONG co cau' khi p >= 0,05", 'KHÔNG có cầu' in js)
kiem("JS canh bao nhieu phep kiem khi p < 0,05", '2,8 bộ' in js)
kiem("chu thich noi ro bo qua ky sau lo hong", 'lỗ hổng dữ liệu' in js)
kiem("duoc goi trong vong tai", 'loadTheoSau(' in js)
kiem("khong giat lua chon cua nguoi dung", '_sel.value' in js)
css = open('static/css/dashboard.css', encoding='utf-8').read()
kiem("co CSS .sel cho o chon", '.sel {' in css)

print("\n=== 9. ENDPOINT DA DANG KY VAO BO QUET ===")
ds = open('scripts/endpoints_readonly.txt', encoding='utf-8').read().splitlines()
kiem("/api/theo-sau co trong danh sach quet", '/api/theo-sau' in ds,
     "chua dang ky — loi 500 se khong ai biet")

print("\n=== 10. CUA SO n KY (P228) ===")
# Du lieu: 20 ky lien tiep, 235 ra o #1, #10, #18 (so thu tu trong day)
ky3, dn3 = [], 200_000
mau = [[2,3,5],[1,4,6],[3,3,5],[1,2,3],[2,2,4],[5,5,6],[1,1,2],[4,5,6],[3,4,5],
       [2,3,5],[6,6,6],[1,3,5],[2,4,6],[1,1,1],[3,5,6],[2,2,2],[4,4,5],
       [2,3,5],[1,2,6],[3,3,3]]
for m in mau:
    dn3 += 1
    ky3.append((dn3, m))
kq3 = chay(ky3)

class CW:
    def __init__(s, ky): s.ky = ky; s.sql=''
    def execute(s, q, *a):
        s.sql = q; s.args = a[0] if a else ()
    def fetchall(s):
        n = s.args[0] if s.args else len(s.ky)
        return [(d, str(v)) for d, v in sorted(s.ky, key=lambda r: -r[0])[:n]]
    def fetchone(s): return (str(s.ky[-1][1]),)
    def close(s): pass
class KW:
    def __init__(s, ky): s.ky = ky
    def cursor(s): return CW(s.ky)
    def close(s): pass

def goi(combo, n=None):
    q = f'/api/theo-sau?combo={combo}' + (f'&n={n}' if n is not None else '')
    with mock.patch.object(A, '_thong_ke', return_value=kq3), \
         mock.patch.object(A.db, 'get_connection', return_value=KW(ky3)):
        return A.app.test_client().get(q).get_json()

# Toan bo: 235 ra 3 lan, ca ba deu co ky ke tiep -> 3 cap
jt = goi('235')
kiem("toan bo: look_back = 0", jt.get('look_back') == 0, str(jt.get('look_back')))
kiem("toan bo: 3 cap (235 ra 3 lan)", jt['total_after'] == 3, str(jt['total_after']))
kiem("toan bo: theo sau co 666, 224(->225?), ...",
     jt['rows'][0]['count'] >= 1)

# Cua so 5 ky cuoi (#200016..#200020): 235 o #200018 -> ke tiep 126
j5 = goi('235', 5)
kiem("n=5: look_back = 5", j5.get('look_back') == 5, str(j5.get('look_back')))
kiem("n=5: chi 1 cap", j5['total_after'] == 1, str(j5['total_after']))
d126 = [r for r in j5['rows'] if r['combo'] == '126'][0]
kiem("n=5: bo theo sau la 1-2-6", d126['count'] == 1, str(d126))

# Cua so 3 ky cuoi (#200018..#200020) VAN chua 235 o #200018 -> 1 cap.
# Lan dau toi viet test nay cho n=3 va doi 0 cap — TEST SAI, khong phai code.
# Phai lui ve n=2 (#200019, #200020) moi khong con 235 nao.
j3 = goi('235', 3)
kiem("n=3: van 1 cap (235 o #200018 nam trong cua so)",
     j3['total_after'] == 1, str(j3['total_after']))
j2 = goi('235', 2)
kiem("n=2: khong cap nao (cua so khong chua 235)",
     j2['total_after'] == 0, str(j2['total_after']))

print("\n=== 11. MAU IT -> KHONG duoc dua con so p ===")
for n in (None, 5, 100):
    j = goi('235', n)
    if j['total_after'] < 216:
        kiem(f"n={n}: du_mau = False", j.get('du_mau') is False, str(j.get('du_mau')))
        kiem(f"n={n}: p = None (khong dua so rac)", j.get('p') is None, str(j.get('p')))
        kiem(f"n={n}: khong bao 'co cau'", j.get('lech_co_y_nghia') is False)

# Du mau -> phai co p tro lai
kq_lon = chay([(300_000 + i, sorted(random.randint(1,6) for _ in range(3)))
               for i in range(60_000)])
with mock.patch.object(A, '_thong_ke', return_value=kq_lon):
    jl = A.app.test_client().get('/api/theo-sau?combo=235').get_json()
kiem("du mau (n>=216) -> du_mau=True", jl.get('du_mau') is True,
     f"total_after={jl.get('total_after')}")
kiem("du mau -> co con so p", jl.get('p') is not None, str(jl.get('p')))

print("\n=== 12. CUA SO CUNG PHAI BO QUA LO HONG ===")
# #400001 235, #400002 146  (lien tiep -> dem)
# #400005 235, #400009 111  (cach 4 ky -> KHONG dem)
ky4 = [(400001,[2,3,5]), (400002,[1,4,6]), (400005,[2,3,5]), (400009,[1,1,1])]
with mock.patch.object(A, '_thong_ke', return_value=kq3), \
     mock.patch.object(A.db, 'get_connection', return_value=KW(ky4)):
    j4 = A.app.test_client().get('/api/theo-sau?combo=235&n=10').get_json()
kiem("cua so: chi dem cap lien tiep that su", j4['total_after'] == 1,
     str(j4['total_after']))
r146 = [r for r in j4['rows'] if r['combo'] == '146'][0]
kiem("cua so: dung cap 235->146", r146['count'] == 1, str(r146))
r111 = [r for r in j4['rows'] if r['combo'] == '111'][0]
kiem("cua so: cap vat qua lo hong bi loai", r111['count'] == 0, str(r111))

print("\n=== 13. GIAO DIEN: o chon cua so + 3 trang thai ===")
html = open('templates/dashboard.html', encoding='utf-8').read()
js   = open('static/js/dashboard.js', encoding='utf-8').read()
kiem("the co o chon cua so", 'id="ts-ws"' in html)
kiem("co muc 100 ky", '>100 kỳ<' in html)
kiem("co muc toan bo", 'toàn bộ lịch sử' in html)
kiem("JS gui tham so n", "qs.push(`n=" in js)
kiem("JS co nhanh 'Qua it mau'", 'Quá ít mẫu để kết luận' in js)
kiem("JS noi ro vi sao khong co p", 'không có con số p' in js)
kiem("ba trang thai tach biet, khong gop",
     js.count('ts-verdict') >= 1 and 'd.du_mau' in js)

print("\n" + "=" * 54)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
