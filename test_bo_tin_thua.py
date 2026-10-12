"""P259: bo tin Telegram noi bo cho dev va tin trung lap. Kiem tra TINH (doc code):
cac cho gui da xoa khong con, cac cho giu lai van con."""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))
ps = open('prediction_service.py', encoding='utf-8').read()
ap = open('app.py', encoding='utf-8').read()
wt = open('sync_to_supabase.py', encoding='utf-8').read()

print("=== 1. prediction_service: da bo ===")
for ten, dau in [("P94 gap alert", "PREDICTION GAP ALERT"), ("streak per-result (STREAK THANG/THUA)", "STREAK THẮNG"),
                 ("WR thap bat thuong", "WIN RATE THẤP BẤT THƯỜNG"), ("P91 WR drop", "WR DROP ALERT"),
                 ("auto-explain", "_send_explain_breakdown"), ("BOCPD", "BOCPD Regime Shift"),
                 ("WATCH gui", "<b>WATCH "), ("CAU TRUNG", "TRÚNG · kỳ"), ("triple cluster", "TRIPLE CLUSTER"),
                 ("triple drought (CR)", "WATCH TRIPLE"), ("pair drought (CR)", "WATCH CẶP ĐÔI"),
                 ("voter drift", "VOTER DRIFT"), ("momentum", "MOMENTUM BIAS"), ("P77 voter reset", "Voter Auto-Reset")]:
    kiem(f"bo: {ten}", dau not in ps, dau)
print("=== 2. prediction_service: giu ===")
kiem("giu WIN STREAK 5/10/20", "WIN STREAK" in ps and "win_streak in (5, 10, 20, 30, 50)" in ps)
kiem("giu THUA LIEN TIEP 5/8/10", "THUA {loss_streak} KỲ LIÊN TIẾP" in ps and "loss_streak in (5, 8, 10)" in ps)
kiem("giu send_result moi ky (gop o P260)", "telegram.send_result(" in ps)
kiem("WATCH van ghi log forward-test", "_alert_mgr.log(db, f'watch_{_lcombo}_{_t}'" in ps)
kiem("khong con telegram.send_message trong khoi WATCH",
     "telegram.send_message" not in ps[ps.index("# Combo→triple forward"):ps.index("logger.info(\"Predicted draw #%d")])

print("=== 3. app.py ===")
for ten in ("_check_lon_excess_alert", "_check_checkpoint_alert", "_check_triple_drought_alert", "_check_size_bias"):
    kiem(f"bo ham {ten}", f"def {ten}(" not in ap and f"{ten}(" not in ap, ten)
for ten in ("_check_sync_lag", "_check_draw_gap_alert", "_check_vang_tong_alert", "_check_lap_lai_alert"):
    kiem(f"giu {ten}", f"def {ten}(" in ap)
kiem("P0 health alert giu", "Bingo18 P0 Alert" in ap)
kiem("daily-summary-evening khong gui nua (tra skipped)", "'skipped': 'P259" in ap)
kiem("daily-summary 23:55 va weekly van gui", "def daily_summary(" in ap and "def weekly_summary(" in ap)

print("=== 4. watcher ===")
for ten in ("check_triple_number", "check_size_bias", "check_wr_alert", "check_confidence_gap", "check_hoa_reeval", "check_draw_gap"):
    kiem(f"bo {ten}", f"def {ten}(" not in wt and f"{ten}(" not in wt, ten)
for ten in ("check_system_health_alert", "check_cold_numbers", "check_and_alert_hot_combo", "check_pair_triple_drought", "check_size_streak"):
    kiem(f"giu {ten}", f"def {ten}(" in wt and f"{ten}(" in wt.split(f"def {ten}(")[0] + wt.split(f"def {ten}(")[1])
kiem("chuoi size bao o 5/8/12", "streak not in (5, 8, 12)" in wt)
kiem("so lanh: 1 lan/dot", "if num in cold_alerted:" in wt)
kiem("cap doi chua ra: chi 9", "for threshold in (9,):" in wt)
kiem("triple chua ra: 50/80 (1 ban duy nhat)", "for threshold in (50, 80):" in wt)

print("=== 5. import duoc ===")
try:
    os.environ.setdefault('DATABASE_URL', '')
    import prediction_service, app  # noqa
    kiem("import prediction_service + app", True)
except Exception as e:
    kiem("import prediction_service + app", False, repr(e))
print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
