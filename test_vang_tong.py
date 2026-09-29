"""P244: /api/tong/vang-lau-nhat — tong vang lau nhat bao nhieu ky."""
import os, sys
from unittest import mock
os.environ.setdefault('DATABASE_URL', '')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as A

DAT = HONG = 0
def kiem(ten, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {ten}" + ('' if ok else f"  -> {ct}"))

# tong 4 ra o ky 100, 105, 106, 120 (du lieu lien tuc) -> vang 4, 0, 13
rows = [(d, 4 if d in (100, 105, 106, 120) else 10, f'2026-09-01 00:{d-100:02d}') for d in range(100, 125)]
r = A._vang_theo_tong(rows)
t4 = r['4']
kiem("so lan", t4['so_lan'] == 4, t4)
kiem("vang lau nhat = 13 ky", t4['vang_lau_nhat']['so_ky'] == 13, t4)
kiem("dung khoang 106 -> 120", (t4['vang_lau_nhat']['tu_ky'], t4['vang_lau_nhat']['den_ky']) == (106, 120))
kiem("dang vang = 4 ky (121..124)", t4['dang_vang'] == 4, t4['dang_vang'])
kiem("top xep giam dan", [k['so_ky'] for k in t4['top']] == [13, 4, 0])
kiem("tong chua ra lan nao -> None, khong chet", r['3']['vang_lau_nhat'] is None and r['3']['dang_vang'] == 25)
kiem("du 16 tong", sorted(map(int, r)) == list(range(3, 19)))

# DB thieu ky 110..114: so ky that 8, theo so ky 13 -> phai lech de lo ra
thung = [x for x in rows if not 110 <= x[0] <= 114]
v = A._vang_theo_tong(thung)['4']['vang_lau_nhat']
kiem("thieu ky -> so_ky dem ky that (8)", v['so_ky'] == 8, v)
kiem("... va theo_so_ky van la 13 de lo lech", v['theo_so_ky'] == 13, v)

class C:
    def execute(s, q, *a): s.q = q
    def fetchall(s): return [(d, None if d == 101 else t, str([1,1,2]) if t == 4 else str([3,3,4]), dt) for d, t, dt in rows]
    def fetchone(s): return None
class K:
    def cursor(s): return C()
    def close(s): pass
with mock.patch.object(A.db, 'get_connection', return_value=K()):
    res = A.app.test_client().get('/api/tong/vang-lau-nhat')
d = res.get_json()
kiem("endpoint 200", res.status_code == 200, res.status_code)
kiem("endpoint tra tong 4 vang 13", d['tong']['4']['vang_lau_nhat']['so_ky'] == 13, d)
kiem("sum_value NULL -> tinh tu numbers", d['tong_so_ky'] == 25, d.get('tong_so_ky'))
kiem("dang ky vao bo quet", '/api/tong/vang-lau-nhat' in open('scripts/endpoints_readonly.txt', encoding='utf-8').read())

print("\n=== P248: TRUNG VI / TB / PHAN VI ===")
kh = [{'so_ky': x, 'theo_so_ky': x} for x in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)] + \
     [{'so_ky': 50, 'theo_so_ky': 900}]              # khoang de len lo thung -> bo
tk = A._thong_ke_khoang(kh)
kiem("bo khoang thung du lieu", tk['so_khoang_sach'] == 10 and tk['so_khoang_bo'] == 1, tk)
kiem("trung vi = 5", tk['trung_vi'] == 5, tk)
kiem("TB = 5.5", tk['tb_sach'] == 5.5, tk)
kiem("P90 = 9, ky luc = 10", tk['p90'] == 9 and tk['ky_luc'] == 10, tk)
kiem("khong co khoang -> None, khong chet", A._thong_ke_khoang([])['trung_vi'] is None)
kiem("tong 4 va 17 cung xac suat 3/216", A._WAYS_TONG[4] == 3 == A._WAYS_TONG[17])

print("\n=== P248: CANH BAO VANG TONG — SQLITE THAT ===")
import sqlite3, tempfile, json as _j, datetime as _dt
from zoneinfo import ZoneInfo
f = tempfile.NamedTemporaryFile(suffix='.db', delete=False).name
k0 = sqlite3.connect(f)
k0.executescript("""CREATE TABLE draw_history (draw_number INT, numbers TEXT, sum_value INT, draw_time TEXT);
  CREATE TABLE system_config (config_key TEXT PRIMARY KEY, config_value TEXT, description TEXT,
                              updated_at TEXT DEFAULT CURRENT_TIMESTAMP);""")
