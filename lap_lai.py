"""Bộ số RA LẠI — hàm thuần dùng chung cho app (Cloud Run) và watcher (máy người dùng).

P260: tin "🔁 bộ vừa ra lại" không còn là tin Telegram riêng (từng chiếm ~73% số
kỳ, ~115 tin/ngày). Nó thành MỘT DÒNG trong tin mỗi kỳ do watcher gửi ngay khi
có kỳ mới. Phần tính toán tách ra đây để app (/api/lap-lai, test) và watcher
dùng chung một quy ước:
  - khoảng cách = HIỆU SỐ KỲ (dữ liệu có thể thủng, "ra lại sau 3 kỳ" là 3 kỳ thật)
  - "kỳ ngay sau" phải đúng là kỳ +1; thiếu thì None, không lấy kỳ kế mà đoán
"""
import json
from datetime import datetime

# P246: người dùng chọn "mọi lần ra" = lần ra trước nằm trong 160 kỳ (≈ 1 ngày).
LAPLAI_ALERT_GAP  = 160
# P238: với mỗi bộ vừa ra lại, liệt kê TỔNG của kỳ NGAY SAU mỗi lần bộ đó ra
# trong ngần này kỳ gần nhất (người dùng chọn 160).
LAPLAI_CUA_SO_SAU = 160

# P245: nhật ký từng kỳ đã gửi tin (xoay vòng) — diagnose đối chiếu với danh
# sách LẼ RA phải báo tính lại từ kết quả thật. Mỗi kỳ một mục:
#   {'luc','den','combo'|None,'cach','ok','nguon'}  (combo=None: kỳ không ra lại)
NK_KEY = 'lap_lai_nhat_ky'
NK_MAX = 400          # ~2,5 ngày với 160 kỳ/ngày

WAYS_COMBO = {}
for _a in range(1, 7):
    for _b in range(_a, 7):
        for _c in range(_b, 7):
            WAYS_COMBO[(_a, _b, _c)] = len({(x, y, z) for x in range(1, 7) for y in range(1, 7)
                                            for z in range(1, 7) if tuple(sorted((x, y, z))) == (_a, _b, _c)})


def parse_bo(raw) -> tuple:
    """'[1, 2, 3]' / [1,2,3] / '123' -> (1, 2, 3) đã sắp xếp. Lỗi -> ()."""
    try:
        if isinstance(raw, (list, tuple)):
            ns = raw
        else:
            s = str(raw).strip()
            ns = json.loads(s) if s.startswith('[') else list(s)
        return tuple(sorted(int(x) for x in ns))
    except Exception:
        return ()


def rows_to_ky(rows) -> list:
    """[(draw_number, numbers_raw)] -> [(dn, bo_sorted, tong)] xếp CŨ -> MỚI, bỏ dòng hỏng."""
    ky = []
    for dn, raw in sorted(rows, key=lambda r: int(r[0])):
        bo = parse_bo(raw)
        if len(bo) == 3:
            ky.append((int(dn), bo, sum(bo)))
    return ky


def tong_sau_cac_lan(ky: list, bo: tuple, den: int, cua_so: int = None) -> list:
    """Mỗi lần `bo` ra TRƯỚC kỳ `den` (trong `cua_so` kỳ gần nhất), kỳ NGAY SAU
    lần đó ra tổng mấy. Trả [(kỳ bộ ra, tổng kỳ sau hoặc None)], cũ -> mới.
    None = kỳ ngay sau bị thiếu trong DB."""
    if cua_so is None:
        cua_so = LAPLAI_CUA_SO_SAU
    theo_dn = {d: (b, t) for d, b, t in ky}
    ra = []
    for d, b, _ in ky:
        if b == bo and den - cua_so <= d < den:
            sau = theo_dn.get(d + 1)
            ra.append((d, sau[1] if sau else None))
    return ra


