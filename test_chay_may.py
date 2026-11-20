"""P298: chạy app trên máy nhà (chay_may.py) thay Cloud Run + watcher gọi app trong máy.

Phần 1: hàm thuần (DATABASE_URL từ DB_*, lịch hẹn giờ, che mật khẩu/token, kiểm tra cài đặt).
Phần 2: giờ tiến trình phải là UTC (mã viết cho Cloud Run lưu datetime.now() như giờ UTC).
Phần 3: chạy THẬT app bằng waitress trên SQLite + bộ hẹn giờ gọi /api/predict, /api/daily-summary.
Phần 4: watcher: app trong máy sống -> gọi trong máy; chết / lỗi -> Cloud Run.
Phần 5: file .bat (CRLF, TZ=UTC0, không taskkill /IM python.exe).
"""
import json, logging, os, re, socket, subprocess, sys, tempfile, threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GOC = os.path.dirname(os.path.abspath(__file__))
os.chdir(GOC)
sys.path.insert(0, GOC)
_TMP = tempfile.mkdtemp()
_DB = os.path.join(_TMP, 'may.db')
for k in ('DATABASE_URL', 'DB_HOST', 'DB_USER', 'DB_PASSWORD', 'APP_USER', 'APP_PASSWORD'):
    os.environ.pop(k, None)
os.environ.update(DB_PATH=_DB, TRIGGER_SECRET='bi-mat-test', ADMIN_SECRET_KEY='admin-test',
                  TELEGRAM_BOT_TOKEN='x', TELEGRAM_CHAT_ID='x')
import chay_may as C

DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))

print("=== 1. HAM THUAN ===")
u = C.tao_database_url({'DB_HOST': 'aws-0.pooler.supabase.com', 'DB_PORT': '6543', 'DB_USER': 'postgres.abc',
                        'DB_PASSWORD': 'p@ss:w/rd#1', 'DB_NAME': 'postgres'})
kiem("DB_* -> URL postgresql, mat khau ma hoa ky tu dac biet",
     u.startswith('postgresql://postgres.abc:p%40ss%3Aw%2Frd%231@aws-0.pooler.supabase.com:6543/postgres?sslmode=require'), u)
kiem("URL co keepalive (Windows phat hien ket noi chet ~35s)", 'keepalives=1&keepalives_idle=20' in u, u)
import psycopg2.extensions as _pe
d = _pe.parse_dsn(u)
kiem("psycopg2 doc dung URL (mat khau giai ma lai nguyen ven)", d.get('password') == 'p@ss:w/rd#1' and d.get('port') == '6543', d)
kiem("co DATABASE_URL thi uu tien", C.tao_database_url({'DATABASE_URL': 'postgresql://a:b@h/db', 'DB_HOST': 'x', 'DB_USER': 'y', 'DB_PASSWORD': 'z'})
     == 'postgresql://a:b@h/db?' + C._KEEPALIVE)
kiem("URL da co ?sslmode -> noi bang &", C.them_keepalive('postgresql://a:b@h/db?sslmode=require').endswith('sslmode=require&' + C._KEEPALIVE))
kiem("da co keepalives -> giu nguyen", C.them_keepalive('postgresql://h/db?keepalives=0') == 'postgresql://h/db?keepalives=0')
kiem("dang 'host=... dbname=...' -> noi bang dau cach", C.them_keepalive('host=h dbname=d') == 'host=h dbname=d keepalives=1 keepalives_idle=20 keepalives_interval=5 keepalives_count=3')
kiem("thieu mat khau -> ''", C.tao_database_url({'DB_HOST': 'h', 'DB_USER': 'u'}) == '')
kiem("an_url che mat khau", C.an_url(u).startswith('postgresql://postgres.abc:***@aws-0'), C.an_url(u))

