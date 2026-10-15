"""P270: ngày có trip thì số trip nằm trong nhóm NÓNG hay LẠNH của chính ngày đó?

Bẫy đã tránh: trip tự thêm 3 lần cho số của nó, nên nếu đếm cả kỳ trip thì số trip
luôn "nóng" một cách máy móc. Ở đây chỉ đếm các KỲ KHÁC trong cùng ngày (VN), loại
kỳ trip ra. Đối chứng: 5 số còn lại của cùng ngày, cũng đếm theo cách đó.

Nóng  = số có nhiều lần nhất trong 2 vị trí đầu (top 2 trong 6)
Lạnh  = số có ít lần nhất trong 2 vị trí cuối (bottom 2 trong 6)
Dưới giả thuyết ngẫu nhiên, mỗi nhóm chiếm 1/3.
"""
import math
from collections import defaultdict


def wilson(k, n, z=1.96):
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    tam = (p + z * z / (2 * n)) / den
    nua = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, tam - nua), min(1.0, tam + nua))


def phan_loai(dem: dict, v: int) -> str:
    """dem: {số: số lần trong các kỳ khác cùng ngày}. Trả 'NONG', 'LANH' hoặc 'GIUA'."""
    cv = dem[v]
    hon = sum(1 for u in dem if dem[u] > cv)      # số nào nhiều hơn v
    kem = sum(1 for u in dem if dem[u] < cv)      # số nào ít hơn v
    if hon <= 1:
        return 'NONG'
    if kem <= 1:
        return 'LANH'
    return 'GIUA'


def phan_tich(rows: list) -> dict:
    """rows: [(dn, bo_sorted_tuple, ngay_vn 'YYYY-MM-DD')] cũ→mới.
    Trả tỷ lệ NÓNG/LẠNH của số trip so với 5 số còn lại cùng ngày."""
    theo_ngay = defaultdict(list)
    for dn, bo, ngay in rows:
        theo_ngay[ngay].append((dn, bo))

    trip_nong = trip_lanh = trip_tong = 0
    dh_nong = dh_lanh = dh_tong = 0          # đối chứng: số không trip cùng ngày
    so_ngay_co_trip = 0
    for ngay, ds in theo_ngay.items():
        trips = [(dn, bo[0]) for dn, bo in ds if len(set(bo)) == 1]
        if not trips:
            continue
        so_ngay_co_trip += 1
        for dn_trip, v in trips:
            # đếm các kỳ KHÁC trong ngày; bỏ tất cả kỳ trip (kể cả trip khác cùng ngày)
            dem = {u: 0 for u in range(1, 7)}
            for dn, bo in ds:
                if len(set(bo)) == 1:
                    continue
                for x in bo:
                    dem[x] += 1
            # nếu ngày không đủ kỳ không-trip thì bỏ
            if sum(dem.values()) < 30:
                continue
            nhan = phan_loai(dem, v)
            trip_tong += 1
            trip_nong += nhan == 'NONG'
            trip_lanh += nhan == 'LANH'
            for u in range(1, 7):
                if u == v:
                    continue
                n2 = phan_loai(dem, u)
                dh_tong += 1
                dh_nong += n2 == 'NONG'
                dh_lanh += n2 == 'LANH'
    return {
        'so_ngay': len(theo_ngay), 'so_ngay_co_trip': so_ngay_co_trip,
        'trip': {'n': trip_tong, 'nong': trip_nong, 'lanh': trip_lanh,
                 'ty_le_nong': round(trip_nong / trip_tong, 4) if trip_tong else None,
                 'ty_le_lanh': round(trip_lanh / trip_tong, 4) if trip_tong else None,
                 'khoang_nong': [round(x, 4) for x in wilson(trip_nong, trip_tong)],
                 'khoang_lanh': [round(x, 4) for x in wilson(trip_lanh, trip_tong)]},
        'doi_chung': {'n': dh_tong, 'nong': dh_nong, 'lanh': dh_lanh,
                      'ty_le_nong': round(dh_nong / dh_tong, 4) if dh_tong else None,
                      'ty_le_lanh': round(dh_lanh / dh_tong, 4) if dh_tong else None},
        'nen_ngau_nhien': round(1 / 3, 4),
    }
