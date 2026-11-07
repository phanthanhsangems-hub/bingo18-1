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
kiem("va_lo_hong cung cho 2 giay moi ky (P290c)", 'time.sleep(2.0)' in body and 'time.sleep(0.35)' not in body)
print("=== 5. get_new_since: LIMIT khong bi doc nhu dict (P276) ===")
with mock.patch.object(S, 'fetch_homepage', return_value=[]), \
     mock.patch.object(S, 'fetch_detail', side_effect=[{'draw_id': 11, 'numbers': [1, 2, 3]}, S.LIMIT, {'draw_id': 13, 'numbers': [4, 5, 6]}]) as fd:
    try:
        kq = S.get_new_since(10); loi = None
    except Exception as e:
        kq, loi = None, e
kiem("khong nem loi", loi is None, loi)
kiem("giu ky lay duoc truoc khi bi chan", kq == [{'draw_id': 11, 'numbers': [1, 2, 3]}], kq)
kiem("dung hoi ngay khi LIMIT", fd.call_count == 2, fd.call_count)
kiem("moi cho goi fetch_detail deu xu ly LIMIT", src.count('fetch_detail(') - 1 <= open('sync_to_supabase.py', encoding='utf-8').read().count('== LIMIT'))
print("=== 6. P290: tries=1 gap 429 -> LIMIT ngay, khong ngu ===")
with mock.patch.object(S, '_session') as ss, mock.patch('time.sleep') as ngu:
    ss.get.return_value = R(429)
    kq = S.fetch_detail(5, tries=1)
kiem("tra LIMIT", kq == S.LIMIT, kq)
kiem("khong ngu", ngu.call_count == 0, ngu.call_count)
with mock.patch.object(S, '_session') as ss, mock.patch('time.sleep') as ngu:
    ss.get.return_value = R(429)
    S.fetch_detail(5)
kiem("tries=3: chi ngu giua cac lan (2 lan, khong ngu sau lan cuoi)", ngu.call_count == 2, ngu.call_count)
print("=== 7. P290: va_lo_hong gap 429 -> nghi 30 phut, khong hoi lai ===")
class Cur:
    def __init__(s): s.q = None
    def execute(s, sql, params=None): s.q = sql
    def fetchone(s): return (100,)
    def fetchall(s): return [(d,) for d in range(-200, 101) if d not in (95, 96)]
class Conn:
    def cursor(s): return Cur()
    def rollback(s): pass
S._VIETLOTT_NGHI[0] = 0.0
khong_co = set()
with mock.patch.object(S, 'fetch_detail', return_value=S.LIMIT) as fd:
    kq1 = S.va_lo_hong_tu_vietlott(Conn(), khong_co)
    kq2 = S.va_lo_hong_tu_vietlott(Conn(), khong_co)
kiem("lan 1 tra [] va khong blacklist", kq1 == [] and not khong_co, (kq1, khong_co))
kiem("hoi Vietlott dung 1 lan, voi tries=1", fd.call_count == 1 and fd.call_args.kwargs.get('tries') == 1,
     (fd.call_count, fd.call_args))
kiem("dat moc nghi ~30 phut", 1700 < S._VIETLOTT_NGHI[0] - __import__('time').time() <= 1800, S._VIETLOTT_NGHI[0])
kiem("vong 2 trong luc nghi: khong hoi", kq2 == [] and fd.call_count == 1, fd.call_count)
S._VIETLOTT_NGHI[0] = 0.0
with mock.patch.object(S, 'fetch_detail', return_value=None) as fd, mock.patch('time.sleep'):
    S.va_lo_hong_tu_vietlott(Conn(), khong_co)
kiem("het nghi -> hoi lai ca 2 ky thieu", fd.call_count == 2, fd.call_count)
S._VIETLOTT_NGHI[0] = 0.0
print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
