"""P293: thẻ "bộ ra ngay trước trip 111-666 / tổng 4 & 17" (từ 01/01).

Phần 1: module thuần truoc_ky (đếm, kỳ vọng, kiểm định, danh sách).
Phần 2: /api/truoc-ky chạy THẬT trên SQLite (đọc năm hiện tại, kỳ trước đầu năm).
Phần 3: template + JS + danh sách trắng thẻ.
"""
import json, os, random, re, sqlite3, sys, tempfile
from datetime import datetime, timedelta

os.environ.pop('DATABASE_URL', None)
_TMP = os.path.join(tempfile.mkdtemp(), 'tk.db')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
config.DB_PATH = _TMP
import truoc_ky as T

DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))

print("=== 1. MODULE THUAN ===")
L = '2026-01-01 00:00:00'
rows = [(99, (3, 3, 6), L), (100, (1, 1, 2), L), (101, (2, 2, 2), L), (102, (1, 2, 3), L),
        (103, (1, 1, 2), L), (104, (2, 4, 6), L), (105, (5, 6, 6), L), (107, (2, 2, 2), L),
        (108, (1, 2, 2), L), (109, (2, 2, 2), L)]                         # 106 thieu
tg = T.phan_tich(rows, 100, 'tong')
t4, t17 = tg['nhom']['4'], tg['nhom']['17']
kiem("chi dem tu tu_dn (ky 99 khong tinh)", tg['so_ky'] == 9 and tg['tu_ky'] == 100, tg['so_ky'])
kiem("tong 4 ra 2 lan", t4['so_lan'] == 2, t4['so_lan'])
kiem("ky dau nam lay duoc ky truoc (99)", any(b == '336' for b, _, _ in t4['top_bo']), t4['top_bo'])
kiem("danh sach moi nhat dung dau", [x[0] for x in t4['ds']] == [103, 100], t4['ds'])
kiem("ds: [ky, luc, bo, bo_truoc]", t4['ds'][0] == [103, L, '112', '123'], t4['ds'][0])
kiem("tong 17: ky truoc 2-4-6", t17['so_lan'] == 1 and t17['ds'][0][3] == '246', t17)
kiem("size ky truoc tong 4: 336 Lon, 123 Nho", t4['size'] == {'NHO': 1, 'HOA': 0, 'LON': 1}, t4['size'])
kiem("ky vong = so_ky * 3/216", t4['ky_vong'] == round(9 * 3 / 216, 1), t4['ky_vong'])
kiem("16 o tong 3..18", len(t4['tong_truoc']) == 16 and sum(t4['tong_truoc']) == 2)
kiem("tong: khong co 'truoc_co_so'", 'truoc_co_so' not in t4)
tt = T.phan_tich(rows, 100, 'trip')
t2 = tt['nhom']['222']
kiem("du 6 nhom trip", sorted(tt['nhom']) == ['111', '222', '333', '444', '555', '666'])
kiem("222 ra 3 lan", t2['so_lan'] == 3, t2['so_lan'])
kiem("ky truoc thieu (106) -> dem rieng", t2['thieu_truoc'] == 1 and t2['co_truoc'] == 2, t2)
kiem("ky truoc co so 2: 112 va 122 -> 2/2", t2['truoc_co_so'] == 2, t2['truoc_co_so'])
kiem("ky vong co so = n*91/216", t2['kv_truoc_co_so'] == round(2 * 91 / 216, 1))
kiem("ky truoc la trip / cung trip", t2['truoc_la_trip'] == 0 and t2['truoc_cung_nhom'] == 0)
kiem("tat_ca = tong 6 trip", tt['tat_ca']['so_lan'] == sum(g['so_lan'] for g in tt['nhom'].values()))
kiem("tat_ca khong mang danh sach (JS tu gop)", 'ds' not in tt['tat_ca'])
kiem("top_bo xep giam dan", all(a[1] >= b[1] for a, b in zip(t2['top_bo'], t2['top_bo'][1:])))
try:
    T.phan_tich(rows, 100, 'xyz'); ok = False
