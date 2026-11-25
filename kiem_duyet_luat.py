"""kiem_duyet_luat.py - CỔNG KIỂM DUYỆT trước khi thêm một luật / bộ lọc / mô hình dự đoán mới.

Chạy RIÊNG, ngoài vòng dự đoán: không đọc / ghi DB, không import app, không đụng gì
tới hệ thống đang chạy. Chỉ cần dữ liệu kỳ quay (jsonl của vietlott-data, mặc định tải
từ GitHub, hoặc một file jsonl trên máy).

Vì sao cần: kết quả Bingo18 khớp với quay ngẫu nhiên độc lập (kiểm định trên ~102.000
kỳ). Khi đó mọi luật đều "trông có vẻ hiệu quả" trên một đoạn lịch sử nào đó: 2.000
chiến lược ngẫu nhiên, mỗi cái chọn 3% kỳ, có cái đạt 48,8%. Luật mới chỉ nên được
thêm khi qua được cổng này.

Cổng làm gì
-----------
1. Walk-forward: tại mỗi kỳ t, luật CHỈ nhận lịch sử các kỳ trước t (cắt tại chỗ khuyết
   dữ liệu, không bao giờ nhìn thấy tương lai).
2. Chia theo thời gian: 60% đầu = "phát triển" (nơi bạn được phép chỉnh luật), 40% cuối =
   "giữ ra" (chỉ dùng để kết luận). Cách chia không phụ thuộc luật nên luật không thể
   chọn lọc nơi bị chấm.
3. Chấm trên "giữ ra": tỷ lệ thắng SIZE, khoảng tin cậy Wilson 95%, p-value nhị thức
   chính xác so với nền (NHỎ/LỚN 37,5%, HÒA 25%).
4. Hiệu chỉnh đa phép thử: p x K, với K = số luật đã thử (cả ở lần chạy này lẫn những
   biến thể bạn đã thử trước đó, truyền qua --so-phep-thu). Càng thử nhiều càng khó qua.
5. Placebo: chạy lại đúng luật trên dữ liệu bị xáo trộn thứ tự (phá mọi cấu trúc thời
   gian nhưng giữ tần suất). Luật không thắng nổi 95% các lần xáo trộn thì chưa chứng
   minh được gì.
6. Ổn định: "giữ ra" chia 4 đoạn liên tiếp; ít nhất 3/4 đoạn phải vượt nền.

Luật qua cổng khi ĐẠT CẢ SÁU: đủ mẫu (>= 2.000 dự đoán giữ ra, phủ >= 30% số kỳ), vượt nền ở
cả "phát triển" lẫn "giữ ra", p đã hiệu chỉnh < 0,05, placebo p < 0,05, ổn định >= 3/4 đoạn.
Qua cổng cũng KHÔNG đảm bảo luật thắng thật: chỉ là bằng chứng đủ để đem chạy thử có theo dõi
(tab "Ngoài mẫu" của /analytics) trước khi cho vào dự đoán chính thức.

Cách dùng
---------
    python kiem_duyet_luat.py --luat nong_30
    python kiem_duyet_luat.py --luat nong_30 --luat lanh_30 --luat file_cua_ban.py:ten_ham
    python kiem_duyet_luat.py --luat file_cua_ban.py:ten_ham --so-phep-thu 20
    python kiem_duyet_luat.py --danh-sach            # liệt kê luật mẫu
Mã thoát: 0 = mọi luật qua cổng, 1 = có luật không qua, 2 = không chạy được.

Luật của bạn là một hàm  ten_ham(lich_su) -> 'NHO' | 'HOA' | 'LON' | None
  lich_su: mảng numpy (m, 3), m <= 2000, các kỳ ĐÃ QUAY ngay trước kỳ cần đoán (cũ -> mới), mỗi dòng
           là 3 số 1-6. Là bản sao nên không với tới được dữ liệu phía sau.
  None = bỏ qua kỳ này (không tính thắng / thua; nhưng bị trừ vào độ phủ).
"""
import argparse
import importlib.util
import json
import math
import os
import sys
import urllib.request
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

import thong_ke_tin_cay as tk

GITHUB_JSONL_URL = ("https://raw.githubusercontent.com/vietvudanh/vietlott-data"
                    "/main/data/bingo18.jsonl")

TEN_SIZE = ('NHO', 'HOA', 'LON')
NEN = np.array([tk.NEN_SIZE['NHO'], tk.NEN_SIZE['HOA'], tk.NEN_SIZE['LON']])

