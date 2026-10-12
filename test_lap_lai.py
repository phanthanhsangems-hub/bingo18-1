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

def goi(ky, n=None, combo=None):
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
        qs = []
        if n is not None:     qs.append(f'n={n}')
        if combo is not None: qs.append(f'combo={combo}')
        q = '/api/lap-lai' + ('?' + '&'.join(qs) if qs else '')
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

print("\n=== 8. LOC THEO MOT BO (P230) ===")
ky_l = [
    (7000,[1,2,3]), (7001,[4,5,6]), (7002,[1,2,3]),   # 123 lap, cach 2
    (7003,[3,3,3]), (7004,[4,5,6]), (7005,[1,1,2]),   # 456 lap, cach 3
]
j_all = goi(ky_l)
kiem("khong loc -> 2 cap (123 va 456)", j_all['so_cap'] == 2, str(j_all['so_cap']))
kiem("khong loc -> combo = None", j_all.get('combo') is None, str(j_all.get('combo')))
kiem("khong loc -> so_bo_lap = 2", j_all['so_bo_lap'] == 2, str(j_all['so_bo_lap']))

j_l = goi(ky_l, combo='123')
kiem("loc 123 -> chi 1 cap", j_l['so_cap'] == 1, str(j_l['so_cap']))
kiem("loc 123 -> dung bo do", all(c['combo'] == '123' for c in j_l['cap']),
     str([c['combo'] for c in j_l['cap']]))
kiem("loc 123 -> tra ve combo='123'", j_l.get('combo') == '123', str(j_l.get('combo')))
kiem("loc 123 -> so_bo_lap = 1 (KHONG phai 2)", j_l['so_bo_lap'] == 1,
     str(j_l['so_bo_lap']))
# Day tong GOM CA ky ra lai (o cuoi, giao dien vien lai). #7001 tong 15,
# #7002 tong 6 (chinh la 1-2-3 ra lai). Lan dau toi viet [15] va quen mat
# quy uoc do chinh tay minh dat.
kiem("loc 123 -> tong giua = [15, 6] (o cuoi la chinh ky ra lai)",
     j_l['cap'][0]['tong_giua'] == [15, 6], str(j_l['cap'][0]['tong_giua']))
kiem("  o cuoi = tong cua bo do (1+2+3 = 6)",
     j_l['cap'][0]['tong_giua'][-1] == 6)

j_k = goi(ky_l, combo='666')
kiem("loc bo khong ra lai -> 0 cap", j_k['so_cap'] == 0, str(j_k['so_cap']))
kiem("  van tra ve combo='666'", j_k.get('combo') == '666', str(j_k.get('combo')))
kiem("  so_bo_lap = 0", j_k['so_bo_lap'] == 0, str(j_k['so_bo_lap']))

for dv in ('1-2-3', '1,2,3', '123'):
    kiem(f"nhan dinh dang {dv!r}", goi(ky_l, combo=dv).get('combo') == '123')
for dv in ('abc', '999', '12', '', '0'):
    jj = goi(ky_l, combo=dv)
    kiem(f"combo={dv!r} xau -> khong loc, khong chet",
         jj.get('combo') is None and jj['so_cap'] == 2, str(jj.get('combo')))

print("\n=== 9. THE CU 'theo-sau' DA GO HAN (P230) ===")
for f in ('templates/dashboard.html', 'static/js/dashboard.js',
          'static/css/dashboard.css', 'scripts/endpoints_readonly.txt'):
    t = open(f, encoding='utf-8').read()
    kiem(f"{f}: khong con dau vet 'theo-sau'",
         'theo-sau' not in t and 'ts-body' not in t and 'loadTheoSau' not in t)
ap = open('app.py', encoding='utf-8').read()
for ten in ("@app.route('/api/theo-sau')", "_SO_CACH_BO", "_p_chi2",
            "_theo_sau_cua_so", "'theo_sau':"):
    kiem(f"app.py: da go {ten}", ten not in ap)
import os
kiem("test_theo_sau.py da xoa", not os.path.exists('test_theo_sau.py'))

