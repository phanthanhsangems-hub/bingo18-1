"""Lưu win_prob (con số hiển thị) song song với confidence (điểm thô).

Trước đây bảng predictions chỉ có cột 'confidence' — mà prediction_service.py
lưu vào đó ĐIỂM THÔ của model, còn số hiện ra màn hình là win_prob đã qua bộ
hiệu chỉnh. Nên không có cách nào đối chiếu con số người dùng nhìn thấy với
kết quả thật.

Ba thứ dễ hỏng nhất, mỗi thứ một test:
  1. migration phải chạy được trên DB CŨ đã có dữ liệu (không mất dòng nào)
  2. insert_prediction gọi kiểu CŨ (4 tham số) phải vẫn chạy — sync_predictions
     .py:171 đang gọi như vậy
  3. endpoint phải đo được ĐÚNG cột được chọn, và dòng cũ có win_prob NULL
     phải bị bỏ qua chứ không tính thành 0
"""
import os
import sqlite3
import tempfile

os.environ.pop('DATABASE_URL', None)
_TMP = os.path.join(tempfile.mkdtemp(), 'wp.db')

# ── 1. Dựng DB theo schema CŨ (không có win_prob) rồi mới nạp app ──
_c = sqlite3.connect(_TMP)
_c.executescript("""
CREATE TABLE predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draw_number INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    predicted_numbers TEXT NOT NULL,
    confidence REAL NOT NULL,
    prediction_time TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO predictions (draw_number, model_name, predicted_numbers, confidence,
                         prediction_time)
VALUES (1, 'cu', '[1, 2, 3]', 0.9, '2026-01-01 10:00:00');
""")
_c.commit(); _c.close()

import config
config.DB_PATH = _TMP
import app as A          # nạp app -> chạy migration trên DB cũ ở trên

fails = []
def ok(dk, ten, ct=''):
    print(f"  {'OK  ' if dk else 'HONG'}  {ten}")
    if not dk:
        fails.append(ten)
        if ct: print(f"        {ct}")

print("=" * 62)
print("win_prob: luu con so hien ra man hinh")
print("=" * 62)

# ── Test 1: migration trên DB cũ ──────────────────────────────
c = sqlite3.connect(_TMP)
cols = [r[1] for r in c.execute("PRAGMA table_info(predictions)")]
ok('win_prob' in cols, "migration them cot win_prob vao DB CU", f"cols={cols}")
n_cu = c.execute("SELECT COUNT(*) FROM predictions WHERE model_name='cu'").fetchone()[0]
ok(n_cu == 1, "dong du lieu CU khong bi mat")
v = c.execute("SELECT win_prob FROM predictions WHERE model_name='cu'").fetchone()[0]
ok(v is None, "dong cu co win_prob = NULL (khong phai 0)", f"nhan duoc {v!r}")
c.close()

# ── Test 2: gọi kiểu CŨ 4 tham số vẫn chạy ────────────────────
db = A.db
try:
    pid, moi = db.insert_prediction(2, 'goi_cu', [1, 2, 4], 0.55)
    ok(pid is not None, "insert_prediction goi kieu CU (4 tham so) van chay")
    c = sqlite3.connect(_TMP)
    v = c.execute("SELECT win_prob FROM predictions WHERE draw_number=2").fetchone()[0]
    c.close()
    ok(v is None, "goi kieu cu -> win_prob NULL")
except TypeError as e:
    ok(False, "insert_prediction goi kieu CU (4 tham so) van chay", str(e))

# ── Test 3: lưu cả hai, giá trị đúng ──────────────────────────
db.insert_prediction(3, 'moi', [1, 2, 5], 0.62, None, 0.39)
c = sqlite3.connect(_TMP)
row = c.execute("SELECT confidence, win_prob FROM predictions WHERE draw_number=3").fetchone()
c.close()
ok(abs(row[0] - 0.62) < 1e-6, "confidence luu dung diem tho", f"{row[0]}")
ok(row[1] is not None and abs(row[1] - 0.39) < 1e-6,
   "win_prob luu dung con so hien thi", f"{row[1]}")
ok(row[0] != row[1], "hai cot KHAC NHAU (khong ghi de nhau)")

