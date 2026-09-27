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

print("\n" + "=" * 54)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