WARMUP = 200                 # số kỳ tối thiểu trong khối trước khi bắt đầu đoán
TI_LE_PHAT_TRIEN = 0.6
SO_DOAN_GIU_RA = 4
MIN_DU_DOAN_GIU_RA = 2000
MIN_PHU = 0.30               # tỷ lệ kỳ giữ ra mà luật phải dám đoán
NGUONG_P = 0.05
MIN_DOAN_VUOT_NEN = 3        # số đoạn (trên 4) phải vượt nền
MAX_LICH_SU = 2000           # luật chỉ nhận tối đa ngần này kỳ gần nhất (bản sao, không phải view)


# ── Dữ liệu ──────────────────────────────────────────────────────────────────

def tai_du_lieu(nguon: Optional[str] = None) -> Tuple[np.ndarray, np.ndarray]:
    """Đọc jsonl (đường dẫn hoặc URL; mặc định GitHub). Trả (ids, kq) sắp theo id."""
    nguon = nguon or GITHUB_JSONL_URL
    if nguon.startswith(('http://', 'https://')):
        with urllib.request.urlopen(nguon, timeout=60) as r:
            text = r.read().decode('utf-8')
    else:
        with open(nguon, encoding='utf-8') as f:
            text = f.read()
    ids, kq = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
            r = [int(x) for x in o['result']]
            if len(r) == 3 and all(1 <= x <= 6 for x in r):
                ids.append(int(o['id']))
                kq.append(r)
        except (ValueError, KeyError, TypeError):
            continue
    if not ids:
        raise ValueError('không đọc được kỳ quay nào từ ' + nguon)
    ids = np.array(ids)
    kq = np.array(kq)
    thu_tu = np.argsort(ids, kind='stable')
    ids, kq = ids[thu_tu], kq[thu_tu]
    _, uniq = np.unique(ids, return_index=True)       # bỏ trùng id
    return ids[uniq], kq[uniq]


def size_cua_tong(tong) -> np.ndarray:
    tong = np.asarray(tong)
    return np.where(tong <= 9, 0, np.where(tong <= 11, 1, 2))


def tach_khoi(ids: np.ndarray) -> List[np.ndarray]:
    """Cắt chuỗi tại mọi chỗ khuyết id: luật không bao giờ nhìn xuyên qua một lỗ hổng."""
    cat = np.where(np.diff(ids) > 1)[0] + 1
    return np.split(np.arange(len(ids)), cat)


# ── Chạy luật ────────────────────────────────────────────────────────────────

def _diem_danh_gia(khoi: List[np.ndarray], warmup: int) -> List[Tuple[int, int]]:
    """Mọi (vị trí toàn cục, vị trí đầu khối) mà luật được hỏi, theo thứ tự thời gian."""
    diem = []
    for k in khoi:
        if len(k) <= warmup:
            continue
        dau = int(k[0])
        for j in range(warmup, len(k)):
            diem.append((int(k[j]), dau))
    diem.sort()
    return diem


def _chay(luat: Callable, kq: np.ndarray, size: np.ndarray, diem: Sequence[Tuple[int, int]]):
    """Hỏi luật tại từng điểm. Trả (du_doan, thang): du_doan = -1 nếu bỏ qua."""
    du_doan = np.full(len(diem), -1, dtype=int)
    thang = np.zeros(len(diem), dtype=bool)
    for i, (vt, dau) in enumerate(diem):
        # Chỉ các kỳ TRƯỚC vt, và là BẢN SAO (ls.base is None): luật không có đường nào với tới
        # mảng gốc để đọc trộm kỳ cần đoán hay các kỳ sau nó.
        ls = kq[max(dau, vt - MAX_LICH_SU):vt].copy()
        out = luat(ls)
        if out is None:
            continue
        if out not in TEN_SIZE:
            raise ValueError("luật phải trả 'NHO' | 'HOA' | 'LON' | None, nhận được %r" % (out,))
        s = TEN_SIZE.index(out)
        du_doan[i] = s
        thang[i] = (s == size[vt])
    return du_doan, thang


def _tom_tat(du_doan: np.ndarray, thang: np.ndarray, so_diem: int) -> Dict:
    co = du_doan >= 0
    n = int(co.sum())
    w = int(thang[co].sum())
    nen = float(NEN[du_doan[co]].mean()) if n else tk.NEN_MAC_DINH
    dg = tk.danh_gia(w, n, nen)
    dg['phu'] = round(n / so_diem, 4) if so_diem else 0.0
    return dg


