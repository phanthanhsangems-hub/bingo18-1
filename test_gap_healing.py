"""P211: watcher phải tự bù lỗ hổng bằng Vietlott, không chỉ GitHub.

Kỳ #183180 (ra 3-3-3) nằm ngoài DB nhiều ngày vì file GitHub thiếu đúng đoạn
#183178-#183217. fill_gaps() chỉ đọc GitHub nên không bao giờ vá được, và
bảng trip báo "333 chưa về 492 kỳ" trong khi thực tế mới 88.
"""
import os
import sys
import types

# Thư viện chỉ có trên máy người dùng — thay bằng bản giả để import được.
for ten, dung in (('bs4', {'BeautifulSoup': type('BS', (), {})}),
                  ('psycopg2', {'Error': type('E', (Exception,), {}),
                                'connect': lambda *a, **k: None,
                                'extras': types.SimpleNamespace()})):
    if ten not in sys.modules:
        m = types.ModuleType(ten)
        for k, v in dung.items():
            setattr(m, k, v)
        sys.modules[ten] = m

os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', '')
os.environ.setdefault('TELEGRAM_CHAT_ID', '')

import sync_to_supabase as S

fails = []


class FakeCursor:
    """Trả MAX(draw_number) rồi danh sách kỳ đang có, theo thứ tự bị gọi."""
    def __init__(self, hi, co):
        self.hi, self.co, self.lan = hi, co, 0
        self.ket_qua = None

    def execute(self, sql, params=None):
        if 'MAX(draw_number)' in sql:
            self.ket_qua = [(self.hi,)]
        elif 'BETWEEN' in sql:
            lo, hi = params
            self.ket_qua = [(d,) for d in self.co if lo <= d <= hi]
        else:
            self.ket_qua = []

    def fetchone(self):
        return self.ket_qua[0] if self.ket_qua else None

    def fetchall(self):
        return self.ket_qua


class FakeConn:
    def __init__(self, hi, co):
        self.hi, self.co = hi, co
        self.da_chen = []
    def cursor(self):
        return FakeCursor(self.hi, self.co)
    def rollback(self): pass
    def commit(self):   pass


def chay(hi, co, co_o_vietlott, khong_co=None, toi_da=10, lookback=300):
    """Chạy va_lo_hong_tu_vietlott với Vietlott giả."""
    conn = FakeConn(hi, co)
    da_hoi = []

    def fake_fetch_detail(dn):
        da_hoi.append(dn)
        if dn in co_o_vietlott:
            return {'draw_id': dn, 'numbers': co_o_vietlott[dn],
                    'total': None, 'draw_date': '2026-08-25'}
        return None

    def fake_insert(c, draw):
        c.da_chen.append(draw['draw_id'])
        return True

    goc_f, goc_i, goc_s = S.fetch_detail, S.insert_draw, S.time.sleep
    S.fetch_detail, S.insert_draw, S.time.sleep = fake_fetch_detail, fake_insert, lambda x: None
    try:
        kq = S.va_lo_hong_tu_vietlott(conn, khong_co if khong_co is not None else set(),
                                      lookback=lookback, toi_da=toi_da)
    finally:
        S.fetch_detail, S.insert_draw, S.time.sleep = goc_f, goc_i, goc_s
    return kq, da_hoi, conn


print("=" * 60)

# 1) Đúng kịch bản thật: #183180 ra 3-3-3, GitHub không có
hi = 183262
co = set(range(hi - 300, hi + 1)) - {183178, 183179, 183180, 183181, 183182}
kq, da_hoi, conn = chay(hi, co, {183178: [6, 1, 3], 183179: [4, 5, 2],
                                 183180: [3, 3, 3], 183181: [5, 3, 2],
                                 183182: [6, 1, 3]})
so = {d[0] for d in kq}
if so == {183178, 183179, 183180, 183181, 183182}:
    print("  OK   Bu du 5 ky GitHub khong co")
else:
    fails.append(f"bu thieu: mong 5 ky, duoc {sorted(so)}")

trip = [d for d in kq if len(set(d[1])) == 1]
if trip and trip[0][0] == 183180 and trip[0][2] == 9:
    print(f"  OK   Bat duoc trip #{trip[0][0]} {trip[0][1]} tong={trip[0][2]}")
else:
    fails.append(f"khong bat duoc trip 333 o #183180: {trip}")

# 2) tổng phải TỰ CỘNG khi Vietlott trả total=None
#    (neu sum_value NULL thi triple_stats loc mat, trip 333 van khong hien)
if all(t == sum(n) for _, n, t in kq):
    print("  OK   Tong tu cong dung khi nguon tra total=None")
else:
    fails.append(f"tong sai: {[(d[0], d[1], d[2]) for d in kq]}")

# 3) Trần mỗi vòng — lỗ hổng lớn không được làm treo vòng lặp watch
co2 = set(range(hi - 300, hi + 1)) - set(range(183100, 183150))
kq2, da_hoi2, _ = chay(hi, co2, {d: [1, 2, 3] for d in range(183100, 183150)}, toi_da=10)
if len(da_hoi2) == 10 and len(kq2) == 10:
    print(f"  OK   50 ky thieu -> chi hoi {len(da_hoi2)} ky moi vong")
else:
    fails.append(f"tran khong hoat dong: hoi {len(da_hoi2)}, bu {len(kq2)}")

# 4) Kỳ nguồn không có -> nhớ lại, KHÔNG hỏi lại (nếu không sẽ hỏi mãi mãi)
khong_co = set()
co3 = set(range(hi - 300, hi + 1)) - {183200, 183201}
kq3, hoi3, _ = chay(hi, co3, {}, khong_co=khong_co)
kq4, hoi4, _ = chay(hi, co3, {}, khong_co=khong_co)
if khong_co == {183200, 183201} and hoi3 == [183200, 183201] and hoi4 == []:
    print("  OK   Ky nguon khong co -> nho lai, vong sau khong hoi nua")
else:
    fails.append(f"khong nho: khong_co={khong_co} hoi lan1={hoi3} lan2={hoi4}")

# 5) DB đầy đủ -> không gọi Vietlott lần nào
kq5, hoi5, _ = chay(hi, set(range(hi - 300, hi + 1)), {})
if kq5 == [] and hoi5 == []:
    print("  OK   Khong co lo hong -> khong goi Vietlott")
else:
    fails.append(f"goi thua khi DB day du: {hoi5}")

# 6) Chỉ nhìn trong lookback, không đào cả lịch sử
co6 = set(range(hi - 300, hi + 1)) - {183180}
co6 |= {5}          # ky rat cu, ngoai cua so
kq6, hoi6, _ = chay(hi, co6, {183180: [3, 3, 3]}, lookback=300)
if hoi6 == [183180]:
    print("  OK   Chi xet trong lookback, khong dao ca lich su")
else:
    fails.append(f"vuot lookback: {hoi6[:10]}")

print("=" * 60)
print(f"RESULTS: {6 - len(fails)} passed, {len(fails)} failed")
for f in fails:
    print("  FAIL " + f)
print("=" * 60)
print("ALL TESTS PASSED" if not fails else "TESTS FAILED")
raise SystemExit(1 if fails else 0)
