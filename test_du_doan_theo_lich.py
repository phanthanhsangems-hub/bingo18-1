"""P297: dự đoán THEO LỊCH khi watcher trễ + che token Telegram trong log.

20/11 07:00-08:19 máy người dùng mất HTTPS -> DB đứng ở #197019 -> vòng dự đoán
toàn "already predicted ahead - skip" -> mất dự đoán 16 kỳ (#197022-#197041).
"""
import io, logging, os, sys
from datetime import datetime as D, timedelta, timezone

os.environ.pop('DATABASE_URL', None)
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'x')
os.environ.setdefault('TELEGRAM_CHAT_ID', 'x')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gio_ky as G

DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))

DAU_2011 = 197011                       # kỳ 06:06 ngày 20/11/2026
print("=== 1. KY SAP QUAY THEO LICH ===")
kiem("05:30 -> ky dau ngay", G.ky_sap_quay(D(2026, 11, 20, 5, 30)) == DAU_2011)
kiem("06:06:00 dang quay -> ky 06:12", G.ky_sap_quay(D(2026, 11, 20, 6, 6)) == DAU_2011 + 1)
kiem("07:15:01 -> #197023 (07:18)", G.ky_sap_quay(D(2026, 11, 20, 7, 15, 1)) == 197023, G.ky_sap_quay(D(2026, 11, 20, 7, 15, 1)))
kiem("21:50 -> ky cuoi ngay 21:54", G.ky_sap_quay(D(2026, 11, 20, 21, 50)) == DAU_2011 + 158)
kiem("21:55 -> ky dau ngay mai", G.ky_sap_quay(D(2026, 11, 20, 21, 55)) == DAU_2011 + 159)
kiem("23:00 -> ky dau ngay mai", G.ky_sap_quay(D(2026, 11, 20, 23, 0)) == DAU_2011 + 159)
kiem("neo 28/10 06:00 -> MOC_KY", G.ky_sap_quay(D(2026, 10, 28, 6, 0)) == G.MOC_KY)

print("=== 2. NEO LICH CO KHOP GIO THAT KHONG ===")
gio_197019 = D(2026, 11, 19, 23, 54)    # 06:54 VN
kiem("dung gio", G.lich_khop(197019, gio_197019))
kiem("ghi tre 3 phut van khop", G.lich_khop(197019, gio_197019 + timedelta(minutes=3)))
kiem("chuoi SQLite cung doc duoc", G.lich_khop(197019, '2026-11-19 23:57:05'))
kiem("datetime co tz cung doc duoc", G.lich_khop(197019, gio_197019.replace(tzinfo=timezone.utc)))
kiem("lech 1 gio -> neo hong", not G.lich_khop(197019, gio_197019 + timedelta(hours=1)))
kiem("lech nguyen 1 ngay (vd nghi Tet) -> neo hong", not G.lich_khop(197019, gio_197019 + timedelta(days=1)))
kiem("ky truoc KY_HIEU_LUC -> khong tin", not G.lich_khop(G.KY_HIEU_LUC - 1, gio_197019))
kiem("khong co gio -> khong tin", not G.lich_khop(197019, None))
kiem("chuoi hong -> khong tin", not G.lich_khop(197019, 'abc'))

print("=== 3. KY CAN DU DOAN ===")
kiem("BINH THUONG (DB kip): None -> giu 'cuoi + 2'",
     G.ky_can_du_doan(D(2026, 11, 20, 7, 15, 1), 197022, D(2026, 11, 20, 0, 12, 40)) is None)
kiem("sang som: ky cuoi hom qua 21:54, 06:00 -> None",
     G.ky_can_du_doan(D(2026, 11, 20, 6, 0, 1), DAU_2011 - 1, D(2026, 11, 19, 14, 54, 30)) is None)
kiem("DB TRE (20/11 07:15, cuoi #197019) -> #197024",
     G.ky_can_du_doan(D(2026, 11, 20, 7, 15, 1), 197019, gio_197019) == 197024)
kiem("tre qua 40 ky (4 gio) -> khong tin lich",
     G.ky_can_du_doan(D(2026, 11, 20, 11, 30), 197019, gio_197019) is None)
kiem("neo hong -> None", G.ky_can_du_doan(D(2026, 11, 20, 7, 15), 197019, gio_197019 + timedelta(hours=2)) is None)
kiem("cuoi = 0 / None -> None", G.ky_can_du_doan(D(2026, 11, 20, 7, 15), 0, None) is None)