def them(dn, bo):
    k0.execute("INSERT INTO draw_history VALUES (?,?,?,?)", (dn, _j.dumps(bo), sum(bo), '2026-09-29'))
    k0.commit()
# lich su: tong 4 (1-1-2) cach nhau 10 ky deu -> trung vi = TB = P90 = ky luc = 10
dn = 1000
for _ in range(8):
    them(dn, [1, 1, 2]); dn += 1
    for _ in range(10):
        them(dn, [3, 3, 4]); dn += 1      # tong 10
them(dn, [1, 1, 2]); dn += 1              # lan ra cuoi
# tong 17 (5-6-6) chi ra 1 lan dau
k0.execute("UPDATE draw_history SET numbers='[5,6,6]', sum_value=17 WHERE draw_number=1001"); k0.commit()
gui = []
def chay(gio=12):
    that = _dt.datetime(2026, 9, 29, gio, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    class FDT(_dt.datetime):
        @classmethod
        def now(cls, tz=None): return that
    bot = mock.MagicMock()
    bot.return_value.send_message.side_effect = lambda m, *a, **kw: gui.append(m) or True
    A._vang_tk_cache.update({'luc': 0.0, 'tk': None})
    with mock.patch.object(A.db, 'get_connection', side_effect=lambda: sqlite3.connect(f)), \
         mock.patch.object(A, 'USE_POSTGRES', False), mock.patch.object(A, 'datetime', FDT), \
         mock.patch.dict('sys.modules', {'telegram_bot': mock.MagicMock(TelegramBot=bot)}):
        A._check_vang_tong_alert('test')
def tt():
    r = k0.execute("SELECT config_value FROM system_config WHERE config_key='vang_tong_trang_thai'").fetchone()
    return _j.loads(r[0]) if r else None
def loi():
    r = k0.execute("SELECT config_value FROM system_config WHERE config_key='vang_tong_loi'").fetchone()
    return r[0] if r else None

chay()
kiem("lan dau: chot trang thai, KHONG gui", tt() is not None and not gui, (tt(), gui))
kiem("khong co loi", loi() is None, loi())
for _ in range(10):
    them(dn, [3, 3, 4]); dn += 1          # vang 10 ky = vuot moi moc (deu = 10)
chay()
kiem("vang du 10 ky -> gui 1 tin", len(gui) == 1, gui)
kiem("tin neu tong 4 va so ky vang", gui and 'Tổng 4</b> đã vắng <b>10</b>' in gui[0], gui)
kiem("tin noi thang: vang lau KHONG lam de ra hon", gui and 'KHÔNG làm' in gui[0] and '1.4%' in gui[0], gui)
chay()
kiem("goi lai, khong co gi moi -> KHONG gui trung", len(gui) == 1, len(gui))
them(dn, [1, 1, 2]); dn += 1             # tong 4 ra lai sau 10 ky
chay()
kiem("tong 4 vua ra -> bao ra sau 10 ky", len(gui) == 2 and 'Tổng 4</b> vừa ra' in gui[1] and 'sau <b>10</b>' in gui[1], gui[-1:])
kiem("... kem xep loai so voi lich su", 'RẤT TRỄ' in gui[1] or 'BÌNH THƯỜNG' in gui[1], gui[-1:])
kiem("... va dat lai moc da bao", tt()['4']['da_bao'] == [], tt())
n = len(gui); chay(gio=23)
kiem("23h: im lang", len(gui) == n)
# duong kia vua doi trang thai -> khong gui trung
for _ in range(10):
    them(dn, [3, 3, 4]); dn += 1
cu = k0.execute("SELECT config_value FROM system_config WHERE config_key='vang_tong_trang_thai'").fetchone()[0]
orig = A._vang_hien_tai
def xen(cur, t):
    k0.execute("UPDATE system_config SET config_value='{\"x\":1}' WHERE config_key='vang_tong_trang_thai'"); k0.commit()
    return orig(cur, t)
with mock.patch.object(A, '_vang_hien_tai', side_effect=xen):
    chay()
kiem("duong kia doi trang thai giua chung -> KHONG gui", len(gui) == n, gui[n:])
kiem("goi tu /api/predict va /api/trigger-prediction",
     "_check_vang_tong_alert('predict')" in open('app.py', encoding='utf-8').read()
     and "_check_vang_tong_alert('trigger')" in open('app.py', encoding='utf-8').read())

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
