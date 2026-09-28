"""P239: bo DANH DAU cua voter chi-bau-SIZE lot ra lam du doan 1-1-1.

Nguoi dung chup du doan 1-1-1 luc 07:00 28/09, ngay sau P237. Voter chi bau
SIZE (prior_nho, regime_bocpd...) dung bo danh dau co dinh; hai voter cung
bau NHO la "dong thuan" tren [1,1,1]. _STRUCTURAL_BANS truoc day vo tinh che
loi nay; P237 go cam la no lo ra.
"""
import os, re, sys, random, logging, json
os.environ.setdefault('DATABASE_URL', ''); os.environ.pop('APP_USER', None)
logging.disable(logging.CRITICAL)
import pandas as pd
from unittest import mock
from collections import Counter
import prediction_service as PS

DAT = HONG = 0
def kiem(ten, dk, ct=''):
    global DAT, HONG
    if dk: DAT += 1; print(f"  DAT  {ten}")
    else:  HONG += 1; print(f"  HONG {ten}" + (f"  -> {ct}" if ct else ''))

src = open('prediction_service.py', encoding='utf-8').read()
L = src.index('def _run_majority_vote'); E = src.index('majority_count = size_tally[majority_size]')
than = src[L:E]

print("=== 1. MOI VOTER DUNG BO DANH DAU CO DINH PHAI NAM TRONG _PLACEHOLDER_VOTERS ===")
# 'nums': [a, b, c] viet thang
co_dinh = set(re.findall(r"'name':\s*'(\w+)',\s*'nums':\s*\[\d", than))
# _xx_nums = [..] if ... else [..]  roi 'name': 'ten', 'nums': _xx_nums
bien = set(re.findall(r"(_\w+_nums)\s*=\s*\[\d", than))
for b in bien:
    co_dinh |= set(re.findall(r"'name':\s*'(\w+)',\s*'nums':\s*" + re.escape(b), than))
kiem(f"tim thay voter co bo danh dau ({len(co_dinh)})", len(co_dinh) >= 5, str(sorted(co_dinh)))
for t in sorted(co_dinh):
    kiem(f"{t} nam trong _PLACEHOLDER_VOTERS", t in PS._PLACEHOLDER_VOTERS)
for t in ('num_absence', 'pair_cooc', 'carryover', 'lstm', 'lstm_full'):
    kiem(f"{t} (chon bo THAT) KHONG bi loai", t not in PS._PLACEHOLDER_VOTERS)

def chay(n, seed):
    rnd = random.Random(seed); ra = Counter()
    for _ in range(n):
        rows = [{'draw_number': 200000 - i, 'numbers': str([rnd.randint(1, 6) for _ in range(3)])} for i in range(300)]
        df = pd.DataFrame(rows); df['sum_value'] = [sum(eval(x)) for x in df['numbers']]
        sel = mock.MagicMock(); sel.get_model.return_value = None
        nums, _, _ = PS._run_majority_vote(df, 200001, mock.MagicMock(), sel, mock.MagicMock(),
                                           mock.MagicMock(), set(), sum(eval(rows[0]['numbers'])))
        ra[tuple(sorted(nums))] += 1
    return ra

print("\n=== 2. GOI THAT _run_majority_vote (80 lan) ===")
ra = chay(80, 42)
kiem("1-1-1 KHONG con bi chon hang loat (ban loi: 80/80)", ra[(1, 1, 1)] <= 4, f"{ra[(1,1,1)]}/80")
kiem("du doan co nhieu bo khac nhau", len(ra) >= 8, str(ra.most_common(5)))

print("\n=== 3. _hot_adjust_size KHONG lay bo dau danh sach ===")
rnd = random.Random(5); chon = Counter()
for _ in range(40):
    rows = [{'draw_number': 300000 - i, 'numbers': str(sorted([rnd.randint(1, 3), rnd.randint(1, 3), rnd.randint(1, 3)]))}
            for i in range(40)]                         # toan NHO -> hot_size = NHO
    df = pd.DataFrame(rows)
    nums, note = PS._hot_adjust_size([4, 5, 6], df, 10, set())
    chon[tuple(sorted(nums))] += 1
kiem("co doi sang NHO", all(sum(c) <= 9 for c in chon), str(chon))
kiem("KHONG phai luc nao cung (1,1,1) (ban loi: dem tran -> hoa 0 -> bo dau)",
     chon[(1, 1, 1)] < 40, str(chon.most_common(3)))
kiem("dung _cold_score, khong con dem tran",
     'min(target, key=lambda c: combo_freq.get(c, 0))' not in src)

print("\n=== 4. /api/vote-log ===")
import app as A
A.limiter.enabled = False
vb = json.dumps({'majority_size': 'NHO', 'final_size': 'NHO', 'size_weights': {'NHO': 0.6, 'LON': 0.4},
                 'all_votes': {'prior_nho': 'NHO', 'pair_cooc': 'LON'}})
class C:
    def execute(s, q, *a): s.a = a
    def fetchall(s): return [(188596, '[2, 2, 5]', vb, '2026-09-28 00:18:00'),
                             (188595, '[1, 1, 1]', None, None)]
class K:
    def cursor(s): return C()
    def close(s): pass
with mock.patch.object(A.db, 'get_connection', return_value=K()):
    r = A.app.test_client().get('/api/vote-log?n=5')
d = r.get_json()
kiem("tra 200", r.status_code == 200, str(r.status_code))
p0 = d['predictions'][0]
kiem("co du truong", all(k in p0 for k in ('draw_number', 'created_at', 'numbers', 'pred_size',
                                          'majority_size', 'final_size', 'size_flipped',
                                          'size_weights', 'all_votes')))
kiem("pred_size tinh lai tu bo so (2+2+5=9 -> NHO)", p0['pred_size'] == 'NHO')
kiem("vote_breakdown NULL -> khong chet", d['predictions'][1]['majority_size'] is None)
with mock.patch.object(A.db, 'get_connection', return_value=K()):
    kiem("n rac -> khong 500", A.app.test_client().get('/api/vote-log?n=abc').status_code == 200)
kiem("da dang ky vao bo quet endpoint",
     '/api/vote-log' in open('scripts/endpoints_readonly.txt', encoding='utf-8').read())
dg = open('.github/workflows/diagnose.yml', encoding='utf-8').read()
kiem("diagnose co buoc nhat ky phieu", '/api/vote-log' in dg and 'nhat_ky_phieu' in dg)
kiem("buoc chot bat buoc co moc nhat_ky_phieu", 'cong_dang_nhap nhat_ky_phieu"' in dg)

print("\n" + "=" * 54)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