print("=== 4. MO PHONG SANG 20/11: DB DUNG O #197019 TU 07:00 DEN 08:19 ===")
du_doan = {197020: D(2026, 11, 19, 23, 48), 197021: D(2026, 11, 19, 23, 57)}   # da co truoc 07:00
last_pred = 197021
t = D(2026, 11, 20, 7, 3, 2)
while t < D(2026, 11, 20, 8, 19):
    k = G.ky_can_du_doan(t, 197019, gio_197019) or 197021
    if last_pred < k:
        du_doan[k] = t - timedelta(hours=7); last_pred = k       # luu gio UTC
    t += timedelta(minutes=6)
def gio_quay_utc(dn):
    return G.gio_lich(dn, G.NGAY_MOC + timedelta(days=G.khoi(dn)))
thieu = [dn for dn in range(197020, 197033) if dn not in du_doan]
kiem("ky #197020 -> #197032 (07:00-08:12) deu co du doan", not thieu, thieu)
muon = [dn for dn in range(197022, 197033) if du_doan.get(dn) and du_doan[dn] >= gio_quay_utc(dn)]
kiem("moi du doan co TRUOC gio quay", not muon, muon)
som = min((gio_quay_utc(dn) - du_doan[dn]).total_seconds() / 60 for dn in range(197022, 197033))
kiem(f"du doan som it nhat ~3 phut truoc gio quay ({som:.0f} phut)", som >= 3, som)

print("=== 5. prediction_service.chon_ky_du_doan ===")
import prediction_service as P
kiem("DB tre -> theo lich", P.chon_ky_du_doan(197019, gio_197019, D(2026, 11, 20, 7, 15, 1)) == 197024)
kiem("binh thuong -> cuoi + 2", P.chon_ky_du_doan(197022, D(2026, 11, 20, 0, 12, 40), D(2026, 11, 20, 7, 15, 1)) == 197024)
kiem("gio hong -> cuoi + 2, khong loi", P.chon_ky_du_doan(197019, object(), D(2026, 11, 20, 7, 15)) == 197021)
kiem("DB rong -> 2", P.chon_ky_du_doan(0, None, D(2026, 11, 20, 7, 15)) == 2)
src = open('prediction_service.py', encoding='utf-8').read()
kiem("vong du doan dung chon_ky_du_doan", 'next_draw = chon_ky_du_doan(last, last_time' in src)

print("=== 6. CHE TOKEN TELEGRAM TRONG LOG ===")
gia = 'bot1234567890:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'      # token GIA, dung de test
import telegram_bot as TB
buf = io.StringIO(); h = logging.StreamHandler(buf); TB.logger.addHandler(h)
TB.logger.error("Telegram send error: %s", f"HTTPSConnectionPool url: /{gia}/sendMessage")
TB.logger.removeHandler(h)
kiem("telegram_bot: token bi che", 'AAAAAAAAAAAAAAAAAAAA' not in buf.getvalue() and 'bot***' in buf.getvalue(), buf.getvalue())
import sync_to_supabase as S
f = S._CheBiMat()
rec = logging.LogRecord('x', logging.WARNING, __file__, 1, "Telegram html: %s", (f"url /{gia}/sendMessage",), None)
f.filter(rec)
kiem("watcher: token bi che", 'AAAAAAAAAAAAAAAAAAAA' not in rec.getMessage() and 'bot***' in rec.getMessage(), rec.getMessage())
kiem("watcher: moi handler deu co bo loc", all(any(isinstance(x, S._CheBiMat) for x in hh.filters)
                                              for hh in logging.getLogger().handlers))
rec = logging.LogRecord('x', logging.INFO, __file__, 1, "Khong co ky moi (last=#%d)", (197019,), None)
f.filter(rec)
kiem("dong log thuong khong bi doi", rec.getMessage() == "Khong co ky moi (last=#197019)", rec.getMessage())


print("=== 7. P298c: KY SAP QUAY CHUA CO DU DOAN -> DU DOAN NO TRUOC ===")
def utc_lich(dn):
    return G.gio_lich(dn, G.NGAY_MOC + timedelta(days=G.khoi(dn)))
CK = P.chon_ky_du_doan
kiem("giay_toi_gio_quay: 13:49:50 -> #197089 (13:54) con 250 giay",
     G.giay_toi_gio_quay(197089, D(2026, 11, 20, 13, 49, 50)) == 250, G.giay_toi_gio_quay(197089, D(2026, 11, 20, 13, 49, 50)))
