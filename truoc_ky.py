"""P293: thẻ dashboard "kỳ NGAY TRƯỚC trip 111-666 / tổng 4 & 17 ra bộ nào" (từ 01/01).

Người dùng nhiều lần hỏi tay câu này; nay đưa thành hai thẻ trên dashboard.
Module thuần (không DB, không mạng) để test được — app.py lo đọc DB + cache.

"Kỳ ngay trước" = đúng kỳ #dn-1. Thiếu trong DB thì không tính vào phân bố
(đếm riêng ở `thieu_truoc`) — tháng 1/2026 cả DB lẫn nguồn GitHub thiếu ~3.200 kỳ.

Đo 01/01-19/11/2026: kỳ trước phân bố y như mọi kỳ (p = 0,21-0,54). Thẻ phải ghi
rõ đây là thống kê tham khảo, kỳ trước KHÔNG báo hiệu trip / tổng.
"""
import math
from collections import Counter
from datetime import datetime, timedelta

W = Counter(a + b + c for a in range(1, 7) for b in range(1, 7) for c in range(1, 7))
TAT_CA_BO = sorted({(a, b, c) for a in range(1, 7) for b in range(a, 7) for c in range(b, 7)})
_NHOM_TONG = [(3, 4)] + [(s,) for s in range(5, 17)] + [(17, 18)]   # gộp đuôi để kỳ vọng >= ~5


def p_bo(bo) -> float:
    """Xác suất ra đúng bộ (không thứ tự) này trong một kỳ."""
    return {3: 6, 2: 3, 1: 1}[len(set(bo))] / 216


def size(s: int) -> str:
    return 'NHO' if s <= 9 else ('HOA' if s <= 11 else 'LON')


def gamma_q(a: float, x: float) -> float:
    """Q(a, x) = 1 - P(a, x): phần đuôi phải của chi-bình phương."""
    if x <= 0:
        return 1.0
    if x < a + 1:
        s = t = 1.0 / a
        n = a
        for _ in range(1000):
            n += 1
            t *= x / n
            s += t
            if abs(t) < abs(s) * 1e-14:
                break
        return max(0.0, 1 - s * math.exp(-x + a * math.log(x) - math.lgamma(a)))
    b = x + 1 - a
    c = 1e300
    d = 1 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        h *= d * c
        if abs(d * c - 1) < 1e-14:
            break
    return min(1.0, math.exp(-x + a * math.log(x) - math.lgamma(a)) * h)


def chi2_p(obs, exp):
    """p của kiểm định chi-bình phương; None nếu không đủ dữ liệu."""
    cap = [(o, e) for o, e in zip(obs, exp) if e > 0]
    if len(cap) < 2 or sum(o for o, _ in cap) == 0:
        return None
    x = sum((o - e) ** 2 / e for o, e in cap)
    return gamma_q((len(cap) - 1) / 2, x / 2)


def _bo_str(bo) -> str:
    return ''.join(str(n) for n in bo)


def _nhom(loai: str):
    """[(khoá, điều kiện, xác suất 1 kỳ, chữ số trip hoặc None)]."""
    if loai == 'trip':
        return [(f'{v}{v}{v}', (lambda v: lambda bo: bo == (v, v, v))(v), 1 / 216, v) for v in range(1, 7)]
    if loai == 'tong':
        return [(str(t), (lambda t: lambda bo: sum(bo) == t)(t), W[t] / 216, None) for t in (4, 17)]
    raise ValueError(loai)


