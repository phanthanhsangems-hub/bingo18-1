"""P215: danh sách 8 lần trip gần nhất trong bảng "Bộ 3 số trùng nhau".

Dòng "Trip gần nhất" cũ chỉ nói được MỘT lần, nên không thấy được nhịp: 4 trip
dồn trong 50 kỳ khác hẳn 4 trip rải đều 800 kỳ, mà cả hai đều hiện y như nhau.
"""
import os
import sqlite3
import tempfile

os.environ.pop('DATABASE_URL', None)
_TMP = os.path.join(tempfile.mkdtemp(), 'trip_recent.db')

import config
config.DB_PATH = _TMP
import app as A

fails = []


def nap(vi_tri, n=200):
    """vi_tri: {số kỳ: giá trị trip}. Các kỳ còn lại là 1-2-4."""
    c = sqlite3.connect(_TMP)
    c.execute("DELETE FROM draw_history")
    for i in range(1, n + 1):
        nums = [vi_tri[i]] * 3 if i in vi_tri else [1, 2, 4]
        s = sum(nums)
        c.execute("INSERT INTO draw_history (draw_number, draw_time, numbers,"
                  " size_category, sum_value) VALUES (?,?,?,?,?)",
                  (i, '2026-01-01 10:00:00', str(nums),
                   'NHO' if s <= 9 else 'LON', s))
    c.commit(); c.close()
    with A._stats_snap_lock:
        A._stats_snap['data'], A._stats_snap['exp'] = None, 0.0
    with A._tv_lock:
        A._tv_snap['data'], A._tv_snap['exp'] = None, 0.0
    return A.app.test_client().get('/api/board-stats').get_json()['any']


print("=" * 62)

# 1) Nhiều hơn 8 trip -> chỉ giữ 8 lần MỚI NHẤT
d = nap({10: 1, 20: 2, 30: 3, 40: 4, 50: 5, 60: 6,
         70: 1, 80: 2, 90: 3, 100: 4, 110: 5, 200: 6})
r = d.get('recent', [])
# 12 trip ở #10,20,...,110,200 -> 8 lần cuối là #50..#110 và #200
mong = [200, 110, 100, 90, 80, 70, 60, 50]
if [x['draw'] for x in r] == mong:
    print("  OK   12 trip -> giữ đúng 8 lần mới nhất (#200 ... #50)")
else:
    fails.append(f"trần 8 sai: {len(r)} mục, {[x['draw'] for x in r]}")

# 2) Sắp theo kỳ giảm dần — mới nhất lên đầu
if all(r[i]['draw'] > r[i + 1]['draw'] for i in range(len(r) - 1)):
    print("  OK   Sắp giảm dần, mới nhất lên đầu")
else:
    fails.append(f"thứ tự sai: {[x['draw'] for x in r]}")

# 3) gap = cách kỳ mới nhất bao nhiêu kỳ
if all(x['gap'] == 200 - x['draw'] for x in r):
    print("  OK   gap tính đúng (cách kỳ mới nhất)")
else:
    fails.append(f"gap sai: {[(x['draw'], x['gap']) for x in r]}")

# 4) combo phải đúng bộ đã ra, không phải bộ khác
d = nap({150: 3, 200: 6})
r = d['recent']
if [x['combo'] for x in r] == ['666', '333']:
    print("  OK   combo khớp đúng trip đã ra")
else:
    fails.append(f"combo sai: {[x['combo'] for x in r]}")

# 5) Ít hơn 8 trip -> trả về bấy nhiêu, không đệm thêm
if len(r) == 2:
    print("  OK   Chỉ 2 trip -> trả 2 mục, không đệm")
else:
    fails.append(f"đệm thừa: {len(r)} mục cho 2 trip")

# 6) Không trip nào -> danh sách rỗng, không nổ
d = nap({})
if d.get('recent') == [] and d.get('last_draw') is None:
    print("  OK   Không trip nào -> danh sách rỗng, không nổ")
else:
    fails.append(f"khi không có trip: recent={d.get('recent')}")

# 7) Trip ở đúng kỳ mới nhất -> gap = 0, hiện 'kỳ này'
d = nap({200: 4})
if d['recent'] and d['recent'][0]['gap'] == 0:
    print("  OK   Trip ở kỳ mới nhất -> gap = 0")
else:
    fails.append(f"gap kỳ mới nhất phải là 0: {d.get('recent')}")

# 8) recent[0] phải trùng last_draw/last_combo cũ — không được mâu thuẫn
d = nap({120: 2, 190: 5})
r = d['recent']
if r[0]['draw'] == d['last_draw'] and r[0]['combo'] == d['last_combo']:
    print("  OK   Mục đầu khớp last_draw/last_combo (không mâu thuẫn)")
else:
    fails.append(f"mục đầu {r[0]} lệch last_draw={d['last_draw']} "
                 f"last_combo={d['last_combo']}")

print("=" * 62)
print(f"RESULTS: {8 - len(fails)} passed, {len(fails)} failed")
for f in fails:
    print("  FAIL " + f)
print("=" * 62)
print("ALL TESTS PASSED" if not fails else "TESTS FAILED")
raise SystemExit(1 if fails else 0)
