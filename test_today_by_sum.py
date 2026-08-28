"""P213: "Bộ số hôm nay" gom theo TỔNG.

Trước đây chỉ có hai đống "đã ra" / "chưa ra". Muốn biết tổng 7 còn thiếu bộ
nào thì phải tự dò trong 56 chip. Giao diện gom theo tổng, nhưng phép gom dựa
hoàn toàn vào trường 'sum' của endpoint — nên hợp đồng đó phải chắc.
"""
import itertools
import os
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone

os.environ.pop('DATABASE_URL', None)
_TMP = os.path.join(tempfile.mkdtemp(), 'today_test.db')

import config
config.DB_PATH = _TMP
import app as A

fails = []
VN = timezone(timedelta(hours=7))
DUNG = Counter(sum(c) for c in itertools.combinations_with_replacement(range(1, 7), 3))


def goi():
    return A.app.test_client().get('/api/today-combos').get_json()


def gom(d):
    """Gom theo tổng ĐÚNG như dashboard.js làm."""
    ro = {t: {'ra': [], 'chua': []} for t in range(3, 19)}
    for c in d.get('appeared', []):     ro[c['sum']]['ra'].append(c)
    for c in d.get('not_appeared', []): ro[c['sum']]['chua'].append(c)
    return ro


def nap(bo_hom_nay):
    """bo_hom_nay: list các bộ 3 số sẽ được ghi với mốc thời gian HÔM NAY (giờ VN)."""
    c = sqlite3.connect(_TMP)
    c.execute("DELETE FROM draw_history")
    # kỳ cũ (hôm kia) — không được tính vào hôm nay
    cu = (datetime.now(VN) - timedelta(days=2)).astimezone(timezone.utc)
    c.execute("INSERT INTO draw_history (draw_number, draw_time, numbers, size_category,"
              " sum_value) VALUES (?,?,?,?,?)",
              (1, cu.strftime('%Y-%m-%d %H:%M:%S'), '[6, 6, 6]', 'LON', 18))
    now = datetime.now(VN).astimezone(timezone.utc)
    for i, b in enumerate(bo_hom_nay, start=2):
        s = sum(b)
        sz = 'NHO' if s <= 9 else ('HOA' if s <= 11 else 'LON')
        c.execute("INSERT INTO draw_history (draw_number, draw_time, numbers, size_category,"
                  " sum_value) VALUES (?,?,?,?,?)",
                  (i, now.strftime('%Y-%m-%d %H:%M:%S'), str(list(b)), sz, s))
    c.commit(); c.close()
    # /api/today-combos có @cache_resp(ttl=60). Không dọn thì lần gọi sau nhận
    # lại bản cũ và test đo nhầm cache thay vì dữ liệu.
    with A._resp_cache_lock:
        A._resp_cache.clear()


print("=" * 60)

# 1) 56 bộ, không thiếu không thừa, không trùng
nap([])
d = goi()
tat = d['appeared'] + d['not_appeared']
dem = Counter(tuple(c['combo']) for c in tat)
if len(tat) == 56 and all(v == 1 for v in dem.values()) and len(dem) == 56:
    print("  OK   Đủ 56 bộ, mỗi bộ đúng một lần, không trùng")
else:
    fails.append(f"số bộ = {len(tat)}, bộ khác nhau = {len(dem)}")

# 2) Kích thước từng rổ phải khớp toán học
ro = gom(d)
lech = [t for t in range(3, 19)
        if len(ro[t]['ra']) + len(ro[t]['chua']) != DUNG[t]]
if not lech:
    print("  OK   16 rổ đúng kích thước (tổng 3 và 18 có 1 bộ, tổng 10-11 có 6 bộ)")
else:
    fails.append("rổ sai kích thước ở tổng: %s" % lech)

# 3) 'sum' phải khớp với chính bộ số — giao diện gom bằng trường này
sai = [c for c in tat if sum(c['combo']) != c['sum']]
if not sai:
    print("  OK   Trường 'sum' khớp với bộ số ở cả 56 bộ")
else:
    fails.append("%d bộ có sum không khớp" % len(sai))

# 4) Bộ ra hôm nay phải vào nhánh 'ra', kèm đúng số lần
nap([(1, 2, 4), (1, 2, 4), (2, 2, 3), (5, 5, 5)])
d = goi(); ro = gom(d)
lay = {tuple(c['combo']): c['count'] for c in d['appeared']}
mong = {(1, 2, 4): 2, (2, 2, 3): 1, (5, 5, 5): 1}
if lay == mong:
    print("  OK   Đếm đúng số lần: 1-2-4 x2, 2-2-3 x1, 5-5-5 x1")
else:
    fails.append("đếm sai: %s (mong %s)" % (lay, mong))

# 5) Tổng 7 có 4 bộ: 1-2-4 và 2-2-3 đã ra, 1-1-5 và 1-3-3 chưa
r7 = ro[7]
ra7 = sorted(tuple(c['combo']) for c in r7['ra'])
chua7 = sorted(tuple(c['combo']) for c in r7['chua'])
if ra7 == [(1, 2, 4), (2, 2, 3)] and chua7 == [(1, 1, 5), (1, 3, 3)]:
    print("  OK   Tổng 7: đã ra 1-2-4, 2-2-3 | chưa ra 1-1-5, 1-3-3")
else:
    fails.append("tổng 7 sai: ra=%s chua=%s" % (ra7, chua7))

# 6) Tổng 15 có 3 bộ, 5-5-5 đã ra -> hàng hiện 1/3
r15 = ro[15]
if len(r15['ra']) == 1 and tuple(r15['ra'][0]['combo']) == (5, 5, 5) \
   and len(r15['ra']) + len(r15['chua']) == 3:
    print("  OK   Tổng 15: 1/3 — chỉ 5-5-5 đã ra")
else:
    fails.append("tổng 15 sai")

# 7) Kỳ của HÔM KIA không được tính vào hôm nay (6-6-6 phải nằm ở 'chưa ra')
if (6, 6, 6) not in lay:
    print("  OK   Kỳ hôm kia không bị tính vào hôm nay")
else:
    fails.append("6-6-6 của hôm kia bị tính nhầm vào hôm nay")

print("=" * 60)
print("RESULTS: %d passed, %d failed" % (7 - len(fails), len(fails)))
for f in fails:
    print("  FAIL " + f)
print("=" * 60)
print("ALL TESTS PASSED" if not fails else "TESTS FAILED")
raise SystemExit(1 if fails else 0)
