"""P271: 429 tu Vietlott phai thu lai, KHONG bi coi la ky khong ton tai."""
import os, sys
from unittest import mock
os.environ.setdefault('DATABASE_URL', '')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync_to_supabase as S
DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))
class R:
    def __init__(s, code, text=''): s.status_code = code; s.text = text
html = '<html>'
print("=== 1. 429 roi 200 -> lay duoc ===")
ket = {'draw_id': 5, 'numbers': [1, 2, 3]}
with mock.patch.object(S, '_session') as ss, mock.patch.object(S, '_parse_bingo18', return_value=[ket]), mock.patch('time.sleep'):
    ss.get.side_effect = [R(429), R(200, html)]
    kq = S.fetch_detail(5)
kiem("tra ve ket qua sau khi thu lai", kq == ket, kq)
print("=== 2. 429 mai -> LIMIT, khong phai None ===")
with mock.patch.object(S, '_session') as ss, mock.patch('time.sleep'):
    ss.get.return_value = R(429)
    kq = S.fetch_detail(5)
kiem("tra LIMIT", kq == S.LIMIT, kq)
print("=== 3. 404/khac -> None (ky khong co that) ===")
with mock.patch.object(S, '_session') as ss:
    ss.get.return_value = R(404)
    kq = S.fetch_detail(5)
kiem("404 -> None", kq is None, kq)
print("=== 4. vong bu khong blacklist khi LIMIT ===")
src = open('sync_to_supabase.py', encoding='utf-8').read()
i = src.index('def va_lo_hong_tu_vietlott'); j = src.index('def bao_da_bu', i)
body = src[i:j]
kiem("va_lo_hong: LIMIT -> break truoc khi khong_co.add", body.index('== LIMIT') < body.index('khong_co.add'))
kiem("mode_gaps: LIMIT -> dung + bao ro", "giới hạn tốc độ (429)" in src and src.index('== LIMIT') < src.index('err += 1'))
kiem("mode_gaps cho 2 giay moi ky", 'time.sleep(2.0)' in src)
print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
