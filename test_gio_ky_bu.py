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
kiem("#193424 theo lich quay: 13:06 VN (khong phai 07:00)", g == '2026-10-28 06:06:00', g)

print("=== 3. TU SUA THEO LICH QUAY (du lieu that 28/10) ===")
that = {193427: u(6, 42), 193428: u(0, 0), 193429: u(0, 0), 193430: u(0, 0), 193431: u(6, 57),
        193432: u(0, 0), 193433: u(7, 2), 193434: u(7, 6)}
cur = Cur(that)
n = S.sua_gio_le(Conn(cur))
kiem("sua ky lech lich (4 ky 07:00 + 2 ky ghi muon)", sorted(k for k, _ in cur.upd) == [193427, 193428, 193429, 193430, 193431, 193432], cur.upd)
kiem("#193428 ve 13:30 VN", cur.ky[193428] == u(6, 30), cur.ky[193428])
kiem("khong dung vao ky dung lich", cur.ky[193433] == u(7, 2) and cur.ky[193434] == u(7, 6))
kiem("chay lai -> khong sua gi nua", S.sua_gio_le(Conn(cur)) == 0)

print("=== 3b. KHONG LECH DAY CHUYEN (loi P281 ngay 30/10) ===")
import gio_ky as G
from datetime import date
lich = lambda dn: G.gio_lich(dn, date(2026, 10, 30))
ky = [(dn, lich(dn) + TD(minutes=1)) for dn in range(193672, 193700)]   # ghi song: tre 1 phut
ky[10] = (193682, DT(2026, 10, 30, 2, 1))                               # 09:01 VN, that 07:06
sua = G.sua_theo_lich(ky)
kiem("chi sua dung ky ghi muon #193682", [x[0] for x in sua] == [193682], sua)
kiem("#193682 ve 07:06 VN", sua and sua[0][2] == DT(2026, 10, 30, 0, 6), sua)
cu = S.gio_ky.tim_gio_le(ky)
kiem("(doi chung) cach cu 'tang dan' day lech ca loat", len(cu) > 5, len(cu))

print("=== 3c. AN TOAN ===")
lech = [(dn, lich(dn) + TD(minutes=6 * 14)) for dn in range(193672, 193700)]   # neo lech 14 vi tri
kiem("ca khoi khong ky nao trung lich -> bo qua", G.sua_theo_lich(lech) == [])
cu_xa = [(150000, u(0, 0)), (150001, u(0, 0)), (150002, u(5, 0))]
kiem("ky truoc 03/04/2026 -> khong sua", G.sua_theo_lich(cu_xa) == [])

print("=== 4. MOI CHO BU KY DEU NOI SUY ===")
src = open('sync_to_supabase.py', encoding='utf-8').read()
kiem("vong watch goi sua_gio_le", 'sua_gio_le(conn)' in src[src.index('def mode_watch'):])
kiem(">= 3 cho insert_draw tu trang chi tiet dung gio_noi_suy",
     src.count("draw['draw_date'] = gio_noi_suy(conn, draw_id)") >= 3)
kiem("fill_gaps (GitHub) uu tien noi suy", 'draw_time = gio_noi_suy(conn, dn)' in src)

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
