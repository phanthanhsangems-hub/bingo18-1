"""P257: endpoint dashboard hay bi goi dong thoi phai co cache ngan, de nhieu luot
goi cung luc chi ton 1 truy van (Supabase bi ket 65s khi dashboard goi don)."""
import os, re, sys
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py'), encoding='utf-8').read()
DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))
for route, fn in [('/api/number_frequency', 'get_number_frequency'), ('/api/draw-grid', 'draw_grid'),
                  ('/api/learning-status', 'learning_status'), ('/api/wl-streak', 'wl_streak'),
                  ('/api/watch-scoreboard', 'watch_scoreboard'), ('/api/cold-streaks', 'cold_streaks'),
                  ('/api/today-combos', 'today_combos')]:
    m = re.search(r"@app\.route\('%s'\)\n((?:@[^\n]+\n)+)def %s\(" % (re.escape(route), fn), src)
    kiem(f"{route} co @cache_resp", bool(m) and '@cache_resp(' in m.group(1), m.group(1) if m else 'khong tim thay')
    t = re.search(r'ttl=(\d+)', m.group(1)) if m else None
    kiem(f"{route} ttl <= 60s (khong lam dashboard cu qua lau)", bool(t) and int(t.group(1)) <= 60)
print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