def _tom_tat(lan: list, p_nhom: float, n_ky: int, chu_so=None, dieu_kien=None) -> dict:
    """lan: [(dn, luc, bo, bo_truoc|None)]. Thống kê phân bố của kỳ trước."""
    co = [x for x in lan if x[3] is not None]
    n = len(co)
    dem_bo = Counter(x[3] for x in co)
    dem_tong = Counter(sum(x[3]) for x in co)
    dem_sz = Counter(size(sum(x[3])) for x in co)
    tom = {
        'so_lan': len(lan), 'ky_vong': round(n_ky * p_nhom, 1),
        'co_truoc': n, 'thieu_truoc': len(lan) - n,
        'top_bo': [[_bo_str(b), c, round(n * p_bo(b), 1)] for b, c in
                   sorted(dem_bo.items(), key=lambda kv: (-kv[1], kv[0]))],
        'size': {k: dem_sz.get(k, 0) for k in ('NHO', 'HOA', 'LON')},
        'size_kv': {'NHO': round(n * 81 / 216, 1), 'HOA': round(n * 54 / 216, 1), 'LON': round(n * 81 / 216, 1)},
        'tong_truoc': [dem_tong.get(s, 0) for s in range(3, 19)],
        'tong_kv': [round(n * W[s] / 216, 1) for s in range(3, 19)],
        'p_tong': None, 'p_bo': None,
        'truoc_la_trip': sum(1 for x in co if len(set(x[3])) == 1),
        'kv_truoc_trip': round(n / 36, 1),
    }
    p = chi2_p([sum(dem_tong.get(s, 0) for s in g) for g in _NHOM_TONG],
               [n * sum(W[s] for s in g) / 216 for g in _NHOM_TONG])
    tom['p_tong'] = round(p, 3) if p is not None else None
    p = chi2_p([dem_bo.get(b, 0) for b in TAT_CA_BO], [n * p_bo(b) for b in TAT_CA_BO])
    tom['p_bo'] = round(p, 3) if p is not None else None
    if dieu_kien is not None:
        tom['truoc_cung_nhom'] = sum(1 for x in co if dieu_kien(x[3]))
        tom['kv_truoc_cung_nhom'] = round(n * p_nhom, 1)
    if chu_so is not None:
        tom['truoc_co_so'] = sum(1 for x in co if chu_so in x[3])
    elif dieu_kien is None:                       # "tất cả trip": có chữ số của CHÍNH trip đó
        tom['truoc_co_so'] = sum(1 for x in co if x[2][0] in x[3])
    if 'truoc_co_so' in tom:
        tom['kv_truoc_co_so'] = round(n * 91 / 216, 1)   # P(bộ có chứa 1 chữ số cho trước)
    return tom


def thang_vn(luc: str) -> str:
    """'YYYY-MM-DD HH:MM:SS' (UTC) -> 'YYYY-MM' theo giờ VN; hỏng thì '????-??'."""
    try:
        return (datetime.strptime(str(luc)[:19], '%Y-%m-%d %H:%M:%S') + timedelta(hours=7)).strftime('%Y-%m')
    except ValueError:
        return '????-??'


def phan_tich(rows: list, tu_dn: int, loai: str) -> dict:
    """rows: [(dn, bo_sorted_tuple, luc_utc 'YYYY-MM-DD HH:MM:SS')] tăng dần theo dn,
    được phép có kỳ trước tu_dn (làm "kỳ trước" cho kỳ đầu năm). Chỉ đếm kỳ >= tu_dn.
    loai: 'trip' (111..666 + 'tat_ca') hoặc 'tong' (4, 17)."""
    nhom = _nhom(loai)
    theo = {dn: bo for dn, bo, _ in rows}
    trong = [r for r in rows if r[0] >= tu_dn]
    out = {'loai': loai, 'so_ky': len(trong),
           'tu_ky': trong[0][0] if trong else None,
           'den_ky': trong[-1][0] if trong else None,
           'den_luc': trong[-1][2] if trong else None,
           # P295: số kỳ CÓ trong DB mỗi tháng — thẻ dùng để báo tháng nào DB thiếu kỳ
           'so_ky_thang': dict(sorted(Counter(thang_vn(luc) for _, _, luc in trong).items())),
           'nhom': {}}
    gop = []
    for khoa, dk, p, chu_so in nhom:
        lan = [(dn, luc, bo, theo.get(dn - 1)) for dn, bo, luc in trong if dk(bo)]
        g = _tom_tat(lan, p, len(trong), chu_so=chu_so, dieu_kien=dk)
        g['ds'] = [[dn, luc, _bo_str(bo), _bo_str(tr) if tr else None] for dn, luc, bo, tr in reversed(lan)]
        out['nhom'][khoa] = g
        gop += lan
    if loai == 'trip':
        gop.sort()
        out['tat_ca'] = _tom_tat(gop, 6 / 216, len(trong))
    return out
