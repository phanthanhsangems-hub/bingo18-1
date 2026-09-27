"""P236: menu /start phai liet ke DU moi lenh bot xu ly.

/trend va /dow chay duoc tu lau nhung menu quen liet ke, nen nguoi dung
khong biet co. Test nay doc thang bo xu ly lenh trong app.py va doi chieu voi
chu trong menu — them lenh ma quen menu la hong ngay.
"""
import os, re, sys, json
from unittest import mock
os.environ.setdefault('DATABASE_URL', ''); os.environ.pop('APP_USER', None)
import app as A
A.limiter.enabled = False

DAT = HONG = 0
def kiem(ten, dk, ct=''):
    global DAT, HONG
    if dk: DAT += 1; print(f"  DAT  {ten}")
    else:  HONG += 1; print(f"  HONG {ten}" + (f"  -> {ct}" if ct else ''))

src = open('app.py', encoding='utf-8').read()
m = re.search(r'if cmd in \(("/predict"[^)]*)\):', src)
kiem("tim thay bo xu ly lenh", m is not None)
xu_ly = re.findall(r'"(/[a-z_]+)"', m.group(1)) if m else []
kiem(f"bo xu ly co {len(xu_ly)} lenh (>= 23)", len(xu_ly) >= 23, str(xu_ly))

# Lay menu THAT bang cach goi webhook voi /start, khong doc chu trong code.
gui = []
with mock.patch.object(A, '_tg_main_keyboard', return_value=None, create=True):
    import telegram_bot
    with mock.patch.object(telegram_bot.TelegramBot, 'send_message',
                           side_effect=lambda self, m, *a, **k: gui.append(m) or True,
                           autospec=True):
        sec = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '')
        h = {'X-Telegram-Bot-Api-Secret-Token': sec} if sec else {}
        r = A.app.test_client().post('/telegram/webhook', headers=h, json={
            'update_id': 1, 'message': {'message_id': 1, 'text': '/start',
            'chat': {'id': int(os.environ.get('TELEGRAM_CHAT_ID', '1') or 1)},
            'from': {'id': 1}}})
menu = '\n'.join(gui) or ''
if not menu:   # moi truong test khong goi duoc bot -> doc chuoi menu trong code
    i = src.index('if cmd in ("/start", "/help"):')
    menu = src[i:src.index('markup=_tg_main_keyboard()', i)]
print('  (nguon menu: ' + ('webhook that' if gui else 'doc chuoi trong code') + ')')
kiem("lay duoc noi dung menu", '/predict' in menu)

for c in xu_ly:
    kiem(f"menu co {c}", re.search(re.escape(c) + r'\b', menu) is not None)
kiem("P236: /trend co trong menu", '/trend' in menu)
kiem("P236: /dow co trong menu", '/dow' in menu)
kiem("/new_checkpoint duoc canh bao la DAT LAI", 'ĐẶT LẠI' in menu)
kiem("menu nhac co the hoi AI bang tin nhan tu do", 'hỏi AI' in menu)
kiem("menu duoi gioi han 4096 ky tu cua Telegram", len(menu) < 4096, str(len(menu)))

print("\n" + "=" * 54)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