kiem("20/11 13:49:50 watcher vua chay lai chen #197087, #197089 chua co -> du doan #197089 (truoc day bo qua)",
     CK(197087, utc_lich(197087), D(2026, 11, 20, 13, 49, 50), last_pred=197088) == 197089)
kiem("13:50:20 chen tiep #197088, #197089 da co -> #197090",
     CK(197088, utc_lich(197088), D(2026, 11, 20, 13, 50, 20), last_pred=197089) == 197090)
kiem("20/11 13:03:24 chen #197080 (ghi 13:03), #197081 chua co -> du doan #197081",
     CK(197080, D(2026, 11, 20, 6, 3, 0), D(2026, 11, 20, 13, 3, 24), last_pred=197080) == 197081)
kiem("con < 2 phut toi gio quay -> KHONG du doan ky sap quay (de khoi muon), lam ky sau",
     CK(197087, utc_lich(197087), D(2026, 11, 20, 13, 53, 10), last_pred=197088) == 197090)
kiem("binh thuong (ky cuoi vua quay, ky sap quay da co) -> cuoi + 2 nhu cu",
     CK(197092, utc_lich(197092) + timedelta(seconds=70), D(2026, 11, 20, 14, 13, 30), last_pred=197093) == 197094)
kiem("goi kieu cu (khong co last_pred) -> nhu P297",
     CK(197092, utc_lich(197092), D(2026, 11, 20, 14, 13, 30)) == 197094)
kiem("da du doan toi sap+1 -> tra sap+1 (vong du doan tu skip)",
     CK(197092, utc_lich(197092), D(2026, 11, 20, 14, 13, 30), last_pred=197094) == 197094)
kiem("neo hong -> cuoi + 2, khong dung lich",
     CK(197087, utc_lich(197087) + timedelta(hours=1), D(2026, 11, 20, 13, 49, 50), last_pred=197088) == 197089)
kiem("cuoi ngay 21:55: ky sap quay la 06:06 mai, da co -> cuoi + 2",
     CK(197169, utc_lich(197169) + timedelta(seconds=60), D(2026, 11, 20, 21, 55, 30), last_pred=197170) == 197171)
kiem("vong du doan truyen last_pred", 'chon_ky_du_doan(last, last_time, last_pred=last_pred)' in src)

def mo_phong(co_hen_gio: bool):
    """20/11 13:30-14:40: watcher chen moi ky sau 60 giay, MAT tu 13:36 toi 13:49:50 (luc cai dat)."""
    def T(dn): return utc_lich(dn) + timedelta(hours=7)          # gio quay VN
    chen = {dn: T(dn) + timedelta(seconds=60) for dn in range(197084, 197100)}
    chen[197087] = D(2026, 11, 20, 13, 49, 50); chen[197088] = D(2026, 11, 20, 13, 50, 20)
    su_kien = [(t, 'chen', dn) for dn, t in chen.items()]
    if co_hen_gio:
        t = D(2026, 11, 20, 13, 30, 5)
        while t < D(2026, 11, 20, 14, 40):
            if t.minute % 6 == 3: su_kien.append((t, 'hen_gio', None))
            t += timedelta(minutes=1)
    su_kien.sort()
    db = {dn: chen[dn] for dn in chen if chen[dn] < D(2026, 11, 20, 13, 30)}
    du = {dn: None for dn in range(197080, 197089)}               # da co truoc 13:36
    for t, loai, dn in su_kien:
        if loai == 'chen': db[dn] = t
        co = [k for k in db if db[k] <= t]
        if not co: continue
        cuoi = max(co)
        lp = max(du)
        k = CK(cuoi, utc_lich(cuoi) + timedelta(seconds=60), t, last_pred=lp)
        if lp < k: du[k] = t
    return {dn: (T(dn) - du[dn]).total_seconds() for dn in range(197089, 197098) if du.get(dn)}, \
           [dn for dn in range(197089, 197098) if dn not in du]
for co in (False, True):
    som, thieu = mo_phong(co)
    ten = 'co hen gio tren may' if co else 'KHONG co hen gio (chi watcher, nhu chieu 20/11)'
    kiem(f"mo phong {ten}: #197089-#197097 deu co du doan", not thieu, thieu)
    kiem(f"mo phong {ten}: moi du doan som >= 2 phut truoc gio quay", min(som.values()) >= 120, som)

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
