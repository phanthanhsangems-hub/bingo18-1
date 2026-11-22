"""P301: gui_thong_ke.py — gửi tin tự soạn tới Telegram, token không bao giờ hiện ra."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts'))
import gui_thong_ke as G

DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))

TOK = '1234567890:' + 'Q' * 35
class R:
    def __init__(s, c, j): s.status_code, s._j = c, j
    def json(s): return s._j

print("=== 1. GUI ===")
nhan = {}
def goi_ok(url, data): nhan.update(url=url, data=data); return R(200, {'ok': True})
ok, ly = G.gui(TOK, '1', '<b>x</b>', goi=goi_ok)
kiem("gui OK -> (True, None)", ok is True and ly is None)
kiem("gui dung URL bot + HTML + khong xem truoc link", f'/bot{TOK}/sendMessage' in nhan['url']
     and nhan['data']['parse_mode'] == 'HTML' and nhan['data']['disable_web_page_preview'] is True)
ok, ly = G.gui(TOK, '1', 'x', goi=lambda u, d: R(401, {'ok': False, 'description': 'Unauthorized'}))
kiem("401 -> (False, mo ta, khong co token)", ok is False and 'Unauthorized' in ly and 'Q' * 10 not in ly, ly)
def loi(u, d): raise ConnectionError(u)
ok, ly = G.gui(TOK, '1', 'x', goi=loi)
kiem("loi mang -> khong lo token", ok is False and 'Q' * 10 not in ly, ly)

print("=== 2. MAIN ===")
d = tempfile.mkdtemp()
G.GOC = d; os.makedirs(os.path.join(d, 'scripts'))
open(os.path.join(d, '.env'), 'w', encoding='utf-8').write(f'TELEGRAM_BOT_TOKEN={TOK}\nTELEGRAM_CHAT_ID=42\n')
import io, contextlib
G.gui = lambda tok, chat, nd, goi=None: (nhan.update(tok=tok, chat=chat, nd=nd), (True, None))[1]
open(os.path.join(d, 'scripts', 'thong_ke.txt'), 'w', encoding='utf-8-sig').write('<b>Tong 4</b> 1-3-6')
buf = io.StringIO()
with contextlib.redirect_stdout(buf): ma = G.main([])
out = buf.getvalue()
kiem("doc thong_ke.txt mac dinh (bo BOM) va gui", ma == 0 and nhan['nd'] == '<b>Tong 4</b> 1-3-6' and nhan['chat'] == '42', nhan)
kiem("thanh cong: khong in token", TOK[:10] not in out and '[OK]' in out, out)
os.remove(os.path.join(d, 'scripts', 'thong_ke.txt'))
buf = io.StringIO()
with contextlib.redirect_stdout(buf): ma = G.main([])
kiem("thieu file -> huong dan, ma 1", ma == 1 and 'Không thấy file' in buf.getvalue())
open(os.path.join(d, 'scripts', 'thong_ke.txt'), 'w').write('x' * 5000)
buf = io.StringIO()
with contextlib.redirect_stdout(buf): ma = G.main([])
kiem("qua 4096 ky tu -> tu choi truoc khi gui", ma == 1 and '4096' in buf.getvalue())
open(os.path.join(d, 'scripts', 'thong_ke.txt'), 'w').write('   \n')
buf = io.StringIO()
with contextlib.redirect_stdout(buf): ma = G.main([])
kiem("file trong -> ma 1", ma == 1)
open(os.path.join(d, '.env'), 'w').write('TELEGRAM_CHAT_ID=42\n')
open(os.path.join(d, 'scripts', 'thong_ke.txt'), 'w').write('x')
buf = io.StringIO()
with contextlib.redirect_stdout(buf): ma = G.main([])
kiem("thieu token trong .env -> ma 1", ma == 1 and 'TELEGRAM_BOT_TOKEN' in buf.getvalue())
print("=== 3. BAT ===")
b = open('scripts/gui_thong_ke.bat', 'rb').read()
kiem("CRLF", b.count(b'\r\n') == b.count(b'\n') and b.count(b'\n') >= 5)
t = b.decode('ascii')
kiem("goi chon_python + gui_thong_ke.py + pause", 'call "%~dp0chon_python.bat"' in t and '%PY% scripts\\gui_thong_ke.py %*' in t and 'pause' in t)
kiem("khong echo token / khong taskkill", 'taskkill' not in t.lower() and 'TELEGRAM_BOT_TOKEN' not in t)
print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
