"""P218: chuỗi khoảng cách cho 6 trip 111..666.

Chỗ đắt giá nhất của bộ test này là một BẤT BIẾN TOÁN HỌC: tổng 3 chỉ ra được
từ 111, tổng 18 chỉ ra được từ 666. Hai bảng tính chuỗi bằng HAI ĐƯỜNG CODE
KHÁC HẲN NHAU — bảng tổng lấy từ truy vấn ROW_NUMBER trên sum_value, bảng trip
lấy từ vòng lặp Python duyệt numbers. Nên gaps của tổng 3 BẮT BUỘC bằng gaps
của trip 111. Lệch là một trong hai sai, và mắt thường không bắt được.

Chiều cũng là chỗ dễ sai: kc[a] dựng theo thứ tự vòng lặp (rows ORDER BY
draw_number tăng dần) nên đã là cũ -> mới; nếu ai đó đổi ORDER BY thì test này
phải đỏ.
"""
import os
import sqlite3
import tempfile

os.environ.pop('DATABASE_URL', None)
_TMP = os.path.join(tempfile.mkdtemp(), 'kct.db')

import config
config.DB_PATH = _TMP
import app as A

fails = []

BO = {1: '[1, 1, 1]', 2: '[2, 2, 2]', 3: '[3, 3, 3]', 4: '[4, 4, 4]',
      5: '[5, 5, 5]', 6: '[6, 6, 6]'}


def nap(vi_tri_trip, n=3000, nen='[1, 2, 4]', nen_sum=7):
    """n kỳ nền, cắm trip vào đúng các kỳ chỉ định. {so: [ky, ...]}"""
    dat = {}
    for so, ds in vi_tri_trip.items():
        for d in ds:
            dat[d] = so
    c = sqlite3.connect(_TMP)
    c.execute("DELETE FROM draw_history")
    for i in range(1, n + 1):
        so = dat.get(i)
        if so:
            ns, sv = BO[so], so * 3
        else:
            ns, sv = nen, nen_sum
        sz = 'NHO' if sv <= 9 else ('HOA' if sv <= 11 else 'LON')
        c.execute("INSERT INTO draw_history (draw_number, draw_time, numbers,"
                  " size_category, sum_value) VALUES (?,?,?,?,?)",
                  (i, '2026-01-01 10:00:00', ns, sz, sv))
    c.commit(); c.close()
    with A._stats_snap_lock:
        A._stats_snap['data'], A._stats_snap['exp'] = None, 0.0
    with A._tv_lock:
        A._tv_snap['data'], A._tv_snap['exp'] = None, 0.0
    d = A.app.test_client().get('/api/board-stats').get_json()
    return ({x['combo']: x for x in d['triples']},
            {x['sum']: x for x in d['sums']}, d)


def ok(dk, ten, ct=''):
    print(f"  {'OK  ' if dk else 'HONG'}  {ten}")
    if not dk:
        fails.append(ten)
        if ct: print(f"        {ct}")


print("=" * 62)
print("P218: chuoi khoang cach theo trip")
print("=" * 62)

# ── 1. Chiều và giá trị ────────────────────────────────────────
# trip 333 ra ở kỳ 100, 104, 123, 200 -> khoảng cách CŨ->MỚI: 4, 19, 77
tr, sm, _ = nap({3: [100, 104, 123, 200]})
g = tr['333']['gaps']
ok(g == [4, 19, 77], "chuoi dung chieu CU -> MOI", f"nhan duoc {g}")
ok(tr['333']['prev_gap'] == g[-1],
   "phan tu cuoi == prev_gap", f"gaps[-1]={g[-1]} prev={tr['333']['prev_gap']}")
ok(tr['333']['current_gap'] == 3000 - 200,
   "current_gap nam NGOAI chuoi (chu ky chua xong)",
   f"cur={tr['333']['current_gap']}")

# ── 2. BẤT BIẾN: tổng 3 == trip 111, tổng 18 == trip 666 ──────
tr, sm, _ = nap({1: [50, 300, 1000, 2500], 6: [77, 400, 1500]})
ok(sm[3]['gaps'] == tr['111']['gaps'],
   "gaps tong 3 == gaps trip 111 (hai duong code khac nhau)",
   f"tong3={sm[3]['gaps']} trip111={tr['111']['gaps']}")
