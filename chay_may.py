"""P298: chạy app Bingo18 TRÊN MÁY NHÀ (Windows, bật 24/24) thay cho Cloud Run.

Mục tiêu: hết tiền Google Cloud. Cloud Run vẫn giữ làm DỰ PHÒNG — không ai gọi
thì không tính tiền; GitHub Actions (sync-draws, gửi bù báo cáo, sửa giờ kỳ...)
gọi nó vài chục lần/ngày, nằm trong phần miễn phí. Ra ngoài vẫn xem dashboard
bằng link Cloud Run được (cùng một DB Supabase).

Một tiến trình làm 2 việc:
  1. Phục vụ dashboard + API (waitress, cổng 8080): http://localhost:8080, hoặc
     http://<IP máy>:8080 trên điện thoại cùng Wi-Fi.
  2. Hẹn giờ THAY Cloud Scheduler (các job bên Google Cloud phải TẠM DỪNG):
       - 06:03-21:57 giờ VN, mỗi 6 phút (phút chia 6 dư 3): GET /api/predict
       - 23:55-23:59 giờ VN: GET /api/daily-summary?bu=1 (báo cáo cuối ngày;
         bu=1 = ngày đó gửi rồi thì thôi -> khởi động lại không gửi trùng)
     22:05 đã tắt từ P259; lấy kết quả Vietlott là việc của watcher.

Watcher (sync_to_supabase.py --mode watch) tự thấy app trong máy và gọi dự đoán ở
đây; app trong máy chết thì nó gọi Cloud Run như cũ.

GIỜ: mã viết cho Cloud Run (giờ hệ thống = UTC) và lưu thẳng datetime.now() vào DB
như giờ UTC. Windows để giờ VN thì mọi prediction_time lệch 7 tiếng. Tiến trình
này BẮT BUỘC chạy với TZ=UTC0: file .bat đặt sẵn; quên thì tự chạy lại chính nó
với TZ=UTC0; vẫn lệch thì DỪNG, không ghi giờ sai vào DB.

Chạy:              scripts\\chay_app_may.bat      (tự chạy lại nếu thoát)
Kiểm tra cài đặt:  python chay_may.py --kiem-tra
"""
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

GOC = os.path.dirname(os.path.abspath(__file__))
VN = timezone(timedelta(hours=7))            # Việt Nam không có giờ mùa hè
log = logging.getLogger('chay_may')

# ── .env + DATABASE_URL ─────────────────────────────────────────────────────