def hieu_chinh_p(p: Optional[float], k: int) -> Optional[float]:
    """Bonferroni: p x K, tối đa 1."""
    if p is None:
        return None
    return min(1.0, p * max(1, int(k)))


def kiem_duyet(luat: Callable, ids: np.ndarray, kq: np.ndarray, ten: str = 'luat',
               so_phep_thu: int = 1, placebo: int = 100, seed: int = 20260101,
               warmup: int = WARMUP) -> Dict:
    """Chạy cổng cho MỘT luật. so_phep_thu = K dùng hiệu chỉnh đa phép thử."""
    kq = np.asarray(kq, dtype=np.int8)
    size = size_cua_tong(kq.sum(axis=1, dtype=int))
    khoi = tach_khoi(ids)
    diem = _diem_danh_gia(khoi, warmup)
    if len(diem) < 500:
        raise ValueError('quá ít kỳ để kiểm duyệt (%d điểm đánh giá)' % len(diem))
    cat = int(len(diem) * TI_LE_PHAT_TRIEN)
    d_pt, d_gr = diem[:cat], diem[cat:]

    du_pt, th_pt = _chay(luat, kq, size, d_pt)
    du_gr, th_gr = _chay(luat, kq, size, d_gr)
    pt = _tom_tat(du_pt, th_pt, len(d_pt))
    gr = _tom_tat(du_gr, th_gr, len(d_gr))
    gr['p_hieu_chinh'] = hieu_chinh_p(gr['p_hai_phia'], so_phep_thu)

    # 4 đoạn liên tiếp của "giữ ra"
    doan = []
    for chi_so in np.array_split(np.arange(len(d_gr)), SO_DOAN_GIU_RA):
        t = _tom_tat(du_gr[chi_so], th_gr[chi_so], len(chi_so))
        t['vuot_nen'] = bool(t['n'] and t['ty_le'] > t['nen'])
        doan.append({k: t[k] for k in ('n', 'thang', 'ty_le', 'nen', 'vuot_nen')})
    so_doan_vuot = sum(1 for d in doan if d['vuot_nen'])

    # Placebo: xáo trộn thứ tự KỲ trong từng khối rồi chạy lại luật trên phần giữ ra
    chenh_that = (gr['ty_le'] - gr['nen']) if gr['n'] else None
    p_placebo = None
    if placebo > 0 and chenh_that is not None:
        rng = np.random.default_rng(seed)
        lon_hon = 0
        for _ in range(placebo):
            kq2 = kq.copy()
            for k in khoi:
                kq2[k] = kq2[k][rng.permutation(len(k))]
            size2 = size_cua_tong(kq2.sum(axis=1, dtype=int))
            du2, th2 = _chay(luat, kq2, size2, d_gr)
            t2 = _tom_tat(du2, th2, len(d_gr))
            c2 = (t2['ty_le'] - t2['nen']) if t2['n'] else -1.0
            if c2 >= chenh_that:
                lon_hon += 1
        p_placebo = (1 + lon_hon) / (1 + placebo)

    ly_do: List[str] = []
    if gr['n'] < MIN_DU_DOAN_GIU_RA:
        ly_do.append('Chưa đủ mẫu giữ ra: %d dự đoán (cần >= %d).' % (gr['n'], MIN_DU_DOAN_GIU_RA))
    if gr['phu'] < MIN_PHU:
        ly_do.append('Độ phủ %.0f%% < %.0f%%: luật né quá nhiều kỳ, dễ chỉ chọn kỳ may.'
                     % (gr['phu'] * 100, MIN_PHU * 100))
    if not (gr['n'] and gr['ty_le'] > gr['nen']):
        ly_do.append('Giữ ra không vượt nền (%s so với nền %s).'
                     % (_pc(gr['ty_le']), _pc(gr['nen'])))
    if not (pt['n'] and pt['ty_le'] > pt['nen']):
        ly_do.append('Phát triển không vượt nền (%s so với nền %s): không cùng chiều với giữ ra.'
                     % (_pc(pt['ty_le']), _pc(pt['nen'])))
    if gr['p_hieu_chinh'] is None or gr['p_hieu_chinh'] >= NGUONG_P:
        ly_do.append('p đã hiệu chỉnh đa phép thử = %s (K=%d) chưa dưới %.2f.'
                     % (_p(gr['p_hieu_chinh']), so_phep_thu, NGUONG_P))
    if p_placebo is None:
        ly_do.append('Chưa chạy placebo (--placebo 0).')
    elif p_placebo >= NGUONG_P:
        ly_do.append('Placebo p = %.3f: dữ liệu xáo trộn cũng cho kết quả tương đương.' % p_placebo)
    if so_doan_vuot < MIN_DOAN_VUOT_NEN:
        ly_do.append('Chỉ %d/%d đoạn giữ ra vượt nền (cần >= %d).'
                     % (so_doan_vuot, SO_DOAN_GIU_RA, MIN_DOAN_VUOT_NEN))

    return {
        'luat': ten, 'dat': not ly_do, 'ly_do_that_bai': ly_do,
        'so_phep_thu': int(so_phep_thu), 'so_diem': len(diem),
        'phat_trien': pt, 'giu_ra': gr, 'cac_doan_giu_ra': doan,
        'so_doan_vuot_nen': so_doan_vuot, 'placebo': int(placebo), 'p_placebo': p_placebo,
    }


