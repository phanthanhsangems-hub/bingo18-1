"""P224: rate limit phải khoá theo IP THẬT, và mọi endpoint phải có giới hạn.

Lỗi gốc: limiter dùng get_remote_address (= request.remote_addr). App không gắn
ProxyFix nên sau biên Google con số đó là địa chỉ PROXY — giống nhau cho mọi
khách. Hệ quả: mọi @limiter.limit dùng CHUNG MỘT XÔ cho cả thế giới, nên không
tách được kẻ lạm dụng khỏi người dùng thật. Thêm giới hạn mà chưa sửa chỗ này
thì chỉ tạo thêm cách để người lạ khoá chính chủ ra ngoài.
"""
import os, re, sys
from unittest import mock

os.environ.setdefault('DATABASE_URL', '')
os.environ.pop('APP_USER', None)

import app as A

DAT = HONG = 0
def kiem(ten, dk, ct=''):
    global DAT, HONG
    if dk: DAT += 1; print(f"  DAT  {ten}")
    else:  HONG += 1; print(f"  HONG {ten}" + (f"  -> {ct}" if ct else ''))

print("=== 1. KHOA GIOI HAN PHAI LA IP THAT, KHONG PHAI IP PROXY ===")
kiem("limiter dung _khoa_gioi_han, khong dung get_remote_address",
     A.limiter._key_func is A._khoa_gioi_han or
     getattr(A.limiter, 'key_func', None) is A._khoa_gioi_han,
     str(getattr(A.limiter, '_key_func', None)))

def voi_xff(xff, remote='169.254.1.1'):
    with A.app.test_request_context('/', headers={'X-Forwarded-For': xff} if xff else {},
                                    environ_base={'REMOTE_ADDR': remote}):
        return A._khoa_gioi_han()

# Client thuong: GFE dat "XFF: <ip that>"
kiem("khach thuong -> lay dung IP that", voi_xff('203.0.113.9') == '203.0.113.9',
     voi_xff('203.0.113.9'))

# Client GIAN tu gui XFF: GFE noi IP that vao CUOI.
# Lay phan tu DAU se de lot gia mao -> phai lay CUOI.
gia = voi_xff('1.2.3.4, 203.0.113.9')
kiem("khach tu gui XFF gia -> KHONG gia mao duoc (lay phan tu cuoi)",
     gia == '203.0.113.9', gia)
kiem("  va KHONG tra ve gia tri gia mao", gia != '1.2.3.4')

# Nhieu chang proxy
n = voi_xff('1.1.1.1, 2.2.2.2, 203.0.113.9')
kiem("nhieu chang -> van lay chang cuoi", n == '203.0.113.9', n)

# Khong co XFF -> roi ve remote_addr, khong duoc nem loi
kiem("khong co XFF -> roi ve remote_addr", voi_xff('', '198.51.100.7') == '198.51.100.7',
     voi_xff('', '198.51.100.7'))

# XFF rac / chi dau phay
for rac in (',', ' , , ', ''):
    try:
        v = voi_xff(rac, '198.51.100.7'); ok = (v == '198.51.100.7')
    except Exception as e:
        ok = False; v = f'nem loi: {e}'
    kiem(f"XFF rac {rac!r} -> roi ve remote_addr, khong chet", ok, str(v))

print("\n=== 2. HAI KHACH KHAC IP PHAI CO XO RIENG ===")
a = voi_xff('203.0.113.9')
b = voi_xff('203.0.113.10')
kiem("hai IP khac nhau -> hai khoa khac nhau", a != b, f"{a} vs {b}")
# Truoc khi sua, ca hai deu ra remote_addr cua proxy -> trung khoa.
kiem("khoa KHONG phai dia chi proxy", a != '169.254.1.1' and b != '169.254.1.1')

print("\n=== 3. MOI ENDPOINT PHAI CO RATE LIMIT ===")
src = open('app.py', encoding='utf-8').read()
dong = src.splitlines()
thieu = []
tong = 0
for i, l in enumerate(dong):
    if l.strip().startswith('@app.route('):
        tong += 1
        ke = "\n".join(dong[i+1:i+5])
        if 'limiter.limit' not in ke:
            m = re.search(r"@app\.route\(\s*['\"]([^'\"]+)", l)
            thieu.append(m.group(1) if m else '?')
print(f"  tong endpoint: {tong}   thieu gioi han: {len(thieu)}")
kiem("khong endpoint nao thieu rate limit", not thieu, str(thieu[:8]))

print("\n=== 4. NGUONG PHAI DU RONG CHO NHUNG CHO BI GOI DAY ===")
def nguong(duong):
    m = re.search(rf"@app\.route\(\s*['\"]{re.escape(duong)}['\"][^\n]*\n"
                  rf"(?:@[^\n]*\n)*?@limiter\.limit\(\s*['\"](\d+) per minute", src)
    return int(m.group(1)) if m else None

# Smoke test cua deploy goi /api/health 10 lan lien tiep; GHA warmup goi nua.
for duong, toi_thieu in (('/api/health', 60), ('/healthz', 60),
                         ('/manifest.json', 60), ('/sw.js', 60)):
    v = nguong(duong)
    kiem(f"{duong} >= {toi_thieu}/phut", v is not None and v >= toi_thieu, str(v))

# Webhook: phai CO gioi han (truoc day khong co) nhung du rong cho lenh that.
v = nguong('/telegram/webhook')
kiem("/telegram/webhook co gioi han", v is not None, 'khong co')
kiem("  va trong khoang 20-120/phut", v is not None and 20 <= v <= 120, str(v))

# SSE: moi luong giu mot thread toi 240 giay -> phai siet, nhung client lui
# dan toi 120 giay nen 30/phut la rong.
v = nguong('/api/sse/draws')
kiem("/api/sse/draws co gioi han va <= 60/phut", v is not None and v <= 60, str(v))

print("\n" + "=" * 52)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
