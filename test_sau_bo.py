"""P299: tin mỗi kỳ — "các lần trước bộ vừa ra, kỳ NGAY SAU có về Tổng 4 / 17 / trip nào".

Phần 1: hàm thuần (đếm 2 khung 30 ngày / từ 01/01, định dạng, in đậm 🔁N).
Phần 2: bộ nhớ đệm kỳ trên SQLite (nạp đầu, đọc thêm, kỳ bù, nạp lại, sang năm).
Phần 3: gắn vào tin mỗi kỳ của watcher (bật/tắt, lỗi không làm mất tin).
"""
import os, sqlite3, sys
from datetime import datetime as D, timedelta

os.environ.pop('DATABASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sau_bo as SB

DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))

print("=== 1. HAM THUAN ===")
kiem("1-1-2 = Tong 4, 5-6-6 = Tong 17", SB.loai_sau((1, 1, 2)) == 'T4' and SB.loai_sau((5, 6, 6)) == 'T17')
kiem("trip 111 / 666", SB.loai_sau((1, 1, 1)) == '111' and SB.loai_sau((6, 6, 6)) == '666')
kiem("bo thuong -> None", SB.loai_sau((1, 2, 3)) is None and SB.loai_sau(()) is None)
X, DEN = (2, 3, 3), 200000
L = D(2026, 11, 20, 3, 0)                       # 10:00 VN
def l(k): return L - timedelta(minutes=6 * (DEN - k))
ky = {k: ((1, 2, 4), l(k)) for k in range(DEN - 6000, DEN + 1)}
for k, sau in ((199990, (1, 1, 2)), (199993, (3, 3, 3)), (199996, (3, 3, 3)), (199998, (5, 6, 6))):
    ky[k] = (X, l(k)); ky[k + 1] = (sau, l(k + 1))
ky[200000] = (X, l(200000))                      # chinh ky vua ra (bo X): khong tinh la 1 lan
ky[199980] = (X, l(199980)); del ky[199981]      # ky sau thieu -> bo qua
cu = DEN - SB.KY_30_NGAY - 5
ky[cu] = (X, l(cu)); ky[cu + 1] = ((1, 1, 2), l(cu + 1))       # ngoai 30 ngay, van trong nam
ky[DEN - 5900] = (X, D(2025, 12, 31, 16, 0)); ky[DEN - 5899] = ((6, 6, 6), D(2025, 12, 31, 16, 6))   # nam truoc
MOC = D(2026, 1, 1) - timedelta(hours=7)
kq = SB.phan_tich(ky, X, DEN, MOC)
kiem("30 ngay: 4 lan (bo qua lan thieu ky sau, khong tinh ky dang xet)", kq['n30'] == 4, kq['n30'])
kiem("30 ngay: su kien T4, 333 x2, T17 theo thu tu", [e[2] for e in kq['sk30']] == ['T4', '333', '333', 'T17'], kq['sk30'])
k2 = dict(ky); k2[DEN - 1] = ((5, 5, 5), l(DEN - 1)); k2[DEN] = ((5, 5, 5), l(DEN))
kq2 = SB.phan_tich(k2, (5, 5, 5), DEN, MOC)
kiem("ky ngay sau = chinh ky vua ra van tinh (555 roi 555)", kq2['sk30'] and kq2['sk30'][-1][:1] == (DEN,) and kq2['sk30'][-1][2] == '555', kq2['sk30'])
kiem("tu 01/01: them 1 lan ngoai 30 ngay, khong tinh nam truoc", kq['nnam'] == 5 and kq['dem_nam'] == {'T4': 2, 'trip': 2, 'T17': 1}, kq)
d = SB.dong_tin(X, kq, 2026)
txt = '\n'.join(d)
print('    ' + txt.replace('\n', '\n    '))
kiem("dong dau ghi ro bo vua ra", d[0].startswith('📜 <b>Sau 2-3-3</b>'))
kiem("ra >= 2 lan: in dam + 🔁N", '<b>333</b> 🔁2 (' in txt)
kiem("ra 1 lan: khong in dam, co ngay gio VN", 'Tổng 4 (20/11 ' in txt and '<b>Tổng 4</b>' not in txt)
kiem("gio VN = UTC + 7 (#199999 luc 09:54 VN)", 'Tổng 17 (20/11 09:54)' in txt, txt)
kiem("dong 30 ngay co so lan bo ra", '• 30 ngày (2-3-3 ra 4 lần):' in txt)
kiem("dong tu 01/01 co ky vong", '• Từ 01/01/2026 (ra 5 lần): Tổng 4 2 (kv 0) · Tổng 17 1 (kv 0) · Trip 2 (kv 0)' in txt, txt)
trong = SB.dong_tin(X, {'n30': 40, 'sk30': [], 'nnam': 0, 'dem_nam': {}}, 2026)
kiem("chua ve lan nao -> 'chua'", 'Tổng 4: chưa · Tổng 17: chưa · Trip: chưa' in trong[1] and len(trong) == 2, trong)
nhieu = SB.dong_tin(X, {'n30': 90, 'sk30': [(k, L, 'T4') for k in range(5)], 'nnam': 0, 'dem_nam': {}}, 2026)
kiem("qua 3 moc gio -> 3 moc moi nhat + 'N'", '<b>Tổng 4</b> 🔁5 (' in nhieu[1] and ' +2)' in nhieu[1], nhieu[1])
kiem("kv tu 01/01 = so lan x xac suat", SB.dong_tin(X, {'n30': 0, 'sk30': [], 'nnam': 2160, 'dem_nam': {'T4': 30, 'T17': 25, 'trip': 61}}, 2026)[2]
     == '• Từ 01/01/2026 (ra 2160 lần): Tổng 4 30 (kv 30) · Tổng 17 25 (kv 30) · Trip 61 (kv 60)')