print("\n=== 10. THE 'BO RA LAI' DA GO KHOI DASHBOARD (P231) ===")
# Nguoi dung: "Bo phan nay ra khoi app chi can gui Telegram".
# Go GIAO DIEN, nhung GIU /api/lap-lai (nguoi dung chon vay).
html = open('templates/dashboard.html', encoding='utf-8').read()
js   = open('static/js/dashboard.js',   encoding='utf-8').read()
css  = open('static/css/dashboard.css', encoding='utf-8').read()
for i in ('ll-body', 'll-ws', 'll-sub', 'll-note', 'll-table', 'll-bo'):
    kiem(f"html: khong con id {i}", f'id="{i}"' not in html)
kiem("html: khong con tieu de the", 'Bộ ra lại' not in html)
kiem("js: khong con loadLapLai", 'loadLapLai' not in js)
kiem("js: khong con goi /api/lap-lai", '/api/lap-lai' not in js)
kiem("css: khong con .ll-t", '.ll-t' not in css)
kiem("css: .sel cung go luon (khong con the nao dung)", '.sel {' not in css)
# DAY LA CHO TOI DA CAT NHAM O P230. Khoa ca hai chieu.
kiem("NHUNG /api/lap-lai VAN CON (nguoi dung chon giu)",
     "@app.route('/api/lap-lai')" in ap)
kiem("va van dang ky trong bo quet endpoint",
     '/api/lap-lai' in open('scripts/endpoints_readonly.txt', encoding='utf-8').read())
kiem("cac the KHAC khong bi cat nham",
     'dd-body' in html and 'tr-body' in html and 'loadPairStats' in js)

print("\n=== 11. TIM BO RA LAI — LOI CUA HAM CANH BAO ===")
# (draw_number, bo, tong). 235 ra o #100 roi ra lai o #103 -> cach 3.
ky = [(100, (2,3,5), 10), (101, (1,1,4), 6), (102, (6,6,6), 18),
      (103, (2,3,5), 10), (104, (1,2,3), 6)]
r = A._tim_bo_ra_lai(ky, moc=102)          # chi xet ky > 102
kiem("chi bat ky MOI (#103, #104)", len(r) == 1, f"{r}")
e = r[0]
kiem("dung bo 235", e['combo'] == '235', e['combo'])
kiem("cach dung 3 ky", e['cach'] == 3, e['cach'])
kiem("tu #100 den #103", (e['tu'], e['den']) == (100, 103))
# Day la cho toi tung tu viet sai test o P230: co gom ky ra lai hay khong.
kiem("tong_giua KHONG gom ky ra lai -> [6, 18]", e['tong_giua'] == [6, 18],
     str(e['tong_giua']))
kiem("tong cua chinh ky ra lai tach rieng = 10", e['tong_lap'] == 10)
kiem("moi phan tu tong_giua la TONG 3..18",
     all(3 <= t <= 18 for t in e['tong_giua']))
kiem("khong gan co thieu ky", e['thieu_ky'] is False)

r2 = A._tim_bo_ra_lai(ky, moc=99)          # xet tu #100 -> khong co gi truoc no
kiem("moc thap hon van chi ra 1 su kien", len(r2) == 1)

print("\n=== 12. NGUONG KHOANG CACH ===")
xa = [(200, (2,3,5), 10)] + [(200+i, (1,1,i%6+1), 5) for i in range(1, 12)] \
     + [(212, (2,3,5), 10)]
kiem("cach 12 ky: KHONG bao o nguong 10",
     not [e for e in A._tim_bo_ra_lai(xa, moc=211, gap=10) if e['combo'] == '235'])
kiem("cach 12 ky: CO bao o nguong 15",
     any(e['combo'] == '235' for e in A._tim_bo_ra_lai(xa, moc=211, gap=15)))
kiem("nguong mac dinh dung _LAPLAI_ALERT_GAP",
     A._tim_bo_ra_lai(xa, moc=211) == A._tim_bo_ra_lai(xa, moc=211,
                                                       gap=A._LAPLAI_ALERT_GAP))
