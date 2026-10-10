"""P253: /api/trip/lich-su — cac lan ra trip (3 so giong nhau) trong N ngay + khoang cach.

Quy uoc khoang cach = HIEU SO KY (184311 -> 184330 = cach 19 ky), giong
_chuoi_khoang_cach va so tay nguoi dung."""
import os, sys, json, sqlite3, tempfile, random
from datetime import datetime, timedelta
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

print("=== 1. HAM THUAN: khoang cach, cung bo, kỳ thieu ===")
def rows_mau(bo_ky_thieu=()):
    ds = {90: [3, 3, 3], 105: [1, 1, 1], 120: [2, 2, 2], 121: [2, 2, 2], 150: [1, 1, 1]}
    out = []
    for dn in range(80, 161):
        if dn in bo_ky_thieu:
            continue
        out.append((dn, ds.get(dn, [1, 2, 4]), f'2026-10-01 {dn // 60:02d}:{dn % 60:02d}:00'))
    return out
tu = '2026-10-01 01:40:00'                     # = ky 100 tro di (100 = 01:40)
r = A._trip_lich_su(rows_mau(), tu)
t = {x['draw_number']: x for x in r['trip']}
kiem("chi lay trip trong khoang (bo #90 nam truoc khoang)", sorted(t) == [105, 120, 121, 150], sorted(t))
kiem("trip DAU khoang van co 'lan truoc' (#90 dung lam moc): 105 cach 15", t[105]['cach_truoc'] == 15, t[105])
kiem("120 cach 15", t[120]['cach_truoc'] == 15)
kiem("121 cach 1 (ra lien tiep), giua = 0", t[121]['cach_truoc'] == 1 and t[121]['giua'] == 0, t[121])
kiem("150 cach 29, giua = 28", t[150]['cach_truoc'] == 29 and t[150]['giua'] == 28, t[150])
kiem("cach LA HIEU SO KY (150-121), khong phai so ky o giua", t[150]['cach_truoc'] == 150 - 121)
kiem("cung bo: 105 (1-1-1) chua co lan truoc trong du lieu -> None", t[105]['cung_bo_cach'] is None, t[105])
kiem("cung bo: 121 (2-2-2) cach 120 la 1", t[121]['cung_bo_cach'] == 1)
kiem("cung bo: 150 (1-1-1) cach 105 la 45", t[150]['cung_bo_cach'] == 45, t[150])
th = r['tong_hop']
kiem("TB = 15,0 (15+15+1+29)/4", th['tb_cach'] == 15.0, th)
kiem("trung vi = 15, nho nhat 1, lon nhat 29", (th['trung_vi'], th['nho_nhat'], th['lon_nhat']) == (15, 1, 29), th)
kiem("ky cuoi 160, dang chua ve 10 ky", (r['ky_cuoi'], r['dang_chua_ve']) == (160, 10), r)
kiem("dem theo bo: 1-1-1 x2, 2-2-2 x2", {b: v['so_lan'] for b, v in r['theo_bo'].items()} == {'1-1-1': 2, '2-2-2': 2}, r['theo_bo'])
kiem("khong co ky thieu -> thieu_ky False het", not any(x['thieu_ky'] for x in r['trip']))

r2 = A._trip_lich_su(rows_mau(bo_ky_thieu=(110,)), tu)
t2 = {x['draw_number']: x for x in r2['trip']}
kiem("DB thieu #110 (giua 105 va 120) -> 120 bi gan co thieu_ky", t2[120]['thieu_ky'] is True, t2[120])
kiem("... ma 121 va 150 thi khong", not t2[121]['thieu_ky'] and not t2[150]['thieu_ky'])
kiem("khong co trip nao -> khong chet", A._trip_lich_su([(1, [1, 2, 3], '2026-10-01 00:00:00')], tu)['so_trip'] == 0)
kiem("rong -> khong chet", A._trip_lich_su([], tu)['so_trip'] == 0)

print("\n=== 2. ENDPOINT — SQLITE THAT, DOI CHIEU VOI TINH TAY ===")
rnd = random.Random(7)
f = tempfile.NamedTemporaryFile(suffix='.db', delete=False).name
k = sqlite3.connect(f)
k.execute("CREATE TABLE draw_history (draw_number INT PRIMARY KEY, numbers TEXT, sum_value INT, draw_time TEXT)")
bay_gio = datetime.utcnow()
N = 3000                                   # ~ 12,5 ngay voi 6 phut/ky
ds = []
for i in range(N):
    dn = 200000 + i
    bo = [rnd.randint(1, 6) for _ in range(3)]
    dt = bay_gio - timedelta(minutes=6 * (N - 1 - i))
    ds.append((dn, bo, dt))
    k.execute("INSERT INTO draw_history VALUES (?,?,?,?)", (dn, json.dumps(bo), sum(bo), dt.strftime('%Y-%m-%d %H:%M:%S')))