print("=== 2. BO NHO DEM KY (SQLITE) ===")
class _Cur:
    def __init__(s, c): s.c = c.cursor()
    def execute(s, q, a=()): s.c.execute(q.replace('%s', '?'), a); return s
    def fetchall(s): return s.c.fetchall()
    def fetchone(s): return s.c.fetchone()
    def close(s): pass
db = sqlite3.connect(':memory:')
db.execute("CREATE TABLE draw_history (draw_number INTEGER PRIMARY KEY, numbers TEXT, draw_time TEXT)")
db.execute("CREATE TABLE predictions (id INTEGER PRIMARY KEY, draw_number INTEGER, predicted_numbers TEXT, win_prob REAL, confidence REAL)")
def nap(dn, bo, utc):
    db.execute("INSERT OR REPLACE INTO draw_history VALUES (?,?,?)", (dn, '[%d, %d, %d]' % bo, utc.strftime('%Y-%m-%d %H:%M:%S')))
nap(100, (4, 5, 6), D(2025, 12, 31, 10, 0))        # 17:00 VN 31/12/2025 -> khong nap
nap(101, (4, 5, 6), D(2025, 12, 31, 22, 0))        # 05:00 VN 01/01 -> nap
for i in range(300):
    nap(1000 + i, (1, 2, 3) if i % 3 else (4, 5, 6), D(2026, 11, 20, 0, 0) + timedelta(minutes=6 * i))