def _pc(x) -> str:
    return '–' if x is None else '%.1f%%' % (x * 100)


def _p(x) -> str:
    return '–' if x is None else ('%.4f' % x)


# ── Luật mẫu ─────────────────────────────────────────────────────────────────
# Đều là luật KHÔNG có cơ sở (vì quay ngẫu nhiên): dùng làm mốc đối chứng, và để chứng
# minh cổng thật sự chặn được những luật nghe rất hợp lý.

def _size_cuoi(ls: np.ndarray, n: int) -> np.ndarray:
    return size_cua_tong(ls[-n:].sum(axis=1))


def luon_lon(ls):
    return 'LON'


def luon_nho(ls):
    return 'NHO'


def ngau_nhien(ls):
    rng = np.random.default_rng(len(ls) * 7919 + int(ls[-1].sum()))
    return 'NHO' if rng.random() < 0.5 else 'LON'


def cung_ky_truoc(ls):
    s = int(size_cua_tong(ls[-1].sum()))
    return 'NHO' if s == 0 else 'LON'          # kỳ trước HÒA -> đoán LỚN


def nguoc_ky_truoc(ls):
    s = int(size_cua_tong(ls[-1].sum()))
    return 'LON' if s == 0 else 'NHO'


def nong_30(ls):
    s = _size_cuoi(ls, 30)
    return 'NHO' if (s == 0).sum() > (s == 2).sum() else 'LON'


def lanh_30(ls):
    s = _size_cuoi(ls, 30)
    return 'LON' if (s == 0).sum() > (s == 2).sum() else 'NHO'


def chi_khi_chuoi_3(ls):
    """Chỉ đoán khi 3 kỳ cuối cùng một SIZE (NHO/LON): đoán đảo chiều. Bỏ qua kỳ còn lại."""
    s = _size_cuoi(ls, 3)
    if s[0] == s[1] == s[2] and s[0] != 1:
        return 'LON' if s[0] == 0 else 'NHO'
    return None


LUAT_MAU: Dict[str, Callable] = {
    'luon_lon': luon_lon, 'luon_nho': luon_nho, 'ngau_nhien': ngau_nhien,
    'cung_ky_truoc': cung_ky_truoc, 'nguoc_ky_truoc': nguoc_ky_truoc,
    'nong_30': nong_30, 'lanh_30': lanh_30, 'chi_khi_chuoi_3': chi_khi_chuoi_3,
}


def nap_luat(mo_ta: str) -> Tuple[str, Callable]:
    """'nong_30' (luật mẫu) hoặc 'duong/dan/file.py:ten_ham' (luật của bạn)."""
    if mo_ta in LUAT_MAU:
        return mo_ta, LUAT_MAU[mo_ta]
    if ':' not in mo_ta:
        raise ValueError("luật '%s' không có trong luật mẫu; dùng file.py:ten_ham" % mo_ta)
    duong, ham = mo_ta.rsplit(':', 1)
    if not os.path.isfile(duong):
        raise ValueError('không thấy file ' + duong)
    spec = importlib.util.spec_from_file_location('luat_ngoai', duong)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, ham, None)
    if not callable(fn):
        raise ValueError('file %s không có hàm %s' % (duong, ham))
    return '%s:%s' % (os.path.basename(duong), ham), fn


