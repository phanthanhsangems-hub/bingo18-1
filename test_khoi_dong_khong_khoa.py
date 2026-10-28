"""P280: Cloud Run mo instance moi KHONG chay DDL khi schema da du (ALTER TABLE
xin AccessExclusiveLock -> ca app dung / deadlock 28/10); watcher autocommit;
watcher ghi ro Vietlott tra loi la."""
import inspect, logging, os, re, sys
from unittest import mock
os.environ.setdefault('DATABASE_URL', '')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database as D
DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))

print("=== 1. DANH SACH KHOP DDL ===")
src = inspect.getsource(D.DatabaseManager.init_database)
pg = src[:src.index('else:  # SQLite')]
bang = set(re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)', pg))
cm = set(re.findall(r'INDEX IF NOT EXISTS (\w+)', pg))
cot = set(re.findall(r'ALTER TABLE (\w+)\s+ADD COLUMN IF NOT EXISTS (\w+)', pg))
kiem("bang", bang == set(D._PG_BANG), bang ^ set(D._PG_BANG))
kiem("chi muc", cm == set(D._PG_CHI_MUC), cm ^ set(D._PG_CHI_MUC))
kiem("cot", cot == set(D._PG_COT), cot ^ set(D._PG_COT))

class Cur:
    def __init__(s, thieu=()):
        s.sql = []; s.thieu = set(thieu); s._r = []
    def execute(s, q, p=None):
        s.sql.append(' '.join(q.split()))
        if 'FROM pg_tables' in q:      s._r = [(b,) for b in D._PG_BANG if b not in s.thieu]
        elif 'FROM pg_indexes' in q:   s._r = [(c,) for c in D._PG_CHI_MUC if c not in s.thieu]
        elif 'information_schema.columns' in q:
            s._r = [c for c in D._PG_COT if c[1] not in s.thieu]
        elif 'FROM pg_views' in q:     s._r = [] if 'predictions_vn' in s.thieu else [(1,)]
        else:                          s._r = []
    def fetchall(s): return s._r
    def fetchone(s): return s._r[0] if s._r else None
class Conn:
    def __init__(s, cur): s.cur = cur; s.commits = 0
    def cursor(s): return s.cur
    def commit(s): s.commits += 1
    def close(s): pass

def chay(thieu=()):
    cur = Cur(thieu); conn = Conn(cur)
    m = D.DatabaseManager.__new__(D.DatabaseManager)
    with mock.patch.object(D, 'USE_POSTGRES', True), \
         mock.patch.object(D.DatabaseManager, 'get_connection', return_value=conn):
        m.init_database()
    return cur.sql, conn
ddl = lambda sql: [q for q in sql if re.match(r'(CREATE|ALTER|DROP|DO )', q)]

print("=== 2. SCHEMA DA DU -> KHONG DDL ===")
sql, conn = chay()
kiem("lock_timeout dat truoc tien", sql[0].startswith("SET LOCAL lock_timeout"), sql[:2])
kiem("khong chay cau DDL nao", not ddl(sql), ddl(sql)[:3])
kiem("van kiem backfill is_win_sum", any('is_win_sum IS NULL' in q for q in sql))
kiem("commit", conn.commits == 1)

print("=== 3. THIEU COT -> CHAY DDL (co lock_timeout) ===")
sql, conn = chay(thieu=('win_prob',))
kiem("co chay ALTER them cot", any('ADD COLUMN IF NOT EXISTS win_prob' in q for q in sql))
kiem("lock_timeout truoc moi DDL", sql.index(ddl(sql)[0]) > 0 and sql[0].startswith('SET LOCAL lock_timeout'))
sql, _ = chay(thieu=('predictions_vn',))
kiem("thieu view -> chay DDL", bool(ddl(sql)))

print("=== 4. WATCHER ===")
import sync_to_supabase as S
with mock.patch('psycopg2.connect') as pc:
    c = S.get_conn()
kiem("get_conn bat autocommit", c.autocommit is True)
class R:
    def __init__(s, code, text=''): s.status_code = code; s.text = text
S._VL_BAO.update(loai=None, luc=0.0)
with mock.patch.object(S, '_session') as ss, mock.patch.object(S.logger, 'warning') as w:
    ss.get.return_value = R(403, 'blocked')
    kq1 = S.fetch_homepage(); kq2 = S.fetch_homepage()
kiem("trang chu 403 -> []", kq1 == [] and kq2 == [])
kiem("ghi canh bao co ma HTTP", w.call_count == 1 and '403' in str(w.call_args), w.call_args_list)
S._VL_BAO.update(loai=None, luc=0.0)
with mock.patch.object(S, '_session') as ss, mock.patch.object(S.logger, 'warning') as w, \
     mock.patch.object(S, '_parse_bingo18', return_value=[]):
    ss.get.return_value = R(200, '<html>doi giao dien</html>')
    S.fetch_homepage()
kiem("200 ma khong doc duoc ky -> canh bao", w.call_count == 1 and 'khong doc duoc' in str(w.call_args))
S._VL_BAO.update(loai=None, luc=0.0)
with mock.patch.object(S, '_session') as ss, mock.patch.object(S.logger, 'warning') as w:
    ss.get.return_value = R(503)
    kq = S.fetch_detail(193422)
kiem("trang ky 503 -> None + canh bao", kq is None and '503' in str(w.call_args), w.call_args_list)

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