# ── Test 4: endpoint đo đúng cột được chọn ────────────────────
c = sqlite3.connect(_TMP)
c.execute("DELETE FROM predictions")
c.execute("DELETE FROM prediction_results")
# 100 kỳ: điểm thô 0.90 (thổi phồng), win_prob 0.40 (sát thực tế), thắng 40%
for i in range(1, 101):
    c.execute("INSERT INTO predictions (draw_number, model_name, predicted_numbers,"
              " confidence, win_prob, prediction_time) VALUES (?,?,?,?,?,?)",
              (i, 'm', '[1, 2, 3]', 0.90, 0.40, '2026-01-01 10:00:00'))
    pid = c.execute("SELECT id FROM predictions WHERE draw_number=?", (i,)).fetchone()[0]
    thang = 1 if i <= 40 else 0
    c.execute("INSERT INTO prediction_results (prediction_id, draw_number, actual_numbers,"
              " match_count, is_win, is_win_size) VALUES (?,?,?,?,?,?)",
              (pid, i, '[1, 2, 3]' if thang else '[6, 6, 6]', 0, thang, thang))
c.commit(); c.close()
A._resp_cache.clear() if hasattr(A, '_resp_cache') else None

cli = A.app.test_client()
d_tho = cli.get('/api/calibration-by-size?n=500').get_json()
d_hth = cli.get('/api/calibration-by-size?n=500&field=win_prob').get_json()
ok(d_tho.get('field') == 'confidence', "mac dinh do cot confidence", str(d_tho.get('field')))
ok(d_hth.get('field') == 'win_prob',   "?field=win_prob do cot win_prob", str(d_hth.get('field')))

s_tho = (d_tho.get('sizes') or {}).get('NHO', {})
s_hth = (d_hth.get('sizes') or {}).get('NHO', {})
ok(abs(s_tho.get('avg_conf', 0) - 0.90) < 0.01,
   "do diem tho -> bao ~0,90", str(s_tho.get('avg_conf')))
ok(abs(s_hth.get('avg_conf', 0) - 0.40) < 0.01,
   "do win_prob -> bao ~0,40", str(s_hth.get('avg_conf')))
ok(abs(s_tho.get('gap', 0) - 0.50) < 0.02,
   "diem tho lech ~+0,50 so voi thuc te 0,40", str(s_tho.get('gap')))
ok(abs(s_hth.get('gap', 0)) < 0.02,
   "win_prob KHOP thuc te, lech ~0", str(s_hth.get('gap')))

# ── Test 5: dòng có win_prob NULL bị bỏ qua, không tính thành 0 ─
c = sqlite3.connect(_TMP)
for i in range(200, 260):
    c.execute("INSERT INTO predictions (draw_number, model_name, predicted_numbers,"
              " confidence, prediction_time) VALUES (?,?,?,?,?)",
              (i, 'cu', '[1, 2, 3]', 0.90, '2026-01-01 10:00:00'))
    pid = c.execute("SELECT id FROM predictions WHERE draw_number=?", (i,)).fetchone()[0]
    c.execute("INSERT INTO prediction_results (prediction_id, draw_number, actual_numbers,"
              " match_count, is_win, is_win_size) VALUES (?,?,?,?,?,?)",
              (pid, i, '[6, 6, 6]', 0, 0, 0))
c.commit(); c.close()
if hasattr(A, '_resp_cache'): A._resp_cache.clear()
d2 = cli.get('/api/calibration-by-size?n=500&field=win_prob&x=1').get_json()
s2 = (d2.get('sizes') or {}).get('NHO', {})
ok(s2.get('n') == 100, "60 dong win_prob NULL bi BO QUA, khong tinh thanh 0",
   f"n={s2.get('n')} (phai la 100)")
ok(abs(s2.get('avg_conf', 0) - 0.40) < 0.01,
   "bao van ~0,40 chu khong bi NULL keo xuong", str(s2.get('avg_conf')))

print("=" * 62)
if fails:
    print(f"HONG {len(fails)} test:")
    for f in fails: print("  - " + f)
    raise SystemExit(1)
print("Tat ca test win_prob deu dat.")
