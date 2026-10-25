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
