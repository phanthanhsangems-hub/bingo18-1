"""P299: tin mỗi kỳ — "bộ VỪA RA: các lần trước bộ này ra thì kỳ NGAY SAU có về
Tổng 4 / Tổng 17 / trip nào không" (người dùng hỏi 20/11/2026).

Kỳ ngay sau = #kỳ + 1 (thiếu trong DB thì bỏ qua lần đó). Hai khung:
  - 30 ngày (30 x 159 kỳ): liệt kê từng lần kèm ngày giờ — đúng kiểu danh sách người
    dùng hay đọc ("bộ nào ra trước trip / tổng 4, 17");
  - từ 01/01: chỉ đếm, kèm kỳ vọng (kv) — để thấy số lần có lệch ngẫu nhiên hay không.
Đo cả năm 2026: kỳ trước KHÔNG báo hiệu trip / tổng (p = 0,21-0,54) — số liệu tham khảo.

Module thuần + bộ nhớ đệm kỳ cho watcher: nạp một lần (~50 nghìn kỳ), mỗi kỳ chỉ đọc
thêm ~400 kỳ cuối (bắt cả kỳ vừa bù) -> không tăng lưu lượng Supabase đáng kể.
"""
import os
from collections import Counter
from datetime import datetime, timedelta

KY_30_NGAY = 30 * 159
LECH_VN = timedelta(hours=7)
NAP_LAI_SAU = timedelta(hours=24)          # nạp lại toàn bộ mỗi ngày (bắt kỳ bù cũ)
DOC_THEM = 400                             # mỗi lần cập nhật đọc lại ngần này kỳ cuối
TOI_DA_GIO = 3                             # mỗi loại liệt kê tối đa ngần này mốc giờ (mới nhất)
P_SAU = {'T4': 3 / 216, 'T17': 3 / 216, 'trip': 6 / 216}


def bat() -> bool:
    """Tắt bằng biến môi trường TIN_SAU_BO=0."""
    return os.environ.get('TIN_SAU_BO', '1').strip() not in ('0', 'false', 'no', 'off')


def loai_sau(bo):
    """'T4' | 'T17' | '111'..'666' | None. (1-1-2 là tổng 4 duy nhất, 5-6-6 là tổng 17
    duy nhất; trip 111/666 có tổng 3/18 nên không trùng.)"""
    if len(bo) != 3:
        return None
    if len(set(bo)) == 1:
        return f"{bo[0]}" * 3
    s = sum(bo)
    return 'T4' if s == 4 else ('T17' if s == 17 else None)