# P246: nguoi dung chon "moi lan ra" = trong cua so 160 ky cua day tong.
kiem("nguong dang dat la 160 = cua so day tong (P246: moi lan ra)",
     A._LAPLAI_ALERT_GAP == 160 == A._LAPLAI_CUA_SO_SAU)
kiem("cach 12 ky: CO bao o nguong mac dinh (P246)",
     any(e['combo'] == '235' for e in A._tim_bo_ra_lai(xa, moc=211)))
xa2 = [(1000, (2,3,5), 10)] + [(1000+i, (1,1,i%6+1), 5) for i in range(1, 158)] \
      + [(1158, (2,3,5), 10)]
kiem("cach 158 ky: van bao", any(e['combo'] == '235' for e in A._tim_bo_ra_lai(xa2, moc=1157)))

print("\n=== 13. LO HONG DU LIEU ===")
# Thieu #102 -> day tong giua bi hut, phai gan co.
thung = [(100, (2,3,5), 10), (101, (1,1,4), 6), (103, (2,3,5), 10)]
e = A._tim_bo_ra_lai(thung, moc=102)[0]
kiem("van do cach bang HIEU SO KY = 3 (khong phai 2 dong con lai)",
     e['cach'] == 3, e['cach'])
kiem("day tong bi hut chi con [6]", e['tong_giua'] == [6], str(e['tong_giua']))
kiem("VA duoc gan co thieu_ky", e['thieu_ky'] is True)
# Ky lien truoc thieu han -> khong duoc suy dien bua
mat = [(100, (2,3,5), 10), (102, (2,3,5), 10)]
kiem("van bat duoc khi ky giua thieu", len(A._tim_bo_ra_lai(mat, moc=101)) == 1)

print("\n=== 14. CHI LAY LAN RA LAI GAN NHAT ===")
ba = [(100, (2,3,5), 10), (101, (1,1,1), 3), (102, (2,3,5), 10)]
r = A._tim_bo_ra_lai(ba, moc=101)
kiem("mot su kien cho #102", len(r) == 1)
kiem("lay lan gan nhat (#100) chu khong nhay xa hon", r[0]['tu'] == 100)
kiem("khong co gi lap -> rong",
     A._tim_bo_ra_lai([(1,(1,2,3),6), (2,(4,5,6),15)], moc=0) == [])
kiem("danh sach rong -> khong chet", A._tim_bo_ra_lai([], moc=0) == [])

print("\n=== 15. TIN MOI KY (P260) — WATCHER GUI 1 TIN/KY ===")
# Truoc P260: 3 tin/ky (ket qua tho + THANG/THUA o Cloud Run + nhac 2 phut) va tin
# "bo ra lai" rieng o ~73% so ky. Nay: MOT tin do watcher gui ngay khi co ky moi.
import sqlite3, json as _js
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'x'); os.environ.setdefault('TELEGRAM_CHAT_ID', '1')
import sync_to_supabase as S
import lap_lai as LL
S.TELEGRAM_TOKEN, S.TELEGRAM_CHAT = 'x', '1'

class _Cur:                      # psycopg2-style %s -> sqlite ?
    def __init__(s, k): s.c = k.cursor()
    def execute(s, q, a=()): s.c.execute(q.replace('%s', '?'), a); return s
    def fetchall(s): return s.c.fetchall()
    def fetchone(s): return s.c.fetchone()
    @property
    def rowcount(s): return s.c.rowcount
    def close(s): s.c.close()
class _Conn:
    def __init__(s, k): s.k = k
    def cursor(s): return _Cur(s.k)
    def commit(s): s.k.commit()
    def rollback(s): s.k.rollback()

def db_moi(ky, du_doan=()):
    """ky: [(dn, bo)]; du_doan: [(dn, bo, win_prob)]. Cot/kieu giong DB that."""
    k = sqlite3.connect(':memory:')
    k.executescript("""
      CREATE TABLE draw_history (draw_number INT PRIMARY KEY, numbers TEXT);
      CREATE TABLE predictions (id INTEGER PRIMARY KEY, draw_number INT, predicted_numbers TEXT,
                                win_prob REAL, confidence REAL);
      CREATE TABLE system_config (config_key TEXT PRIMARY KEY, config_value TEXT,
                                  description TEXT, updated_at TIMESTAMP);
    """)
    for dn, bo in ky:
        k.execute("INSERT INTO draw_history VALUES (?,?)", (dn, str(list(bo))))   # watcher luu str(list)
    for dn, bo, wp in du_doan:
        k.execute("INSERT INTO predictions (draw_number, predicted_numbers, win_prob, confidence) "
                  "VALUES (?,?,?,?)", (dn, _js.dumps(list(bo)), wp, 0.6))
    k.commit()
    return k