# ── Giao diện dòng lệnh ──────────────────────────────────────────────────────

def in_bao_cao(kq_luat: Dict) -> None:
    gr, pt = kq_luat['giu_ra'], kq_luat['phat_trien']
    print('=' * 70)
    print('LUẬT: %s   ->   %s' % (kq_luat['luat'], 'ĐẠT CỔNG' if kq_luat['dat'] else 'KHÔNG ĐẠT'))
    print('=' * 70)
    for ten, g in (('Phát triển (60% đầu)', pt), ('Giữ ra (40% cuối)', gr)):
        print('  %-22s %6d dự đoán  phủ %5s  thắng %s  KTC95 %s – %s  nền %s  p=%s'
              % (ten, g['n'], _pc(g['phu']), _pc(g['ty_le']), _pc(g['ktc_duoi']),
                 _pc(g['ktc_tren']), _pc(g['nen']), _p(g['p_hai_phia'])))
    print('  p hiệu chỉnh (K=%d): %s    placebo p: %s    đoạn vượt nền: %d/%d'
          % (kq_luat['so_phep_thu'], _p(gr['p_hieu_chinh']),
             '–' if kq_luat['p_placebo'] is None else '%.3f' % kq_luat['p_placebo'],
             kq_luat['so_doan_vuot_nen'], SO_DOAN_GIU_RA))
    print('  Các đoạn giữ ra: ' + ' | '.join('%s (nền %s)' % (_pc(d['ty_le']), _pc(d['nen']))
                                             for d in kq_luat['cac_doan_giu_ra']))
    if kq_luat['dat']:
        print('  -> Đủ bằng chứng để chạy thử CÓ THEO DÕI (tab "Ngoài mẫu"). Chưa phải bằng chứng thắng thật.')
    else:
        for ld in kq_luat['ly_do_that_bai']:
            print('  - ' + ld)


def main(argv: Optional[Sequence[str]] = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    ap = argparse.ArgumentParser(description='Cổng kiểm duyệt luật dự đoán Bingo18 (xem docstring).')
    ap.add_argument('--luat', action='append', default=[], help='tên luật mẫu hoặc file.py:ten_ham (lặp được)')
    ap.add_argument('--du-lieu', default=None, help='jsonl trên máy hoặc URL (mặc định GitHub vietlott-data)')
    ap.add_argument('--so-phep-thu', type=int, default=1,
                    help='tổng số luật / biến thể bạn đã thử (kể cả trước lần chạy này); K = max(giá trị này, số --luat)')
    ap.add_argument('--placebo', type=int, default=100, help='số lần xáo trộn dữ liệu (0 = bỏ qua, sẽ không đạt)')
    ap.add_argument('--json', default=None, help='ghi kết quả ra file JSON')
    ap.add_argument('--danh-sach', action='store_true', help='liệt kê luật mẫu rồi thoát')
    a = ap.parse_args(argv)

    if a.danh_sach:
        for k, f in LUAT_MAU.items():
            print('%-18s %s' % (k, (f.__doc__ or '').strip().splitlines()[0] if f.__doc__ else ''))
        return 0
    if not a.luat:
        ap.error('cần ít nhất một --luat (xem --danh-sach)')
    try:
        luats = [nap_luat(m) for m in a.luat]
        ids, kq = tai_du_lieu(a.du_lieu)
    except Exception as e:
        print('KHÔNG CHẠY ĐƯỢC: %s' % e, file=sys.stderr)
        return 2
    print('Dữ liệu: %d kỳ, #%d – #%d, %d khối liên tục.' % (len(ids), ids[0], ids[-1], len(tach_khoi(ids))))
    k = max(a.so_phep_thu, len(luats))
    ket_qua = []
    try:
        for ten, fn in luats:
            kq_luat = kiem_duyet(fn, ids, kq, ten=ten, so_phep_thu=k, placebo=a.placebo)
            in_bao_cao(kq_luat)
            ket_qua.append(kq_luat)
    except Exception as e:
        print('KHÔNG CHẠY ĐƯỢC: %s' % e, file=sys.stderr)
        return 2
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(ket_qua, f, ensure_ascii=False, indent=2)
    return 0 if all(r['dat'] for r in ket_qua) else 1


if __name__ == '__main__':
    sys.exit(main())