def _luc(x):
    """draw_time (datetime / chuỗi SQLite) -> datetime UTC naive | None."""
    if x is None:
        return None
    if isinstance(x, datetime):
        return x.replace(tzinfo=None)
    try:
        return datetime.strptime(str(x)[:19], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None


def phan_tich(ky: dict, bo: tuple, den: int, moc_nam_utc: datetime) -> dict:
    """ky: {dn: (bo_sorted, luc_utc)}. Xét mọi lần `bo` ra ở kỳ k < den mà kỳ k+1 (<= den)
    có trong DB. Trả số lần + các 'sự kiện' (kỳ sau là T4 / T17 / trip) cho 2 khung."""
    tu_30 = den - KY_30_NGAY
    n30, sk30, nnam, dem_nam = 0, [], 0, Counter()
    for k, (b, luc) in ky.items():
        if b != bo or k >= den:
            continue
        sau = ky.get(k + 1)
        if sau is None:
            continue
        l = loai_sau(sau[0])
        if k >= tu_30:
            n30 += 1
            if l:
                sk30.append((k + 1, _luc(sau[1]), l))
        lk = _luc(luc)
        if lk is not None and lk >= moc_nam_utc:
            nnam += 1
            if l:
                dem_nam['trip' if l[0].isdigit() else l] += 1
    sk30.sort()
    return {'n30': n30, 'sk30': sk30, 'nnam': nnam, 'dem_nam': dem_nam}


def _gio(luc) -> str:
    return (luc + LECH_VN).strftime('%d/%m %H:%M') if luc else '?'


def _muc(ten: str, ds: list) -> str:
    """'<b>333</b> 🔁3 (11/11 21:12 · 18/11 17:18 · 20/11 12:42)' — ra >= 2 lần thì in đậm + 🔁N."""
    n = len(ds)
    moc = [_gio(l) for _, l, _ in ds[-TOI_DA_GIO:]]
    them = f" +{n - TOI_DA_GIO}" if n > TOI_DA_GIO else ''
    nhan = f"<b>{ten}</b> 🔁{n}" if n >= 2 else ten
    return f"{nhan} ({' · '.join(moc)}{them})"


def dong_tin(bo: tuple, kq: dict, nam: int) -> list:
    """Các dòng HTML cho tin mỗi kỳ."""
    ten_bo = '-'.join(map(str, bo))
    dong = [f"📜 <b>Sau {ten_bo}</b> — kỳ ngay sau các lần {ten_bo} ra:"]
    nhom = {}
    for e in kq['sk30']:
        nhom.setdefault(e[2], []).append(e)
    phan = []
    for khoa, ten in (('T4', 'Tổng 4'), ('T17', 'Tổng 17')):
        phan.append(_muc(ten, nhom[khoa]) if khoa in nhom else f"{ten}: chưa")
    trip = [_muc(k, nhom[k]) for k in sorted(nhom) if k[0].isdigit()]
    phan.append("Trip: " + (' · '.join(trip) if trip else 'chưa'))
    dong.append(f"• 30 ngày ({ten_bo} ra {kq['n30']} lần): " + ' · '.join(phan))
    n, d = kq['nnam'], kq['dem_nam']
    if n:
        kv = {k: n * p for k, p in P_SAU.items()}
        dong.append(f"• Từ 01/01/{nam} (ra {n} lần): Tổng 4 {d['T4']} (kv {kv['T4']:.0f}) · "
                    f"Tổng 17 {d['T17']} (kv {kv['T17']:.0f}) · Trip {d['trip']} (kv {kv['trip']:.0f})")
    return dong


class BoNhoKy:
    """Bộ nhớ đệm {dn: (bo, luc_utc)} từ min(01/01 giờ VN, 31 ngày trước) tới nay."""

    def __init__(self):
        self.ky = {}
        self.nam = None
        self.nap_luc = None

    def moc_nam_utc(self, nam: int) -> datetime:
        return datetime(nam, 1, 1) - LECH_VN

    def cap_nhat(self, cur, bay_gio_utc: datetime = None, ph: str = '%s') -> None:
        from lap_lai import parse_bo
        now = bay_gio_utc or datetime.utcnow()
        nam = (now + LECH_VN).year
        if self.nam != nam or self.nap_luc is None or now - self.nap_luc > NAP_LAI_SAU or not self.ky:
            tu = min(self.moc_nam_utc(nam), now - timedelta(days=31))
            cur.execute(f"SELECT draw_number, numbers, draw_time FROM draw_history WHERE draw_time >= {ph}",
                        (tu.strftime('%Y-%m-%d %H:%M:%S'),))
            self.ky, self.nam, self.nap_luc = {}, nam, now
        else:
            cur.execute(f"SELECT draw_number, numbers, draw_time FROM draw_history WHERE draw_number > {ph}",
                        (max(self.ky) - DOC_THEM,))
        for dn, nums, luc in cur.fetchall():
            b = parse_bo(nums)
            if len(b) == 3:
                self.ky[int(dn)] = (b, luc)

    def tin(self, bo: tuple, den: int, bay_gio_utc: datetime = None) -> list:
        now = bay_gio_utc or datetime.utcnow()
        nam = (now + LECH_VN).year
        return dong_tin(bo, phan_tich(self.ky, bo, den, self.moc_nam_utc(nam)), nam)
