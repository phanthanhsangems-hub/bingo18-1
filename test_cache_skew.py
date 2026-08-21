"""P207: bảng tổng và bảng trip phải luôn cùng một mốc kỳ.

Tổng 3 CHỈ ra được từ 111, tổng 18 CHỈ ra được từ 666. Nên trên màn hình
"chưa về" của tổng 3 và của trip 111 BẮT BUỘC bằng nhau — mọi lúc.

Trước P207 hai endpoint cache 300s riêng, hết hạn độc lập. Kỳ mới về thì
bảng nào hết hạn trước sẽ nhảy trước, bảng kia đứng yên tới 5 phút. Người
dùng nhìn thấy 183 vs 182 và kết luận "hệ thống chưa cập nhật".
"""
import os
import sqlite3
import tempfile

os.environ.pop('DATABASE_URL', None)

_TMP = os.path.join(tempfile.mkdtemp(), 'cache_skew_test.db')

import config
config.DB_PATH = _TMP
import app as A

fails = []
_next = [0]


def nap(sach=True):
    """200 kỳ: #100 là 111 (tổng 3), #150 là 666 (tổng 18), còn lại 1-2-3."""
    c = sqlite3.connect(_TMP)
    if sach:
        c.execute("DELETE FROM draw_history")
    for i in range(1, 201):
        ns, sv, sz = '[1, 2, 3]', 6, 'NHO'
        if i == 100: ns, sv, sz = '[1, 1, 1]', 3, 'NHO'
        if i == 150: ns, sv, sz = '[6, 6, 6]', 18, 'LON'
        c.execute("INSERT INTO draw_history (draw_number, draw_time, numbers,"
                  " size_category, sum_value) VALUES (?,?,?,?,?)",
                  (i, '2026-01-01 10:00:00', ns, sz, sv))
    c.commit(); c.close()
    _next[0] = 201


def them_ky(n=1):
    """Thêm n kỳ mới, không kỳ nào là trip."""
    c = sqlite3.connect(_TMP)
    for _ in range(n):
        c.execute("INSERT INTO draw_history (draw_number, draw_time, numbers,"
                  " size_category, sum_value) VALUES (?,?,?,?,?)",
                  (_next[0], '2026-01-01 10:00:00', '[1, 2, 4]', 'NHO', 7))
        _next[0] += 1
    c.commit(); c.close()


def doc(cl):
    ss = cl.get('/api/sum-stats').get_json()
    ts = cl.get('/api/triple-stats').get_json()
    sm = {x['sum']: x['current_gap'] for x in ss['sums']}
    tt = {x['combo']: x['current_gap'] for x in ts['triples']}
    return sm, tt


def reset_cache():
    with A._resp_cache_lock:
        A._resp_cache.clear()
    with A._latest_dn_lock:
        A._latest_dn['dn'] = 0


nap()
cl = A.app.test_client()

print("=" * 60)

# 1) moc ban dau phai khop
reset_cache()
sm, tt = doc(cl)
print(f"  tong  3 = {sm[3]:3d} | trip 111 = {tt['111']:3d}")
print(f"  tong 18 = {sm[18]:3d} | trip 666 = {tt['666']:3d}")
if sm[3] == tt['111'] and sm[18] == tt['666']:
    print("  OK   Moc ban dau: hai bang khop")
else:
    fails.append(f"moc ban dau lech: tong3={sm[3]} trip111={tt['111']}, "
                 f"tong18={sm[18]} trip666={tt['666']}")

# 2) TAI HIEN LOI: nap cache cho RIENG sum-stats, roi moi co ky moi ve.
#    Truoc P207: sum-stats tra ban cu (HIT), triple-stats tinh moi (MISS)
#    -> hai bang lech dung 1 ky, y het anh chup cua nguoi dung.
reset_cache()
cl.get('/api/sum-stats')          # chi nap mot ben
them_ky(1)                        # ky moi ve
sm, tt = doc(cl)
print()
print(f"  Sau khi nap cache LECH PHA roi co 1 ky moi:")
print(f"  tong  3 = {sm[3]:3d} | trip 111 = {tt['111']:3d}")
print(f"  tong 18 = {sm[18]:3d} | trip 666 = {tt['666']:3d}")
if sm[3] == tt['111'] and sm[18] == tt['666']:
    print("  OK   Ky moi ve: hai bang van khop (cache truot cung luc)")
else:
    fails.append(f"cache lech pha: tong3={sm[3]} trip111={tt['111']}, "
                 f"tong18={sm[18]} trip666={tt['666']} (chenh "
                 f"{sm[3]-tt['111']} / {sm[18]-tt['666']})")

# 3) gia tri phai DUNG chu khong chi bang nhau
reset_cache()
sm, tt = doc(cl)
c = sqlite3.connect(_TMP)
maxdn = int(list(c.execute("SELECT MAX(draw_number) FROM draw_history"))[0][0])
c.close()
mong = maxdn - 100        # 111 nam o ky #100
print()
print(f"  Ky moi nhat #{maxdn}, trip 111 o #100 -> chua ve phai la {mong}")
if tt['111'] == mong and sm[3] == mong:
    print(f"  OK   Gia tri dung ({mong})")
else:
    fails.append(f"gia tri sai: mong {mong}, tong3={sm[3]} trip111={tt['111']}")

# 4) nhieu ky lien tiep — moi ky deu phai keo CA HAI bang di cung
reset_cache()
lech = []
for buoc in range(5):
    cl.get('/api/sum-stats')      # co tinh lam lech pha moi vong
    them_ky(1)
    sm, tt = doc(cl)
    if sm[3] != tt['111'] or sm[18] != tt['666']:
        lech.append(f"buoc {buoc}: tong3={sm[3]} trip111={tt['111']}, "
                    f"tong18={sm[18]} trip666={tt['666']}")
print()
if lech:
    fails.append("5 ky lien tiep bi lech: " + "; ".join(lech))
    print("  FAIL 5 ky lien tiep:")
    for x in lech: print("    " + x)
else:
    print("  OK   5 ky lien tiep: khong ky nao lam hai bang lech")

# 5) cache van con tac dung (khong pha vo muc dich ban dau)
reset_cache()
cl.get('/api/sum-stats')
r = cl.get('/api/sum-stats')
if r.headers.get('X-Cache') == 'HIT':
    print("  OK   Cache van hoat dong khi chua co ky moi (X-Cache: HIT)")
else:
    fails.append(f"cache mat tac dung: X-Cache={r.headers.get('X-Cache')}")

print("=" * 60)
print(f"RESULTS: {5 - len(fails)} passed, {len(fails)} failed")
for f in fails:
    print("  FAIL " + f)
print("=" * 60)
print("ALL TESTS PASSED" if not fails else "TESTS FAILED")
raise SystemExit(1 if fails else 0)
