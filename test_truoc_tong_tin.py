"""P292: cứ 20 kỳ gửi tin "từ 01/01, kỳ NGAY TRƯỚC tổng 4 / tổng 17 ra bộ nào".

Phần 1: module thuần truoc_tong_tin (mốc, thống kê, soạn tin).
Phần 2: chạy THẬT _check_truoc_tong_tin + /api/truoc-tong/tin trên SQLite,
chặn Telegram để bắt nội dung.
"""
import json, os, random, sqlite3, sys, tempfile
from datetime import datetime, timedelta

os.environ.pop('DATABASE_URL', None)
os.environ['TELEGRAM_BOT_TOKEN'] = 'x'
os.environ['TELEGRAM_CHAT_ID'] = 'x'
_TMP = os.path.join(tempfile.mkdtemp(), 'tt.db')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
config.DB_PATH = _TMP
import gio_ky
import truoc_tong_tin as T

DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))

D0 = 196534                      # kỳ đầu ngày 17/11/2026 (06:06)
print("=== 1. MOC 20 KY ===")
kiem("vi tri 0 dung la ky dau ngay", gio_ky.vi_tri(D0) == 0, gio_ky.vi_tri(D0))
kiem("ky thu 19 -> chua toi moc", T.moc_tin(D0 + 18) is None, T.moc_tin(D0 + 18))
m20, m40 = T.moc_tin(D0 + 19), T.moc_tin(D0 + 39)
kiem("ky thu 20 -> moc", m20 is not None, m20)
kiem("ky thu 21..39 cung moc voi ky 20", all(T.moc_tin(D0 + k) == m20 for k in range(19, 39)))
kiem("ky thu 40 -> moc moi lon hon", m40 is not None and m40 > m20, (m20, m40))
kiem("ky cuoi ngay (159) -> moc 7", T.moc_tin(D0 + 158) == m20 + 6, T.moc_tin(D0 + 158))
kiem("ky 20 ngay sau > ky cuoi hom nay", T.moc_tin(D0 + 159 + 19) > T.moc_tin(D0 + 158))
kiem("truoc KY_HIEU_LUC -> None", T.moc_tin(gio_ky.KY_HIEU_LUC - 5) is None)
kiem("7 moc/ngay", len({T.moc_tin(D0 + k) for k in range(159)} - {None}) == 7)

print("=== 2. THONG KE + SOAN TIN ===")
rows = [(100, (3, 3, 6), '23:55 31/12'), (101, (1, 1, 2), '00:05 01/01'),
        (102, (1, 3, 5), 'x'), (103, (1, 1, 2), 'x'), (104, (2, 2, 4), 'x'),
        (105, (5, 6, 6), 'x'), (107, (1, 1, 2), 'x')]          # 106 thieu
tk = T.thong_ke(rows, tu_dn=101, cua_so=5)
t4, t17 = tk['tong'][4], tk['tong'][17]
kiem("so ky tu 01/01 (khong tinh ky 2025)", tk['so_ky'] == 6, tk['so_ky'])
kiem("tong 4 ra 3 lan", t4['so_lan'] == 3, t4)
kiem("ky dau nam lay duoc ky truoc 2025", (3, 3, 6) in dict(t4['top_bo']), t4['top_bo'])
kiem("ky truoc thieu -> dem rieng", t4['thieu_truoc'] == 1 and t4['co_truoc'] == 2, t4)
kiem("gan nhat moi nhat dung dau", [x[0] for x in t4['gan_nhat']] == [107, 103, 101], t4['gan_nhat'])
kiem("tong 17: ky truoc 2-2-4", t17['so_lan'] == 1 and t17['top_bo'] == [((2, 2, 4), 1)], t17)
kiem("size ky truoc", t4['size'] == {'Nhỏ': 1, 'Hòa': 0, 'Lớn': 1}, t4['size'])
kiem("cua so 5 ky: tong 4 ra 2 lan (103, 107)", t4['trong_cua_so'] == 2, t4['trong_cua_so'])
tin = T.soan_tin(tk, '01/01/2026', cua_so=5)
kiem("HTML escape &", '&amp;' in tin and ' & ' not in tin, tin[:80])
kiem("co dong tong 4", '<b>TỔNG 4</b> — 3 lần' in tin, tin)
kiem("ky moi danh dau 🆕", '🆕 #107' in tin and '🆕 #101' not in tin, tin)
kiem("ghi ro thieu ky truoc", '#107 x ← thiếu dữ liệu kỳ trước' in tin, tin)
kiem("canh bao khong bao hieu", 'không báo hiệu' in tin, tin)
random.seed(1)
lon = [(200000 + i, tuple(sorted(random.randint(1, 6) for _ in range(3))), '08:00 01/02') for i in range(50000)]
tin_lon = T.soan_tin(T.thong_ke(lon, 200000), '01/01/2026')
kiem("50.000 ky: tin < 4096 ky tu", len(tin_lon) < 4096, len(tin_lon))
kiem("khong co du lieu -> van soan duoc", 'Chưa có dữ liệu' in T.soan_tin({'den_dn': None}, '01/01/2026'))

