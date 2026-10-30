"""P283: /api/sua-gio-ky sua ky bu bi ghi 07:00 (00:00 UTC) tren Cloud Run."""
import json, os, sqlite3, sys, tempfile
os.environ.pop('DATABASE_URL', None)
_TMP = os.path.join(tempfile.mkdtemp(), 'sg.db')
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
c = A.app.test_client(); c.get('/api/health')
k = sqlite3.connect(_TMP)
for dn, t in [(193427, '2026-10-28 06:42:14'), (193428, '2026-10-28 00:00:00'), (193429, '2026-10-28 00:00:00'),
              (193430, '2026-10-28 00:00:00'), (193431, '2026-10-28 06:57:00'), (193432, '2026-10-28 00:00:00'),
              (193433, '2026-10-28 07:02:00'), (193434, '2026-10-28 07:06:30')]:
    k.execute("INSERT INTO draw_history (draw_number, draw_time, numbers, size_category, sum_value) "
              "VALUES (?,?,?,?,?)", (dn, t, '[1,2,3]', 'NHO', 6))
k.commit()
A.config.TRIGGER_SECRET = 'bm'
kiem("khong secret -> 403", c.post('/api/sua-gio-ky').status_code == 403)
d = c.post('/api/sua-gio-ky?thu=1', headers={'X-Trigger-Secret': 'bm'}).get_json()
kiem("chi xem: thay 6 ky lech lich", d.get('so_ky_sua') == 6 and d['chi_xem'], d)
kiem("chi xem: KHONG ghi", k.execute("SELECT draw_time FROM draw_history WHERE draw_number=193428").fetchone()[0].startswith('2026-10-28 00:00'))
d = c.post('/api/sua-gio-ky', headers={'X-Trigger-Secret': 'bm'}).get_json()
kiem("sua 6 ky", d.get('so_ky_sua') == 6, d)
gio = [r[0] for r in k.execute("SELECT draw_time FROM draw_history ORDER BY draw_number")]
kiem("gio tang dan sau khi sua", all(b > a for a, b in zip(gio, gio[1:])), gio)
kiem("gio moi dung lich: #193428 = 13:30", any(x['ky'] == 193428 and x['gio_moi_vn'] == '28/10 13:30' for x in d['ky']), d['ky'])
kiem("chay lai -> 0", c.post('/api/sua-gio-ky', headers={'X-Trigger-Secret': 'bm'}).get_json()['so_ky_sua'] == 0)
print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
