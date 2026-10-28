"""P282: /api/today-draws?tu=&den= lay ky theo SO KY (doi chieu mot ngay da qua)."""
import json, os, sqlite3, sys, tempfile
os.environ.pop('DATABASE_URL', None)
_TMP = os.path.join(tempfile.mkdtemp(), 'td.db')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
config.DB_PATH = _TMP
import app as A
DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))
c = A.app.test_client()
c.get('/api/health')
k = sqlite3.connect(_TMP)
for dn, ns, t in [(100, [6, 6, 6], '2026-10-28 03:00:00'), (101, [1, 2, 3], '2026-10-28 00:00:00'),
                  (102, [6, 6, 6], '2026-10-28 03:12:00'), (200, [1, 1, 1], '2026-10-29 03:00:00')]:
    k.execute("INSERT INTO draw_history (draw_number, draw_time, numbers, size_category, sum_value) "
              "VALUES (?,?,?,?,?)", (dn, t, json.dumps(ns), 'LON', sum(ns)))
k.commit()
d = c.get('/api/today-draws?tu=100&den=150').get_json()
kiem("lay dung 3 ky trong khoang (ke ca ky gio lech)", sorted(x['draw_number'] for x in d['draws']) == [100, 101, 102], d)
kiem("tra so", [x['numbers'] for x in sorted(d['draws'], key=lambda x: x['draw_number'])][0] == [6, 6, 6])
kiem("thieu den -> 400", c.get('/api/today-draws?tu=100').status_code == 400)
kiem("khoang qua 400 -> 400", c.get('/api/today-draws?tu=1&den=1000').status_code == 400)
kiem("khong tham so -> van chay (hom nay)", c.get('/api/today-draws').status_code == 200)
print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