print("=== 3. CHAY THAT TREN SQLITE ===")
import app as A
import telegram_bot as TB
bat = []
TB.TelegramBot.send_message = lambda self, m, *a, **k: bat.append(m) or True
A.app.test_client().get('/api/health')         # tao bang
A.config.TRIGGER_SECRET = 'bi-mat'

def nap(dn, bo, utc):
    c = sqlite3.connect(_TMP)
    c.execute("INSERT OR REPLACE INTO draw_history (draw_number, draw_time, numbers, size_category, sum_value)"
              " VALUES (?,?,?,?,?)", (dn, utc.strftime('%Y-%m-%d %H:%M:%S'), json.dumps(list(bo)), 'X', sum(bo)))
    c.commit(); c.close()

GOC = datetime(2026, 11, 16, 23, 6)            # 06:06 VN 17/11
DAC_BIET = {D0 + 5: (1, 3, 5), D0 + 6: (1, 1, 2), D0 + 10: (2, 2, 4), D0 + 11: (5, 6, 6)}
def nap_toi(k_cuoi):
    for k in range(k_cuoi + 1):
        nap(D0 + k, DAC_BIET.get(D0 + k, (1, 2, 4)), GOC + timedelta(minutes=6 * k))
nap(D0 - 1, (3, 3, 6), datetime(2025, 12, 31, 16, 55))   # ky cuoi 2025
nap(D0 - 2, (1, 1, 2), datetime(2025, 12, 31, 16, 50))   # tong 4 NAM 2025: khong duoc dem

GIO = datetime(2026, 11, 17, 10, 0)
nap_toi(18)
kiem("ky thu 19: khong gui", A._check_truoc_tong_tin('t', GIO) is False and not bat, bat)
nap_toi(19)
kiem("ky thu 20: GUI", A._check_truoc_tong_tin('t', GIO) is True and len(bat) == 1, len(bat))
m = bat[-1] if bat else ''
kiem("tin: tong 4 ra 1 lan (khong dem ky 2025)", '<b>TỔNG 4</b> — 1 lần' in m, m)
kiem("tin: ky truoc tong 4 la 1-3-5", f'#{D0 + 6} 06:42 17/11 ← 1-3-5 (tổng 9)' in m, m)
kiem("tin: ky truoc tong 17 la 2-2-4", f'#{D0 + 11} 07:12 17/11 ← 2-2-4 (tổng 8)' in m, m)
kiem("tin: den ky moi nhat", f'#{D0 + 19}' in m and '08:00 17/11' in m, m[:160])
kiem("goi lai cung moc: KHONG gui trung", A._check_truoc_tong_tin('t', GIO) is False and len(bat) == 1)
nap_toi(30)
kiem("ky 31 (van moc 20): khong gui", A._check_truoc_tong_tin('t', GIO) is False and len(bat) == 1)
nap_toi(39)
kiem("ky thu 40: gui tin thu 2", A._check_truoc_tong_tin('t', GIO) is True and len(bat) == 2, len(bat))
nap_toi(65)
kiem("ngoai gio 22h-6h: khong gui", A._check_truoc_tong_tin('t', datetime(2026, 11, 17, 22, 30)) is False
     and len(bat) == 2)
kiem("bo lo moc 60 -> chi gui MOC HIEN TAI 1 tin", A._check_truoc_tong_tin('t', GIO) is True and len(bat) == 3)
c = sqlite3.connect(_TMP)
c.execute("UPDATE system_config SET config_value=? WHERE config_key=?", (str(T.moc_tin(D0 + 150)), A._TT_MOC_KEY))
c.commit(); c.close()
nap_toi(79)
kiem("duong kia da gianh moc cao hon -> khong gui", A._check_truoc_tong_tin('t', GIO) is False and len(bat) == 3)

print("=== 4. ENDPOINT XEM TRUOC / GUI TAY ===")
cl = A.app.test_client()
r = cl.get('/api/truoc-tong/tin')
kiem("khong secret -> 401", r.status_code == 401, r.status_code)
r = cl.get('/api/truoc-tong/tin', headers={'X-Trigger-Secret': 'bi-mat'})
d = r.get_json() or {}
kiem("xem truoc 200 + co tin", r.status_code == 200 and 'TỔNG 17' in d.get('tin', ''), (r.status_code, d))
kiem("xem truoc KHONG gui", d.get('da_gui') is None and len(bat) == 3, len(bat))
moc_truoc = d.get('moc_da_gui')
r = cl.post('/api/truoc-tong/tin?gui=1', headers={'X-Trigger-Secret': 'bi-mat'})
d = r.get_json() or {}
kiem("gui tay -> da_gui", d.get('da_gui') is True and len(bat) == 4, (d.get('da_gui'), len(bat)))
kiem("gui tay khong doi moc tu dong", d.get('moc_da_gui') == moc_truoc, (moc_truoc, d.get('moc_da_gui')))

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
