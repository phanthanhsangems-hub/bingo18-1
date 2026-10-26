"""P274: trip 444 / 666 có ra NHIỀU BẤT THƯỜNG không — kiểm định thống kê.

Mỗi bộ trip cụ thể có xác suất 1/216 mỗi kỳ. Với n kỳ, số lần ra ~ Poisson(n/216).
Ba phép kiểm:
  1. Từng bộ: p = P(X >= số lần thấy) — nhỏ hơn 0,05/6 (Bonferroni, vì xét 6 bộ) mới đáng ngờ.
  2. Giữa 6 bộ trip với nhau: chi-bình phương df=5 (trong các kỳ ra trip, mỗi bộ 1/6).
  3. Mặt xúc xắc: nếu thật sự lệch về 4/6 thì MỌI kỳ (không chỉ trip) cũng phải
     nhiều số 4/6 hơn 1/6 — chi-bình phương df=5 trên 3n viên.
"""
import math
from collections import Counter

P_BO = 1 / 216
BONF = 0.05 / 6


def _gamma_q(s: float, x: float) -> float:
    """Q(s, x) = 1 - P(s, x) (gamma chính quy trên)."""
    if x <= 0:
        return 1.0
    if x < s + 1:                      # chuỗi cho P
        tong = hang = 1.0 / s
        a = s
        for _ in range(1000):
            a += 1
            hang *= x / a
            tong += hang
            if hang < tong * 1e-15:
                break
        return max(0.0, 1.0 - tong * math.exp(-x + s * math.log(x) - math.lgamma(s)))
    # phân số liên tục cho Q (Lentz)
    b = x + 1 - s
    c = 1 / 1e-300
    d = 1 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - s)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        de = d * c
        h *= de
        if abs(de - 1) < 1e-15:
            break
    return math.exp(-x + s * math.log(x) - math.lgamma(s)) * h


def chi2_p(x: float, df: int) -> float:
    return _gamma_q(df / 2, x / 2)


def poisson_tren(k: int, lam: float) -> float:
    """P(X >= k), X ~ Poisson(lam)."""
    if k <= 0:
        return 1.0
    # P(X >= k) = P(k, lam) (gamma chính quy dưới) = 1 - Q(k, lam)
    return max(0.0, 1.0 - _gamma_q(k, lam))


def _chi2(dem: dict, keys, n_tong: int, p: float):
    if n_tong == 0:
        return None, None
    e = n_tong * p
    x = sum((dem.get(k, 0) - e) ** 2 / e for k in keys)
    return round(x, 2), round(chi2_p(x, len(keys) - 1), 4)


def kiem_dinh_khoang(ky: list) -> dict:
    """ky: [(dn, bo_sorted)] trong một khoảng."""
    n = len(ky)
    trip = Counter(bo[0] for _, bo in ky if bo[0] == bo[2])
    mat = Counter(v for _, bo in ky for v in bo)
    lam = n * P_BO
    bo = {}
    for v in range(1, 7):
        k = trip.get(v, 0)
        p = poisson_tren(k, lam)
        bo[f"{v}{v}{v}"] = {'so_lan': k, 'ky_vong': round(lam, 1),
                            'ti_le': round(k / lam, 2) if lam else None,
                            'p_nhieu_hon': round(p, 4), 'dang_ngo': p < BONF}
    n_trip = sum(trip.values())
    x_trip, p_trip = _chi2(trip, range(1, 7), n_trip, 1 / 6)
    x_mat, p_mat = _chi2(mat, range(1, 7), 3 * n, 1 / 6)
    return {
        'so_ky': n, 'tu_ky': ky[0][0] if ky else None, 'den_ky': ky[-1][0] if ky else None,
        'bo': bo, 'tong_trip': n_trip, 'ky_vong_tong_trip': round(n / 36, 1),
        'p_tong_trip_nhieu_hon': round(poisson_tren(n_trip, n / 36), 4),
        'chi2_giua_6_trip': x_trip, 'p_giua_6_trip': p_trip,
        'mat': {str(v): {'so_lan': mat.get(v, 0), 'ty_le_pct': round(100 * mat.get(v, 0) / (3 * n), 3) if n else None}
                for v in range(1, 7)},
        'chi2_mat': x_mat, 'p_mat': p_mat,
    }


def phan_tich(rows: list, tu_ngay: str, ngay_moi: str = None) -> dict:
    """rows: [(dn, bo_sorted, ngay_vn 'YYYY-MM-DD')] cũ->mới, mỗi dn một lần.
    Trả: toàn bộ, từ `tu_ngay`, từng tháng từ `tu_ngay`, 30 ngày gần nhất."""
    rows = sorted(rows, key=lambda r: r[0])
    ky = [(dn, bo) for dn, bo, _ in rows]
    out = {'toan_bo': kiem_dinh_khoang(ky),
           'tu_ngay': tu_ngay,
           'tu_moc': kiem_dinh_khoang([(dn, bo) for dn, bo, d in rows if d >= tu_ngay])}
    thang = sorted({d[:7] for _, _, d in rows if d >= tu_ngay})
    out['theo_thang'] = {m: kiem_dinh_khoang([(dn, bo) for dn, bo, d in rows if d[:7] == m]) for m in thang}
    if rows:
        from datetime import date, timedelta
        moi = ngay_moi or rows[-1][2]
        moc30 = (date.fromisoformat(moi) - timedelta(days=29)).isoformat()
        out['30_ngay'] = kiem_dinh_khoang([(dn, bo) for dn, bo, d in rows if d >= moc30])
        out['30_ngay']['tu_ngay'] = moc30
    out['nguong_dang_ngo'] = BONF
    return out
