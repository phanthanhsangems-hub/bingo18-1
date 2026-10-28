"""P279: watcher dung im tu 12:49 28/10 — ket noi DB chet im lang, truy van cho mai.
Keepalive (watcher + Cloud Run) va canh gac vong lap watch."""
import os, sys, time
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

print("=== 1. KEEPALIVE ===")
c = S.DB_CONFIG
kiem("watcher bat keepalive", c.get('keepalives') == 1 and c.get('keepalives_idle', 999) <= 60, c)
kiem("watcher do ra ket noi chet trong ~2 phut",
     c['keepalives_idle'] + c['keepalives_interval'] * c['keepalives_count'] <= 120)
import database as D, config
with mock.patch('psycopg2.connect') as pc:
    D.DatabaseManager._connect_pg_retry()
kw = pc.call_args.kwargs
kiem("Cloud Run bat keepalive", kw.get('keepalives') == 1 and kw.get('keepalives_idle', 999) <= 60, kw)
kiem("Cloud Run van giu connect_timeout", kw.get('connect_timeout') == 10, kw)

print("=== 2. CANH GAC ===")
class Thoat(Exception): pass
def chay(env, tre):
    S._NHIP[0] = time.time() - tre
    with mock.patch.dict(os.environ, env, clear=False), \
         mock.patch.object(S.time, 'sleep', side_effect=[None, Thoat()]), \
         mock.patch.object(S.os, '_exit', side_effect=SystemExit) as ex:
        try:
            S._canh_gac(); kq = 'chay tiep'
        except SystemExit:
            kq = 'thoat'
        except Thoat:
            kq = 'chay tiep'
    return kq, ex
kq, ex = chay({'BINGO_WATCHDOG': '1'}, S.WATCHDOG_GIAY + 60)
kiem("chay qua bat + treo qua nguong -> thoat 75", kq == 'thoat' and ex.call_args.args == (75,), (kq, ex.call_args))
kq, ex = chay({'BINGO_WATCHDOG': '1'}, 30)
kiem("vong lap binh thuong -> khong thoat", kq == 'chay tiep' and not ex.called)
os.environ.pop('BINGO_WATCHDOG', None)
kq, ex = chay({}, S.WATCHDOG_GIAY + 60)
kiem("chay tay (khong co bat) -> KHONG tu tat", kq == 'chay tiep' and not ex.called)
kiem("chay tay: dat lai nhip de khong bao moi 30s", time.time() - S._NHIP[0] < 5)
kiem("nguong >= 15 phut (vong bu Vietlott 429 co the lau)", S.WATCHDOG_GIAY >= 900)

print("=== 3. NOI VAO VONG LAP ===")
src = open('sync_to_supabase.py', encoding='utf-8').read()
i = src.index('def mode_watch'); j = src.index('\ndef ', i + 10); mw = src[i:j]
kiem("mode_watch khoi dong canh gac", "target=_canh_gac" in mw)
kiem("dau moi vong cap nhat nhip", mw.index('_NHIP[0] = time.time()') < mw.index('get_conn()'))
kiem("cho lui (sai mat khau) khong bi coi la treo", '_NHIP[0] = time.time() + _cho' in mw)
b = open('scripts/start_watcher.bat', 'rb').read()
kiem("bat dat BINGO_WATCHDOG=1 truoc :loop", b.index(b'set BINGO_WATCHDOG=1') < b.index(b'\r\n:loop'))
kiem("bat giu xuong dong CRLF (LF lam goto hong tren Windows)", b.count(b'\n') == b.count(b'\r\n'))

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
