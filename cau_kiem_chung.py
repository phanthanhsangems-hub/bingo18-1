"""P265: kiểm chứng 'cầu' (bộ kích hoạt → bộ ba đích kỳ kế) trên TOÀN lịch sử.

Câu hỏi: khi cầu ĐÃ trúng, còn các lần bộ đích ra mà KHÔNG có cầu đứng trước thì
sao? Và xác suất có điều kiện P(đích | kích hoạt) có cao hơn nền P(đích) không?
Hàm thuần: nhận [(kỳ, bộ_sắp_xếp)] cũ→mới, không đụng DB.
"""
import math

NEN = 1 / 36   # xác suất một kỳ là trip bất kỳ (6 trip / 216 bộ có thứ tự)


def wilson(k: int, n: int, z: float = 1.96):
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    tam = (p + z * z / (2 * n)) / den
    nua = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, tam - nua), min(1.0, tam + nua))


def kiem_chung(ky: list, cau: dict) -> dict:
    """ky: [(dn, bo_sorted_tuple)] cũ→mới, liên tục theo dn (kỳ thiếu đã được loại).
    cau: {'123': [('111', n_lich_su), ...], ...}  (cùng cấu trúc _WATCH_PAIRS).

    Trả:
      cap: danh sách mỗi cặp (kích hoạt, đích) với n_kich_hoat, trung_cau (đích ra
           ngay sau kích hoạt), ty_le_cau, ty_le_nen_sau_kich_hoat, nen_toan_cuc,
           lan_dich_ngoai_cau (đích ra mà không có kích hoạt đứng trước), tong_lan_dich
      tong_hop: tổng theo từng đích và tổng toàn bộ
    """
    n = len(ky)
    by_dn = {d: b for d, b in ky}
    # trước mỗi kỳ có bộ gì (kỳ liền trước phải tồn tại)
    truoc = {}
    for i in range(1, n):
        if ky[i][0] - ky[i - 1][0] == 1:
            truoc[ky[i][0]] = ky[i - 1][1]
    tong_ky_co_truoc = len(truoc)

    def la_bo_ba(b, t):
        return b == (t, t, t)

    cap = []
    theo_dich = {}
    for kich, dich_list in cau.items():
        kb = tuple(int(x) for x in kich)
        ds_kich = [d for d, b in by_dn.items() if b == kb and d + 1 in by_dn]
        for dich, _nlsu in dich_list:
            t = int(dich[0])
            tb = (t, t, t)
            # kỳ đích có cầu đứng trước (kỳ kích hoạt = kỳ trước đích)
            trung_cau = sum(1 for d in ds_kich if by_dn[d + 1] == tb)
            # tất cả kỳ đích, và trong đó bao nhiêu có kích hoạt đứng trước
            tat_ca_dich = [d for d in truoc if by_dn[d] == tb]
            ngoai_cau = [d for d in tat_ca_dich if truoc.get(d) != kb]
            n_kich = len(ds_kich)
            # xác suất đích ngay sau các kỳ KHÔNG phải kích hoạt
            ds_khong = [d for d in truoc if truoc[d] != kb]
            dich_sau_khong = sum(1 for d in ds_khong if by_dn[d] == tb)
            ty_cau = trung_cau / n_kich if n_kich else 0.0
            ty_nen = dich_sau_khong / len(ds_khong) if ds_khong else 0.0
            lo, hi = wilson(trung_cau, n_kich)
            row = {
                'kich_hoat': kich, 'dich': dich,
                'n_kich_hoat': n_kich, 'trung_cau': trung_cau,
                'ty_le_cau': round(ty_cau, 4),
                'khoang_95': [round(lo, 4), round(hi, 4)],
                'ty_le_khong_cau': round(ty_nen, 4),
                'lan_dich_ngoai_cau': len(ngoai_cau),
                'tong_lan_dich': len(tat_ca_dich),
                # chỉ kết luận khi đủ mẫu (>=30 lần kích hoạt) VÀ khoảng 95% nằm hẳn trên nền 1/36
                'co_y_nghia': n_kich >= 30 and lo > 1 / 36,
            }
            cap.append(row)
            g = theo_dich.setdefault(dich, {'tong_lan_dich': len(tat_ca_dich), 'sau_kich_hoat_cau': set()})
            g['sau_kich_hoat_cau'].update(d for d in tat_ca_dich if truoc.get(d) == kb)
    cap.sort(key=lambda r: (-r['ty_le_cau'], -r['n_kich_hoat']))
    # tổng hợp theo đích: trong các lần đích T ra, bao nhiêu lần có cầu đứng trước
    # (những lần này "cầu đã trúng") và bao nhiêu lần KHÔNG có cầu (trip khác)
    tong_hop = {}
    for dich, g in theo_dich.items():
        tong = g['tong_lan_dich']
        sau = len(g['sau_kich_hoat_cau'])
        tong_hop[dich] = {'tong_lan_dich': tong, 'sau_cau': sau, 'khong_cau': tong - sau,
                          'ty_le_nen': round(tong / tong_ky_co_truoc, 4) if tong_ky_co_truoc else 0.0}
    return {'so_ky_co_truoc': tong_ky_co_truoc, 'nen_1_36': round(NEN, 4), 'cap': cap,
            'tong_hop': tong_hop}
