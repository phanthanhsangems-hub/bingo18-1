"""P206: kiểm tra ?fill_gaps=1 của /api/sync-github.

Trọng tâm: (1) bù đúng lỗ hổng ở giữa, (2) KHÔNG nới lịch sử về quá khứ —
nới thì total_draws đổi và mọi cột "TB kỳ về" lệch theo.
"""
import json
import os
import sqlite3
import sys
from unittest import mock

os.environ.pop('DATABASE_URL', None)
os.environ['TRIGGER_SECRET'] = 's3cr3t'

import tempfile
_TMP = os.path.join(tempfile.mkdtemp(), 'fill_gaps_test.db')

import config
config.TRIGGER_SECRET = 's3cr3t'
# DB rieng: data/bingo18.db that da tich tu lo hong tu nhieu lan seed, dung
# no thi test do nham lo hong cua nguoi khac.
config.DB_PATH = _TMP
import app as A
A.config.TRIGGER_SECRET = 's3cr3t'
import database

fails = []

# Dung DB sach: 200 ky lien tuc, khong lo hong
# app da tao san schema khi import (config.DB_PATH tro vao day), nen chi
# can don sach roi nap du lieu test.
_c = sqlite3.connect(_TMP)
_c.execute("DELETE FROM draw_history")
for i in range(1, 201):
    _c.execute("INSERT INTO draw_history (draw_number, draw_time, numbers,"
               " size_category, sum_value) VALUES (?,?,?,?,?)",
               (i, '2026-01-01 10:00:00', '[1, 2, 3]', 'NHO', 6))
_c.commit(); _c.close()


def dem(path=_TMP):
    c = sqlite3.connect(path)
    r = list(c.execute("SELECT MIN(draw_number), MAX(draw_number), COUNT(*) FROM draw_history"))[0]
    ds = {x[0] for x in c.execute("SELECT draw_number FROM draw_history")}
    c.close()
    lo, hi, n = int(r[0]), int(r[1]), int(r[2])
    return lo, hi, n, sorted(set(range(lo, hi + 1)) - ds)


lo, hi, n0, _ = dem()
# tao 2 lo hong o giua + xoa 3 ky dau de thu "noi lich su"
giua = [lo + 40, lo + 41]
dau  = [lo, lo + 1, lo + 2]
c = sqlite3.connect(_TMP)
for d in giua + dau:
    c.execute("DELETE FROM draw_history WHERE draw_number = ?", (d,))
c.commit(); c.close()

lo2, hi2, n1, thieu = dem()
print(f"  Da xoa {len(giua)} ky o giua {giua} va {len(dau)} ky dau {dau}")
print(f"  Truoc khi bu: {n1} ky, khoang #{lo2}-#{hi2}, lo hong o giua: {thieu[:10]}")
if thieu != giua:
    fails.append(f"lo hong phai la {giua}, do duoc {thieu}")

# gia lap file GitHub: co ĐU ca ky o giua, ky dau, VA ky cu hon lo2
gia = ([{"id": d, "result": [1, 2, 3], "date": "2026-01-01"} for d in giua]
       + [{"id": d, "result": [1, 2, 3], "date": "2026-01-01"} for d in dau]
       + [{"id": lo2 - 500 + i, "result": [4, 5, 6], "date": "2026-01-01"} for i in range(50)])
body = "\n".join(json.dumps(x) for x in gia)


class R:
    status_code = 200
    text = body


c = A.app.test_client()
with mock.patch('requests.get', return_value=R()):
    r = c.get('/api/sync-github?fill_gaps=1', headers={'X-Trigger-Secret': 's3cr3t'})
d = r.get_json()
print(f"\n  HTTP {r.status_code}: {json.dumps(d, ensure_ascii=False)[:200]}")

lo3, hi3, n2, thieu2 = dem()
print(f"\n  Sau khi bu  : {n2} ky, khoang #{lo3}-#{hi3}, lo hong con lai: {thieu2[:10]}")

print("\n" + "=" * 60)
if d.get('gaps_filled') != len(giua):
    fails.append(f"gaps_filled phai la {len(giua)}, thuc te {d.get('gaps_filled')}")
else:
    print(f"  OK   Bu dung {len(giua)} ky lo hong o giua")
if thieu2:
    fails.append(f"van con lo hong {thieu2[:10]}")
else:
    print("  OK   Khong con lo hong o giua")
if lo3 < lo2:
    fails.append(f"DA NOI LICH SU: min tu #{lo2} lui ve #{lo3} — lam lech TB ky ve")
else:
    print(f"  OK   Khong noi lich su ve qua khu (min van la #{lo3})")
# 3 ky dau da xoa nam NGOAI khoang [lo2,hi2] nen khong duoc chen lai
if any(x in range(lo3, hi3 + 1) and x < lo2 for x in dau):
    fails.append("chen lai ky nam ngoai khoang")
else:
    print("  OK   Ky dau da xoa nam ngoai khoang -> dung la khong chen lai")

print("=" * 60)
print(f"RESULTS: {4 - len(fails)} passed, {len(fails)} failed")
print("=" * 60)
if fails:
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL TESTS PASSED")