D = datetime
V = C.viec_den_han
kiem("06:00 -> chua co viec", V(D(2026, 11, 20, 6, 0), {}) == [])
kiem("06:03 -> du doan", [v[0] for v in V(D(2026, 11, 20, 6, 3, 5), {})] == ['du_doan'])
kiem("du doan goi /api/predict", V(D(2026, 11, 20, 6, 3), {})[0][2:4] == ('GET', '/api/predict'))
kiem("21:57 -> van du doan (ky cuoi 21:54)", [v[0] for v in V(D(2026, 11, 20, 21, 57), {})] == ['du_doan'])
kiem("22:03 -> het gio quay, khong du doan", V(D(2026, 11, 20, 22, 3), {}) == [])
kiem("05:57 -> chua toi gio", V(D(2026, 11, 20, 5, 57), {}) == [])
tk = V(D(2026, 11, 20, 23, 55, 10), {})
kiem("23:55 -> tong ket ngay, co ?bu=1 (khoi dong lai khong gui trung)",
     [v[0] for v in tk] == ['tong_ket_ngay'] and tk[0][3] == '/api/daily-summary?bu=1', tk)
kiem("23:58 sau khi da chay -> khong chay lai", V(D(2026, 11, 20, 23, 58), {'tong_ket_ngay': '2026-11-20'}) == [])
kiem("23:58 may vua mo lai, chua chay -> chay bu", [v[0] for v in V(D(2026, 11, 20, 23, 58), {})] == ['tong_ket_ngay'])
kiem("cung phut da chay -> khong chay lai", V(D(2026, 11, 20, 6, 3, 40), {'du_doan': '2026-11-20 06:03'}) == [])
# mo phong ca ngay, nhip 20 giay
goi_ds, da = [], {}
t = D(2026, 11, 20, 0, 0, 7)
while t < D(2026, 11, 21, 0, 0):
    for v in V(t, da):
        da[v[0]] = v[1]; goi_ds.append((v[0], t))
    t += timedelta(seconds=20)
dd = [x for x in goi_ds if x[0] == 'du_doan']
kiem("ca ngay: 160 lan du doan (06:03 -> 21:57)", len(dd) == 160 and dd[0][1].strftime('%H:%M') == '06:03'
     and dd[-1][1].strftime('%H:%M') == '21:57', (len(dd), dd[:1], dd[-1:]))
kiem("ca ngay: 1 lan tong ket", [x[1].strftime('%H:%M') for x in goi_ds if x[0] == 'tong_ket_ngay'] == ['23:55'])
kiem("du doan luon 3 phut truoc gio quay (phut chia 6 du 3)", all(x[1].minute % 6 == 3 for x in dd))

dong_ho = iter([D(2026, 11, 20, 6, 3), D(2026, 11, 20, 6, 3, 30), D(2026, 11, 20, 6, 9)])
ghi, dung = [], threading.Event()
def gia_goi(ten, m, p, cho):
    ghi.append((ten, p))
    if len(ghi) >= 2: dung.set()
def gio_gia():
    try: return next(dong_ho)
    except StopIteration: dung.set(); return D(2026, 11, 20, 6, 10)
C.vong_hen_gio(dung, gia_goi, bay_gio=gio_gia, nhip=0)
kiem("vong hen gio: 06:03 goi 1 lan, 06:09 goi tiep", ghi == [('du_doan', '/api/predict')] * 2, ghi)

f = C.CheToken()
rec = logging.LogRecord('x', logging.ERROR, __file__, 1, "loi %s", ("https://api.telegram.org/bot1234567890:AAAAAAAAAAAAAAAAAAAAAAAAAAAA/sendMessage",), None)
f.filter(rec)
kiem("log: token Telegram bi che", 'AAAAAAAAAAAA' not in rec.getMessage() and 'bot***' in rec.getMessage(), rec.getMessage())

kq = dict((m, (lv, g)) for m, lv, g in C.kiem_tra_cai_dat({'TRIGGER_SECRET': 's'}))
kiem("kiem tra: thieu DB -> LOI", kq['DB Supabase'][0] == 'LOI', kq['DB Supabase'])
kiem("kiem tra: thieu APP_USER -> canh bao (khong chan)", kq['Dang nhap dashboard'][0] == 'CANH BAO')
kq = C.kiem_tra_cai_dat({'DATABASE_URL': u, 'TRIGGER_SECRET': 's', 'TELEGRAM_BOT_TOKEN': 't', 'TELEGRAM_CHAT_ID': 'c',
                         'ADMIN_SECRET_KEY': 'a', 'APP_USER': 'u'})
