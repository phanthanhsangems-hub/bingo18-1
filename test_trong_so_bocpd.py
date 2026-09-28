"""P240: giam trong so phieu SIZE cua regime_bocpd + tinh lai luot bau.

Nguoi dung: sang 28/09 16/16 du doan NHO; nhat ky phieu cho thay regime_bocpd
bau NHO 16/16. Nguoi dung chon giam trong so no.
"""
import os, sys, random, json, logging, subprocess
os.environ.setdefault('DATABASE_URL', ''); os.environ.pop('APP_USER', None)
logging.disable(logging.CRITICAL)
import pandas as pd, yaml
from unittest import mock
from collections import Counter
import prediction_service as PS

DAT = HONG = 0
def kiem(ten, dk, ct=''):
    global DAT, HONG
    if dk: DAT += 1; print(f"  DAT  {ten}")
    else:  HONG += 1; print(f"  HONG {ten}" + (f"  -> {ct}" if ct else ''))

print("=== 1. HE SO ===")
kiem("regime_bocpd x0.5", PS._VOTER_SCALE.get('regime_bocpd') == 0.5, str(PS._VOTER_SCALE))
kiem("voter khac khong bi doi", all(k == 'regime_bocpd' for k in PS._VOTER_SCALE))

def chuoi(scale, n=120, seed=3):
    rnd = random.Random(seed)
    draws = [[rnd.randint(1, 6) for _ in range(3)] for _ in range(300 + n)]
    PS._sw_ema = {}
    cu = dict(PS._VOTER_SCALE); PS._VOTER_SCALE.clear(); PS._VOTER_SCALE.update({'regime_bocpd': scale})
    ra = []
    try:
        for t in range(300, 300 + n):
            hist = draws[:t][::-1][:300]
            df = pd.DataFrame([{'draw_number': t - i, 'numbers': str(h)} for i, h in enumerate(hist)])
            sel = mock.MagicMock(); sel.get_model.return_value = None
            nums, _, vb = PS._run_majority_vote(df, t + 1, mock.MagicMock(), sel, mock.MagicMock(),
                                                mock.MagicMock(), set(), sum(hist[0]))
            ra.append((t + 1, nums, vb))
    finally:
        PS._VOTER_SCALE.clear(); PS._VOTER_SCALE.update(cu)
    return ra

print("\n=== 2. HE SO CO TAC DUNG THAT (goi _run_majority_vote) ===")
a = chuoi(1.0); b = chuoi(0.5)
nho = lambda r: sum(1 for _, _, v in r if v['majority_size'] == 'NHO')
kiem("giam trong so bocpd -> NHO it hon", nho(b) < nho(a), f"x1.0: {nho(a)}/120  x0.5: {nho(b)}/120")
d = b[-1][2]['all_votes_detail'].get('regime_bocpd')
if d:
    kiem("detail ghi scale 0.5", d.get('scale') == 0.5)
    kiem("mult KHONG gom scale (de tinh lai duoc)", 'mult' in d)
else:
    kiem("bocpd co bo phieu trong mau thu", False, "khong co phieu bocpd")

print("\n=== 3. BUOC DIAGNOSE TAI HIEN DUNG ===")
P = []
for dn, nums, vb in b:
    P.append({'draw_number': dn, 'created_at': '2026-09-28 01:00:00', 'numbers': nums,
              'majority_size': vb['majority_size'], 'final_size': vb['majority_size'],
              'size_flipped': None, 'size_weights': vb['size_weights'], 'all_votes': vb['all_votes'],
              'detail': {k: {'size': x['size'], 'conf': x['conf'], 'mult': x['mult'],
                             'scale': x.get('scale', 1.0)} for k, x in vb['all_votes_detail'].items()},
              'nho_share_min': (vb.get('adaptive') or {}).get('nho_share_min'),
              'bocpd_dist': vb.get('bocpd_dist')})
P.reverse()
json.dump({'n': len(P), 'predictions': P}, open('/tmp/vl.json', 'w'))
w = yaml.safe_load(open('.github/workflows/diagnose.yml'))
st = [x for j in w['jobs'].values() for x in j['steps'] if 'P239' in x.get('name', '')][0]
py = st['run'].split("<<'PYEOF'\n", 1)[1].split("\nPYEOF", 1)[0]
r = subprocess.run([sys.executable, '-c', py], capture_output=True, text=True)
kiem("buoc diagnose chay khong loi", r.returncode == 0, r.stderr[-300:])
kiem("tai hien khop 100%", 'khop 120/120 = 100.0%' in r.stdout,
     [l for l in r.stdout.split('\n') if 'khop' in l][:1])
kiem(f"tinh lai o x0.5 = dung SIZE that da chon ({nho(b)}/120 NHO)",
     f"NHO {nho(b)*100/120:5.1f}%" in [l for l in r.stdout.split('\n') if 'x0.5' in l][0])
kiem(f"tinh lai o x1.0 = dung chuoi chay that o x1.0 ({nho(a)}/120 NHO)",
     f"NHO {nho(a)*100/120:5.1f}%" in [l for l in r.stdout.split('\n') if 'x1.0' in l][0],
     [l for l in r.stdout.split('\n') if 'x1.0' in l])

print("\n=== 4. /api/vote-log TRA DETAIL ===")
import app as A
A.limiter.enabled = False
vb = json.dumps({'majority_size': 'NHO', 'all_votes_detail': {'regime_bocpd': {'size': 'NHO', 'conf': 0.3, 'mult': 1.2, 'scale': 0.5}},
                 'adaptive': {'nho_share_min': 0.33}, 'bocpd_dist': {'NHO': 0.7, 'LON': 0.3}})
class C:
    def execute(s, *a): pass
    def fetchall(s): return [(1, '[1,2,3]', vb, '2026-09-28 01:00:00')]
class K:
    def cursor(s): return C()
    def close(s): pass
with mock.patch.object(A.db, 'get_connection', return_value=K()):
    p0 = A.app.test_client().get('/api/vote-log?n=1').get_json()['predictions'][0]
kiem("co detail conf/mult/scale", p0['detail']['regime_bocpd'] == {'size': 'NHO', 'conf': 0.3, 'mult': 1.2, 'scale': 0.5})
kiem("nho_share_min lay tu khoa 'adaptive'", p0['nho_share_min'] == 0.33)
kiem("co bocpd_dist", p0['bocpd_dist'] == {'NHO': 0.7, 'LON': 0.3})

print("\n" + "=" * 54)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
