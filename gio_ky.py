"""P281/P283: gio ghi cho ky BU lo hong — ham thuan dung chung watcher va Cloud Run.

Trang chi tiet Vietlott va file GitHub chi co NGAY, khong co gio, nen ky bu tung
bi ghi 00:00 UTC = 07:00 sang gio VN (28/10: 13 ky hien 07:00 xen giua chieu).
"""
from datetime import timedelta

KHOANG_PHUT = 6     # phut giua hai ky


def noi_suy(truoc, sau, dn: int):
    """Gio cho ky `dn` tu ky gan nhat phia truoc / phia sau: (dn, datetime) hoac None."""
    if truoc and sau and sau[1] > truoc[1]:
        return truoc[1] + (sau[1] - truoc[1]) * ((dn - truoc[0]) / (sau[0] - truoc[0]))
    if truoc:
        return truoc[1] + timedelta(minutes=KHOANG_PHUT * (dn - truoc[0]))
    if sau:
        return sau[1] - timedelta(minutes=KHOANG_PHUT * (sau[0] - dn))
    return None


def tim_gio_le(ky: list) -> list:
    """KHONG DUNG NUA (P284: gay lech day chuyen) — giu cho test cu.
    ky: [(dn, datetime)] bat ky thu tu. Ky co gio KHONG tang dan (som hon ky
    truoc no) = gio ghi sai. Tra [(dn, gio_cu, gio_moi)] da noi suy, cu -> moi."""
    ky = sorted(ky)
    sua = []
    for i in range(1, len(ky)):
        if ky[i][1] > ky[i - 1][1]:
            continue
        sau = next((x for x in ky[i + 1:] if x[1] > ky[i - 1][1]), None)
        moi = noi_suy(ky[i - 1], sau, ky[i][0])
        if not moi:
            continue
        sua.append((ky[i][0], ky[i][1], moi))
        ky[i] = (ky[i][0], moi)
    return sua


def sua_gio_le(cur, table: str = 'draw_history', ph: str = '%s', lookback: int = 300) -> list:
    """Doc `lookback` ky gan nhat, dua gio ky lech ve DUNG LICH (P284 — khong con
    dung tim_gio_le). Caller commit (neu can)."""
    cur.execute(f"SELECT draw_number, draw_time FROM {table} ORDER BY draw_number DESC LIMIT {ph}",
                (lookback,))
    sua = sua_theo_lich(cur.fetchall())
    for dn, _, moi in sua:
        cur.execute(f"UPDATE {table} SET draw_time = {ph} WHERE draw_number = {ph}",
                    (moi.strftime('%Y-%m-%d %H:%M:%S'), dn))
    return sua


# ── P284: gio THEO LICH QUAY ────────────────────────────────────────────
# Cach "gio phai tang dan" o tren (P281) GAY HAI: mot ky bi ghi MUON (watcher
# dung roi bat kip — #193682 that 07:06 bi ghi 09:01 ngay 30/10) lam moi ky DUNG
# gio phia sau bi coi la "som hon ky truoc" va bi day len -> ca ngay lech +1h55.
# Lich quay thi co dinh: moi ngay dung 159 ky, ky dau 06:06, cach 6 phut, ky cuoi
# 21:54 (GitHub: 89/90 ngay tu 01/08 dung 159 ky; ngay con lai la GitHub thieu
# ky). Ky dau ngay 28/10/2026 la #193354 -> vi tri trong ngay = (dn - MOC) % 159.
MOC_KY = 193354
KY_MOI_NGAY = 159
# Neo dung tu ngay 03/04/2026 (#160282). 02/04 chi quay 141 ky nen truoc do lech 14
# vi tri. Ky cu hon -> khong sua theo lich.
KY_HIEU_LUC = 160282
# Mot khoi (ngay) chi sua khi co it nhat ngan nay ky DANG dung lich: watcher ghi
# luc phat hien nen ky ghi song luon trung lich; neu sau nay co ngay quay thieu
# ky lam lech neo thi se khong con ky nao trung -> bo qua thay vi sua sai.
KY_DUNG_TOI_THIEU = 2
GIO_KY_DAU_VN = (6, 6)          # 06:06 gio VN
LECH_VN = timedelta(hours=7)
NGUONG_PHUT = 4                 # watcher ghi luc phat hien: tre 0-2 phut la binh thuong


