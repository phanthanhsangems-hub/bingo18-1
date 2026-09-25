"""P223: ảnh chụp thống kê phải hết hiệu lực khi CÓ KỲ MỚI, không chỉ khi hết TTL.

Vì sao: _STATS_TTL = 60 giây mà kỳ về mỗi ~360 giây. Nên ngay sau mỗi kỳ có một
cửa sổ tới 60 giây mà /api/sum-stats còn nói về kỳ TRƯỚC — đúng cái tổng vừa ra
lại hiện "chưa về" của lần trước. Người dùng nhìn thấy sai (~17% thời gian), và
chẩn đoán báo động giả: lần chạy #31 kết luận "cột sum_value nghi ghi sai" trong
khi dữ liệu hoàn toàn đúng, chỉ vì draw-grid đọc sống còn sum-stats đọc ảnh cũ.

Test 2 dưới đây dựng lại đúng lần chạy #31 và đòi bản mới KHÔNG được trả ảnh cũ.
"""
import os, sys
from unittest import mock

os.environ.setdefault('DATABASE_URL', '')
os.environ.pop('APP_USER', None)

import app as A

DAT = HONG = 0
def kiem(ten, dk, ct=''):
    global DAT, HONG
    if dk: DAT += 1; print(f"  DAT  {ten}")
    else:  HONG += 1; print(f"  HONG {ten}" + (f"  -> {ct}" if ct else '')); 

def dat_lai():
    A._stats_snap['data'] = None
    A._stats_snap['exp']  = 0.0

print("=== 1. MOC KHONG DOI -> dung lai anh cu, KHONG tinh lai ===")
dat_lai()
dem = {'n': 0}
def gia_tinh(moc):
    def f():
        dem['n'] += 1
        return {'total_draws': 100, 'max_draw': moc, 'sums': [], 'triples': [], 'any': {}}
    return f

with mock.patch.object(A, '_tinh_thong_ke', gia_tinh(188122)), \
     mock.patch.object(A, '_moc_ky_hien_tai', return_value=188122):
    a = A._thong_ke()
    b = A._thong_ke()
    c = A._thong_ke()
kiem("chi tinh MOT lan cho ba lan goi", dem['n'] == 1, f"tinh {dem['n']} lan")
kiem("tra ve cung mot anh", a is b is c)
kiem("anh mang dung moc ky", a['max_draw'] == 188122)

print("\n=== 2. CANH THAT #31: co ky moi -> PHAI tinh lai ===")
dat_lai()
dem['n'] = 0
with mock.patch.object(A, '_tinh_thong_ke', gia_tinh(188122)), \
     mock.patch.object(A, '_moc_ky_hien_tai', return_value=188122):
    d1 = A._thong_ke()
kiem("lan dau tinh, moc 188122", d1['max_draw'] == 188122 and dem['n'] == 1)

# ky #188123 vua ve. TTL con han (moi vua tinh), nhung moc da dich.
with mock.patch.object(A, '_tinh_thong_ke', gia_tinh(188123)), \
     mock.patch.object(A, '_moc_ky_hien_tai', return_value=188123):
    d2 = A._thong_ke()
kiem("moc dich -> tinh lai DU TTL CON HAN", dem['n'] == 2, f"tinh {dem['n']} lan")
kiem("tra ve moc MOI, khong phai anh cu", d2['max_draw'] == 188123, str(d2['max_draw']))

print("\n=== 3. HET TTL nhung moc khong doi -> van tinh lai (chot phu giu nguyen) ===")
dat_lai()
dem['n'] = 0
with mock.patch.object(A, '_tinh_thong_ke', gia_tinh(188122)), \
     mock.patch.object(A, '_moc_ky_hien_tai', return_value=188122):
    A._thong_ke()
    A._stats_snap['exp'] = 0.0          # gia lap het TTL
    A._thong_ke()
kiem("het TTL thi tinh lai", dem['n'] == 2, f"tinh {dem['n']} lan")

print("\n=== 4. HOI MOC KHONG DUOC (DB chop) -> roi ve hanh vi cu, KHONG hong ===")
dat_lai()
dem['n'] = 0
with mock.patch.object(A, '_tinh_thong_ke', gia_tinh(188122)), \
     mock.patch.object(A, '_moc_ky_hien_tai', return_value=None):
    e1 = A._thong_ke()
    e2 = A._thong_ke()
kiem("moc None -> dung anh cu theo TTL nhu truoc", dem['n'] == 1, f"tinh {dem['n']} lan")
kiem("van tra ve du lieu, khong nem loi", e1 is e2 and e1['total_draws'] == 100)

print("\n=== 5. _moc_ky_hien_tai: DB sap thi tra None chu khong nem ===")
with mock.patch.object(A.db, 'get_connection', side_effect=RuntimeError('DB sap')):
    try:
        v = A._moc_ky_hien_tai(); ok = (v is None)
    except Exception:
        ok = False
kiem("DB sap -> None", ok)

class GiaCur:
    def __init__(self, gt): self.gt = gt
    def execute(self, *a, **k): pass
    def fetchone(self): return (self.gt,)
    def close(self): pass
class GiaConn:
    def __init__(self, gt): self.gt = gt; self.dong = False
    def cursor(self): return GiaCur(self.gt)
    def close(self): self.dong = True

for gt, mong in ((188123, 188123), (None, None)):
    c = GiaConn(gt)
    with mock.patch.object(A.db, 'get_connection', return_value=c):
        v = A._moc_ky_hien_tai()
    kiem(f"MAX tra {gt} -> {mong}", v == mong, str(v))
    kiem(f"  connection duoc dong (MAX={gt})", c.dong)

print("\n=== 6. HAI ENDPOINT phai tra max_draw ra ngoai ===")
# Khong co moc thi nguoi goi khong the phan biet "du lieu sai" voi "anh cu".
src = open('app.py', encoding='utf-8').read()
import re
for ten in ('sum_stats', 'triple_stats'):
    m = re.search(rf'def {ten}\(\):(.*?)\n@app\.route', src, re.S)
    than = m.group(1) if m else ''
    kiem(f"/{ten} tra ve max_draw", "'max_draw'" in than, than[:120])

print("\n=== 7. _tinh_thong_ke phai dua max_draw vao ket qua ===")
kiem("co khoa 'max_draw' trong return cua _tinh_thong_ke",
     "'max_draw':    max_dn" in src)

print("\n" + "=" * 52)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
