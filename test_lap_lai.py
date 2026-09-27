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
kiem("nguong dang dat la 10 (nguoi dung chon)", A._LAPLAI_ALERT_GAP == 10)

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

print("\n=== 15. TIN TELEGRAM ===")
def chay_canh_bao(ky, moc, gio=12):
    """Chay _check_lap_lai_alert, tra ve (tin da gui hoac None, moc da ghi)."""
    ghi = {}
    class C:
        def execute(s, q, *a):
            s.q = q; s.a = a[0] if a else ()
            if 'system_config' in q and q.strip().upper().startswith('SELECT'):
                s.mode = 'moc'
            elif 'system_config' in q:
                ghi['moc'] = int(s.a[1]); s.mode = 'ghi'
            else:
                s.mode = 'ky'
        def fetchone(s):
            return None if moc is None else (str(moc),)
        def fetchall(s):
            k = s.a[0] if s.a else len(ky)
            return [(d, str(list(b))) for d, b, _ in sorted(ky, key=lambda r: -r[0])[:k]]
        def close(s): pass
    class K:
        def cursor(s): return C()
        def commit(s): pass
        def close(s): pass
    import datetime as _dt
    from zoneinfo import ZoneInfo
    that = _dt.datetime(2026, 9, 27, gio, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    class FakeDT(_dt.datetime):
        @classmethod
        def now(cls, tz=None): return that
    gui = []
    bot = mock.MagicMock()
    bot.return_value.send_message.side_effect = lambda m, *a, **k: gui.append(m)
    with mock.patch.object(A.db, 'get_connection', return_value=K()), \
         mock.patch.object(A, 'datetime', FakeDT), \
         mock.patch.dict('sys.modules', {'telegram_bot': mock.MagicMock(TelegramBot=bot)}):
        A._check_lap_lai_alert()
    return (gui[0] if gui else None), ghi.get('moc')

ky = [(100, (2,3,5), 10), (101, (1,1,4), 6), (102, (6,6,6), 18),
      (103, (2,3,5), 10)]
tin, moc_moi = chay_canh_bao(ky, moc=102)
kiem("co gui tin", tin is not None)
kiem("tin neu ten bo dang 2-3-5", '2-3-5' in (tin or ''))
kiem("tin noi ro cach may ky", 'ra lại sau <b>3 kỳ</b>' in (tin or ''))
kiem("tin co ca hai moc ky", '#100' in (tin or '') and '#103' in (tin or ''))
kiem("tin liet ke TONG o giua (6, 18)",
     'Tổng các kỳ ở giữa' in (tin or '') and '6 · 18' in (tin or ''))
kiem("tin TACH RIENG tong cua ky ra lai",
     'Tổng của chính kỳ ra lại: <b>10</b>' in (tin or ''))
kiem("tin ghi ro nguong dang dung", '≤ 10 kỳ' in (tin or ''))
kiem("da ghi moc moi = ky moi nhat", moc_moi == 103, str(moc_moi))

print("\n=== 16. KHONG DUOC SPAM ===")
tin, moc_moi = chay_canh_bao(ky, moc=103)
kiem("khong co ky moi -> KHONG gui gi", tin is None)

# Lan dau chay (mat state / vua deploy): chot moc, KHONG bung mot trang tin.
tin, moc_moi = chay_canh_bao(ky, moc=None)
kiem("lan dau chay: KHONG gui tin nao", tin is None)
kiem("lan dau chay: van chot moc = ky moi nhat", moc_moi == 103, str(moc_moi))

# Ngoai gio xo thi im
tin, _ = chay_canh_bao(ky, moc=102, gio=23)
kiem("23h: im lang", tin is None)
tin, _ = chay_canh_bao(ky, moc=102, gio=5)
kiem("5h: im lang", tin is None)
tin, _ = chay_canh_bao(ky, moc=102, gio=6)
kiem("6h: co bao", tin is not None)

print("\n=== 17. NGUOI MAY LAU -> KHONG BU MOT TRANG ===")
# 300 ky moi ke tu moc, ky nao cung 111 -> ky nao cung "ra lai sau 1 ky".
# Neu khong chan, se bu ca 300 ky va bung ra mot trang tin.
dai = [(500 + i, (1, 1, 1), 3) for i in range(300)]
tin, moc_moi = chay_canh_bao(dai, moc=500)
kiem("van chot moc len ky moi nhat", moc_moi == 799, str(moc_moi))
kiem("CO gui tin (khong duoc im lang)", tin is not None)
kiem(f"chi liet ke toi da {A._LAPLAI_MAX_LIET_KE} su kien",
     tin.count('ra lại sau') == A._LAPLAI_MAX_LIET_KE,
     str(tin.count('ra lại sau')))
kiem("co ghi chu '+N lan nua'", 'lần nữa)' in tin)
# Chan bu: chi xet _LAPLAI_MAX_CATCHUP ky gan nhat, nen su kien cu nhat
# khong duoc som hon moc nay.
som_nhat = 799 - A._LAPLAI_MAX_CATCHUP
su = A._tim_bo_ra_lai([(d, b, t) for d, b, t in dai],
                      moc=max(500, 799 - A._LAPLAI_MAX_CATCHUP))
kiem(f"khong bu qua {A._LAPLAI_MAX_CATCHUP} ky",
     len(su) <= A._LAPLAI_MAX_CATCHUP, str(len(su)))
kiem("va khong dung toi ky qua cu",
     all(e['den'] > som_nhat for e in su))

print("\n=== 18. CANH BAO HONG KHONG DUOC LAM CHET VONG DU DOAN ===")
with mock.patch.object(A.db, 'get_connection', side_effect=RuntimeError('DB die')):
    try:
        A._check_lap_lai_alert()
        kiem("DB chet -> nuot loi, khong nem ra ngoai", True)
    except Exception as ex:
        kiem("DB chet -> nuot loi, khong nem ra ngoai", False, repr(ex))
kiem("da duoc goi trong /api/predict", '_check_lap_lai_alert()' in ap)
kiem("moc luu o system_config (song qua nguoi may), khong phai bien RAM",
     "_LAPLAI_STATE_KEY" in ap and "system_config" in ap)

print("\n" + "=" * 54)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
