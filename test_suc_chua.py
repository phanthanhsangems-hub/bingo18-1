"""P222: sức chứa — số luồng SSE phải nhỏ hơn hẳn số thread của gunicorn.

Đây là một BẤT BIẾN VẮT QUA HAI FILE, loại dễ vỡ âm thầm nhất: ai đó nâng
_SSE_MAX_CLIENTS trong app.py, hoặc hạ --threads trong Dockerfile, và không có
gì báo. Hậu quả không phải lỗi rõ ràng mà là app treo dưới tải nhẹ — đúng cảnh
"app không chạy" mà mọi phép kiểm tuần tự vẫn xanh.

Cơ chế: gunicorn --threads dùng worker gthread, mỗi request giữ một thread đến
khi trả xong. /api/sse/draws giữ trọn một thread tới _SSE_MAX_LIFETIME giây.
Nên số thread còn lại cho phần còn lại của app = threads - _SSE_MAX_CLIENTS.
"""
import os, re, sys

os.environ.setdefault('DATABASE_URL', '')
os.environ.pop('APP_USER', None)

DAT = HONG = 0
def kiem(ten, dk, ct=''):
    global DAT, HONG
    if dk: DAT += 1; print(f"  DAT  {ten}")
    else:  HONG += 1; print(f"  HONG {ten}" + (f"  -> {ct}" if ct else ''))

# ── Đọc số thread từ Dockerfile ──────────────────────────────
src_docker = open('Dockerfile', encoding='utf-8').read()
m = re.search(r'--threads\s+(\d+)', src_docker)
kiem("Dockerfile co khai bao --threads", m is not None)
threads = int(m.group(1)) if m else 0

m_w = re.search(r'--workers\s+(\d+)', src_docker)
workers = int(m_w.group(1)) if m_w else 0
kiem("Dockerfile co khai bao --workers", m_w is not None)

# ── Đọc hằng số SSE từ app.py (đọc text, khỏi phải import cả app) ──
src_app = open('app.py', encoding='utf-8').read()
def hang(ten):
    mm = re.search(rf'^{ten}\s*=\s*(\d+)', src_app, re.M)
    return int(mm.group(1)) if mm else None

sse_max  = hang('_SSE_MAX_CLIENTS')
sse_life = hang('_SSE_MAX_LIFETIME') or hang(r'\s*_SSE_MAX_LIFETIME')
if sse_life is None:
    mm = re.search(r'_SSE_MAX_LIFETIME\s*=\s*(\d+)', src_app)
    sse_life = int(mm.group(1)) if mm else None

kiem("app.py co _SSE_MAX_CLIENTS", sse_max is not None)
kiem("app.py co _SSE_MAX_LIFETIME", sse_life is not None)

print(f"\n  do duoc: workers={workers}  threads={threads}  "
      f"_SSE_MAX_CLIENTS={sse_max}  _SSE_MAX_LIFETIME={sse_life}s")

con_lai = threads - (sse_max or 0)
print(f"  thread con lai khi SSE day: {con_lai}\n")

# ── Bất biến ─────────────────────────────────────────────────
kiem("SSE khong duoc chiem qua 1/3 so thread",
     sse_max is not None and threads > 0 and sse_max * 3 <= threads,
     f"{sse_max} luong / {threads} thread = {100*sse_max/max(threads,1):.0f}%")

kiem("con >= 12 thread cho phan con lai khi SSE day",
     con_lai >= 12, f"chi con {con_lai}")

# Cảnh 22/09 thật: 5 tab dashboard + 1 request chậm (/api/weight-optimizer
# đo được quá 30 giây). Với threads=8 thì còn 2 — quá mỏng.
kiem("5 tab SSE + 3 request cham van con >= 8 thread",
     threads - (sse_max or 0) - 3 >= 8,
     f"con {threads - (sse_max or 0) - 3}")

kiem("SSE phai dong truoc timeout cua gunicorn",
     sse_life is not None and sse_life < 300, f"_SSE_MAX_LIFETIME={sse_life}")

m_t = re.search(r'--timeout\s+(\d+)', src_docker)
timeout = int(m_t.group(1)) if m_t else 0
kiem("SSE_MAX_LIFETIME < --timeout cua gunicorn",
     sse_life is not None and timeout > 0 and sse_life < timeout,
     f"{sse_life} vs {timeout}")

# workers=1 la co y (khong pool ket noi DB) — khoa lai de khoi ai tang bua
kiem("workers giu = 1 (app co y khong dung connection pool)",
     workers == 1, f"workers={workers}")

# Moi request dong thoi = mot ket noi Postgres. Giu duoi han muc Supabase.
kiem("threads <= 30 (moi thread la mot ket noi Postgres)",
     0 < threads <= 30, f"threads={threads}")

print("\n" + "=" * 52)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