def vi_tri(dn: int) -> int:
    return (dn - MOC_KY) % KY_MOI_NGAY


def khoi(dn: int) -> int:
    """So thu tu 'ngay quay' (khoi 159 ky) cua ky dn."""
    return (dn - MOC_KY) // KY_MOI_NGAY


def gio_lich(dn: int, ngay_vn):
    """Gio UTC (naive) theo lich cua ky dn, biet ngay VN (date) cua no."""
    from datetime import datetime as _dt
    h, m = GIO_KY_DAU_VN
    vn = _dt(ngay_vn.year, ngay_vn.month, ngay_vn.day, h, m) + timedelta(minutes=KHOANG_PHUT * vi_tri(dn))
    return vn - LECH_VN


def sua_theo_lich(ky: list, nguong_phut: int = NGUONG_PHUT) -> list:
    """ky: [(dn, datetime UTC naive)]. Ngay VN cua moi khoi 159 ky = ngay chiem
    da so trong khoi (ky ghi sai gio thuong van cung ngay: 07:00, +1h55...).
    Khoi khong co ngay nao chiem > 1/2, hoac it hon KY_DUNG_TOI_THIEU ky dang
    trung lich (tru khi ngay lien truoc da tin duoc va du 159 ky), thi bo qua.
    Tra [(dn, gio_cu, gio_moi)] cho ky lech lich qua `nguong_phut`."""
    from collections import Counter, defaultdict
    theo_khoi = defaultdict(list)
    for dn, t in ky:
        if t is not None and dn >= KY_HIEU_LUC:
            theo_khoi[khoi(dn)].append((dn, t))
    sua = []
    tin_truoc = None        # (so khoi, ngay) cua khoi lien truoc DA tin duoc va du 159 ky
    for b, ds in sorted(theo_khoi.items()):
        dem = Counter((t + LECH_VN).date() for _, t in ds)
        ngay, n = dem.most_common(1)[0]
        if n * 2 <= len(ds):
            tin_truoc = None
            continue
        dung = sum(1 for dn, t in ds if abs((t - gio_lich(dn, ngay)).total_seconds()) <= nguong_phut * 60)
        # Ngay hom truoc dung neo va du 159 ky (khong quay thieu) -> neo hom nay
        # chac chan con dung, ke ca khi ca ngay bi ghi lech (30/10: 0/159 ky trung lich).
        noi_tiep = tin_truoc is not None and tin_truoc[0] == b - 1 and tin_truoc[1] < ngay
        if dung < KY_DUNG_TOI_THIEU and not noi_tiep:
            tin_truoc = None
            continue
        tin_truoc = (b, ngay) if len(ds) == KY_MOI_NGAY else None
        for dn, t in sorted(ds):
            moi = gio_lich(dn, ngay)
            if abs((t - moi).total_seconds()) > nguong_phut * 60:
                sua.append((dn, t, moi))
    return sua


def gio_cho_ky_bu(dn: int, truoc, sau):
    """Gio cho ky BU dn: theo lich, lay ngay tu ky ke ben CUNG khoi; khong co thi
    noi suy. truoc/sau: (dn, datetime) hoac None."""
    if dn >= KY_HIEU_LUC:
        for ke in (truoc, sau):
            if ke and khoi(ke[0]) == khoi(dn):
                return gio_lich(dn, (ke[1] + LECH_VN).date())
    return noi_suy(truoc, sau, dn)
