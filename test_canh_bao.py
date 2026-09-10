"""P220: cảnh báo tổng ra trễ / ra sớm.

p_vang = P(vắng lâu hơn số kỳ đang vắng), p_som = P(khoảng cách <= chu kỳ vừa
xong). Phân phối hình học nên có công thức đóng, không cần quét lịch sử.

CHỖ DỄ SAI NHẤT là LỆCH MỘT ĐƠN VỊ, và tôi đã suýt mắc khi kiểm lần đầu:
  current_gap = c  ->  đã vắng c kỳ mà CHƯA ra  ->  khoảng cách hoàn chỉnh G > c
  nên p_vang = P(G > c) = (1-p)^c,  KHÔNG phải P(G >= c) = (1-p)^(c-1)
Sai một đơn vị thì mọi con số vẫn "hợp lý" — chỉ lệch vài phần trăm, mắt
thường không bắt được. Nên test này đối chiếu với MÔ PHỎNG thật.

Và cảnh báo này nói HIẾM chứ không nói SẮP RA: phân phối hình học không nhớ.
Có một test khẳng định thẳng tính chất đó.
"""
import math
import os
import random
import tempfile

os.environ.pop('DATABASE_URL', None)
import config
config.DB_PATH = os.path.join(tempfile.mkdtemp(), 'cb.db')
import app as A

fails = []
def ok(dk, ten, ct=''):
    print(f"  {'OK  ' if dk else 'HONG'}  {ten}")
    if not dk:
        fails.append(ten)
        if ct: print(f"        {ct}")

print("=" * 62)
print("P220: canh bao ra tre / ra som")
print("=" * 62)

# ── 1. Đối chiếu công thức với mô phỏng ───────────────────────
random.seed(5)
N = 400_000
tong = [random.randint(1, 6) + random.randint(1, 6) + random.randint(1, 6)
        for _ in range(N)]
lech_vang = lech_som = 0
for sv in (7, 10, 15):
    w  = A._WAYS[sv]
    vt = [i for i, t in enumerate(tong) if t == sv]
    gaps = [vt[i + 1] - vt[i] for i in range(len(vt) - 1)]
    n = len(gaps)
    for c in (5, 20, 50):
        mp = sum(1 for x in gaps if x > c) / n        # P(G > c)
        ct = A._do_hiem_vang(c, w)
        if abs(mp - ct) > max(0.004, ct * 0.07):
            lech_vang += 1
            print(f"        tong {sv} c={c}: mo phong {mp:.5f} vs cong thuc {ct:.5f}")
    for g in (3, 10, 30):
        mp = sum(1 for x in gaps if x <= g) / n
        ct = A._do_hiem_som(g, w)
        if abs(mp - ct) > max(0.004, ct * 0.07):
            lech_som += 1
            print(f"        tong {sv} g={g}: mo phong {mp:.5f} vs cong thuc {ct:.5f}")
ok(lech_vang == 0, "p_vang khop mo phong (9 phep so)", f"{lech_vang} lech")
ok(lech_som == 0, "p_som khop mo phong (9 phep so)", f"{lech_som} lech")

# ── 2. Bắt LỆCH MỘT ĐƠN VỊ ────────────────────────────────────
# Cong thuc SAI (1-p)^(c-1) phai cho ket qua KHAC han o gap nho.
w = A._WAYS[10]
dung = A._do_hiem_vang(5, w)
sai  = (1 - w / 216.0) ** 4          # bản lệch một đơn vị
ok(abs(dung - sai) > 0.05,
   "cong thuc dung KHAC han ban lech mot don vi",
   f"dung={dung:.5f} ban_lech={sai:.5f}")
ok(abs(dung - (1 - w / 216.0) ** 5) < 1e-12,
   "p_vang = (1-p)^c dung nhu dinh nghia")

# ── 3. Tính chất KHÔNG NHỚ — cảnh báo không được hiểu là 'sắp ra' ─
# P(ra o ky toi | da vang c ky) phai KHONG doi theo c.
for sv in (7, 15):
    w = A._WAYS[sv]
    p_ky_toi = [A._do_hiem_vang(c, w) and
                (A._do_hiem_vang(c, w) - A._do_hiem_vang(c + 1, w)) / A._do_hiem_vang(c, w)
                for c in (0, 10, 50, 200)]
    dung = all(abs(x - w / 216.0) < 1e-9 for x in p_ky_toi)
    ok(dung, f"tong {sv}: P(ra ky toi) khong doi du da vang bao lau",
       str([round(x, 6) for x in p_ky_toi]))

# ── 4. Đơn điệu và biên ───────────────────────────────────────
w = A._WAYS[9]
ok(all(A._do_hiem_vang(c, w) > A._do_hiem_vang(c + 1, w) for c in range(1, 80)),
   "vang cang lau -> p_vang cang nho (don dieu giam)")
ok(all(A._do_hiem_som(g, w) < A._do_hiem_som(g + 1, w) for g in range(1, 80)),
   "gap cang dai -> p_som cang lon (don dieu tang)")
ok(A._do_hiem_vang(0, w) == 1.0, "chua vang ky nao -> p_vang = 1")
ok(A._do_hiem_vang(None, w) == 1.0, "gap None -> 1 (khong gan co)")
ok(A._do_hiem_som(None, w) == 1.0, "prev_gap None -> 1 (khong gan co)")
ok(A._do_hiem_vang(10, 0) == 1.0, "ways=0 -> 1, khong chia cho 0")