kiem("kiem tra: du cau hinh -> khong LOI", C.in_kiem_tra(kq), kq)
kiem("kiem tra: khong in mat khau DB", all('p@ss' not in g and 'p%40ss' not in g for _, _, g in kq))

print("=== 2. GIO TIEN TRINH PHAI LA UTC ===")
kiem("tien trinh test dang UTC", C.lech_gio_phut() == 0, C.lech_gio_phut())
ma = ("import os,time,sys; os.environ['TZ']='Asia/Ho_Chi_Minh'; time.tzset(); sys.path.insert(0,'.');"
      "import chay_may as C; a=C.lech_gio_phut(); C.dam_bao_gio_utc([]); print(a, C.lech_gio_phut())")
r = subprocess.run([sys.executable, '-c', ma], capture_output=True, text=True, cwd=GOC)
kiem("may de gio VN (lech 420) -> tu chuyen ve UTC", r.stdout.split() == ['420', '0'], (r.stdout, r.stderr[-300:]))
r = subprocess.run([sys.executable, '-c', 'import chay_may as C; print(C.lech_gio_phut())'], capture_output=True,
                   text=True, cwd=GOC, env=dict(os.environ, TZ='UTC0'))
kiem("tien trinh moi voi TZ=UTC0 (cach file .bat lam) -> lech 0", r.stdout.strip() == '0', (r.stdout, r.stderr[-200:]))
# Windows khong co time.tzset -> phai CHAY LAI chinh no voi TZ=UTC0
_luu = (C.lech_gio_phut, getattr(C.time, 'tzset', None), C.subprocess.call)
bat = {}
C.lech_gio_phut = lambda: 420
del C.time.tzset
C.subprocess.call = lambda args, env=None: bat.update(args=args, env=env) or 0
os.environ.pop('_BINGO_TZ_DA_DAT', None)
try:
    C.dam_bao_gio_utc(['--kiem-tra']); thoat = None
except SystemExit as e:
    thoat = e.code
kiem("khong co tzset (Windows): chay lai chinh no voi TZ=UTC0", thoat == 0 and bat.get('env', {}).get('TZ') == 'UTC0'
     and bat['args'][1].endswith('chay_may.py') and bat['args'][2:] == ['--kiem-tra'], (thoat, bat.get('args')))
os.environ['_BINGO_TZ_DA_DAT'] = '1'
try:
    C.dam_bao_gio_utc([]); thoat = None
except SystemExit as e:
    thoat = str(e.code)
kiem("da chay lai ma van lech -> DUNG (khong ghi gio sai vao DB)", thoat and 'DUNG' in thoat, thoat)
os.environ.pop('_BINGO_TZ_DA_DAT', None); os.environ.pop('TZ', None)
C.lech_gio_phut, C.subprocess.call = _luu[0], _luu[2]
if _luu[1]: C.time.tzset = _luu[1]; C.time.tzset()

r = subprocess.run([sys.executable, 'chay_may.py'], capture_output=True, text=True, cwd=GOC, timeout=120,
                   env={k: v for k, v in os.environ.items() if k not in ('DATABASE_URL', 'DB_HOST')})
kiem("khong co DB Supabase -> thoat ma 2, KHONG chay am tham tren SQLite", r.returncode == 2 and 'DB Supabase' in r.stdout,
     (r.returncode, r.stdout[-400:], r.stderr[-300:]))

print("=== 3. CHAY THAT: WAITRESS + HEN GIO TREN SQLITE ===")
r = subprocess.run([sys.executable, 'scripts/seed_test_db.py', '200'], capture_output=True, text=True, cwd=GOC,
                   env=dict(os.environ, DB_PATH=_DB), timeout=300)