def gui(k, dn, bo, tra=True):
    da_gui = []
    with mock.patch.object(S, '_tg_html', side_effect=lambda t: (da_gui.append(t), tra)[1]):
        ok = S.gui_tin_ky(_Conn(k), {'draw_id': dn, 'numbers': list(bo)})
    return da_gui, ok
def nk(k):
    r = k.execute("SELECT config_value FROM system_config WHERE config_key=?", (LL.NK_KEY,)).fetchone()
    return _js.loads(r[0]) if r else []

# 235 ra o #100 (ky sau #101 tong 6) roi ra lai o #103. Du doan #103 = 1-2-6 (9 NHO) vs 10 HOA -> THUA.
# Chuoi truoc: #100 L (1-2-3 vs HOA), #101 W, #102 W.
k = db_moi([(100,(2,3,5)), (101,(1,1,4)), (102,(6,6,6)), (103,(2,3,5))],
           [(100,(1,2,3),0.4), (101,(1,2,3),0.4), (102,(4,5,6),0.4), (103,(1,2,6),0.42), (104,(2,4,6),0.41)])
tins, ok = gui(k, 103, (2,3,5))
tin = tins[0] if tins else ''
kiem("gui DUNG MOT tin", len(tins) == 1, len(tins))
kiem("tieu de KY #103 — THUA", 'KỲ #103 — THUA' in tin, tin)
kiem("ket qua + size", 'Kết quả <b>2·3·5 (10 HÒA)</b>' in tin, tin)
kiem("du doan cua ky nay + khop", 'Dự đoán 1·2·6 (9 NHỎ)' in tin and 'Khớp 1/3' in tin, tin)
kiem("chuoi W/L 3 ky truoc + ky nay: L W W L", '❌  ✅  ✅  ❌  ← kỳ này' in tin, tin)
kiem("dong RA LAI: sau 3 ky", '🔁 Ra lại sau <b>3</b> kỳ' in tin, tin)
kiem("P238: tong cua ky NGAY SAU lan truoc (#101 = 6)", 'ra tổng: <b>6</b>' in tin, tin)
kiem("du doan KY TOI #104 kem win_prob 41%", 'Kỳ tới <b>#104</b>: <b>2·4·6 (12 LỚN)</b> · 41%' in tin, tin)
kiem("khong con tin rieng 'vừa ra lại'", 'vừa ra lại' not in tin)
m = nk(k)
kiem("nhat ky: 1 muc den=103 combo=235 cach=3 ok=True", len(m) == 1 and (m[0]['den'], m[0].get('combo'), m[0].get('cach'), m[0]['ok']) == (103, '235', 3, True), m)
kiem("nguon = watcher", m[0].get('nguon') == 'watcher')

print("\n--- khong ra lai, khong co du doan ---")
k = db_moi([(200,(1,2,3)), (201,(4,5,6))])
tins, ok = gui(k, 201, (4,5,6))
tin = tins[0]
kiem("van gui tin (ket qua)", 'KỲ #201' in tin and 'Kết quả <b>4·5·6 (15 LỚN)</b>' in tin, tin)
kiem("noi ro khong co du doan", 'không có dự đoán' in tin, tin)
kiem("khong co dong ra lai", '🔁' not in tin)
kiem("ky toi: chua co du doan", 'chưa có dự đoán' in tin, tin)
m = nk(k)
kiem("nhat ky: muc KHONG co 'combo' (de P245 khong tinh la 'bao thua')", len(m) == 1 and 'combo' not in m[0] and m[0]['den'] == 201, m)

