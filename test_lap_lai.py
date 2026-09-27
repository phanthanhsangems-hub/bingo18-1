"""P229: trong n kỳ gần nhất, bộ nào RA LẠI và sau nó đã ra những TỔNG nào.

Tôi hiểu sai yêu cầu hai lần trước đó, nên bộ test này ghim lại đúng ba điểm
mà người dùng phải sửa tôi:
  1. trigger là một bộ LẶP LẠI trong cửa sổ — không phải tra cứu từng bộ
  2. nội dung là TỔNG (3..18) — không phải bộ số
  3. phạm vi là n kỳ gần nhất — không phải toàn bộ lịch sử
"""
import os, sys
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

def goi(ky, n=None):
    class C:
        def execute(s, q, *a): s.a = a[0] if a else ()
        def fetchall(s):
            k = s.a[0] if s.a else len(ky)
            return [(d, str(v)) for d, v in sorted(ky, key=lambda r: -r[0])[:k]]
        def close(s): pass
    class K:
        def cursor(s): return C()
        def close(s): pass
    with mock.patch.object(A.db, 'get_connection', return_value=K()):
        q = '/api/lap-lai' + (f'?n={n}' if n is not None else '')
        return A.app.test_client().get(q).get_json()

print("=== 1. CANH DUNG NHU VI DU NGUOI DUNG NEU ===")
# 2-3-5 ra o #1000, roi 3 ky sau (#1003) ra lai.
# Cac ky giua: #1001 tong 11, #1002 tong 6, #1003 tong 10 (chinh la 2-3-5)
ky = [
    (1000, [2,3,5]),   # tong 10
    (1001, [4,4,3]),   # tong 11
    (1002, [1,2,3]),   # tong  6
    (1003, [2,3,5]),   # tong 10  <- ra lai
    (1004, [6,6,6]),   # tong 18
]
j = goi(ky)
kiem("tim ra 1 cap lap", j['so_cap'] == 1, str(j['so_cap']))
c = j['cap'][0]
kiem("dung bo 235", c['combo'] == '235', c['combo'])
kiem("tu #1000 den #1003", (c['tu'], c['den']) == (1000, 1003), str((c['tu'], c['den'])))
kiem("cach 3 ky", c['cach'] == 3, str(c['cach']))
kiem("TONG giua = [11, 6, 10]  <- day la thu nguoi dung muon",
     c['tong_giua'] == [11, 6, 10], str(c['tong_giua']))
kiem("khong co cau nao la 'combo' trong tong_giua",
     all(isinstance(x, int) and 3 <= x <= 18 for x in c['tong_giua']))
kiem("so_bo_lap = 1", j['so_bo_lap'] == 1, str(j['so_bo_lap']))

print("\n=== 2. NHIEU BO LAP -> SAP XEP KHOANG CACH NGAN NHAT TRUOC ===")
ky2 = [
    (2000, [1,2,3]),   # A
    (2001, [4,5,6]),   # B
    (2002, [1,2,3]),   # A lap, cach 2
    (2003, [3,3,3]),
    (2004, [2,2,4]),
    (2005, [4,5,6]),   # B lap, cach 4
    (2006, [1,1,1]),
]
j2 = goi(ky2)
kiem("2 cap", j2['so_cap'] == 2, str(j2['so_cap']))
kiem("cap dau la cai CACH NGAN NHAT (123, cach 2)",
     j2['cap'][0]['combo'] == '123' and j2['cap'][0]['cach'] == 2,
     str(j2['cap'][0]))
kiem("cap sau cach 4", j2['cap'][1]['cach'] == 4, str(j2['cap'][1]['cach']))
kiem("123: tong giua = [15, 6]", j2['cap'][0]['tong_giua'] == [15, 6],
     str(j2['cap'][0]['tong_giua']))

print("\n=== 3. MOT BO RA BA LAN -> HAI CAP LIEN TIEP ===")
ky3 = [(3000,[1,2,3]), (3001,[6,6,6]), (3002,[1,2,3]),
       (3003,[1,1,2]), (3004,[1,2,3])]
j3 = goi(ky3)
kiem("2 cap (3000-3002 va 3002-3004)", j3['so_cap'] == 2, str(j3['so_cap']))
kiem("so_bo_lap van = 1 (cung mot bo)", j3['so_bo_lap'] == 1, str(j3['so_bo_lap']))
cs = sorted(x['tu'] for x in j3['cap'])
kiem("hai cap noi tiep nhau: 3000->3002 va 3002->3004",
     cs == [3000, 3002], str(cs))

