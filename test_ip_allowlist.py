"""P202: kiểm tra danh sách IP được vào.

Cơ chế này có thể khoá chính chủ ra ngoài, và quan trọng hơn: nếu đặt sai chỗ
thì chặn luôn Cloud Scheduler / GitHub Actions / Telegram — đúng sự cố P189.
Nên test kỹ cả bốn nhóm: chủ máy, người lạ, tự động hoá, và kẻ giả mạo header.
"""
import os
import sys

os.environ['APP_USER'] = 'BINGO18'
os.environ['APP_PASSWORD'] = 'matkhau12345'
os.environ['TRIGGER_SECRET'] = 's3cr3t'
os.environ['ALLOWED_IPS'] = '203.0.113.7, 198.51.100.0/24'

import app as A

A.config.APP_USER = 'BINGO18'
A.config.APP_PASSWORD = 'matkhau12345'
A.config.TRIGGER_SECRET = 's3cr3t'
A.config.ALLOWED_IPS = '203.0.113.7, 198.51.100.0/24'
A._ALLOWED_NETS = A._parse_allowed_ips(A.config.ALLOWED_IPS)

c = A.app.test_client()
fails = []


def goi(path, ip=None, secret=False, xff=None):
    h = {}
    if xff is not None:
        h['X-Forwarded-For'] = xff
    elif ip:
        h['X-Forwarded-For'] = ip
    if secret:
        h['X-Trigger-Secret'] = 's3cr3t'
    return c.get(path, headers=h)


def kiem(ten, r, mong, ghichu=''):
    ok = r.status_code in mong
    print(f"  {'OK  ' if ok else 'SAI '} {ten:46s} -> {r.status_code} {ghichu}")
    if not ok:
        fails.append(f"{ten}: {r.status_code}, mong {mong}")


print("=" * 74)
print("1. Máy của chủ (IP trong danh sách) — phải QUA được chốt IP")
print("=" * 74)
# 302 = bị cổng đăng nhập chuyển hướng, tức đã qua chốt IP (không phải 403)
kiem("IP đơn 203.0.113.7", goi('/', ip='203.0.113.7'), {200, 302})
kiem("IP trong dải 198.51.100.42", goi('/', ip='198.51.100.42'), {200, 302})

print("\n" + "=" * 74)
print("2. Người lạ — phải bị chặn 403")
print("=" * 74)
kiem("IP lạ 8.8.8.8", goi('/', ip='8.8.8.8'), {403})
kiem("IP lạ gọi API", goi('/api/triple-stats', ip='8.8.8.8'), {403})
kiem("IP ngay ngoài dải 198.51.101.1", goi('/', ip='198.51.101.1'), {403})

print("\n" + "=" * 74)
print("3. Tự động hoá — TUYỆT ĐỐI không được chặn (bài học P189)")
print("=" * 74)
kiem("Cloud Scheduler /api/predict", goi('/api/predict', ip='35.187.1.1'), {200, 400, 500},
     "(cron path)")
kiem("Cloud Scheduler /api/daily-summary", goi('/api/daily-summary', ip='35.187.1.1'),
     {200, 400, 500}, "(cron path)")
kiem("GitHub Actions /api/health", goi('/api/health', ip='140.82.1.1'), {200, 503},
     "(public path)")
kiem("Telegram /telegram/webhook", c.post('/telegram/webhook',
     headers={'X-Forwarded-For': '149.154.167.99'}, json={}), {200, 403},
     "(public path, có secret riêng)")
kiem("Máy gọi máy có X-Trigger-Secret", goi('/api/triple-stats', ip='8.8.8.8', secret=True),
     {200, 500}, "(secret thắng IP)")
kiem("/whoami luôn mở", goi('/whoami', ip='8.8.8.8'), {200}, "(đường thoát khi tự khoá)")

print("\n" + "=" * 74)
print("4. Giả mạo header — phải KHÔNG lọt")
print("=" * 74)
r = goi('/', xff='203.0.113.7, 8.8.8.8')          # kẻ lạ tự nhét IP hợp lệ lên đầu
kiem("XFF giả '203.0.113.7, 8.8.8.8'", r, {403}, "(lấy phần tử CUỐI)")
r = goi('/', xff='8.8.8.8, 203.0.113.7')          # GFE nối IP thật vào cuối
kiem("XFF thật '8.8.8.8, 203.0.113.7'", r, {200, 302}, "(cuối là IP thật)")

print("\n" + "=" * 74)
print("5. Chưa cấu hình -> fail-open, không khoá ai")
print("=" * 74)
A._ALLOWED_NETS = A._parse_allowed_ips('')
kiem("ALLOWED_IPS rỗng, IP bất kỳ", goi('/', ip='8.8.8.8'), {200, 302})
A._ALLOWED_NETS = A._parse_allowed_ips('khong-phai-ip, 203.0.113.7')
kiem("Bỏ qua mục sai cú pháp, giữ mục đúng", goi('/', ip='203.0.113.7'), {200, 302})
kiem("Mục sai không mở cửa cho IP lạ", goi('/', ip='8.8.8.8'), {403})

print("\n" + "=" * 74)
print(f"RESULTS: {17 - len(fails)} passed, {len(fails)} failed")
print("=" * 74)
if fails:
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL TESTS PASSED")