print("\n--- trip ---")
k = db_moi([(300,(1,2,3)), (301,(5,5,5))], [(301,(1,2,3),0.4)])
tin = gui(k, 301, (5,5,5))[0][0]
kiem("trip: dong dau TRIPLE 5-5-5", tin.startswith('🎰🎰🎰 <b>TRIPLE 5-5-5</b>'), tin)
kiem("trip van co THANG/THUA (15 LON vs 6 NHO -> THUA)", 'THUA' in tin)

print("\n--- ky ngay sau bi thieu -> '?' ---")
k = db_moi([(500,(1,2,3)), (502,(4,5,6)), (503,(1,2,3))])
tin = gui(k, 503, (1,2,3))[0][0]
kiem("hien '?' va giai thich", 'ra tổng: <b>?</b>' in tin and 'kỳ sau bị thiếu' in tin, tin)

print("\n--- Telegram tu choi -> ghi ok=False, khong nem loi ---")
k = db_moi([(600,(1,2,3)), (601,(1,2,3))])
tins, ok = gui(k, 601, (1,2,3), tra=False)
kiem("tra False", ok is False)
kiem("nhat ky ghi ok=False (diagnose P245 se bao 'hong')", nk(k)[0]['ok'] is False, nk(k))

print("\n--- DB hong luc soan -> van gui tin toi thieu ---")
k = db_moi([(700,(2,2,6))])
with mock.patch.object(S, 'doc_du_lieu_tin_ky', side_effect=RuntimeError('DB chet')):
    tins, ok = gui(k, 700, (2,2,6))
kiem("van gui 1 tin", len(tins) == 1 and 'KỲ #700' in tins[0] and '2·2·6' in tins[0], tins)
kiem("nhat ky van ghi (ket noi con)", nk(k) and nk(k)[0]['den'] == 700, nk(k))

print("\n--- bat kip nhieu ky: 1 tin tom tat + 1 tin day du ---")
k = db_moi([(800,(1,2,3)), (801,(4,5,6)), (802,(1,2,3)), (803,(2,3,4)), (804,(4,5,6))],
           [(804,(1,2,3),0.4), (805,(2,2,2),0.39)])
da_gui = []
with mock.patch.object(S, '_tg_html', side_effect=lambda t: (da_gui.append(t), True)[1]):
    S.gui_tin_bat_kip(_Conn(k), [{'draw_id': d, 'numbers': list(b)} for d, b in
                                 [(802,(1,2,3)), (803,(2,3,4)), (804,(4,5,6))]])
kiem("dung 2 tin", len(da_gui) == 2, len(da_gui))
kiem("tin 1: 'Bắt kịp 3 kỳ' + tung ky cu, 🔁 cho #802 (ra lai sau 2)", 'Bắt kịp 3 kỳ' in da_gui[0]
     and '#802: 1·2·3 (6 NHỎ) 🔁 sau 2 kỳ' in da_gui[0] and '#803: 2·3·4 (9 NHỎ)' in da_gui[0], da_gui[0])
kiem("tin 1 KHONG gom ky moi nhat", '#804' not in da_gui[0])
kiem("tin 2: day du cho #804 (ra lai sau 3, ky toi #805)", 'KỲ #804' in da_gui[1] and 'Ra lại sau <b>3</b>' in da_gui[1]
     and 'Kỳ tới <b>#805</b>' in da_gui[1], da_gui[1])
m = nk(k)
kiem("nhat ky: 3 muc (802 combo, 803 khong combo, 804 combo)", [(x['den'], x.get('combo')) for x in m] == [(802,'123'),(803,None),(804,'456')], m)
kiem("muc bat kip ghi nguon rieng", m[0]['nguon'] == 'watcher_bat_kip' and m[2]['nguon'] == 'watcher')

print("\n--- nhat ky xoay vong ---")
k = db_moi([(900,(1,2,3))])
c = _Cur(k)
LL.ghi_nhat_ky(c, [LL.muc_nhat_ky(i, None, True) for i in range(LL.NK_MAX + 50)]); k.commit()
kiem(f"giu toi da {LL.NK_MAX} muc moi nhat", len(nk(k)) == LL.NK_MAX and nk(k)[-1]['den'] == LL.NK_MAX + 49)

