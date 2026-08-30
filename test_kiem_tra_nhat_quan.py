"""P214: bộ kiểm tra nhất quán phải THẬT SỰ bắt được lỗi.

Các phép kiểm này trước đây nằm dạng heredoc trong diagnose.yml. Chúng chạy
được, nhưng chưa ai từng chứng minh chúng KÊU khi dữ liệu hỏng — một câu lệnh
so sánh viết sai vẫn "pass" mãi mãi mà không ai biết.

Mỗi test dưới đây dựng dữ liệu sạch, cố tình phá đúng MỘT chỗ, rồi đòi bộ
kiểm phải bắt được. Ba kịch bản đầu tái dựng đúng ba sự cố có thật.
"""
import copy
import sys

sys.path.insert(0, 'scripts')
from kiem_tra_nhat_quan import kiem_tra

fails = []


def sach():
    """Dữ liệu nhất quán: 60 kỳ liên tục, có 111 ở #1010 và 666 ở #1040."""
    grid = []
    for dn in range(1001, 1061):
        n = [1, 2, 3]
        if dn == 1010: n = [1, 1, 1]
        if dn == 1040: n = [6, 6, 6]
        grid.append({'draw_number': dn, 'numbers': n, 'sum': sum(n),
                     'size': 'NHO' if sum(n) <= 9 else 'LON'})
    maxdn = 1060
    sums, trips = [], []
    for s in range(3, 19):
        sums.append({'sum': s, 'avg_gap': 200, 'median_gap': 150,
                     'current_gap': maxdn - (1010 if s == 3 else (1040 if s == 18 else 1050))})
    for t in range(1, 7):
        c = str(t) * 3
        last = 1010 if t == 1 else (1040 if t == 6 else None)
        trips.append({'combo': c, 'avg_gap': 200, 'median_gap': 150,
                      'current_gap': (maxdn - last) if last else 9999,
                      'last_draw': last})
    return {'total_draws': 88000, 'sums': sums, 'triples': trips}, grid


def thu(ten, sua, mong_bat):
    """sua(board, grid) phá dữ liệu; mong_bat = đoạn chữ phải có trong lỗi."""
    b, g = sach()
    sua(b, g)
    loi = kiem_tra(b, g)
    bat = any(mong_bat in x for x in loi)
    if bat:
        print(f"  OK   {ten}")
        print(f"         -> {[x for x in loi if mong_bat in x][0][:78]}")
    else:
        fails.append(f"{ten}: KHÔNG bắt được (lỗi trả về: {loi})")
        print(f"  FAIL {ten} — không bắt được")


print("=" * 66)
# 0) dữ liệu sạch phải im lặng — nếu không thì mọi test sau đều vô nghĩa
b, g = sach()
l0 = kiem_tra(b, g)
if not l0:
    print("  OK   Dữ liệu sạch -> không báo lỗi giả")
else:
    fails.append(f"báo lỗi giả trên dữ liệu sạch: {l0}")
    print(f"  FAIL Dữ liệu sạch mà vẫn báo lỗi: {l0}")

print("\n  ── Ba sự cố CÓ THẬT đã xảy ra ──")

# 1) Vụ trip 333: lưới CÓ trip mà bảng bỏ sót (do kỳ đó từng thiếu trong DB)
thu("Lưới có trip mà bảng bỏ sót (vụ 333)",
    lambda b, g: b['triples'].__setitem__(
        0, {**b['triples'][0], 'last_draw': 900, 'current_gap': 160}),
    "lưới có 111")

# 2) Vụ hai bảng lệch 1 kỳ (cache hết hạn khác lúc)
thu("Tổng 3 và trip 111 lệch nhau (vụ cache lệch pha)",
    lambda b, g: b['sums'].__setitem__(0, {**b['sums'][0], 'current_gap': 51}),
    'tổng 3')

# 3) Vụ tổng 7/14: cột sum_value ghi khác numbers
thu("sum_value không khớp numbers (vụ tổng 7/14)",
    lambda b, g: g[5].__setitem__('sum', 99),
    "sum_value")

print("\n  ── Các hỏng hóc khác ──")

thu("Thiếu kỳ ở giữa",
    lambda b, g: g.pop(20),
    "thiếu 1 kỳ")

thu("Trung vị hai bảng lệch nhau",
    lambda b, g: b['sums'].__setitem__(0, {**b['sums'][0], 'median_gap': 77}),
    "trung vị tổng 3")

thu("Trung vị lớn hơn TB (phép tính sai)",
    lambda b, g: b['sums'].__setitem__(4, {**b['sums'][4], 'median_gap': 999}),
    "> TB")

thu("Kỳ có số ngoài 1..6",
    lambda b, g: g[3].__setitem__('numbers', [7, 2, 3]),
    "không hợp lệ")

thu("Kỳ chỉ có 2 số",
    lambda b, g: g[4].__setitem__('numbers', [1, 2]),
    "không hợp lệ")

# 4) secret có ký tự xuống dòng vẫn phải gọi được — lỗi làm job đầu tiên chết
import json as _json, urllib.request as _ur
import kiem_tra_nhat_quan as K
_goi = []
class _R:
    def __enter__(s): return s
    def __exit__(s, *a): pass
    def read(s): return _json.dumps({"ok": 1}).encode()
_ur.urlopen = lambda req, timeout=None: (_goi.append(dict(req.headers)), _R())[1]
K.lay("https://x/y", "abc123\n")
if _goi and all("\n" not in v for v in _goi[0].values()):
    print("\n  OK   Secret có xuống dòng -> vẫn tạo được header hợp lệ")
else:
    fails.append(f"header còn ký tự xuống dòng: {_goi}")
    print(f"\n  FAIL header còn xuống dòng: {_goi}")

# 5) không gọi được -> KhongGoiDuoc, không được lẫn với "dữ liệu lệch"
_ur.urlopen = lambda req, timeout=None: (_ for _ in ()).throw(OSError("mạng hỏng"))
try:
    K.lay("https://x/y", "abc")
    fails.append("lỗi mạng mà không ném KhongGoiDuoc")
    print("  FAIL lỗi mạng mà im lặng")
except K.KhongGoiDuoc:
    print("  OK   Lỗi mạng -> KhongGoiDuoc (phân biệt với dữ liệu lệch)")
except Exception as e:
    fails.append(f"ném sai loại: {type(e).__name__}")
    print(f"  FAIL ném sai loại: {type(e).__name__}")

# 6) payload rỗng không được im lặng nuốt
loi = kiem_tra({'sums': [], 'triples': []}, [])
if loi:
    print(f"\n  OK   Payload rỗng -> báo lỗi, không im lặng bỏ qua")
else:
    fails.append("payload rỗng mà không báo gì")
    print(f"\n  FAIL Payload rỗng mà im lặng")

print("=" * 66)
tong = 12
print(f"RESULTS: {tong - len(fails)} passed, {len(fails)} failed")
for f in fails:
    print("  FAIL " + f)
print("=" * 66)
print("ALL TESTS PASSED" if not fails else "TESTS FAILED")
raise SystemExit(1 if fails else 0)
