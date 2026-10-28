"""P281: ky BU lo hong khong duoc ghi 07:00 (00:00 UTC) — noi suy tu ky ke ben;
ky da ghi sai thi tu sua."""
import os, sys
from datetime import datetime as DT, timedelta as TD
from unittest import mock
os.environ.setdefault('DATABASE_URL', '')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync_to_supabase as S
import gio_ky
DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))
u = lambda h, m: DT(2026, 10, 28, h, m)      # gio UTC

print("=== 1. NOI SUY ===")
kiem("giua hai ky: chia deu", gio_ky.noi_suy((193427, u(6, 42)), (193431, u(6, 58)), 193429) == u(6, 50))
kiem("chi co ky truoc: +6 phut/ky", gio_ky.noi_suy((193421, u(5, 49)), None, 193423) == u(6, 1))
kiem("chi co ky sau: -6 phut/ky", gio_ky.noi_suy(None, (193431, u(6, 58)), 193430) == u(6, 52))
kiem("ky sau KHONG muon hon ky truoc -> bo ky sau", gio_ky.noi_suy((10, u(6, 42)), (12, u(0, 0)), 11) == u(6, 48))
kiem("khong co gi -> None", gio_ky.noi_suy(None, None, 5) is None)

class Cur:
    def __init__(s, ky): s.ky = dict(ky); s.r = []; s.upd = []
    def execute(s, q, p=()):
        q = ' '.join(q.split())
        if 'draw_number < %s' in q:
            xs = sorted(k for k in s.ky if k < p[0]); s.r = [(xs[-1], s.ky[xs[-1]])] if xs else []
        elif 'draw_number > %s' in q:
            xs = sorted(k for k in s.ky if k > p[0]); s.r = [(xs[0], s.ky[xs[0]])] if xs else []
        elif q.startswith('SELECT draw_number, draw_time') and 'LIMIT %s' in q:
            s.r = sorted(s.ky.items(), reverse=True)[:p[0]]
        elif q.startswith('UPDATE'):
            s.upd.append((p[1], p[0])); s.ky[p[1]] = DT.strptime(p[0], '%Y-%m-%d %H:%M:%S')
    def fetchone(s): return s.r[0] if s.r else None
    def fetchall(s): return s.r
class Conn:
    def __init__(s, cur): s.c = cur
    def cursor(s): return s.c

print("=== 2. KY BU LAY GIO TU KY KE BEN ===")
cur = Cur({193421: u(5, 49), 193427: u(6, 42)})
g = S.gio_noi_suy(Conn(cur), 193424)
kiem("#193424 nam giua 12:49 va 13:42 VN (khong phai 07:00)", g == '2026-10-28 06:15:30', g)

print("=== 3. TU SUA KY DA GHI 07:00 (du lieu that 28/10) ===")
that = {193427: u(6, 42), 193428: u(0, 0), 193429: u(0, 0), 193430: u(0, 0), 193431: u(6, 57),
        193432: u(0, 0), 193433: u(7, 2), 193434: u(7, 6)}
cur = Cur(that)
n = S.sua_gio_le(Conn(cur))
kiem("sua dung 4 ky bi 07:00", sorted(k for k, _ in cur.upd) == [193428, 193429, 193430, 193432], cur.upd)
ds = sorted(cur.ky.items())
kiem("sau khi sua gio tang dan", all(b[1] > a[1] for a, b in zip(ds, ds[1:])), ds)
kiem("khong dung vao ky dung", cur.ky[193431] == u(6, 57) and cur.ky[193433] == u(7, 2))
kiem("chay lai -> khong sua gi nua", S.sua_gio_le(Conn(cur)) == 0)

print("=== 4. MOI CHO BU KY DEU NOI SUY ===")
src = open('sync_to_supabase.py', encoding='utf-8').read()
kiem("vong watch goi sua_gio_le", 'sua_gio_le(conn)' in src[src.index('def mode_watch'):])
kiem(">= 3 cho insert_draw tu trang chi tiet dung gio_noi_suy",
     src.count("draw['draw_date'] = gio_noi_suy(conn, draw_id)") >= 3)
kiem("fill_gaps (GitHub) uu tien noi suy", 'draw_time = gio_noi_suy(conn, dn)' in src)

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