db.commit()
B = SB.BoNhoKy()
NOW = D(2026, 11, 20, 10, 0)
B.cap_nhat(_Cur(db), NOW)
kiem("nap dau: tu 01/01 gio VN (bo 31/12 truoc 00:00 VN)", 101 in B.ky and 100 not in B.ky and len(B.ky) == 301, len(B.ky))
kiem("luu bo da sap xep + gio", B.ky[1000] == ((4, 5, 6), '2026-11-20 00:00:00'), B.ky[1000])
nap(1300, (1, 1, 2), D(2026, 11, 20, 6, 0)); nap(1250, (6, 6, 6), D(2026, 11, 20, 5, 0)); db.commit()
B.ky.pop(1250, None)
B.cap_nhat(_Cur(db), NOW + timedelta(minutes=6))
kiem("doc them: ky moi + ky vua bu (trong 400 ky cuoi)", B.ky.get(1300, ((),))[0] == (1, 1, 2) and B.ky[1250][0] == (6, 6, 6))
db.execute("DELETE FROM draw_history WHERE draw_number = 101"); db.commit()
B.cap_nhat(_Cur(db), NOW + timedelta(hours=25))
kiem("qua 24 gio -> nap lai toan bo (ky da xoa bien mat)", 101 not in B.ky and 1300 in B.ky)
tin = B.tin((4, 5, 6), 1300, NOW)
kiem("tin tu bo nho dem: 2 dong + tieu de", len(tin) == 3 and 'Sau 4-5-6' in tin[0], tin)
nap(5000, (2, 2, 2), D(2026, 12, 31, 18, 0)); db.commit()       # 01:00 VN 01/01/2027
B.cap_nhat(_Cur(db), D(2026, 12, 31, 18, 30))
kiem("sang nam: nap lai, van giu 31 ngay truoc cho khung 30 ngay", B.nam == 2027 and 5000 in B.ky and 1000 not in B.ky, (B.nam, sorted(B.ky)[:3]))

print("=== 3. GAN VAO TIN MOI KY CUA WATCHER ===")
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'x'); os.environ.setdefault('TELEGRAM_CHAT_ID', 'x')
import sync_to_supabase as S
class _Conn:
    def cursor(s): return _Cur(db)
    def rollback(s): pass
    def commit(s): db.commit()
db2 = sqlite3.connect(':memory:'); db = db2
db.execute("CREATE TABLE draw_history (draw_number INTEGER PRIMARY KEY, numbers TEXT, draw_time TEXT)")
db.execute("CREATE TABLE predictions (id INTEGER PRIMARY KEY, draw_number INTEGER, predicted_numbers TEXT, win_prob REAL, confidence REAL)")
goc = D.utcnow() - timedelta(hours=10)
seq = [(1, 2, 3), (4, 5, 6), (5, 5, 5), (1, 3, 5), (4, 5, 6), (1, 1, 2), (2, 4, 6), (4, 5, 6)]
for i, bo in enumerate(seq):
    nap(500 + i, bo, goc + timedelta(minutes=6 * i))
db.commit()
DN = 500 + len(seq) - 1
S._BO_NHO_KY = SB.BoNhoKy()
dl = S.doc_du_lieu_tin_ky(_Conn(), DN)
kiem("doc_du_lieu_tin_ky co phan 'sau_bo'", 'sau_bo' in dl and 'Sau 4-5-6' in dl['sau_bo'][0], dl.get('sau_bo'))
html, _ = S.soan_tin_ky(DN, [6, 4, 5], dl)
print('    ' + html.replace('\n', '\n    '))
kiem("tin kỳ: 4-5-6 truoc do ve 555 va Tong 4", '555 (' in html and 'Tổng 4 (' in html, html)
kiem("phan 'sau bo' nam truoc dong du doan", html.index('📜') < html.index('🔮'))
os.environ['TIN_SAU_BO'] = '0'
S._BO_NHO_KY = SB.BoNhoKy()
kiem("TIN_SAU_BO=0 -> tat", 'sau_bo' not in S.doc_du_lieu_tin_ky(_Conn(), DN))
os.environ.pop('TIN_SAU_BO')
class _Hong(SB.BoNhoKy):
    def cap_nhat(self, *a, **k): raise RuntimeError('DB chet giua chung')
S._BO_NHO_KY = _Hong()
dl = S.doc_du_lieu_tin_ky(_Conn(), DN)
kiem("loi phan 'sau bo' -> tin van du phan con lai", 'sau_bo' not in dl and dl['ky'] and '🎯' in S.soan_tin_ky(DN, [6, 4, 5], dl)[0])

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