def nap_env(duong_dan: str = None) -> bool:
    """Đọc .env, KHÔNG ghi đè biến đã đặt sẵn (vd TZ trong file .bat)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    return load_dotenv(duong_dan or os.path.join(GOC, '.env'))


_KEEPALIVE = 'keepalives=1&keepalives_idle=20&keepalives_interval=5&keepalives_count=3'


def them_keepalive(url: str) -> str:
    """P279: Windows mất ~2 tiếng mới phát hiện kết nối Supabase chết im lặng
    -> truy vấn treo. Bật keepalive (~35 giây) cho cả pool lẫn kết nối lẻ."""
    if not url or 'keepalives' in url:
        return url
    if '://' in url:
        return url + ('&' if '?' in url else '?') + _KEEPALIVE
    return url + ' ' + _KEEPALIVE.replace('&', ' ')          # dạng "host=... dbname=..."


def tao_database_url(env) -> str:
    """Máy nhà thường chỉ có DB_HOST/DB_USER/DB_PASSWORD (của watcher), không có DATABASE_URL."""
    if (env.get('DATABASE_URL') or '').strip():
        return them_keepalive(env['DATABASE_URL'].strip())
    host = (env.get('DB_HOST') or '').strip()
    user = (env.get('DB_USER') or '').strip()
    mk = env.get('DB_PASSWORD') or ''
    if not (host and user and mk):
        return ''
    cong = (env.get('DB_PORT') or '5432').strip()
    ten = (env.get('DB_NAME') or 'postgres').strip()
    return them_keepalive(f"postgresql://{quote(user, safe='')}:{quote(mk, safe='')}@{host}:{cong}/"
                          f"{quote(ten, safe='')}?sslmode=require")


def an_url(url: str) -> str:
    """Che mật khẩu khi in ra màn hình."""
    return re.sub(r'(://[^:/@]+:)[^@]*@', r'\1***@', url or '')

# ── Giờ UTC ─────────────────────────────────────────────────────────────────

def lech_gio_phut() -> int:
    """Giờ địa phương của tiến trình lệch UTC bao nhiêu phút (phải = 0)."""
    return round((datetime.now() - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds() / 60)


def dam_bao_gio_utc(argv) -> None:
    lech = lech_gio_phut()
    if lech == 0:
        return
    os.environ['TZ'] = 'UTC0'
    if hasattr(time, 'tzset'):                          # Linux/macOS: đổi ngay được
        time.tzset()
        if lech_gio_phut() == 0:
            return
    if os.environ.get('_BINGO_TZ_DA_DAT') != '1':       # Windows: chạy lại chính nó với TZ=UTC0
        print(f"Gio tien trinh dang lech UTC {lech} phut -> chay lai voi TZ=UTC0 ...", flush=True)
        env = dict(os.environ, TZ='UTC0', _BINGO_TZ_DA_DAT='1')
        sys.exit(subprocess.call([sys.executable, os.path.abspath(__file__)] + list(argv), env=env))
    raise SystemExit(f"LOI: gio tien trinh van lech UTC {lech_gio_phut()} phut du da dat TZ=UTC0 "
                     "-> DUNG de khong ghi gio sai vao DB.")

# ── Log ─────────────────────────────────────────────────────────────────────

_MAU_TOKEN = re.compile(r'bot\d{5,}:[A-Za-z0-9_-]{20,}')


class CheToken(logging.Filter):
    """Không để token bot Telegram lọt vào log (URL lỗi của requests chứa nó)."""
    def filter(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return True
        if _MAU_TOKEN.search(msg):
            record.msg, record.args = _MAU_TOKEN.sub('bot***', msg), None
        return True


def cai_log() -> None:
    from logging.handlers import RotatingFileHandler
    os.makedirs(os.path.join(GOC, 'logs'), exist_ok=True)
    fmt = logging.Formatter('%(asctime)s VN [%(levelname)s] %(name)s - %(message)s')
    fmt.converter = lambda t: datetime.fromtimestamp(t, VN).timetuple()     # log ghi giờ VN cho dễ đọc
    goc = logging.getLogger()
    goc.setLevel(getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper(), logging.INFO))
    for h in (logging.StreamHandler(sys.stdout),
              RotatingFileHandler(os.path.join(GOC, 'logs', 'app_may.log'),
                                  maxBytes=5_000_000, backupCount=3, encoding='utf-8')):
        h.setFormatter(fmt)
        h.addFilter(CheToken())
        goc.addHandler(h)

# ── Hẹn giờ (thay Cloud Scheduler) ──────────────────────────────────────────

def viec_den_han(gio_vn: datetime, da_chay: dict) -> list:
    """[(tên, khoá lần chạy, method, path, timeout giây)] tới hạn mà chưa chạy với khoá đó."""
    viec = []
    h, m = gio_vn.hour, gio_vn.minute
    if 6 <= h < 22 and m % 6 == 3:
        viec.append(('du_doan', gio_vn.strftime('%Y-%m-%d %H:%M'), 'GET', '/api/predict', 600))
    if h == 23 and m >= 55:
        viec.append(('tong_ket_ngay', gio_vn.strftime('%Y-%m-%d'), 'GET', '/api/daily-summary?bu=1', 300))
    return [v for v in viec if da_chay.get(v[0]) != v[1]]


def _phien():
    import requests
    s = requests.Session()
    s.trust_env = False                  # 127.0.0.1: không đi qua proxy hệ thống
    return s


def tao_goi(cong: int, secret: str):
    s = _phien()
    tieu_de = {'X-Trigger-Secret': secret} if secret else {}

    def goi(ten, method, path, cho):
        t0 = time.time()
        try:
            r = s.request(method, f"http://127.0.0.1:{cong}{path}", headers=tieu_de, timeout=cho)
            log.info("Hen gio %s: HTTP %d (%.0fs) %s", ten, r.status_code, time.time() - t0,
                     r.text[:200].replace('\n', ' '))
            return r.status_code
        except Exception as e:
            log.warning("Hen gio %s loi: %s", ten, e)
            return None
    return goi


def vong_hen_gio(dung: threading.Event, goi, bay_gio=lambda: datetime.now(VN).replace(tzinfo=None),
                 nhip: float = 20) -> None:
    da_chay = {}
    while not dung.is_set():
        for ten, khoa, method, path, cho in viec_den_han(bay_gio(), da_chay):
            da_chay[ten] = khoa
            goi(ten, method, path, cho)
        dung.wait(nhip)

# ── Máy chủ web ─────────────────────────────────────────────────────────────

def ip_lan():
    """IP của máy trong mạng nhà (không gửi gói tin nào ra ngoài)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
    except OSError:
        return None