print("\n=== 4. LO HONG DU LIEU PHAI DUOC GAN CO ===")
# 123 o #4000 va #4005, nhung thieu #4002, #4003 -> danh sach tong bi hut
ky4 = [(4000,[1,2,3]), (4001,[6,6,6]), (4004,[1,1,2]), (4005,[1,2,3])]
j4 = goi(ky4)
c4 = j4['cap'][0]
kiem("cach van tinh theo SO KY = 5", c4['cach'] == 5, str(c4['cach']))
kiem("chi co 3 tong thay vi 5 -> danh sach BI HUT",
     len(c4['tong_giua']) == 3, str(c4['tong_giua']))
kiem("PHAI gan co thieu_ky = True", c4['thieu_ky'] is True, str(c4['thieu_ky']))
kiem("canh khong thieu ky thi co = False", j['cap'][0]['thieu_ky'] is False)

print("\n=== 5. CUA SO n ===")
kiem("mac dinh n = 160", goi(ky)['look_back'] == 160, str(goi(ky)['look_back']))
kiem("n=300 duoc ton trong", goi(ky, 300)['look_back'] == 300)
kiem("n qua nho bi keo len 10", goi(ky, 1)['look_back'] == 10, str(goi(ky,1)['look_back']))
kiem("n qua lon bi chan 5000", goi(ky, 99999)['look_back'] == 5000)
kiem("n rac -> ve mac dinh 160", goi(ky, 'abc')['look_back'] == 160)
# Cua so co that su thu hep khong. LUU Y: n duoi 10 bi KEP len 10 (dong
# tren vua khang dinh), nen phai dung du lieu dai hon moi thu duoc — lan dau
# toi viet "n=3 -> 0 cap" va tu mau thuan voi chinh phep kiem ke tren.
ky_dai = [(1000, [2,3,5]), (1001, [4,4,3]), (1002, [1,2,3]), (1003, [2,3,5])]
ky_dai += [(1004 + i, [1,1,2]) for i in range(12)]      # 12 ky dem, khong lap 235
kiem("n=100 (phu het) -> co cap 235", goi(ky_dai, 100)['so_cap'] >= 1,
     str(goi(ky_dai, 100)['so_cap']))
j_hep = goi(ky_dai, 10)      # 10 ky cuoi: #1006..#1015, khong chua 235 nao
kiem("n=10 -> cua so THU HEP, khong con cap 235",
     all(c['combo'] != '235' for c in j_hep['cap']),
     str([c['combo'] for c in j_hep['cap']]))

print("\n=== 6. KHONG CO GI LAP / DU LIEU RONG -> KHONG CHET ===")
j5 = goi([(5000,[1,2,3]), (5001,[4,5,6]), (5002,[1,1,2])])
kiem("khong bo nao lap -> 0 cap", j5['so_cap'] == 0 and j5['so_bo_lap'] == 0)
j6 = goi([(6000,[1,2,3])])
kiem("chi 1 ky -> khong chet", j6.get('so_bo_lap') == 0, str(j6))
j7 = goi([])
kiem("rong -> khong chet", j7.get('cap') == [], str(j7))

print("\n=== 7. DA DANG KY VAO BO QUET ===")
ds = open('scripts/endpoints_readonly.txt', encoding='utf-8').read().splitlines()
kiem("/api/lap-lai co trong danh sach quet", '/api/lap-lai' in ds)

print("\n=== 8. GIAO DIEN ===")
html = open('templates/dashboard.html', encoding='utf-8').read()
js   = open('static/js/dashboard.js',   encoding='utf-8').read()
css  = open('static/css/dashboard.css', encoding='utf-8').read()
for i in ('ll-body', 'll-ws', 'll-sub', 'll-note', 'll-table'):
    kiem(f"the co id {i}", f'id="{i}"' in html)
kiem("mac dinh 160 ky duoc chon san", 'value="160" selected' in html)
kiem("cot noi ro la TONG", 'Các tổng đã ra sau đó' in html)
kiem("JS goi /api/lap-lai", '/api/lap-lai?n=' in js)
kiem("JS to mau theo NHO/HOA/LON", "'nho'" in js and "'hoa'" in js and "'lon'" in js)
kiem("JS vien o cuoi (chinh la ky ra lai)", "' dich'" in js)
kiem("JS canh bao khi khoang thieu ky", 'thiếu kỳ' in js)
kiem("chu thich noi ro ~39/56 bo ra lai la BINH THUONG", '~39 trong 56' in js)
kiem("chu thich neu muc TB cua tung loai bo", '36 kỳ' in js and '216 kỳ' in js)
kiem("duoc goi trong vong tai", 'loadLapLai()' in js)
kiem("CSS co .ll-t", '.ll-t {' in css)

print("\n" + "=" * 54)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
