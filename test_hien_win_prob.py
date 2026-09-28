"""P247: con so 'tin cay' HIEN RA phai la win_prob (da hieu chinh), khong phai
diem tho 'confidence' (~60%) — va canh bao #47 phai do dung con so do."""
import os, re, sys
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DAT = HONG = 0
def kiem(ten, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {ten}" + ('' if ok else f"  -> {ct}"))

src = open('app.py', encoding='utf-8').read()
def than(ham):
    i = src.index(f'def {ham}(')
    j = src.find('\ndef ', i + 10)
    return src[i:j]

print("=== 1. CHO HIEN RA DUNG win_prob ===")
for ham in ('get_predictions_history', 'daily_card', 'prediction_timeline', 'daily_summary',
            'weekly_leaderboard', '_tg_cmd_predict', '_tg_cmd_explain', '_tg_cmd_recap',
            '_tg_ai_chat', 'recent_outcomes', 'today_draws'):
    t = than(ham)
    tho = re.findall(r'(?<!COALESCE\(p\.win_prob, )p\.confidence(?!\))', t)
    kiem(f"{ham}: dung win_prob", 'win_prob' in t and not tho, tho)

print("\n=== 2. CHO PHAN TICH GIU DIEM THO (can de hieu chinh) ===")
for ham in ('calibration_report', 'confidence_histogram', 'bet_signal'):
    kiem(f"{ham}: van doc confidence tho", 'win_prob' not in than(ham))

print("\n=== 3. CANH BAO #47 DO win_prob ===")
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'x'); os.environ.setdefault('TELEGRAM_CHAT_ID', '1')
import sync_to_supabase as S
S.TELEGRAM_TOKEN, S.TELEGRAM_CHAT = 'x', '1'
def chay(rows):
    q = {}
    class C:
        def execute(s, sql, *a): q['sql'] = sql
        def fetchall(s): return rows
        def close(s): pass
    class K:
        def cursor(s): return C()
    gui = []
    with mock.patch.object(S, '_tg_html', side_effect=gui.append):
        S.check_confidence_gap(K(), {})
    return q.get('sql', ''), gui
sql, gui = chay([(0.39, i % 5 < 2) for i in range(20)])   # 39% vs WR 40%
kiem("doc cot win_prob", 'p.win_prob' in sql and 'p.confidence' not in sql, sql)
kiem("win_prob ~ WR -> KHONG canh bao", not gui, gui)
sql, gui = chay([(0.60, i % 5 < 2) for i in range(20)])   # lech that 20 diem
kiem("lech that > 15% -> VAN canh bao", len(gui) == 1, gui)

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