ok(sm[18]['gaps'] == tr['666']['gaps'],
   "gaps tong 18 == gaps trip 666",
   f"tong18={sm[18]['gaps']} trip666={tr['666']['gaps']}")
ok(sm[3]['current_gap'] == tr['111']['current_gap'], "current_gap tong 3 == trip 111")
ok(sm[18]['current_gap'] == tr['666']['current_gap'], "current_gap tong 18 == trip 666")

# ── 3. Tổng 6 KHÁC trip 222 (tổng 6 còn 1-2-3 và 1-1-4) ───────
c = sqlite3.connect(_TMP)
c.execute("DELETE FROM draw_history")
for i in range(1, 601):
    if   i == 100: ns, sv = '[2, 2, 2]', 6      # trip
    elif i == 200: ns, sv = '[1, 2, 3]', 6      # cung tong 6, KHONG phai trip
    elif i == 300: ns, sv = '[2, 2, 2]', 6      # trip
    else:          ns, sv = '[1, 2, 4]', 7
    c.execute("INSERT INTO draw_history (draw_number, draw_time, numbers,"
              " size_category, sum_value) VALUES (?,?,?,?,?)",
              (i, '2026-01-01 10:00:00', ns, 'NHO', sv))
c.commit(); c.close()
with A._stats_snap_lock: A._stats_snap['data'], A._stats_snap['exp'] = None, 0.0
with A._tv_lock: A._tv_snap['data'], A._tv_snap['exp'] = None, 0.0
d = A.app.test_client().get('/api/board-stats').get_json()
tr = {x['combo']: x for x in d['triples']}
sm = {x['sum']: x for x in d['sums']}
ok(tr['222']['gaps'] == [200], "trip 222: chi dem 2 lan trip -> [200]", f"{tr['222']['gaps']}")
ok(sm[6]['gaps'] == [100, 100], "tong 6: dem ca 1-2-3 -> [100, 100]", f"{sm[6]['gaps']}")
ok(tr['222']['gaps'] != sm[6]['gaps'], "trip 222 KHAC tong 6 (dung nhu mong doi)")

# ── 4. Ra 1 lần / chưa ra lần nào ─────────────────────────────
tr, _, _ = nap({4: [500]})
ok(tr['444']['gaps'] == [], "ra dung 1 lan -> chuoi rong", f"{tr['444']['gaps']}")
ok(tr['555']['gaps'] == [], "chua ra lan nao -> chuoi rong")
ok(tr['555']['current_gap'] is None, "chua ra lan nao -> current_gap None")

# ── 5. Cắt đúng _KC_SO_LAN lần về gần nhất ────────────────────
tr, _, _ = nap({2: [i * 30 for i in range(1, 41)]}, n=1500)
g = tr['222']['gaps']
ok(len(g) == A._KC_SO_LAN - 1,
   f"gioi han {A._KC_SO_LAN} lan ve -> {A._KC_SO_LAN - 1} khoang cach", f"{len(g)}")
ok(all(x == 30 for x in g), "moi khoang cach deu bang 30", f"{g}")

# ── 6. Dòng "bất kỳ trip nào" KHÔNG lẫn vào 6 trip ────────────
tr, _, d = nap({1: [100, 500], 6: [300]})
ok('***' not in [x for x in tr if len(x) == 3 and x.isdigit()],
   "dong '***' khong bi coi la trip")
ok(isinstance(d['any'].get('gaps'), list),
   "dong 'any' cung co gaps (giao dien tu loc bang regex)")

# ── 7. Tổng các khoảng cách == lần cuối trừ lần đầu ───────────
tr, _, _ = nap({5: [10, 60, 61, 400, 1200]})
g = tr['555']['gaps']
ok(sum(g) == 1200 - 10, "tong cac khoang cach == lan cuoi - lan dau",
   f"sum={sum(g)} can {1200 - 10}")
ok(g == [50, 1, 339, 800], "chuoi dung tung phan tu", f"{g}")

print("=" * 62)
if fails:
    print(f"HONG {len(fails)} test:")
    for f in fails: print("  - " + f)
    raise SystemExit(1)
print("Tat ca test P218 deu dat.")
