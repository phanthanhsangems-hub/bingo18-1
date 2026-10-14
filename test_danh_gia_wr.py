"""P264: danh gia ty le thang so voi muc ngau nhien 37,5% (Wilson 95%)."""
import os, sys
os.environ.setdefault('DATABASE_URL', '')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as A
DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))
f = A._danh_gia_wr
print("=== 1. tuan 1000 ky ===")
kiem("38,6% tren 1000 ky -> KHONG khac (khop so da bao)", 'KHÔNG khác' in f(386, 1000), f(386, 1000))
kiem("45% tren 1000 ky -> VUOT", 'VƯỢT' in f(450, 1000), f(450, 1000))
kiem("30% tren 1000 ky -> DUOI", 'DƯỚI' in f(300, 1000), f(300, 1000))
print("=== 2. mau nho ===")
kiem("5/10 -> KHONG khac (mau nho khong ket luan duoc)", 'KHÔNG khác' in f(5, 10), f(5, 10))
kiem("0 ky -> chua du", f(0, 0) == "chưa đủ kỳ để đánh giá")
print("=== 3. khoang Wilson dung ===")
txt = f(386, 1000)
kiem("khoang 95% ~ 35.6–41.7 (tinh tay)", '35.' in txt and '41.' in txt, txt)
kiem("bieu dien phan tram 1 chu so", '38.6%' in txt, txt)
print("=== 4. tich hop tong ket tuan ===")
src = open('app.py', encoding='utf-8').read()
kiem("tong ket tuan co dong so voi ngau nhien", "📐 So với ngẫu nhiên: {danh_gia}" in src)
print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