def cong_dang_ban(cong: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(('127.0.0.1', cong)) == 0


def cho_app_len(cong: int, giay: float = 180) -> bool:
    het = time.time() + giay
    while time.time() < het:
        if la_app_cua_minh(cong):
            return True
        time.sleep(1)
    return False


def la_app_cua_minh(cong: int) -> bool:
    """Cổng đang bận là app Bingo18 (/whoami trả JSON có 'ip_may_chu_thay' — không đụng DB,
    giống cách watcher nhận ra app), không phải chương trình khác."""
    try:
        r = _phien().get(f"http://127.0.0.1:{cong}/whoami", timeout=10)
        return r.status_code == 200 and 'ip_may_chu_thay' in (r.json() or {})
    except Exception:
        return False


def nap_app():
    """(module app, None) hoặc (None, tên thư viện thiếu) — báo dễ hiểu thay vì traceback."""
    try:
        import app as A
        return A, None
    except ImportError as e:
        return None, getattr(e, 'name', None) or str(e)


def phuc_vu(app, cong: int) -> None:
    try:
        from waitress import serve
    except ImportError:
        log.warning("Chua cai waitress -> dung server co san cua Flask (pip install -r requirements-may.txt)")
        app.run(host='0.0.0.0', port=cong, threaded=True, debug=False, use_reloader=False)
        return
    serve(app, host='0.0.0.0', port=cong, threads=16, ident='bingo18', channel_timeout=300)

# ── Kiểm tra cài đặt ────────────────────────────────────────────────────────

def kiem_tra_cai_dat(env) -> list:
    """[(mục, mức 'OK'|'CANH BAO'|'LOI', ghi chú)]."""
    kq = []
    v = sys.version_info
    # P298b: máy nhà có cả 3.14 (lệnh "python") lẫn 3.11. Thư viện ghim trong requirements.txt
    # (scikit-learn 1.6.1, numpy 1.26.4...) không có bản dựng sẵn cho >= 3.13 -> pip phải biên
    # dịch C++ và hỏng. File .bat tự chọn "py -3.11" (scripts/chon_python.bat).
    kq.append(('Python', 'OK' if (3, 9) <= v[:2] <= (3, 12) else ('LOI' if v < (3, 9) else 'CANH BAO'),
               sys.version.split()[0] + ('' if v[:2] <= (3, 12) else
                                         ' - nen dung Python 3.11 (py -3.11): thu vien ghim chua co ban cho ban nay')))
    lech = lech_gio_phut()
    kq.append(('Gio tien trinh = UTC', 'OK' if lech == 0 else 'LOI', f'lech {lech} phut'))
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo('Asia/Ho_Chi_Minh')
        kq.append(('Mui gio Asia/Ho_Chi_Minh', 'OK', ''))
    except Exception as e:
        kq.append(('Mui gio Asia/Ho_Chi_Minh', 'LOI', f'{e} -> pip install tzdata'))
    try:
        import waitress  # noqa: F401
        kq.append(('waitress', 'OK', ''))
    except ImportError:
        kq.append(('waitress', 'CANH BAO', 'chua cai -> pip install -r requirements-may.txt'))
    url = env.get('DATABASE_URL', '')
    kq.append(('DB Supabase', 'OK' if url else 'LOI',
               an_url(url) if url else 'thieu DATABASE_URL (hoac DB_HOST/DB_USER/DB_PASSWORD) trong .env'))
    for k, muc in (('TRIGGER_SECRET', 'LOI'), ('TELEGRAM_BOT_TOKEN', 'CANH BAO'), ('TELEGRAM_CHAT_ID', 'CANH BAO')):
        kq.append((k, 'OK' if env.get(k) else muc, '' if env.get(k) else 'chua co trong .env'))
    kq.append(('ADMIN_SECRET_KEY', 'OK' if env.get('ADMIN_SECRET_KEY') else 'CANH BAO',
               '' if env.get('ADMIN_SECRET_KEY') else 'chua co -> trang admin khong khoa (chi trong mang nha)'))
    kq.append(('Dang nhap dashboard', 'OK' if env.get('APP_USER') else 'CANH BAO',
               '' if env.get('APP_USER') else 'chua dat APP_USER/APP_PASSWORD -> ai cung Wi-Fi cung xem duoc'))
    return kq


def kiem_tra_health(s, cong: int) -> bool:
    """/api/health trả 503 cả khi chỉ DỮ LIỆU trễ > 60 phút (đêm, watcher tắt) — với việc
    kiểm tra cài đặt chỉ cần app lên + kết nối được DB; độ trễ đồng bộ chỉ in ra."""
    try:
        r = s.get(f"http://127.0.0.1:{cong}/api/health", timeout=60)
        tp = (r.json() or {}).get('components') or {}
    except Exception as e:
        print(f"  [LOI     ] /api/health: {e}", flush=True)
        return False
    db = tp.get('database') or {}
    dong_bo = tp.get('sync') or {}
    db_ok = db.get('status') == 'ok' or db.get('connected') is True
    print(f"  [{'OK' if db_ok else 'LOI':8}] Ket noi DB tu app - {db.get('query_latency_ms', '?')} ms", flush=True)
    print(f"  [{'OK' if dong_bo.get('status') == 'ok' else 'CANH BAO':8}] Du lieu: ky cuoi "
          f"#{dong_bo.get('last_draw_number')}, tre {dong_bo.get('lag_minutes')} phut", flush=True)
    return db_ok


def in_kiem_tra(kq) -> bool:
    for muc, muc_do, ghi in kq:
        print(f"  [{muc_do:8}] {muc}" + (f" - {ghi}" if ghi else ''), flush=True)
    return not any(m == 'LOI' for _, m, _ in kq)

# ── Chạy ────────────────────────────────────────────────────────────────────

def main(argv) -> int:
    os.chdir(GOC)
    nap_env()
    dam_bao_gio_utc(argv)
    url = tao_database_url(os.environ)
    if url:
        os.environ['DATABASE_URL'] = url
    cong = int(os.environ.get('PORT') or 8080)
    thu = '--kiem-tra' in argv

    print("=== Bingo18 - app tren may nha (P298) ===", flush=True)
    ok = in_kiem_tra(kiem_tra_cai_dat(os.environ))
    if not ok:
        print("Con muc LOI o tren -> sua .env / cai thu vien roi chay lai.", flush=True)
        return 2
    if cong_dang_ban(cong):
        if la_app_cua_minh(cong):
            print(f"App Bingo18 DA CHAY SAN o cong {cong} (cua so 'Bingo18 App' khac) -> khong chay them.",
                  flush=True)
            return 0 if thu else 3
        print(f"LOI: cong {cong} dang co chuong trinh khac (vd 'python app.py' cu?). "
              "Dong chuong trinh do roi chay lai.", flush=True)
        return 3
    cai_log()          # sau khi chắc chỉ có MỘT app: 2 tiến trình cùng xoay vòng 1 file log trên Windows sẽ lỗi

    A, thieu = nap_app()
    if A is None:
        print(f"LOI: Python {sys.version.split()[0]} thieu thu vien '{thieu}' -> chay scripts\\cai_dat_may.bat "
              "(tu cai bang Python 3.11).", flush=True)
        return 2
    ung_dung = A.create_app()
    secret = os.environ.get('TRIGGER_SECRET', '')
    goi = tao_goi(cong, secret)

    if thu:
        threading.Thread(target=phuc_vu, args=(ung_dung, cong), daemon=True).start()
        if not cho_app_len(cong, 120):
            print("LOI: app khong len sau 120 giay.", flush=True)
            return 1
        db_ok = kiem_tra_health(_phien(), cong)
        ma = goi('du_doan (thu)', 'GET', '/api/predict', 600)
        dat = db_ok and ma == 200
        print("KIEM TRA XONG: " + ("DAT" if dat else "CO LOI - xem dong tren"), flush=True)
        return 0 if dat else 1

    dung = threading.Event()

    def _hen_gio():
        if cho_app_len(cong):
            log.info("Hen gio bat dau: du doan moi 6 phut (06:03-21:57 VN), tong ket 23:55 VN")
            vong_hen_gio(dung, goi)
        else:
            log.error("App khong len -> khong chay hen gio")
    threading.Thread(target=_hen_gio, daemon=True, name='hen-gio').start()

    ip = ip_lan()
    print(f"\nDashboard tren may nay : http://localhost:{cong}", flush=True)
    if ip:
        print(f"Dien thoai cung Wi-Fi  : http://{ip}:{cong}", flush=True)
    print("Dung app: DONG CUA SO NAY (khong dung taskkill /IM python.exe - chet ca watcher)\n", flush=True)
    phuc_vu(ung_dung, cong)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
