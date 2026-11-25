"""thong_ke_tin_cay.py - khoảng tin cậy, p-value và đánh giá NGOÀI MẪU cho tỷ lệ thắng.

Vì sao có file này: kết quả Bingo18 khớp với quay ngẫu nhiên độc lập (kiểm định trên
~102.000 kỳ: chi-bình-phương, tự tương quan, runs test, backtest walk-forward đều không
vượt tỷ lệ nền). Khi đó một tỷ lệ thắng "đẹp" trên 50-300 kỳ gần như chắc chắn là nhiễu
(cửa sổ 300 kỳ cho chiến lược luôn đoán LỚN dao động 31% đến 44%). Mọi con số thắng/thua
hiển thị ra ngoài nên đi kèm khoảng tin cậy và p-value so với tỷ lệ nền để người xem
không đọc nhiễu thành tín hiệu.

Thuần Python (math), không cần scipy, dùng được cả trên Cloud Run lẫn máy nhà.

Định nghĩa "ngoài mẫu" ở đây: dự đoán được GHI TRƯỚC giờ quay của kỳ đó
(prediction_time < draw_time). Dự đoán bù (backfill) tạo SAU khi đã biết kết quả không
được tính là ngoài mẫu, vì thuật toán/ngưỡng có thể đã được chỉnh theo dữ liệu đó.
"""
import math
from collections import OrderedDict
from datetime import datetime
from typing import Dict, Iterable, Optional, Tuple

# Xác suất ngẫu nhiên để một dự đoán SIZE trúng (3 xúc xắc 1-6, 216 khả năng):
#   NHO (tổng 3-9) = 81/216, HOA (tổng 10-11) = 54/216, LON (tổng 12-18) = 81/216.
NEN_SIZE: Dict[str, float] = {'NHO': 81 / 216, 'HOA': 54 / 216, 'LON': 81 / 216}
NEN_MAC_DINH = 0.375       # dự đoán NHO/LON (HÒA đang bị chặn nên gần như luôn là mốc này)
MIN_MAU = 200              # ít hơn số kỳ này thì không kết luận
Z95 = 1.959963984540054


def wilson(wins: int, total: int, z: float = Z95) -> Tuple[Optional[float], Optional[float]]:
    """Khoảng tin cậy Wilson cho tỷ lệ. Trả (None, None) nếu total = 0."""
    if total <= 0:
        return None, None
    p = wins / total
    z2 = z * z
    mau = 1 + z2 / total
    tam = (p + z2 / (2 * total)) / mau
    bien = z * math.sqrt(p * (1 - p) / total + z2 / (4 * total * total)) / mau
    return max(0.0, tam - bien), min(1.0, tam + bien)


def _log_pmf(k: int, n: int, p: float) -> float:
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
            + k * math.log(p) + (n - k) * math.log1p(-p))


def _duoi_tren(wins: int, total: int, p0: float) -> float:
    """P(X >= wins) với X ~ Binomial(total, p0). Chính xác, cộng từng số hạng."""
    if wins <= 0:
        return 1.0
    if wins > total:
        return 0.0
    return min(1.0, sum(math.exp(_log_pmf(k, total, p0)) for k in range(wins, total + 1)))


def p_value(wins: int, total: int, p0: float = NEN_MAC_DINH) -> Dict[str, Optional[float]]:
    """p-value nhị thức chính xác so với tỷ lệ nền p0.

    p_cao_hon: kiểm định một phía "thắng nhiều hơn nền".
    p_hai_phia: tổng xác suất của mọi kết quả khó xảy ra bằng hoặc hơn kết quả quan sát
    (cùng cách tính với scipy.stats.binomtest). Total = 0 -> toàn None.
    """
    if total <= 0 or not (0.0 < p0 < 1.0):
        return {'p_hai_phia': None, 'p_cao_hon': None}
    wins = max(0, min(int(wins), int(total)))
    tren = _duoi_tren(wins, total, p0)
    ngat = _log_pmf(wins, total, p0) + 1e-7
    hai = sum(math.exp(lp) for lp in (_log_pmf(k, total, p0) for k in range(total + 1))
              if lp <= ngat)
    return {'p_hai_phia': min(1.0, hai), 'p_cao_hon': tren}


