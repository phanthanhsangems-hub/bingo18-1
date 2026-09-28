"""P244: /api/tong/vang-lau-nhat — tong vang lau nhat bao nhieu ky."""
import os, sys
from unittest import mock
os.environ.setdefault('DATABASE_URL', '')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as A

DAT = HONG = 0
def kiem(ten, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {ten}" + ('' if ok else f"  -> {ct}"))

# tong 4 ra o ky 100, 105, 106, 120 (du lieu lien tuc) -> vang 4, 0, 13
rows = [(d, 4 if d in (100, 105, 106, 120) else 10, f'2026-09-01 00:{d-100:02d}') for d in range(100, 125)]
r = A._vang_theo_tong(rows)
t4 = r['4']
kiem("so lan", t4['so_lan'] == 4, t4)
kiem("vang lau nhat = 13 ky", t4['vang_lau_nhat']['so_ky'] == 13, t4)
kiem("dung khoang 106 -> 120", (t4['vang_lau_nhat']['tu_ky'], t4['vang_lau_nhat']['den_ky']) == (106, 120))
kiem("dang vang = 4 ky (121..124)", t4['dang_vang'] == 4, t4['dang_vang'])
kiem("top xep giam dan", [k['so_ky'] for k in t4['top']] == [13, 4, 0])
kiem("tong chua ra lan nao -> None, khong chet", r['3']['vang_lau_nhat'] is None and r['3']['dang_vang'] == 25)
kiem("du 16 tong", sorted(map(int, r)) == list(range(3, 19)))

# DB thieu ky 110..114: so ky that 8, theo so ky 13 -> phai lech de lo ra
thung = [x for x in rows if not 110 <= x[0] <= 114]
v = A._vang_theo_tong(thung)['4']['vang_lau_nhat']
kiem("thieu ky -> so_ky dem ky that (8)", v['so_ky'] == 8, v)
kiem("... va theo_so_ky van la 13 de lo lech", v['theo_so_ky'] == 13, v)

class C:
    def execute(s, q, *a): s.q = q
    def fetchall(s): return [(d, None if d == 101 else t, str([1,1,2]) if t == 4 else str([3,3,4]), dt) for d, t, dt in rows]
class K:
    def cursor(s): return C()
    def close(s): pass
with mock.patch.object(A.db, 'get_connection', return_value=K()):
    res = A.app.test_client().get('/api/tong/vang-lau-nhat')
d = res.get_json()
kiem("endpoint 200", res.status_code == 200, res.status_code)
kiem("endpoint tra tong 4 vang 13", d['tong']['4']['vang_lau_nhat']['so_ky'] == 13, d)
kiem("sum_value NULL -> tinh tu numbers", d['tong_so_ky'] == 25, d.get('tong_so_ky'))
kiem("dang ky vao bo quet", '/api/tong/vang-lau-nhat' in open('scripts/endpoints_readonly.txt', encoding='utf-8').read())

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
