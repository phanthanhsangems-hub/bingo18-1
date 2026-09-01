"""P215: 8 KỲ QUAY gần nhất trong bảng "Bộ 3 số trùng nhau".

Kết quả thật của 8 kỳ vừa rồi — MỌI kỳ, không riêng trip. Bản đầu tôi làm
nhầm thành "8 lần trip gần nhất"; người dùng sửa lại.
"""
import os
import sqlite3
import tempfile

os.environ.pop('DATABASE_URL', None)
_TMP = os.path.join(tempfile.mkdtemp(), 'recent_draws.db')

import config
config.DB_PATH = _TMP
import app as A

fails = []


def nap(danh_sach):
    """danh_sach: [(số kỳ, [3 số]), ...] — nạp đúng những kỳ này."""
    c = sqlite3.connect(_TMP)
    c.execute("DELETE FROM draw_history")
    for dn, nums in danh_sach:
        s = sum(nums)
        c.execute("INSERT INTO draw_history (draw_number, draw_time, numbers,"
                  " size_category, sum_value) VALUES (?,?,?,?,?)",
                  (dn, '2026-01-01 10:00:00', str(nums),
                   'NHO' if s <= 9 else ('HOA' if s <= 11 else 'LON'), s))
    c.commit(); c.close()
    with A._stats_snap_lock:
        A._stats_snap['data'], A._stats_snap['exp'] = None, 0.0
    with A._tv_lock:
        A._tv_snap['data'], A._tv_snap['exp'] = None, 0.0
    return A.app.test_client().get('/api/board-stats').get_json()


def day(n=30):
    return [(i, [1, 2, 4]) for i in range(1, n + 1)]


print("=" * 62)

# 1) Đúng 8 kỳ, mới nhất lên đầu
d = nap(day(30))
r = d.get('recent_draws', [])
if len(r) == 8 and [x['draw'] for x in r] == list(range(30, 22, -1)):
    print("  OK   Trả đúng 8 kỳ, mới nhất lên đầu (#30 -> #23)")
else:
    fails.append(f"sai danh sách: {[x['draw'] for x in r]}")

# 2) MỌI kỳ, không lọc trip — đây chính là chỗ tôi làm nhầm lần đầu
ds = day(30)
ds[29] = (30, [5, 5, 5])          # chỉ kỳ cuối là trip
d = nap(ds)
r = d['recent_draws']
if len(r) == 8 and sum(1 for x in r if x['is_trip']) == 1:
    print("  OK   Lấy MỌI kỳ (7 kỳ thường + 1 trip), không lọc riêng trip")
else:
    fails.append(f"lọc nhầm: {[(x['draw'], x['is_trip']) for x in r]}")

# 3) numbers/sum/size đúng
d = nap([(1, [1, 2, 3]), (2, [4, 4, 3]), (3, [6, 6, 6])])
r = d['recent_draws']
mong = [(3, [6, 6, 6], 18, 'LON', True),
        (2, [3, 4, 4], 11, 'HOA', False),
        (1, [1, 2, 3], 6, 'NHO', False)]
got = [(x['draw'], sorted(x['numbers']), x['sum'], x['size'], x['is_trip']) for x in r]
if got == [(a, sorted(b), c, e, f) for a, b, c, e, f in mong]:
    print("  OK   numbers/sum/size/is_trip đều đúng")
else:
    fails.append(f"nội dung sai: {got}")

# 4) Ít hơn 8 kỳ -> trả bấy nhiêu
if len(r) == 3:
    print("  OK   Chỉ 3 kỳ -> trả 3, không đệm thêm")
else:
    fails.append(f"đệm thừa: {len(r)}")

# 5) sum phải TỰ CỘNG từ numbers, không lấy cột sum_value có thể sai.
#    Đây đúng loại lỗi vụ tổng 7/14: numbers đúng mà sum_value ghi sai.
c = sqlite3.connect(_TMP)
c.execute("DELETE FROM draw_history")
c.execute("INSERT INTO draw_history (draw_number, draw_time, numbers,"
          " size_category, sum_value) VALUES (?,?,?,?,?)",
          (7, '2026-01-01 10:00:00', '[1, 2, 3]', 'LON', 99))   # sum_value SAI
c.commit(); c.close()
with A._stats_snap_lock:
    A._stats_snap['data'], A._stats_snap['exp'] = None, 0.0
with A._tv_lock:
    A._tv_snap['data'], A._tv_snap['exp'] = None, 0.0
r = A.app.test_client().get('/api/board-stats').get_json()['recent_draws']
if r and r[0]['sum'] == 6:
    print("  OK   sum tự cộng từ numbers (không tin cột sum_value ghi sai)")
else:
    fails.append(f"lấy nhầm sum_value: {r}")

# 6) DB rỗng -> danh sách rỗng, không nổ
d = nap([])
if d.get('recent_draws') == []:
    print("  OK   DB rỗng -> danh sách rỗng, không nổ")
else:
    fails.append(f"DB rỗng: {d.get('recent_draws')}")

# 7) Kỳ mới nhất phải trùng mốc mà bảng dùng để tính "chưa về"
d = nap(day(50))
r = d['recent_draws']
t = {x['combo']: x for x in d['triples']}
# 50 kỳ toàn 1-2-4, không trip nào -> current_gap phải là None
if r[0]['draw'] == 50 and all(t[c]['current_gap'] is None for c in t):
    print("  OK   Kỳ mới nhất khớp mốc của bảng")
else:
    fails.append(f"mốc lệch: recent[0]={r[0]['draw']}")

print("=" * 62)
print(f"RESULTS: {7 - len(fails)} passed, {len(fails)} failed")
for f in fails:
    print("  FAIL " + f)
print("=" * 62)
print("ALL TESTS PASSED" if not fails else "TESTS FAILED")
raise SystemExit(1 if fails else 0)