# ── 5. Tổng hiếm hơn thì vắng lâu là bình thường hơn ──────────
# Vang 100 ky: voi tong 10 la cuc hiem, voi tong 18 la binh thuong.
p10 = A._do_hiem_vang(100, A._WAYS[10])
p18 = A._do_hiem_vang(100, A._WAYS[18])
ok(p10 < 0.001 and p18 > 0.5,
   "vang 100 ky: hiem voi tong 10, binh thuong voi tong 18",
   f"tong10={p10:.6f} tong18={p18:.4f}")

# ── 6. Endpoint trả về hai trường mới ─────────────────────────
import sqlite3, json
c = sqlite3.connect(config.DB_PATH)
c.execute("DELETE FROM draw_history")
# tong 10 ra o ky 1 va 900 -> dang vang 100 ky (max=1000): cuc hiem
for i in range(1, 1001):
    if i in (1, 900): ns, sv = '[2, 4, 4]', 10
    else:             ns, sv = '[1, 2, 4]', 7
    sz = 'NHO' if sv <= 9 else ('HOA' if sv <= 11 else 'LON')
    c.execute("INSERT INTO draw_history (draw_number, draw_time, numbers,"
              " size_category, sum_value) VALUES (?,?,?,?,?)",
              (i, '2026-01-01 10:00:00', ns, sz, sv))
c.commit(); c.close()
with A._stats_snap_lock: A._stats_snap['data'], A._stats_snap['exp'] = None, 0.0
with A._tv_lock: A._tv_snap['data'], A._tv_snap['exp'] = None, 0.0
d = A.app.test_client().get('/api/board-stats').get_json()
sm = {x['sum']: x for x in d['sums']}
ok('p_vang' in sm[10] and 'p_som' in sm[10], "payload co p_vang va p_som")
ok(sm[10]['current_gap'] == 100, "current_gap = 100", str(sm[10]['current_gap']))
ok(abs(sm[10]['p_vang'] - A._do_hiem_vang(100, 27)) < 1e-4,
   "p_vang khop cong thuc", f"{sm[10]['p_vang']}")
ok(sm[10]['p_vang'] < 0.05, "tong 10 vang 100 ky -> duoi nguong canh bao",
   f"{sm[10]['p_vang']}")
ok(sm[7]['p_vang'] > 0.05, "tong 7 vua ra -> KHONG gan co", f"{sm[7]['p_vang']}")

# ── 7. P221: còn bao nhiêu kỳ nữa sẽ ra ──────────────────────
print()
print("  -- P221: con bao nhieu ky nua --")

# Đối chiếu với mô phỏng: lọc riêng những thời điểm đã vắng đúng d kỳ,
# đo thời gian chờ THÊM. Đây là bằng chứng cho tính không nhớ.
random.seed(7)
N2 = 600_000
t2 = [random.randint(1, 6) + random.randint(1, 6) + random.randint(1, 6)
      for _ in range(N2)]
S = 16
vt = [i for i, t in enumerate(t2) if t == S]
lech = []
for d in (0, 30, 66):
    cho = sorted(b - a - d for a, b in zip(vt, vt[1:]) if b - a > d)
    if len(cho) < 500:
        continue
    n = len(cho)
    for q, k_lt in ((0.50, A._ky_nua(0.50, 6)), (0.80, A._ky_nua(0.80, 6))):
        k_mp = cho[int(n * q)]
        if abs(k_mp - k_lt) > max(3, k_lt * 0.10):
            lech.append((d, q, k_mp, k_lt))
ok(not lech, "k50/k80 khop mo phong DU da vang 0/30/66 ky", str(lech))

# Tính KHÔNG NHỚ nói thẳng: horizon chỉ phụ thuộc ways, không phụ thuộc gap.
# Nếu ai đó sau này thêm tham số gap vào _ky_nua thì test này đỏ.
import inspect
tham_so = list(inspect.signature(A._ky_nua).parameters)
ok(tham_so == ['q', 'ways'],
   "_ky_nua CHI nhan (q, ways) — khong nhan gap", str(tham_so))

ok(A._ky_nua(0.50, 6) == 25 and A._ky_nua(0.80, 6) == 58
   and A._ky_nua(0.95, 6) == 107,
   "tong 16: 50%->25, 80%->58, 95%->107 ky",
   f"{A._ky_nua(0.5,6)}/{A._ky_nua(0.8,6)}/{A._ky_nua(0.95,6)}")
ok(A._ky_nua(0.50, 27) < A._ky_nua(0.50, 6) < A._ky_nua(0.50, 1),
   "tong hay ra -> cho it ky hon")
ok(all(A._ky_nua(0.5, w) < A._ky_nua(0.8, w) < A._ky_nua(0.95, w)
       for w in (1, 6, 15, 27)), "50% < 80% < 95% o moi tong")
ok(A._ky_nua(0.5, 0) == 0 and A._ky_nua(0, 6) == 0 and A._ky_nua(1, 6) == 0,
   "bien: ways=0 / q=0 / q=1 -> 0, khong no")

# Payload
ok(all(k in sm[10] for k in ('k50', 'k80', 'k95')), "payload co k50/k80/k95")
ok(sm[10]['k50'] == A._ky_nua(0.50, 27), "k50 trong payload khop ham",
   f"{sm[10]['k50']}")
# Tong 10 dang vang 100 ky nhung horizon van y het tong 10 vua ra
ok(sm[10]['k50'] == 6 and sm[7]['k50'] == 10,
   "horizon chi theo tong, khong theo dang vang bao lau",
   f"tong10={sm[10]['k50']} tong7={sm[7]['k50']}")

print("=" * 62)
if fails:
    print(f"HONG {len(fails)} test:")
    for f in fails: print("  - " + f)
    raise SystemExit(1)
print("Tat ca test P220 deu dat.")