kiem("seed SQLite tam", r.returncode == 0, r.stderr[-300:])
import config
config.DB_PATH = _DB
import app as A
def cong_trong():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); return s.getsockname()[1]
CONG = cong_trong()
kiem("cong trong -> chua ban", not C.cong_dang_ban(CONG))
ung = A.create_app()
threading.Thread(target=C.phuc_vu, args=(ung, CONG), daemon=True).start()
kiem("app len (waitress) trong 60 giay", C.cho_app_len(CONG, 60))
kiem("cong dang ban -> phat hien duoc (khong chay 2 app)", C.cong_dang_ban(CONG))
s = C._phien()
r = s.get(f"http://127.0.0.1:{CONG}/", timeout=30)
kiem("dashboard / tra 200", r.status_code == 200 and 'html' in r.headers.get('Content-Type', ''), r.status_code)
r = s.get(f"http://127.0.0.1:{CONG}/api/health", timeout=60)
kiem("/api/health: DB ket noi duoc (503 o day chi vi du lieu seed cu > 60 phut)",
     (r.json().get('components', {}).get('database', {}) or {}).get('connected') is True, r.text[:200])
kiem("kiem_tra_health: DB ok -> DAT du du lieu tre", C.kiem_tra_health(s, CONG))
goi = C.tao_goi(CONG, 'bi-mat-test')
kiem("hen gio goi /api/predict -> 200", goi('du_doan', 'GET', '/api/predict', 600) == 200)
kiem("hen gio goi /api/daily-summary?bu=1 -> 200", goi('tong_ket_ngay', 'GET', '/api/daily-summary?bu=1', 300) == 200)
# --kiem-tra (buoc 2 cua cai_dat_may.bat) chay tron vong tren cong khac
_kt = C.kiem_tra_cai_dat
C.kiem_tra_cai_dat = lambda env: [('gia lap', 'OK', '')]
os.environ['PORT'] = str(cong_trong())
try:
    ma_kt = C.main(['--kiem-tra'])
finally:
    C.kiem_tra_cai_dat = _kt
    os.environ.pop('PORT', None)
    for h in logging.getLogger().handlers[:]:
        if any(isinstance(x, C.CheToken) for x in h.filters):
            logging.getLogger().removeHandler(h)
kiem("python chay_may.py --kiem-tra -> DAT (ma 0)", ma_kt == 0, ma_kt)
kiem("log ghi vao logs/app_may.log", os.path.exists(os.path.join(GOC, 'logs', 'app_may.log')))
# P298b: cai dat lai khi app DA chay (cong ban boi chinh app minh)
kiem("cong ban boi app Bingo18 -> nhan ra", C.la_app_cua_minh(CONG))
C.kiem_tra_cai_dat = lambda env: [('gia lap', 'OK', '')]
os.environ['PORT'] = str(CONG)
try:
    ma_kt2 = C.main(['--kiem-tra'])
    ma_chay2 = C.main([])
finally:
    C.kiem_tra_cai_dat = _kt
    os.environ.pop('PORT', None)
kiem("--kiem-tra khi app da chay san -> DAT (cai_dat_may.bat di tiep)", ma_kt2 == 0, ma_kt2)
kiem("chay them app thu 2 -> ma 3 (cua so .bat dung, khong chay chong)", ma_chay2 == 3, ma_chay2)
_app_goc = sys.modules['app']
sys.modules['app'] = None                      # gia lap thieu thu vien khi import app
try:
    A2, thieu = C.nap_app()
finally:
    sys.modules['app'] = _app_goc
kiem("thieu thu vien -> bao ten, khong traceback", A2 is None and thieu == 'app', (A2, thieu))
_v = C.sys.version_info
class _V(tuple):
    def __lt__(s, o): return tuple(s) < tuple(o)
for ver, muc in (((3, 14, 6), 'CANH BAO'), ((3, 11, 9), 'OK'), ((3, 12, 1), 'OK'), ((3, 8, 0), 'LOI')):
    C.sys.version_info = _V(ver)
    try:
        lv = dict((m, l) for m, l, _ in C.kiem_tra_cai_dat({}))['Python']
    finally:
        C.sys.version_info = _v
    kiem(f"Python {ver[0]}.{ver[1]} -> {muc}", lv == muc, lv)

