"""Khoảng tin cậy, p-value và đánh giá NGOÀI MẪU (thong_ke_tin_cay.py + /api/danh-gia-ngoai-mau).

Hai phần:
 1) Hàm thuần: Wilson và p-value nhị thức so với số tham chiếu của scipy (tính sẵn bằng
    scipy.stats.binomtest, không cần scipy khi chạy test).
 2) Endpoint trên SQLite tạm: dự đoán ghi TRƯỚC giờ quay vào nhóm 'ngoai_mau', ghi SAU
    giờ quay (dự đoán bù) vào nhóm 'bu', và tỷ lệ nền tính theo SIZE đã dự đoán (HÒA 25%).
"""
import json
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta, timezone

os.environ.pop('DATABASE_URL', None)
_TMP = os.path.join(tempfile.mkdtemp(), 'ngoai_mau_test.db')

import config
config.DB_PATH = _TMP
import thong_ke_tin_cay as T
import app as A

fails = []
ok_count = 0


def check(cond, msg):
    global ok_count
    if cond:
        ok_count += 1
        print("  OK   " + msg)
    else:
        fails.append(msg)


def gan(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol


print("=" * 62)
print("1) Ham thuan so voi scipy.stats.binomtest / wilson")
tham_chieu = [
    # wins, n, p0, p hai phia, p cao hon, wilson thap, wilson cao
    (380, 1000, 0.375, 0.7440601135778067, 0.38346135531525916, 0.3504293063571445, 0.4104891156793888),
    (2630, 7016, 0.375, 0.9901623179461898, 0.5143444261950536, 0.3636015557926993, 0.38625034466674485),
    (300, 600, 0.375, 6.017593117589235e-10, 3.117810926727157e-10, 0.4601198639241893, 0.5398801360758106),
    (30, 100, 0.25, 0.24907145667188566, 0.14954104656657063, 0.21894885294932764, 0.39584854633346667),
]
for w, n, p0, p2, p1, lo, hi in tham_chieu:
    pv = T.p_value(w, n, p0)
    kl, kh = T.wilson(w, n)
    check(abs(pv['p_hai_phia'] - p2) <= max(1e-9, p2 * 1e-6), "p hai phia %d/%d nen %.3f = %.4g" % (w, n, p0, p2))
    check(abs(pv['p_cao_hon'] - p1) <= max(1e-9, p1 * 1e-6), "p cao hon %d/%d = %.4g" % (w, n, p1))
    check(gan(kl, lo) and gan(kh, hi), "Wilson %d/%d = %.4f-%.4f" % (w, n, lo, hi))

check(T.wilson(0, 0) == (None, None), "Wilson n=0 -> (None, None), khong chia 0")
dg = T.danh_gia(0, 0)
check(dg['n'] == 0 and dg['ty_le'] is None and 'Chưa có' in dg['ket_luan'], "danh_gia n=0 an toan")
t0 = time.time()
T.danh_gia(11250, 30000)
check(time.time() - t0 < 1.0, "danh_gia 30.000 ky chay duoi 1 giay")

dg = T.danh_gia(30, 100)
check('Chưa đủ mẫu' in dg['ket_luan'], "100 ky -> 'chua du mau', khong ket luan du ty le 30%")
dg = T.danh_gia(380, 1000)
check('Không khác' in dg['ket_luan'], "38% tren 1000 ky -> khong khac nen 37,5%")
dg = T.danh_gia(450, 1000)
check('Cao hơn nền' in dg['ket_luan'], "45% tren 1000 ky -> cao hon nen co y nghia")
dg = T.danh_gia(300, 1000)
check('Thấp hơn nền' in dg['ket_luan'], "30% tren 1000 ky -> thap hon nen co y nghia")

print("\n2) tong_hop_ngoai_mau")
t = datetime(2026, 11, 20, 10, 0, 0)
rows = [(t - timedelta(minutes=3), t, 'LON', True),
        (t - timedelta(minutes=3), t, 'LON', False),
        (t + timedelta(hours=1), t, 'NHO', True),          # bu: ghi sau gio quay
        (None, t, 'NHO', True),                            # khong ro gio -> khong tinh ngoai mau
        ('2026-11-20 09:50:00', '2026-11-20 10:00:00', 'HOA', False)]  # chuoi (SQLite)
r = T.tong_hop_ngoai_mau(rows)
check(r['ngoai_mau']['n'] == 3 and r['ngoai_mau']['thang'] == 1, "ngoai mau: 3 ky, thang 1 (chuoi gio cung duoc doc)")
check(r['bu']['n'] == 2 and r['bu']['thang'] == 2, "bu: 2 ky (ghi sau gio quay + khong ro gio)")
check(r['tat_ca']['n'] == 5, "tat ca = ngoai mau + bu")
check(gan(r['ngoai_mau']['nen'], (0.375 + 0.375 + 0.25) / 3, 1e-4), "nen ngoai mau = trung binh theo SIZE (co 1 ky HOA)")
check(r['so_du_doan_hoa'] == 1, "dem so du doan HOA")
check(len(r['theo_tuan']) == 1 and r['theo_tuan'][0]['n'] == 3, "theo tuan chi gom nhom ngoai mau")
r0 = T.tong_hop_ngoai_mau([])
check(r0['ngoai_mau']['n'] == 0 and r0['theo_tuan'] == [], "khong co du lieu -> rong, khong no")

print("\n3) Endpoint /api/danh-gia-ngoai-mau")
c = sqlite3.connect(_TMP)
base = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=8)


