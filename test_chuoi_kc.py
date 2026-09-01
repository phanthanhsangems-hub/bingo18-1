"""P216: chuỗi khoảng cách theo tổng — thứ người dùng vẫn ghi tay trong sổ.

Mỗi tổng một dòng, mỗi số là khoảng cách giữa hai lần ra LIÊN TIẾP, đọc từ
CŨ sang MỚI. Điểm dễ sai nhất là chiều: câu truy vấn trả về giảm dần theo số
kỳ (mới nhất đứng đầu), còn sổ tay ghi tăng dần. Đảo nhầm chiều thì mọi con
số vẫn "hợp lý" nên mắt thường không bắt được — phải có test.

Ràng buộc thứ hai: 'gaps' và 'prev_gap' lấy từ CÙNG một nguồn, nên phần tử
CUỐI của gaps bắt buộc bằng prev_gap. Lệch là một trong hai tính sai.
"""
import os
import sqlite3
import tempfile

os.environ.pop('DATABASE_URL', None)
_TMP = os.path.join(tempfile.mkdtemp(), 'kc_test.db')

import config
config.DB_PATH = _TMP
import app as A

fails = []


def nap(vi_tri_theo_tong, n=400):
    """n kỳ nền tổng 10, cắm các tổng khác vào đúng những kỳ chỉ định.

    vi_tri_theo_tong: {sum_value: [số kỳ, ...]}
    """
    dat = {}
    for sv, ds in vi_tri_theo_tong.items():
        for d in ds:
            dat[d] = sv
    bo = {3: '[1, 1, 1]', 4: '[1, 1, 2]', 7: '[1, 2, 4]', 10: '[2, 4, 4]',
          15: '[3, 6, 6]', 18: '[6, 6, 6]'}
    c = sqlite3.connect(_TMP)
    c.execute("DELETE FROM draw_history")
    for i in range(1, n + 1):
        sv = dat.get(i, 10)
        sz = 'NHO' if sv <= 9 else ('HOA' if sv <= 11 else 'LON')
        c.execute("INSERT INTO draw_history (draw_number, draw_time, numbers,"
                  " size_category, sum_value) VALUES (?,?,?,?,?)",
                  (i, '2026-01-01 10:00:00', bo[sv], sz, sv))
    c.commit(); c.close()
    with A._stats_snap_lock:
        A._stats_snap['data'], A._stats_snap['exp'] = None, 0.0
    with A._tv_lock:
        A._tv_snap['data'], A._tv_snap['exp'] = None, 0.0
    d = A.app.test_client().get('/api/board-stats').get_json()
    return {x['sum']: x for x in d['sums']}, d


def ok(dieu_kien, ten, chi_tiet=''):
    print(f"  {'OK  ' if dieu_kien else 'HONG'}  {ten}")
    if not dieu_kien:
        fails.append(ten)
        if chi_tiet:
            print(f"        {chi_tiet}")


print("=" * 62)
print("P216: chuoi khoang cach theo tong")
print("=" * 62)

# ── 1. Chiều và giá trị ────────────────────────────────────────
# tổng 3 ra ở kỳ 100, 104, 123, 200. Khoảng cách CŨ->MỚI: 4, 19, 77.
by, _ = nap({3: [100, 104, 123, 200]})
g = by[3]['gaps']
ok(g == [4, 19, 77], "chuoi dung chieu CU -> MOI", f"nhan duoc {g}")
ok(by[3]['prev_gap'] == g[-1],
   "phan tu cuoi cua gaps == prev_gap", f"gaps[-1]={g[-1]} prev_gap={by[3]['prev_gap']}")
ok(by[3]['current_gap'] == 400 - 200,
   "current_gap khong nam trong chuoi (chu ky chua xong)",
   f"current_gap={by[3]['current_gap']}, gaps={g}")

# ── 2. Ra đúng 1 lần thì không có khoảng cách nào ──────────────
by, _ = nap({3: [150]})
ok(by[3]['gaps'] == [], "ra dung 1 lan -> chuoi rong", f"{by[3]['gaps']}")
ok(by[3]['prev_gap'] is None, "ra dung 1 lan -> prev_gap None")

# ── 3. Chưa ra lần nào ────────────────────────────────────────
by, _ = nap({3: [150]})
ok(by[18]['gaps'] == [], "tong chua ra lan nao -> chuoi rong")
ok(by[18]['current_gap'] is None, "tong chua ra lan nao -> current_gap None")

# ── 4. Cắt đúng _KC_SO_LAN lần về gần nhất ────────────────────
# 40 lần ra, cách nhau 5 kỳ -> chỉ giữ 25 lần gần nhất = 24 khoang cach.
by, _ = nap({3: [i * 5 for i in range(1, 41)]}, n=400)
g = by[3]['gaps']
ok(len(g) == A._KC_SO_LAN - 1,
   f"gioi han {A._KC_SO_LAN} lan ve -> {A._KC_SO_LAN - 1} khoang cach",
   f"nhan duoc {len(g)}")
ok(all(x == 5 for x in g), "moi khoang cach deu bang 5", f"{g}")

# ── 5. Tổng vừa sổ: current_gap = 0 và chu kỳ vừa xong đã chốt ─
# tổng 15 ra ở kỳ 380 và 400 (kỳ mới nhất).
by, _ = nap({15: [380, 400]}, n=400)
ok(by[15]['current_gap'] == 0, "tong ra o ky moi nhat -> current_gap 0")
ok(by[15]['gaps'] == [20], "chu ky vua xong da vao chuoi", f"{by[15]['gaps']}")

# ── 6. Nhiều tổng cùng lúc, không lẫn sang nhau ───────────────
by, _ = nap({3: [10, 30], 4: [50, 51, 90], 18: [200, 340]}, n=400)
ok(by[3]['gaps'] == [20],  "tong 3 rieng", f"{by[3]['gaps']}")
ok(by[4]['gaps'] == [1, 39], "tong 4 rieng", f"{by[4]['gaps']}")
ok(by[18]['gaps'] == [140], "tong 18 rieng", f"{by[18]['gaps']}")

# ── 7. Tổng các khoảng cách phải khớp với khoảng thời gian thật ─
# lan ve dau tien den lan ve cuoi cung = tong cac khoang cach.
by, _ = nap({7: [3, 17, 18, 60, 61, 99, 250]}, n=400)
g = by[7]['gaps']
ok(sum(g) == 250 - 3, "tong cac khoang cach == lan cuoi - lan dau",
   f"sum={sum(g)} can {250 - 3}")
ok(g == [14, 1, 42, 1, 38, 151], "chuoi dung tung phan tu", f"{g}")

# ── 8. Hàm thuần: đổi chiều đúng ──────────────────────────────
ok(A._chuoi_khoang_cach([184330, 184311, 184307]) == [4, 19],
   "_chuoi_khoang_cach doi chieu dung")
ok(A._chuoi_khoang_cach([100]) == [], "_chuoi_khoang_cach 1 phan tu -> rong")
ok(A._chuoi_khoang_cach([]) == [], "_chuoi_khoang_cach rong -> rong")

print("=" * 62)
if fails:
    print(f"HONG {len(fails)} test:")
    for f in fails:
        print("  - " + f)
    raise SystemExit(1)
print("Tat ca test P216 deu dat.")