k.commit(); k.close()
with mock.patch.object(A.db, 'get_connection', side_effect=lambda: sqlite3.connect(f)), \
     mock.patch.object(A, 'USE_POSTGRES', False):
    res = A.app.test_client().get('/api/trip/lich-su?ngay=10')
d = res.get_json()
kiem("200", res.status_code == 200, (res.status_code, d if res.status_code != 200 else ''))
# tinh tay, doc lap voi ham
tu10 = bay_gio - timedelta(days=10)
tat_ca = [(dn, bo[0]) for dn, bo, dt in ds if bo[0] == bo[1] == bo[2]]
trong = [(dn, v) for dn, v in tat_ca if [x for x in ds if x[0] == dn][0][2] >= tu10]
kiem(f"so trip trong 10 ngay khop tinh tay ({len(trong)})", d['so_trip'] == len(trong), (d['so_trip'], len(trong)))
kiem("danh sach ky trip khop tinh tay", [x['draw_number'] for x in d['trip']] == [dn for dn, _ in trong])
cach_tay = []
for dn, _ in trong:
    truoc = max(x for x, _ in tat_ca if x < dn) if any(x < dn for x, _ in tat_ca) else None
    cach_tay.append(dn - truoc if truoc else None)
kiem("moi khoang cach khop tinh tay (hieu so ky)", [x['cach_truoc'] for x in d['trip']] == cach_tay)
kiem("so ky trong khoang ~ 2400 (10 ngay x 240)", 2395 <= d['so_ky_trong_khoang'] <= 2401, d['so_ky_trong_khoang'])
with mock.patch.object(A.db, 'get_connection', side_effect=lambda: sqlite3.connect(f)), \
     mock.patch.object(A, 'USE_POSTGRES', False):
    d1 = A.app.test_client().get('/api/trip/lich-su?ngay=1').get_json()
tu1 = bay_gio - timedelta(days=1)
tay1 = [dn for dn, v in tat_ca if [x for x in ds if x[0] == dn][0][2] >= tu1]
kiem(f"ngay=1: dung {len(tay1)} trip, khop tinh tay", [x['draw_number'] for x in d1['trip']] == tay1,
     ([x['draw_number'] for x in d1['trip']], tay1))
kiem("ngay=1: so ky ~ 240", 236 <= d1['so_ky_trong_khoang'] <= 241, d1['so_ky_trong_khoang'])
kiem("dang ky vao bo quet", '/api/trip/lich-su' in open('scripts/endpoints_readonly.txt', encoding='utf-8').read())

print("\n=== 3. THE TRONG DASHBOARD (P254) ===")
html = open('templates/dashboard.html', encoding='utf-8').read()
js = open('static/js/dashboard.js', encoding='utf-8').read()
css = open('static/css/dashboard.css', encoding='utf-8').read()
kiem("HTML co the data-the=\"trip-ngay\"", 'data-the="trip-ngay"' in html)
kiem("khoa nam trong danh sach trang _THE_DASHBOARD (bat/tat the duoc)", 'trip-ngay' in A._THE_DASHBOARD)
kiem("JS co ten hien thi cho khoa (trang cai dat)", "'trip-ngay':" in js)
for i in ('tn-ngay', 'tn-sum', 'tn-bo', 'tn-body', 'tn-sub', 'tn-note'):
    kiem(f"HTML co #{i} ma JS dung", f'id="{i}"' in html and f"$('{i}')" in js)
kiem("JS goi /api/trip/lich-su", "/api/trip/lich-su?ngay=" in js)
kiem("tai luc dau, khi doi so ngay, va dinh ky", "safe(loadTripNgay)" in js and "addEventListener('change'" in js
     and "setInterval(() => safe(loadTripNgay)" in js)
kiem("gio doi tu UTC sang VN (+7)", '7 * 3600e3' in js)
kiem("chi hien 20 lan moi nhat + nut hien tat ca", 'TN_GOI_Y = 20' in js and 'id="tn-them"' in html and "addEventListener('click'" in js)
kiem("mau TINH (khong nhap nhay nhu .overdue-hi): .tn-dai khong co animation",
     '.tn-dai{' in css and 'animation' not in css.split('.tn-dai{')[1].split('}')[0])
kiem("co luat cho man hep va khi phong to (hep-640)", 'html.hep-640 #tn-table' in css)
kiem("endpoint co cache 120s (dashboard goi moi 2 phut)", '@cache_resp(ttl=120)\ndef trip_lich_su' in open('app.py', encoding='utf-8').read())

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
