"""P263: tin Telegram gửi hỏng vào hàng đợi, thử lại mỗi vòng, bỏ sau N lần."""
import os, sys, json, tempfile
from unittest import mock
os.environ.setdefault('DATABASE_URL', '')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync_to_supabase as S
import lap_lai as LL
DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))

tmp = tempfile.mkdtemp()
S._TIN_CHO_FILE = os.path.join(tmp, 'tin_cho_gui.json')
class _Conn:
    def __init__(s): s.nk = []
    def cursor(s): return s
    def execute(s, *a, **k): pass
    def fetchone(s): return None
    def commit(s): pass
    def rollback(s): pass
    def close(s): pass

print("=== 1. gui hong -> vao hang doi, nhat ky ok=False ===")
conn = _Conn(); ghi = []
with mock.patch.object(S, '_tg_html', return_value=False), \
     mock.patch.object(S, 'doc_du_lieu_tin_ky', return_value={'ky': [], 'du_doan': {}, 'trail': []}), \
     mock.patch.object(S, '_ghi_nhat_ky_tin', side_effect=lambda c, m: ghi.extend(m)):
    S.gui_tin_ky(conn, {'draw_id': 500, 'numbers': [1, 2, 3]})
hang = S._doc_tin_cho()
kiem("co 1 tin trong hang doi", len(hang) == 1, hang)
kiem("tin giu dung ky va lan=1", hang and hang[0]['dn'] == 500 and hang[0]['lan'] == 1)
kiem("nhat ky ghi ok=False", ghi and ghi[0]['ok'] is False, ghi)

print("\n=== 2. vong sau: gui duoc -> xoa khoi hang, ghi nhat ky retry ok=True ===")
ghi2 = []
with mock.patch.object(S, '_tg_html', return_value=True), \
     mock.patch.object(S, '_ghi_nhat_ky_tin', side_effect=lambda c, m: ghi2.extend(m)):
    n = S.thu_gui_lai_tin_cho(conn)
kiem("gui duoc 1 tin", n == 1, n)
kiem("hang rong", S._doc_tin_cho() == [])
kiem("nhat ky nguon=retry ok=True", ghi2 and ghi2[0]['nguon'] == 'retry' and ghi2[0]['ok'] is True, ghi2)

print("\n=== 3. van hong -> tang lan, bo sau _TIN_CHO_MAX_LAN lan gui tong ===")
# lan=1 la lan gui dau (da hong khi xep hang). Moi lan thu lai hong -> lan+1.
S._xep_tin_cho('t', 600, None, 'watcher')
with mock.patch.object(S, '_tg_html', return_value=False):
    for i in range(S._TIN_CHO_MAX_LAN - 2):          # den lan = MAX-1 van con trong hang
        S.thu_gui_lai_tin_cho(None)
    hang = S._doc_tin_cho()
kiem(f"lan = {S._TIN_CHO_MAX_LAN - 1}, van trong hang", len(hang) == 1 and hang[0]['lan'] == S._TIN_CHO_MAX_LAN - 1, hang)
with mock.patch.object(S, '_tg_html', return_value=False):
    S.thu_gui_lai_tin_cho(None)                       # lan thu thu MAX -> bo
kiem("tong MAX lan gui hong -> bo khoi hang", S._doc_tin_cho() == [])

print("\n=== 4. hang doi hong / file khong co -> khong chet ===")
with open(S._TIN_CHO_FILE, 'w', encoding='utf-8') as f: f.write('{khong phai json')
kiem("file hong -> hang rong, khong nem loi", S._doc_tin_cho() == [])
os.remove(S._TIN_CHO_FILE)
kiem("khong co file -> 0 tin", S.thu_gui_lai_tin_cho(None) == 0)

print("\n=== 5. tich hop ===")
src = open('sync_to_supabase.py', encoding='utf-8').read()
kiem("import json o dau file", '\nimport argparse, json,' in src)
kiem("vong watch thu gui lai moi vong", src.index('thu_gui_lai_tin_cho(conn)') < src.index('if new:', src.index('thu_gui_lai_tin_cho(conn)')))
kiem("ca 2 cho gui deu xep hang khi hong", src.count('_xep_tin_cho(') >= 3)
kiem("hang doi nam canh script, gitignore", 'tin_cho_gui.json' in open('.gitignore', encoding='utf-8').read())
print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
