"""P251: /api/next_prediction phai tra MOI du doan chua xo (he thong du doan truoc
2 ky), ky gan nhat dung dau — khong chi du doan moi nhat.

Loi that: dashboard hien #190580 ma khong co #190579 du #190579 da co trong DB tu
6 phut truoc, vi endpoint chi tra dong co draw_number lon nhat."""
import os, re, sys, json, sqlite3, tempfile
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


def tao_db(ky_xo, du_doan):
    """ky_xo: [draw_number]; du_doan: [(id, draw_number, nums, conf)]."""
    f = tempfile.NamedTemporaryFile(suffix='.db', delete=False).name
    k = sqlite3.connect(f)
    k.executescript("""
      CREATE TABLE draw_history (draw_number INT PRIMARY KEY, numbers TEXT, sum_value INT, draw_time TEXT);
      CREATE TABLE predictions (id INTEGER PRIMARY KEY, draw_number INT, model_name TEXT,
          predicted_numbers TEXT, confidence REAL, prediction_time TEXT, vote_breakdown TEXT);
      -- view CO DINH danh sach cot, giong Postgres (P247b)
      CREATE VIEW predictions_vn AS SELECT p.id, p.draw_number, p.model_name, p.predicted_numbers,
          p.confidence, p.prediction_time, p.vote_breakdown,
          p.prediction_time AS full_time_vietnam,
          substr(p.prediction_time, 12, 5) AS display_time_vietnam FROM predictions p;
    """)
    for d in ky_xo:
        k.execute("INSERT INTO draw_history VALUES (?,?,?,?)", (d, '[1,2,3]', 6, '2026-10-10 07:00:00'))
    for i, d, nums, c in du_doan:
        k.execute("INSERT INTO predictions VALUES (?,?,?,?,?,?,?)",
                  (i, d, 'majority_vote', json.dumps(nums), c, f'2026-10-10 14:{d % 60:02d}:00', None))
    k.commit(); k.close()
    return f


def goi(f):
    with mock.patch.object(A.db, 'get_connection', side_effect=lambda: sqlite3.connect(f)), \
         mock.patch.object(A.db, '_ph', return_value='?'), \
         mock.patch('calibration.get_calibrator', side_effect=RuntimeError('khong can')):
        r = A.app.test_client().get('/api/next_prediction')
    return r.status_code, r.get_json()


print("=== 1. CA HAI KY CHUA XO DEU HIEN (dung canh #579/#580) ===")
f = tao_db(range(570, 579), [(i, i, [1, 3, 5], 0.6) for i in range(570, 581)])
st, d = goi(f)
kiem("200", st == 200, (st, d))
kiem("pending co dung 2 ky: [579, 580]", [x['draw_number'] for x in d.get('pending', [])] == [579, 580], d.get('pending'))
kiem("ky gan nhat (579) dung dau", d['pending'][0]['draw_number'] == 579)
kiem("truong cap tren cung = KY SAP XO (579), khong phai 580", d.get('draw_number') == 579, d.get('draw_number'))
kiem("last_draw = 578", d.get('last_draw') == 578, d.get('last_draw'))
kiem("moi muc pending co so du doan", all(x['predicted_numbers'] == [1, 3, 5] for x in d['pending']))

print("\n=== 2. KHONG CON DU DOAN CHUA XO -> lui ve cai moi nhat nhu cu ===")
f = tao_db(range(570, 581), [(i, i, [2, 2, 2], 0.5) for i in range(570, 579)])
st, d = goi(f)
kiem("pending rong", d.get('pending') == [], d.get('pending'))
kiem("van tra du doan moi nhat (578)", d.get('draw_number') == 578, d.get('draw_number'))

print("\n=== 3. NHIEU DONG CUNG MOT KY -> chi lay dong moi nhat ===")
f = tao_db(range(570, 579), [(1, 579, [1, 1, 1], 0.5), (2, 579, [4, 5, 6], 0.5), (3, 580, [3, 3, 3], 0.5)])
st, d = goi(f)
kiem("moi ky 1 muc", [x['draw_number'] for x in d['pending']] == [579, 580], d.get('pending'))
kiem("ky 579 lay dong id lon nhat (4-5-6)", d['pending'][0]['predicted_numbers'] == [4, 5, 6], d['pending'][0])

print("\n=== 4. RONG ===")
f = tao_db([], [])
st, d = goi(f)
kiem("khong du doan nao -> {} (khong 500)", st == 200 and d == {}, (st, d))

print("\n=== 5. DASHBOARD HIEN MOI DONG CHUA XO ===")
js = open('static/js/dashboard.js', encoding='utf-8').read()
kiem("dashboard.js doc np.pending", 'np.pending' in js)
kiem("moi du doan chua xo ra mot dong (.map tren pend)", re.search(r"pend\.slice\(\)\.sort\(.*\)\.map\(", js) is not None)
kiem("nhan 'KY TOI' cho ky gan nhat", 'KỲ TỚI' in js)
kiem("lui ve may chu cu khong co 'pending'", 'pend = [np]' in js)
html = open('templates/dashboard.html', encoding='utf-8').read()
kiem("doi ?v= de dien thoai chac chan tai ban moi", 'dashboard.js?v=p251' in html)

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