except ValueError:
    ok = True
kiem("loai la -> ValueError", ok)
random.seed(7)
ngau = [(i, tuple(sorted(random.randint(1, 6) for _ in range(3))), L) for i in range(30000)]
r = T.phan_tich(ngau, 0, 'tong')['nhom']['4']
kiem("du lieu ngau nhien: p tong > 0,01", r['p_tong'] is not None and r['p_tong'] > 0.01, r['p_tong'])
kiem("du lieu ngau nhien: p bo > 0,01", r['p_bo'] is not None and r['p_bo'] > 0.01, r['p_bo'])
lech = [(i, (1, 2, 3) if i % 2 == 0 else (1, 1, 2), L) for i in range(2000)]
r = T.phan_tich(lech, 0, 'tong')['nhom']['4']
kiem("du lieu co quy luat (123 luon truoc 112): p bo ~ 0", r['p_bo'] is not None and r['p_bo'] < 1e-6, r['p_bo'])
kiem("gamma_q: chi2 df=1 tai 3,841 ~ 0,05", abs(T.gamma_q(0.5, 3.841 / 2) - 0.05) < 1e-3, T.gamma_q(0.5, 3.841 / 2))

print("=== 2. /api/truoc-ky TREN SQLITE ===")
import app as A
A.app.test_client().get('/api/health')                  # tao bang
nam = (datetime.utcnow() + timedelta(hours=7)).year
goc = datetime(nam - 1, 12, 31, 17, 6)                   # 00:06 VN 01/01
c = sqlite3.connect(_TMP)
def nap(dn, bo, utc):
    c.execute("INSERT OR REPLACE INTO draw_history (draw_number, draw_time, numbers, size_category, sum_value)"
              " VALUES (?,?,?,?,?)", (dn, utc.strftime('%Y-%m-%d %H:%M:%S'), json.dumps(list(bo)), 'X', sum(bo)))
nap(500, (5, 5, 5), goc - timedelta(minutes=13))          # nam truoc: khong duoc dem
nap(501, (4, 4, 6), goc - timedelta(minutes=7))           # 23:59 VN 31/12: ky truoc cua 502
for i, bo in enumerate([(1, 1, 2), (3, 3, 3), (2, 3, 4), (5, 6, 6), (1, 2, 4), (6, 6, 6)]):
    nap(502 + i, bo, goc + timedelta(minutes=6 * i))
c.commit(); c.close()
A._truoc_ky_cache['rows'] = None
cl = A.app.test_client()
r = cl.get('/api/truoc-ky?loai=tong')
d = r.get_json() or {}
kiem("200", r.status_code == 200, (r.status_code, r.data[:200]))
kiem("dem 6 ky tu 01/01 (khong dem 2 ky nam truoc)", d.get('so_ky') == 6, d.get('so_ky'))
kiem("tu_ngay = 01/01/<nam nay>", d.get('tu_ngay') == f'01/01/{nam}', d.get('tu_ngay'))
g4 = d.get('nhom', {}).get('4', {})
kiem("tong 4 dau nam: ky truoc lay tu nam truoc (446)", g4.get('ds') == [[502, (goc).strftime('%Y-%m-%d %H:%M:%S'), '112', '446']], g4.get('ds'))
g17 = d.get('nhom', {}).get('17', {})
kiem("tong 17: ky truoc 2-3-4", g17.get('ds', [[None] * 4])[0][3] == '234', g17.get('ds'))
d = cl.get('/api/truoc-ky?loai=trip').get_json() or {}
kiem("trip: 333 truoc la 1-1-2", d['nhom']['333']['ds'][0][3] == '112', d['nhom']['333'])
kiem("trip: 555 nam truoc KHONG dem", d['nhom']['555']['so_lan'] == 0, d['nhom']['555'])
kiem("trip: tat_ca = 2 lan (333, 666)", d['tat_ca']['so_lan'] == 2, d['tat_ca']['so_lan'])
kiem("den_ky = ky moi nhat", d.get('den_ky') == 507, d.get('den_ky'))
r = cl.get('/api/truoc-ky?loai=abc')
kiem("loai sai -> 400", r.status_code == 400, r.status_code)
A._truoc_ky_cache.update(rows=None)
c = sqlite3.connect(_TMP); c.execute("DELETE FROM draw_history"); c.commit(); c.close()
r = cl.get('/api/truoc-ky?loai=tong&cb=1')
kiem("DB rong -> 200, so_ky 0", r.status_code == 200 and (r.get_json() or {}).get('so_ky') == 0, r.data[:150])

