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
    """ky: [(dn, datetime)] bat ky thu tu. Ky co gio KHONG tang dan (som hon ky
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
    """Doc `lookback` ky gan nhat, sua gio ky ghi sai. Caller commit (neu can)."""
    cur.execute(f"SELECT draw_number, draw_time FROM {table} ORDER BY draw_number DESC LIMIT {ph}",
                (lookback,))
    sua = tim_gio_le(cur.fetchall())
    for dn, _, moi in sua:
        cur.execute(f"UPDATE {table} SET draw_time = {ph} WHERE draw_number = {ph}",
                    (moi.strftime('%Y-%m-%d %H:%M:%S'), dn))
    return sua