def them(draw_no, draw_t, pred_t, nums, win):
    c.execute("INSERT OR IGNORE INTO draw_history (draw_number, draw_time, numbers, size_category, sum_value)"
              " VALUES (?,?,?,?,?)", (draw_no, draw_t.strftime('%Y-%m-%d %H:%M:%S'), '[1, 2, 4]', 'NHO', 7))
    cur = c.execute("INSERT INTO predictions (draw_number, model_name, predicted_numbers, confidence,"
                    " prediction_time, win_prob) VALUES (?,?,?,?,?,?)",
                    (draw_no, 'majority_vote', json.dumps(nums), 0.5,
                     pred_t.strftime('%Y-%m-%d %H:%M:%S'), 0.4))
    c.execute("INSERT INTO prediction_results (prediction_id, draw_number, actual_numbers, match_count,"
              " is_win, is_win_size, is_win_sum) VALUES (?,?,?,?,?,?,?)",
              (cur.lastrowid, draw_no, '[1, 2, 4]', 0, int(win), int(win), 0))


# A: 300 du doan LON ghi 3 phut TRUOC gio quay, thang 120 (40%)
# H: 20 du doan HOA ghi truoc gio quay, thang 5
# B: 100 du doan NHO ghi 1 gio SAU gio quay (bu), thang het
n = 1
for i in range(300):
    dt = base + timedelta(minutes=i)
    them(n, dt, dt - timedelta(minutes=3), [6, 6, 6], i < 120); n += 1
for i in range(20):
    dt = base + timedelta(minutes=300 + i)
    them(n, dt, dt - timedelta(minutes=3), [5, 5, 1], i < 5); n += 1
for i in range(100):
    dt = base + timedelta(minutes=320 + i)
    them(n, dt, dt + timedelta(hours=1), [1, 1, 1], True); n += 1
c.commit(); c.close()

cl = A.app.test_client()
d = cl.get('/api/danh-gia-ngoai-mau?days=7').get_json()
check('error' not in d, "endpoint tra ve khong loi (%s)" % d.get('error'))
om, bu, tc = d['ngoai_mau'], d['bu'], d['tat_ca']
check(om['n'] == 320 and om['thang'] == 125, "ngoai mau: 320 ky, thang 125 (got %s/%s)" % (om['thang'], om['n']))
check(bu['n'] == 100 and bu['thang'] == 100 and bu['ty_le'] == 1.0,
      "bu: 100 ky thang het, tach rieng khoi ngoai mau")
check(tc['n'] == 420, "tat ca 420 ky")
check(d['so_du_doan_hoa'] == 20, "dem dung 20 du doan HOA")
check(gan(om['nen'], (300 * 0.375 + 20 * 0.25) / 320, 1e-4), "nen ngoai mau = %.4f (tinh theo SIZE da du doan)" % om['nen'])
check(om['ktc_duoi'] < om['ty_le'] < om['ktc_tren'], "KTC 95% bao quanh ty le")
check(om['p_hai_phia'] is not None and 0 <= om['p_hai_phia'] <= 1, "co p-value")
check(bu['ktc_duoi'] > bu['nen'] and 'Chưa đủ mẫu' in bu['ket_luan'],
      "nhom bu 100 ky thang het van bi ghi 'chua du mau' (khong ket luan tren mau nho)")
check(len(d['theo_tuan']) >= 1 and sum(x['n'] for x in d['theo_tuan']) == 320, "theo tuan cong lai = 320 ky ngoai mau")
d0 = cl.get('/api/danh-gia-ngoai-mau?days=0').get_json()
check(d0['tat_ca']['n'] == 420, "days=0 -> toan bo")
d_since = cl.get('/api/danh-gia-ngoai-mau?since=2999-01-01').get_json()
check(d_since['tat_ca']['n'] == 0 and 'error' not in d_since, "since o tuong lai -> 0 ky, khong no")
resp = cl.get('/api/danh-gia-ngoai-mau?since=khong-phai-ngay')
check(resp.status_code == 400, "since sai dinh dang -> 400")

st = cl.get('/api/statistics').get_json()
check('win_rate_size_ktc95' in st and 'win_rate_size_p' in st, "/api/statistics co them KTC 95% va p-value")
check(len(st['win_rate_size_ktc95']) == 2 and st['win_rate_size_ktc95'][0] < st['win_rate_size'] < st['win_rate_size_ktc95'][1],
      "KTC cua /api/statistics bao quanh win_rate_size")

print("=" * 62)
print("RESULTS: %d passed, %d failed" % (ok_count, len(fails)))
for f in fails:
    print("  FAIL " + f)
print("=" * 62)
print("ALL TESTS PASSED" if not fails else "TESTS FAILED")
raise SystemExit(1 if fails else 0)