print("=== 3. TEMPLATE + JS + DANH SACH TRANG ===")
H = open('templates/dashboard.html', encoding='utf-8').read()
JS = open('static/js/dashboard.js', encoding='utf-8').read()
for loai, khoa in (('trip', 'truoc-trip'), ('tong', 'truoc-tong')):
    kiem(f"HTML co the data-the=\"{khoa}\"", f'data-the="{khoa}"' in H)
    kiem(f"khoa {khoa} trong _THE_DASHBOARD", khoa in A._THE_DASHBOARD)
    kiem(f"JS co ten the {khoa}", f"'{khoa}':" in JS)
    ids = ['sub', 'chon', 'sum', 'nhan', 'top', 'ds', 'note']
    kiem(f"HTML du id tk-{loai}-*", all(f'id="tk-{loai}-{x}"' in H for x in ids),
         [x for x in ids if f'id="tk-{loai}-{x}"' not in H])
kiem("JS goi /api/truoc-ky", "/api/truoc-ky?loai=" in JS)
kiem("JS lam moi cung refreshThongKe", re.search(r"function refreshThongKe\(\)[^}]*loadTruocKy\('trip'\)", JS) is not None)
kiem("the ghi ro 'không báo hiệu'", 'không báo hiệu' in JS)
print("=== 4. P294: CHE DO 'TUNG TRIP' (6 CUM RIENG) ===")
kiem("HTML co khung cum tk-trip-nhom", 'id="tk-trip-nhom"' in H)
kiem("HTML: khung danh sach co id de an khi xem tung cum", 'id="tk-trip-ds"' in H)
kiem("nut mac dinh la 'Từng trip'", "'Từng trip'" in JS)
kiem("moi cum la <details> rieng, nho cum da thu gon", 'data-khoi=' in JS and "addEventListener('toggle'" in JS)
print("=== 5. P295: DANH SACH TACH RIENG TUNG THANG ===")
kiem("JS dung tkThangHtml cho ca 3 danh sach (cum trip, 1 trip, tong)", JS.count('tkThangHtml(') >= 3, JS.count('tkThangHtml('))
kiem("moi thang la <details data-thang> rieng", 'data-thang=' in JS and 'class="tk-thang"' in JS)
kiem("mac dinh chi mo thang moi nhat", 'm === moiNhat' in JS)
kiem("nho thang da mo / thu gon qua lan lam moi", '_tkThang[el.dataset.thang] = el.open' in JS)
kiem("khong con nut 'Hien tat ca' cuon chung", 'id="tk-trip-them"' not in H and 'id="tk-tong-them"' not in H and 'moHet' not in JS)
kiem("thang_vn: 17:00 UTC 31/01 -> thang 2 gio VN", T.thang_vn('2026-01-31 17:00:00') == '2026-02', T.thang_vn('2026-01-31 17:00:00'))
kiem("thang_vn: chuoi hong -> '????-??'", T.thang_vn('abc') == '????-??')
sk = T.phan_tich([(1, (1, 1, 2), '2026-01-31 16:59:00'), (2, (2, 3, 4), '2026-01-31 17:00:00'),
                  (3, (1, 1, 2), '2026-02-01 03:00:00')], 1, 'tong')['so_ky_thang']
kiem("so_ky_thang dem theo thang VN", sk == {'2026-01': 1, '2026-02': 2}, sk)

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