def tim_bo_ra_lai(ky: list, moc: int, gap: int = None, chi_xet: set = None) -> list:
    """Các kỳ MỚI (draw_number > moc) mà bộ của nó đã ra trong `gap` kỳ liền trước.
    Chỉ lấy lần ra lại GẦN NHẤT của mỗi kỳ. 'tong_giua' không gồm kỳ ra lại."""
    if gap is None:
        gap = LAPLAI_ALERT_GAP
    theo_dn = {d: (b, t) for d, b, t in ky}
    ra = []
    for dn, bo, tong in ky:
        if dn <= moc:
            continue
        if chi_xet is not None and dn not in chi_xet:
            continue
        for g in range(1, gap + 1):
            truoc = theo_dn.get(dn - g)
            if truoc is None:
                continue            # kỳ đó thiếu trong DB -> không kết luận được
            if truoc[0] != bo:
                continue
            giua = [(dn - g + k) for k in range(1, g)]
            ra.append({
                'combo':     ''.join(map(str, bo)),
                'tu':        dn - g,
                'den':       dn,
                'cach':      g,
                'tong_giua': [theo_dn[m][1] for m in giua if m in theo_dn],
                'tong_lap':  tong,
                'thieu_ky':  any(m not in theo_dn for m in giua),
            })
            break
    return ra


def ra_lai_cua_ky(ky: list, dn: int):
    """Kỳ `dn` có phải là lần ra lại không. Trả None hoặc
    {'cach': số kỳ kể từ lần trước, 'tong_sau': [(kỳ, tổng kỳ sau|None)], 'combo': '235'}."""
    su = tim_bo_ra_lai(ky, dn - 1, chi_xet={dn})
    if not su:
        return None
    e = su[0]
    bo = tuple(int(x) for x in e['combo'])
    return {'combo': e['combo'], 'cach': e['cach'], 'tong_sau': tong_sau_cac_lan(ky, bo, dn)}


def dong_ra_lai(info) -> str:
    """Một dòng HTML cho tin mỗi kỳ. Giữ đúng nội dung người dùng chọn (P238):
    tổng của kỳ NGAY SAU mỗi lần bộ đó ra trong 160 kỳ, cũ -> mới."""
    if not info:
        return ''
    cac = info['tong_sau']
    day = ' · '.join('?' if t is None else str(t) for _, t in cac)
    s = (f"🔁 Ra lại sau <b>{info['cach']}</b> kỳ · kỳ sau các lần trước "
         f"({len(cac)} lần/160 kỳ) ra tổng: <b>{day}</b>")
    if any(t is None for _, t in cac):
        s += " <i>(? = kỳ sau bị thiếu)</i>"
    return s


def doc_nhat_ky(cur, ph: str = '%s') -> list:
    cur.execute(f"SELECT config_value FROM system_config WHERE config_key = {ph}", (NK_KEY,))
    r = cur.fetchone()
    try:
        v = json.loads(r[0]) if r and r[0] else []
        return v if isinstance(v, list) else []
    except Exception:
        return []


def ghi_nhat_ky(cur, muc: list, ph: str = '%s'):
    """Nối `muc` vào nhật ký (giữ NK_MAX mục mới nhất). Cú pháp upsert chạy được
    cả Postgres lẫn SQLite (CURRENT_TIMESTAMP thay NOW()). Caller commit."""
    if not muc:
        return
    cu = doc_nhat_ky(cur, ph)
    gt = json.dumps((cu + list(muc))[-NK_MAX:], ensure_ascii=False)
    cur.execute(
        f"INSERT INTO system_config (config_key, config_value, description) VALUES ({ph}, {ph}, {ph}) "
        f"ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, "
        f"updated_at = CURRENT_TIMESTAMP",
        (NK_KEY, gt, 'P260: nhat ky tin moi ky (bo ra lai)'))


def muc_nhat_ky(dn: int, info, ok: bool, nguon: str = 'watcher') -> dict:
    m = {'luc': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), 'den': int(dn),
         'ok': bool(ok), 'nguon': nguon}
    if info:
        m['combo'] = info['combo']
        m['cach'] = info['cach']
    return m
