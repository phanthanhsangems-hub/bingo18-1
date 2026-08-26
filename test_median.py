"""P212: trung vị khoảng cách cho bảng tổng và bảng trip.

Cột "TB kỳ về" là TRUNG BÌNH, bị vài đợt hạn cực dài kéo lệch. Đo trên 87.412
kỳ: trip 111 trung bình 218 kỳ nhưng trung vị chỉ 158.

Điểm mấu chốt của bộ test này: tổng và trip tính trung vị bằng HAI ĐƯỜNG CODE
KHÁC HẲN NHAU — tổng tính bằng SQL (LAG + ROW_NUMBER trong DB), trip tính
bằng vòng lặp Python. Tổng 3 CHỈ ra được từ 111 và tổng 18 CHỈ ra được từ 666,
nên hai đường đó bắt buộc cho cùng một con số. Lệch là một trong hai sai.
"""
import os
import sqlite3
import tempfile

os.environ.pop('DATABASE_URL', None)
_TMP = os.path.join(tempfile.mkdtemp(), 'median_test.db')

import config
config.DB_PATH = _TMP
import app as A

fails = []


def nap(vi_tri_111, vi_tri_666, n=400):
    """n kỳ nền tổng 7, cắm 111 và 666 vào đúng các kỳ chỉ định."""
    c = sqlite3.connect(_TMP)
    c.execute("DELETE FROM draw_history")
    for i in range(1, n + 1):
        ns, sv, sz = '[1, 2, 4]', 7, 'NHO'
        if i in vi_tri_111: ns, sv, sz = '[1, 1, 1]', 3, 'NHO'
        if i in vi_tri_666: ns, sv, sz = '[6, 6, 6]', 18, 'LON'
        c.execute("INSERT INTO draw_history (draw_number, draw_time, numbers,"
                  " size_category, sum_value) VALUES (?,?,?,?,?)",
                  (i, '2026-01-01 10:00:00', ns, sz, sv))
    c.commit(); c.close()
    with A._stats_snap_lock:
        A._stats_snap['data'], A._stats_snap['exp'] = None, 0.0
    with A._tv_lock:
        A._tv_snap['data'], A._tv_snap['exp'] = None, 0.0
    d = A.app.test_client().get('/api/board-stats').get_json()
    return ({x['sum']: x for x in d['sums']}, {x['combo']: x for x in d['triples']}, d)


print("=" * 62)

# 1) SO LE: 4 lan ra -> 3 khoang cach 10/20/40 -> trung vi = 20
sm, tt, _ = nap({10, 20, 40, 80}, {5, 105})
print("  111 tai ky 10,20,40,80 -> khoang cach 10, 20, 40")
if tt['111']['median_gap'] == 20:
    print("  OK   So le: trung vi = 20 (phan tu giua)")
else:
    fails.append("so le: mong 20, duoc %s" % tt['111']['median_gap'])

# 2) HAI DUONG CODE PHAI KHOP — tong 3 chi ra tu 111
if sm[3]['median_gap'] == tt['111']['median_gap']:
    print("  OK   SQL (tong 3) == Python (trip 111): %s" % sm[3]['median_gap'])
else:
    fails.append("tong 3 = %s nhung trip 111 = %s — hai duong code lech"
                 % (sm[3]['median_gap'], tt['111']['median_gap']))

# 3) SO CHAN: 5 lan ra -> 4 khoang 10/20/40/80 -> trung vi = (20+40)/2 = 30
sm, tt, _ = nap({10, 20, 40, 80, 160}, {5, 105, 205})
print("\n  111 tai 10,20,40,80,160 -> khoang cach 10, 20, 40, 80")
if tt['111']['median_gap'] == 30:
    print("  OK   So chan: trung vi = 30 (trung binh hai phan tu giua)")
else:
    fails.append("so chan: mong 30, duoc %s" % tt['111']['median_gap'])
if sm[3]['median_gap'] == 30:
    print("  OK   SQL cung ra 30 o truong hop so chan")
else:
    fails.append("SQL so chan: mong 30, duoc %s" % sm[3]['median_gap'])

# 4) tong 18 <-> trip 666
if sm[18]['median_gap'] == tt['666']['median_gap'] == 100:
    print("  OK   tong 18 == trip 666 == 100")
else:
    fails.append("tong 18 = %s, trip 666 = %s (mong ca hai = 100)"
                 % (sm[18]['median_gap'], tt['666']['median_gap']))

# 5) Ve DUNG MOT lan -> khong co khoang cach nao -> None, khong duoc no
sm, tt, _ = nap({50}, {60})
print()
if sm[3]['median_gap'] is None and tt['111']['median_gap'] is None:
    print("  OK   Ve dung 1 lan -> trung vi = None (khong no)")
else:
    fails.append("ve 1 lan: tong3=%s trip111=%s, mong None"
                 % (sm[3]['median_gap'], tt['111']['median_gap']))

# 6) TRUNG VI PHAI THAP HON TRUNG BINH khi co mot dot han dai bat thuong
#    (day chinh la ly do them cot nay)
sm, tt, _ = nap({10, 20, 30, 40, 400}, {5}, n=400)
tv, tb = tt['111']['median_gap'], tt['111']['avg_gap']
print("\n  111 tai 10,20,30,40,400 -> khoang 10, 10, 10, 360")
print("  trung vi = %s | TB (tong ky / so lan ve) = %s" % (tv, tb))
if tv is not None and tb is not None and tv < tb:
    print("  OK   Mot dot han dai keo TB len, trung vi khong bi anh huong")
else:
    fails.append("trung vi %s khong thap hon TB %s" % (tv, tb))

print("=" * 62)
print("RESULTS: %d passed, %d failed" % (7 - len(fails), len(fails)))
for f in fails:
    print("  FAIL " + f)
print("=" * 62)
print("ALL TESTS PASSED" if not fails else "TESTS FAILED")
raise SystemExit(1 if fails else 0)
