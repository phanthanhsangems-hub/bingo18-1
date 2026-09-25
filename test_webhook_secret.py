"""P225: /telegram/set-webhook phải làm Telegram KHỚP với cấu hình của app.

Cái bẫy đã bịt: endpoint này trước đây chỉ gửi url. Ai bấm nó sau khi đã cài
TELEGRAM_WEBHOOK_SECRET sẽ XOÁ secret_token bên Telegram — Telegram thôi gửi
header, app vẫn đòi header, nên mọi lệnh bot bị 403 và không có gì nói vì sao.
Nút "thiết lập webhook" lại làm bot chết.
"""
import os, sys
from unittest import mock

os.environ.setdefault('DATABASE_URL', '')
os.environ.pop('APP_USER', None)

import app as A
import config

# Tat limiter trong test. Lan chay dau bo test nay do o buoc "sai admin secret
# -> 401" nhung thuc te tra 429: dung rate limit 5/phut vua them cho endpoint
# nay o P224 — bay phep goi truoc do da dot het xo. Do la limiter chay DUNG,
# khong phai loi code. O day ta kiem LOGIC cua endpoint, con chuyen endpoint co
# gioi han hay khong thi test_gioi_han_ip.py da khoa rieng.
A.limiter.enabled = False

DAT = HONG = 0
def kiem(ten, dk, ct=''):
    global DAT, HONG
    if dk: DAT += 1; print(f"  DAT  {ten}")
    else:  HONG += 1; print(f"  HONG {ten}" + (f"  -> {ct}" if ct else ''))

def goi(secret, admin='admin-xyz'):
    """Gọi endpoint, trả (body gửi lên Telegram, JSON endpoint trả về)."""
    gui = {}
    class GiaResp:
        def json(self): return {"ok": True, "result": True}
    def gia_post(url, json=None, timeout=None):
        gui['url'] = url; gui['json'] = json
        return GiaResp()
    with mock.patch.object(config, 'TELEGRAM_WEBHOOK_SECRET', secret, create=True), \
         mock.patch.object(config, 'ADMIN_SECRET_KEY', admin, create=True), \
         mock.patch.object(config, 'TELEGRAM_BOT_TOKEN', '111:AAA', create=True), \
         mock.patch.object(A.requests, 'post', gia_post):
        c = A.app.test_client()
        r = c.post('/telegram/set-webhook', headers={'X-Admin-Secret': 'admin-xyz'})
    return gui, r

print("=== 1. CO SECRET -> phai gui kem secret_token DUNG gia tri ===")
gui, r = goi('abc123def456')
kiem("goi dung setWebhook cua Telegram", 'setWebhook' in gui.get('url', ''), gui.get('url'))
kiem("body CO khoa secret_token", 'secret_token' in (gui.get('json') or {}),
     str(gui.get('json')))
kiem("secret_token dung gia tri cua app",
     (gui.get('json') or {}).get('secret_token') == 'abc123def456',
     str((gui.get('json') or {}).get('secret_token')))
kiem("van gui url webhook", 'telegram/webhook' in (gui.get('json') or {}).get('url', ''))
kiem("endpoint bao secret_token_da_dat = True",
     r.get_json().get('secret_token_da_dat') is True, str(r.get_json()))

print("\n=== 2. CONFIG RONG -> xoa token ben Telegram (ca hai TAT, nhat quan) ===")
gui, r = goi('')
kiem("van gui khoa secret_token (rong)", 'secret_token' in (gui.get('json') or {}))
kiem("gia tri la chuoi rong", (gui.get('json') or {}).get('secret_token') == '')
kiem("endpoint bao secret_token_da_dat = False",
     r.get_json().get('secret_token_da_dat') is False, str(r.get_json()))

print("\n=== 3. CAI BAY CU: KHONG BAO GIO duoc gui thieu secret_token ===")
# Day la phep kiem quan trong nhat. Ban cu gui {"url", "drop_pending_updates"}
# va lam bot chet. Neu ai go secret_token di, test nay phai do.
for s in ('abc123', '', 'X' * 64):
    gui, _ = goi(s)
    kiem(f"secret={s[:8]!r} -> body luon co secret_token",
         'secret_token' in (gui.get('json') or {}), str(gui.get('json')))

print("\n=== 4. SAI ADMIN SECRET -> 401, KHONG goi Telegram ===")
gui = {}
class GiaResp2:
    def json(self): return {"ok": True}
def gia_post2(url, json=None, timeout=None):
    gui['goi'] = True
    return GiaResp2()
with mock.patch.object(config, 'ADMIN_SECRET_KEY', 'dung', create=True), \
     mock.patch.object(A.requests, 'post', gia_post2):
    r = A.app.test_client().post('/telegram/set-webhook',
                                 headers={'X-Admin-Secret': 'sai'})
kiem("tra 401", r.status_code == 401, str(r.status_code))
kiem("KHONG goi Telegram", 'goi' not in gui)

print("\n=== 5. TEN HEADER app kiem PHAI dung ten Telegram gui ===")
# Telegram gui header 'X-Telegram-Bot-Api-Secret-Token'. Sai mot chu la hong.
src = open('app.py', encoding='utf-8').read()
kiem("app doc dung 'X-Telegram-Bot-Api-Secret-Token'",
     "X-Telegram-Bot-Api-Secret-Token" in src)

print("\n" + "=" * 52)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
