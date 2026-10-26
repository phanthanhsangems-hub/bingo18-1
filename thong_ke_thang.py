"""P272: đếm tổng và trip trong một tháng (giờ VN)."""
from collections import Counter

# số tổ hợp có thứ tự cho mỗi tổng 3..18 (3 viên, 216 kết quả)
_WAYS = Counter(a + b + c for a in range(1, 7) for b in range(1, 7) for c in range(1, 7))
TONG_QUAN_TAM = (4, 5, 6, 15, 16, 17)


def thong_ke(rows: list, thang: str) -> dict:
    """rows: [(dn, bo_sorted_tuple, ngay_vn 'YYYY-MM-DD')]. thang: 'YYYY-MM'."""
    trong = [(dn, bo) for dn, bo, ngay in rows if ngay[:7] == thang]
    n = len(trong)
    tong = Counter(sum(bo) for _, bo in trong)
    trip = Counter(bo[0] for _, bo in trong if len(set(bo)) == 1)
    dns = sorted(dn for dn, _ in trong)
    thieu = (dns[-1] - dns[0] + 1 - len(dns)) if dns else 0
    return {
        'thang': thang, 'so_ky': n, 'tu_ky': dns[0] if dns else None, 'den_ky': dns[-1] if dns else None,
        'so_ky_thieu_trong_khoang': thieu,
        'tong': {str(t): {'so_lan': tong.get(t, 0), 'ky_vong': round(n * _WAYS[t] / 216, 1),
                          'xac_suat_ly_thuyet': round(_WAYS[t] / 216, 4)} for t in TONG_QUAN_TAM},
        'trip': {f"{v}{v}{v}": {'so_lan': trip.get(v, 0), 'ky_vong': round(n / 216, 1)} for v in range(1, 7)},
        'tong_trip': sum(trip.values()), 'ky_vong_tong_trip': round(n / 36, 1),
    }


def truoc_tong(rows: list, thang: str, cac_tong=(4, 7)) -> dict:
    """P275: với mỗi kỳ trong `thang` ra tổng thuộc `cac_tong`, kỳ NGAY TRƯỚC (đúng
    kỳ -1, thiếu thì None) ra bộ nào. rows: [(dn, bo_sorted_tuple, ngay_vn)].
    Kèm 'nen': tỉ lệ mỗi bộ/tổng trên mọi kỳ của tháng để so xem có lệch không."""
    theo_dn = {dn: bo for dn, bo, _ in rows}
    trong = sorted((dn, bo) for dn, bo, ngay in rows if ngay[:7] == thang)
    n = len(trong)
    nen_bo = Counter(''.join(map(str, bo)) for _, bo in trong)
    nen_tong = Counter(sum(bo) for _, bo in trong)
    out = {'thang': thang, 'so_ky': n}
    for t in cac_tong:
        ds, dem_bo, dem_tong, thieu = [], Counter(), Counter(), 0
        for dn, bo in trong:
            if sum(bo) != t:
                continue
            tr = theo_dn.get(dn - 1)
            if tr is None:
                thieu += 1
            else:
                dem_bo[''.join(map(str, tr))] += 1
                dem_tong[sum(tr)] += 1
            ds.append({'ky': dn, 'bo': ''.join(map(str, bo)),
                       'bo_truoc': ''.join(map(str, tr)) if tr else None,
                       'tong_truoc': sum(tr) if tr else None})
        m = len(ds) - thieu
        out[str(t)] = {
            'so_lan': len(ds), 'thieu_ky_truoc': thieu, 'danh_sach': ds,
            'bo_truoc': [{'bo': b, 'so_lan': c, 'ky_vong': round(m * nen_bo[b] / n, 1) if n else None}
                         for b, c in dem_bo.most_common()],
            'tong_truoc': [{'tong': s, 'so_lan': dem_tong.get(s, 0),
                            'ky_vong': round(m * nen_tong.get(s, 0) / n, 1) if n else None}
                           for s in range(3, 19)],
        }
    return out