print("=== 4. WATCHER: GOI APP TRONG MAY, CHET THI CLOUD RUN ===")
import sync_to_supabase as S
S.TRIGGER_SECRET = 'bi-mat-test'
class Gia(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _tra(self, ma, obj):
        b = json.dumps(obj).encode(); self.send_response(ma)
        self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        self.server.ghi.append(('GET', self.path))
        self._tra(*self.server.healthz) if self.path == '/whoami' else self._tra(404, {})
    def do_POST(self):
        self.server.ghi.append(('POST', self.path, self.headers.get('X-Trigger-Secret')))
        self._tra(self.server.ma_trigger, {'success': self.server.ma_trigger == 200})
def gia(healthz=(200, {'ip_may_chu_thay': '127.0.0.1'}), ma_trigger=200):
    sv = ThreadingHTTPServer(('127.0.0.1', 0), Gia)
    sv.ghi, sv.healthz, sv.ma_trigger = [], healthz, ma_trigger
    threading.Thread(target=sv.serve_forever, daemon=True).start()
    return sv, f"http://127.0.0.1:{sv.server_address[1]}"
cloud, cloud_url = gia()
S.CLOUD_RUN_URL = cloud_url
S.APP_MAY_URL = f"http://127.0.0.1:{CONG}"
kiem("app THAT trong may song -> nhan ra", S._app_may_song())
kiem("trigger -> app trong may (du doan that, 200)", S.trigger_prediction() is True)
kiem("... va KHONG danh thuc Cloud Run", not any(x[0] == 'POST' for x in cloud.ghi), cloud.ghi)
S.APP_MAY_URL = f"http://127.0.0.1:{cong_trong()}"           # khong ai nghe
kiem("app trong may tat -> khong nhan nham", not S._app_may_song())
kiem("trigger -> Cloud Run nhu cu", S.trigger_prediction() is True and cloud.ghi[-1] == ('POST', '/api/trigger-prediction', 'bi-mat-test'), cloud.ghi)
loi, loi_url = gia(ma_trigger=500)
S.APP_MAY_URL = loi_url
n = len(cloud.ghi)
kiem("app trong may tra 500 -> goi bu Cloud Run", S.trigger_prediction() is True and loi.ghi[-1][:2] == ('POST', '/api/trigger-prediction')
     and len(cloud.ghi) == n + 1, (loi.ghi, cloud.ghi[n:]))
khac, khac_url = gia(healthz=(200, {'hello': 1}))
S.APP_MAY_URL = khac_url
kiem("chuong trinh KHAC chiem cong 8080 -> khong coi la app", not S._app_may_song())
yeu, yeu_url = gia(healthz=(503, {'status': 'error', 'db': 'timeout'}))
S.APP_MAY_URL = yeu_url
kiem("/whoami khong tra 200 -> khong coi la app", not S._app_may_song())
src_w = open('sync_to_supabase.py', encoding='utf-8').read()
kiem("watcher nhan app bang /whoami (khong dung DB), cho 10 giay",
     '/whoami", timeout=10)' in src_w and '/healthz", timeout' not in src_w)
S.APP_MAY_URL = cloud_url.rstrip('/')
S.CLOUD_RUN_URL = cloud_url + '/'
n = len(cloud.ghi)
S.trigger_prediction()
kiem("APP_MAY_URL trung CLOUD_RUN_URL -> chi goi 1 lan", sum(1 for x in cloud.ghi[n:] if x[0] == 'POST') == 1, cloud.ghi[n:])
S.APP_MAY_URL = ''
kiem("APP_MAY_URL rong -> tat che do may nha", not S._app_may_song())
src = open('sync_to_supabase.py', encoding='utf-8').read()
kiem("watcher van goi trigger trong luong rieng (khong chan vong lap)", 'threading.Thread(target=trigger_prediction' in src)

print("=== 4b. P298d: TELEGRAM TRA LOI HTTP -> GHI LOG (TRUOC DAY IM LANG) ===")
class _R:
    def __init__(s, ma, j): s.status_code, s.ok, s._j, s.text = ma, ma == 200, j, str(j)
    def json(s): return s._j
_goc_post, _goc_tok, _goc_chat, _goc_gap = S.requests.post, S.TELEGRAM_TOKEN, S.TELEGRAM_CHAT, S._MIN_TG_INTERVAL
_goi_tg = []
S.requests.post = lambda url, json=None, timeout=None: (_goi_tg.append(url), _R(401, {'ok': False, 'description': 'Unauthorized'}))[1]
S.TELEGRAM_TOKEN, S.TELEGRAM_CHAT, S._MIN_TG_INTERVAL = '1234567890:' + 'A' * 35, '1', 0
_buf = __import__('io').StringIO(); _h = logging.StreamHandler(_buf); _h.addFilter(S._CheBiMat())
logging.getLogger().addHandler(_h)
try:
    _kq = S._tg_html('<b>x</b>')
finally:
    logging.getLogger().removeHandler(_h)
    S.requests.post, S.TELEGRAM_TOKEN, S.TELEGRAM_CHAT, S._MIN_TG_INTERVAL = _goc_post, _goc_tok, _goc_chat, _goc_gap
_log = _buf.getvalue()
kiem("token bi thu hoi (401): tra False, thu lai ban chu thuong", _kq is False and len(_goi_tg) == 2, (_kq, len(_goi_tg)))
kiem("log ghi 'HTTP 401: Unauthorized' + goi y sua token", 'HTTP 401: Unauthorized' in _log and 'TOKEN SAI' in _log, _log)
kiem("log KHONG chua token", 'A' * 20 not in _log, _log)

print("=== 5. FILE .BAT ===")
BAT = ('scripts/chay_app_may.bat', 'scripts/cai_dat_may.bat', 'scripts/chon_python.bat')
for ten in BAT:
    b = open(ten, 'rb').read()
    kiem(f"{ten}: CRLF (cmd doc nhan :loop dung)", b.count(b'\r\n') == b.count(b'\n') and b.count(b'\n') > 5)
    t = b.decode('ascii')
    lenh = [l for l in t.splitlines() if not l.lstrip().upper().startswith('REM')]
    kiem(f"{ten}: khong chay taskkill (chi duoc nhac trong REM)", not any('taskkill' in l.lower() for l in lenh))
    # "echo ... ma 2>> file": CMD hieu "2>>" la chuyen huong luong 2 -> mat dong log
    xau = [l for l in t.splitlines() if l.lstrip().lower().startswith('echo') and re.search(r'[0-9%]>>', l)]
    kiem(f"{ten}: khong co 'echo ...<so>>> file'", not xau, xau)
    kiem(f"{ten}: moi ( deu dong )", t.count('(') == t.count(')'))
for ten in BAT[:2]:
    t = open(ten, encoding='ascii').read()
    kiem(f"{ten}: dat TZ=UTC0, chon Python 3.11", 'set TZ=UTC0' in t and 'call "%~dp0chon_python.bat"' in t)
p = open('scripts/chon_python.bat', encoding='ascii').read()
kiem("chon_python.bat: uu tien py -3.11, roi Python311, cuoi cung python",
     p.index('py -3.11 -c') < p.index('Python311\\python.exe') < p.index('set PY=python'), p)
b = open('scripts/chay_app_may.bat', encoding='ascii').read()
kiem("chay_app_may.bat: %PY% chay_may.py + tu chay lai + ma 3 thi dung",
     '%PY% chay_may.py' in b and 'goto loop' in b and 'if "%MA%"=="3" goto het' in b)
c = open('scripts/cai_dat_may.bat', encoding='ascii').read()
kiem("cai_dat_may.bat: cai thu vien + kiem tra bang %PY%", '%PY% -m pip install -r requirements-may.txt' in c
     and '%PY% chay_may.py --kiem-tra' in c)
kiem("cai_dat_may.bat: schtasks, khong co quyen thi thu muc Startup", 'schtasks /Create /TN Bingo18App' in c
     and 'if errorlevel 1 goto startup' in c and 'Start Menu\\Programs\\Startup' in c and ':startup' in c)
kiem("cai_dat_may.bat: chay app ngay khi xong", 'start "Bingo18 App"' in c.split(':tuong_lua')[1])
kiem("cai_dat_may.bat: nhan :startup / :tuong_lua deu co", ':startup\r' in open('scripts/cai_dat_may.bat', 'rb').read().decode()
     and ':tuong_lua\r' in open('scripts/cai_dat_may.bat', 'rb').read().decode())
r = open('requirements-may.txt', encoding='ascii').read()
kiem("requirements-may.txt: requirements.txt + waitress + tzdata", all(x in r for x in ('-r requirements.txt', 'waitress', 'tzdata')))

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