def danh_gia(wins: int, total: int, p0: float = NEN_MAC_DINH, min_mau: int = MIN_MAU) -> Dict:
    """Gói đánh giá một tỷ lệ thắng: tỷ lệ, KTC 95%, p-value, kết luận bằng lời."""
    out: Dict = {
        'n': int(total), 'thang': int(wins), 'nen': round(p0, 4),
        'ty_le': None, 'ktc_duoi': None, 'ktc_tren': None,
        'chenh_nen': None, 'p_hai_phia': None, 'p_cao_hon': None,
    }
    if total <= 0:
        out['ket_luan'] = 'Chưa có dự đoán nào để đánh giá.'
        return out
    rate = wins / total
    lo, hi = wilson(wins, total)
    pv = p_value(wins, total, p0)
    out.update({
        'ty_le': round(rate, 4), 'ktc_duoi': round(lo, 4), 'ktc_tren': round(hi, 4),
        'chenh_nen': round(rate - p0, 4),
        'p_hai_phia': round(pv['p_hai_phia'], 4), 'p_cao_hon': round(pv['p_cao_hon'], 4),
    })
    if total < min_mau:
        out['ket_luan'] = ('Chưa đủ mẫu để kết luận (%d kỳ, cần ít nhất %d). '
                           'Với mẫu nhỏ, chênh lệch vài điểm phần trăm chỉ là nhiễu.' % (total, min_mau))
    elif pv['p_hai_phia'] >= 0.05:
        out['ket_luan'] = ('Không khác tỷ lệ nền %.1f%% (nằm trong sai số ngẫu nhiên).' % (p0 * 100))
    elif rate > p0:
        out['ket_luan'] = ('Cao hơn nền có ý nghĩa thống kê (p=%.3f). Chỉ đáng tin nếu giữ được '
                           'ở giai đoạn sau; xem nhiều cửa sổ thì có cái ngẫu nhiên vượt nền.' % pv['p_hai_phia'])
    else:
        out['ket_luan'] = 'Thấp hơn nền có ý nghĩa thống kê (p=%.3f).' % pv['p_hai_phia']
    return out


def _to_dt(v) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace('Z', '').strip())
    except ValueError:
        return None


def _tuan(dt: datetime) -> str:
    y, w, _ = dt.isocalendar()
    return '%d-W%02d' % (y, w)


def tong_hop_ngoai_mau(rows: Iterable[Tuple]) -> Dict:
    """Gom các dự đoán đã có kết quả thành ba nhóm và đánh giá từng nhóm.

    rows: (prediction_time, draw_time, predicted_size, thang)
        predicted_size: 'NHO' | 'HOA' | 'LON' (quyết định tỷ lệ nền của dự đoán đó)
        thang: True nếu đoán đúng SIZE
    Nhóm: 'ngoai_mau' (ghi trước giờ quay), 'bu' (ghi sau giờ quay), 'tat_ca'.
    Tỷ lệ nền của nhóm = trung bình xác suất ngẫu nhiên của các SIZE đã dự đoán.
    Không rõ thời gian thì không xếp vào ngoai_mau (chỉ vào 'bu' và 'tat_ca').
    """
    nhom = {k: {'n': 0, 'w': 0, 'nen': 0.0} for k in ('ngoai_mau', 'bu', 'tat_ca')}
    tuan: 'OrderedDict[str, Dict]' = OrderedDict()
    so_hoa = 0
    for pred_t, draw_t, size, thang in rows:
        nen = NEN_SIZE.get(size, NEN_MAC_DINH)
        p, d = _to_dt(pred_t), _to_dt(draw_t)
        truoc = p is not None and d is not None and p < d
        ten = 'ngoai_mau' if truoc else 'bu'
        for k in (ten, 'tat_ca'):
            nhom[k]['n'] += 1
            nhom[k]['w'] += 1 if thang else 0
            nhom[k]['nen'] += nen
        if size == 'HOA':
            so_hoa += 1
        if truoc:
            t = tuan.setdefault(_tuan(d), {'n': 0, 'w': 0, 'nen': 0.0})
            t['n'] += 1
            t['w'] += 1 if thang else 0
            t['nen'] += nen
    out: Dict = {'so_du_doan_hoa': so_hoa}
    for k, v in nhom.items():
        nen = (v['nen'] / v['n']) if v['n'] else NEN_MAC_DINH
        out[k] = danh_gia(v['w'], v['n'], nen)
    out['theo_tuan'] = []
    for ten, v in sorted(tuan.items()):
        lo, hi = wilson(v['w'], v['n'])
        out['theo_tuan'].append({
            'tuan': ten, 'n': v['n'], 'thang': v['w'],
            'ty_le': round(v['w'] / v['n'], 4),
            'ktc_duoi': round(lo, 4), 'ktc_tren': round(hi, 4),
            'nen': round(v['nen'] / v['n'], 4),
        })
    return out
