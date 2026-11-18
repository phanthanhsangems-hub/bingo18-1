"""P292: tin Telegram định kỳ "từ 01/01 đến nay, kỳ NGAY TRƯỚC tổng 4 / tổng 17 ra bộ nào".

Người dùng muốn cứ 20 kỳ nhận một tin. Mốc = kỳ thứ 20, 40, ..., 140 trong ngày
(theo lịch 159 kỳ/ngày, kỳ đầu 06:06) -> 08:00, 10:00, ..., 20:00, 7 tin/ngày.

Module thuần (không DB, không mạng) để test được. app.py lo đọc DB, giành mốc
trong system_config và gửi Telegram.

Đo trên 47.804 kỳ 01/01-17/11/2026: tổng/size/bộ của kỳ trước phân bố y như mọi
kỳ (p = 0,26 / 0,24 cho tổng, 0,26 / 0,61 cho 56 bộ). Tin nhắn phải nói rõ đây là
thống kê tham khảo, kỳ trước KHÔNG báo hiệu tổng 4/17.
"""
from collections import Counter
from html import escape

import gio_ky

MOI_BAO_NHIEU_KY = 20
CAC_TONG = (4, 17)
_DAU = {4: '🟢', 17: '🟠'}


def moc_tin(dn: int):
    """Khoá mốc tăng dần cho kỳ `dn`, hoặc None nếu chưa tới mốc đầu trong ngày.

    khoi*10 + (vị trí trong ngày // 20): mỗi ngày tối đa 7 mốc (20..140), 7 < 10 nên
    khoá luôn tăng theo thời gian, kể cả qua ngày. Trước KY_HIEU_LUC lịch quay khác
    -> không tính được vị trí -> None.
    """
    if dn is None or dn < gio_ky.KY_HIEU_LUC:
        return None
    b = (gio_ky.vi_tri(dn) + 1) // MOI_BAO_NHIEU_KY
    if b <= 0:
        return None
    return gio_ky.khoi(dn) * 10 + b


def _size(s: int) -> str:
    return 'Nhỏ' if s <= 9 else ('Hòa' if s <= 11 else 'Lớn')


def _bo(bo) -> str:
    return '-'.join(str(n) for n in bo)


def thong_ke(rows: list, tu_dn: int, cac_tong=CAC_TONG, so_gan: int = 3,
             cua_so: int = MOI_BAO_NHIEU_KY) -> dict:
    """rows: [(dn, bo_sorted_tuple, gio_vn 'HH:MM dd/mm')] tăng dần theo dn, có thể
    gồm cả kỳ trước tu_dn (để lấy "kỳ trước" của kỳ đầu năm). Chỉ đếm kỳ >= tu_dn.
    Kỳ trước = đúng kỳ dn-1; thiếu trong DB thì không tính vào phân bố."""
    theo = {dn: (bo, gio) for dn, bo, gio in rows}
    trong = [r for r in rows if r[0] >= tu_dn]
    max_dn = trong[-1][0] if trong else None
    out = {'so_ky': len(trong), 'den_dn': max_dn,
           'den_gio': trong[-1][2] if trong else '', 'tong': {}}
    for t in cac_tong:
        lan, dem_bo, dem_sz, thieu = [], Counter(), Counter(), 0
        for dn, bo, gio in trong:
            if sum(bo) != t:
                continue
            tr = theo.get(dn - 1)
            if tr is None:
                thieu += 1
            else:
                dem_bo[tr[0]] += 1
                dem_sz[_size(sum(tr[0]))] += 1
            lan.append((dn, gio, tr[0] if tr else None))
        n = len(lan) - thieu
        out['tong'][t] = {
            'so_lan': len(lan), 'co_truoc': n, 'thieu_truoc': thieu,
            'top_bo': dem_bo.most_common(6),
            'size': {k: dem_sz.get(k, 0) for k in ('Nhỏ', 'Hòa', 'Lớn')},
            'ky_vong_bo': round(n * 6 / 216, 1),
            'gan_nhat': list(reversed(lan[-so_gan:])),
            'trong_cua_so': sum(1 for dn, _, _ in lan if max_dn is not None and dn > max_dn - cua_so),
        }
    return out


def soan_tin(tk: dict, tu_ngay: str, cua_so: int = MOI_BAO_NHIEU_KY) -> str:
    """HTML cho Telegram (parse_mode=HTML), luôn < 4096 ký tự."""
    if not tk.get('den_dn'):
        return '📋 <b>BỘ RA TRƯỚC TỔNG 4 &amp; TỔNG 17</b>\nChưa có dữ liệu.'
    d = [f"📋 <b>BỘ RA TRƯỚC TỔNG {' &amp; TỔNG '.join(str(t) for t in tk['tong'])}</b>",
         f"Từ {escape(tu_ngay)} đến #{tk['den_dn']} ({escape(tk['den_gio'])}) · "
         f"{tk['so_ky']:,} kỳ".replace(',', '.')]
    max_dn = tk['den_dn']
    for t, x in tk['tong'].items():
        d.append('')
        d.append(f"{_DAU.get(t, '•')} <b>TỔNG {t}</b> — {x['so_lan']} lần")
        if x['top_bo']:
            d.append('Bộ ra ngay trước nhiều nhất:')
            top = [f"{_bo(b)} ×{c}" for b, c in x['top_bo']]
            d.append(' · '.join(top[:3]))
            if len(top) > 3:
                d.append(' · '.join(top[3:]))
            sz = x['size']
            d.append(f"Kỳ trước: Nhỏ {sz['Nhỏ']} · Hòa {sz['Hòa']} · Lớn {sz['Lớn']}")
        if x['gan_nhat']:
            d.append(f"{len(x['gan_nhat'])} lần gần nhất:")
            for dn, gio, tr in x['gan_nhat']:
                moi = '🆕 ' if dn > max_dn - cua_so else ''
                truoc = f"{_bo(tr)} (tổng {sum(tr)})" if tr else 'thiếu dữ liệu kỳ trước'
                d.append(f"{moi}#{dn} {escape(gio)} ← {truoc}")
    d.append('')
    d.append(f"🕑 {cua_so} kỳ vừa qua: " + ' · '.join(
        f"tổng {t} ra {x['trong_cua_so']} lần" for t, x in tk['tong'].items()))
    kv = next(iter(tk['tong'].values()))['ky_vong_bo'] if tk['tong'] else 0
    d.append(f"<i>Mỗi bộ 3 số khác nhau kỳ vọng ~{kv:g} lần; chênh lệch ở trên là ngẫu nhiên — "
             f"kỳ trước không báo hiệu tổng 4/17. Chỉ để tham khảo.</i>")
    tin = '\n'.join(d)
    return tin[:4000]
