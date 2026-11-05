"""P286: bỏ SSE để Cloud Run không bị tính tiền 24/24.

Trước P286: mỗi tab dashboard giữ một luồng /api/sse/draws 240 giây, tự nối lại,
truy vấn DB mỗi 6 giây. Cloud Run tính tiền suốt thời gian có request đang chạy
-> một tab để mở = instance bị tính tiền ~24/24 (hoá đơn tháng 10 ~2,4 triệu đ).
Giờ: endpoint trả 204 ngay (tab cũ ngừng nối lại), JS phát hiện kỳ mới trong vòng
làm mới 60s, và không gọi máy chủ khi tab ẩn.
"""
import os, re, sys, time
os.environ.pop('DATABASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))

print("=== 1. /api/sse/draws tra 204 ngay, khong mo luong ===")
from unittest import mock
import app as A
with mock.patch.object(A.db, 'get_connection', side_effect=AssertionError('khong duoc dung DB')):
    t0 = time.time()
    r = A.app.test_client().get('/api/sse/draws', headers={'X-Trigger-Secret': os.environ.get('TRIGGER_SECRET', '')})
    dt = time.time() - t0
kiem("ma 204 (EventSource: ngung noi lai)", r.status_code == 204, r.status_code)
kiem("tra ngay (< 1 giay)", dt < 1, dt)
kiem("khong co than / khong phai stream", r.data == b'' and 'event-stream' not in (r.content_type or ''), r.content_type)
src = open('app.py', encoding='utf-8').read()
kiem("app.py khong con vong SSE", 'stream_with_context(generate())' not in src and '_SSE_MAX_LIFETIME' not in src)

print("=== 2. Dashboard JS ===")
js = open('static/js/dashboard.js', encoding='utf-8').read()
kiem("khong con EventSource", 'EventSource' not in js)
kiem("khong goi connectSSE", 'connectSSE' not in js)
kiem("phat hien ky moi trong loadRecent", re.search(r'async function loadRecent[\s\S]*?baoKyMoi\(latest\)', js) is not None)
kiem("ky moi -> toast + nap thong ke", re.search(r'function baoKyMoi[\s\S]*?toast\([\s\S]*?refreshThongKe\(\)', js) is not None)
vong = re.findall(r'setInterval\(([^;]*)\);', js)
khong_boc = [v for v in vong if 'khiHien' not in v and 'tick' not in v]
kiem("moi vong goi may chu deu dung khi tab an (khiHien)", not khong_boc, khong_boc)
kiem("hien lai tab -> nap ngay", "visibilitychange" in js and "refreshAllVaGhiMoc();" in js)

print("=== 3. Deploy khong build lai khi chi sua workflow/test ===")
dp = open('.github/workflows/deploy.yml', encoding='utf-8').read()
for m in ("'.github/workflows/**'", "'test_*.py'", "'scripts/**'"):
    kiem(f"paths-ignore {m}", m in dp)

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