print("\n=== 16. CHI MOT NGUON GUI: Cloud Run khong gui tin ky, watcher khong gui tin le ===")
ps = open('prediction_service.py', encoding='utf-8').read()
tb = open('telegram_bot.py', encoding='utf-8').read()
wt = open('sync_to_supabase.py', encoding='utf-8').read()
ap = open('app.py', encoding='utf-8').read()
kiem("prediction_service: khong con send_result", 'send_result(' not in ps)
kiem("telegram_bot: bo send_result", 'def send_result' not in tb)
kiem("app: bo _check_lap_lai_alert (tin rieng)", '_check_lap_lai_alert' not in ap)
kiem("app: dung ham thuan tu lap_lai", 'from lap_lai import' in ap and A._tim_bo_ra_lai is LL.tim_bo_ra_lai)
kiem("watcher: bo tin ket qua tho (send_telegram), nhac 2 phut, announce",
     'def send_telegram(' not in wt and '_send_play_reminder' not in wt and 'announce_prediction' not in wt)
kiem("watcher: mode_watch goi gui_tin_ky / gui_tin_bat_kip", 'gui_tin_ky(conn, da_chen[0])' in wt and 'gui_tin_bat_kip(conn, da_chen)' in wt)
kiem("watcher: gui tin SAU khi da bat trigger (khong cho Cloud Run)",
     wt.index('threading.Thread(target=trigger_prediction') < wt.index('gui_tin_ky(conn, da_chen[0])'))
kiem("_tg_html / _tg_send tra bool", 'def _tg_html(text: str) -> bool' in wt and 'def _tg_send(text: str) -> bool' in wt)

print("\n=== 17. /api/canh-bao/lap-lai: doc tu nhat ky ===")
NK = [{'luc':'2026-10-12 10:00:00','den':190900,'ok':True,'nguon':'watcher'},
      {'luc':'2026-10-12 10:06:00','den':190901,'combo':'235','cach':4,'ok':False,'nguon':'watcher'},
      {'luc':'2026-10-12 10:12:00','den':190902,'combo':'114','cach':9,'ok':True,'nguon':'watcher'}]
class C2:
    def execute(s, q, *a): s.q = q; s.a = a[0] if a else ()
    def fetchone(s):
        if 'MAX(draw_number)' in s.q: return (190903,)
        if s.a and s.a[0] == LL.NK_KEY: return (_js.dumps(NK),)
        return None
    def close(s): pass
class K2:
    def cursor(s): return C2()
    def close(s): pass
with mock.patch.object(A.db, 'get_connection', return_value=K2()):
    r = A.app.test_client().get('/api/canh-bao/lap-lai')
dd = r.get_json()
kiem("tra 200", r.status_code == 200, str(r.status_code))
kiem("nhat_ky nguyen ven", dd['nhat_ky'] == NK)
kiem("lan_chay_gan_nhat = muc cuoi", dd['lan_chay_gan_nhat']['den'] == 190902)
kiem("gui_duoc_cuoi / hong_cuoi / so_hong", dd['gui_duoc_cuoi']['den'] == 190902 and dd['hong_cuoi']['den'] == 190901 and dd['so_hong'] == 1, dd)
kiem("ky_moi_nhat + nguong_cach 160", dd['ky_moi_nhat'] == 190903 and dd['nguong_cach'] == 160)
kiem("dang ky vao bo quet", '/api/canh-bao/lap-lai' in open('scripts/endpoints_readonly.txt', encoding='utf-8').read())

print("\n=== 18. DIAGNOSE doi chieu theo nhat ky moi ===")
dg = open('.github/workflows/diagnose.yml', encoding='utf-8').read()
kiem("P245 chi doi chieu ky watcher da gui (da_xet)", "k[0] in da_xet" in dg and "da_xet = {m['den']" in dg)
kiem("buoc 'Tin moi ky (P260)' bao tut hau / gui hong", 'Tin mỗi kỳ (P260)' in dg and 'nhat ky tut hau' in dg and 'lan gan nhat gui hong' in dg)

print("\n" + "=" * 54)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
