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

print("\n=== 4. /api/predictions CHAY THAT tren VIEW cu (khong co win_prob) ===")
# Loi that sau deploy P247: predictions_vn tao bang SELECT p.* TRUOC khi co
# cot win_prob -> Postgres co dinh danh sach cot -> view khong co cot do -> 500.
# SQLite tu mo rong p.* moi lan nen phai liet ke cot de dung lai dung canh do.
import sqlite3, app as A
k = sqlite3.connect(':memory:')
k.executescript("""
  CREATE TABLE predictions (id INTEGER PRIMARY KEY, draw_number INT, model_name TEXT,
      predicted_numbers TEXT, confidence REAL, prediction_time TEXT);
  CREATE VIEW predictions_vn AS SELECT p.id, p.draw_number, p.model_name, p.predicted_numbers,
      p.confidence, p.prediction_time, p.prediction_time AS full_time_vietnam FROM predictions p;
  ALTER TABLE predictions ADD COLUMN win_prob REAL;
  CREATE TABLE prediction_results (prediction_id INT, actual_numbers TEXT, match_count INT,
      is_win INT, is_win_size INT);
  INSERT INTO predictions VALUES (1, 100, 'majority_vote', '[1,2,3]', 0.61, '2026-09-28', 0.39);
  INSERT INTO predictions VALUES (2, 101, 'majority_vote', '[4,5,6]', 0.60, '2026-09-28', NULL);
""")
kiem("view that su KHONG co win_prob (dung canh loi)",
     'win_prob' not in [r[1] for r in k.execute("PRAGMA table_info(predictions_vn)")])
class KK:
    def cursor(s): return k.cursor()
    def close(s): pass
with mock.patch.object(A.db, 'get_connection', return_value=KK()), \
     mock.patch.object(A.db, '_ph', return_value='?'):
    r = A.app.test_client().get('/api/predictions?limit=5')
d = r.get_json()
kiem("/api/predictions tra 200", r.status_code == 200, (r.status_code, d))
if r.status_code == 200:
    c = {x['draw_number']: x['confidence'] for x in d}
    kiem("co win_prob -> hien 0.39 (khong phai 0.61)", c.get(100) == 0.39, c)
    kiem("chua co win_prob -> lui ve confidence", c.get(101) == 0.60, c)

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
