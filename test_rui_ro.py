"""P268: ghi chu ngau nhien + muc nen 37,5% (khong con 35%)."""
import os, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))
H = open('templates/dashboard.html', encoding='utf-8').read()
J = open('static/js/dashboard.js', encoding='utf-8').read()
kiem("co ghi chu ngau nhien tren the du doan", 'Kết quả Bingo18 là ngẫu nhiên' in H)
kiem("ghi chu nam trong hero (cung the du doan)", H.index('rui-ro') > H.index('class="hero"') and H.index('rui-ro') < H.index('class="hero-side"'))
kiem("khong con 'baseline 35%' o giao dien", 'Baseline 35' not in H and 'baseline 35%' not in H)
kiem("JS khong con tru 35", 'conf - 35;' not in J and 'conf - 37.5' in J)
kiem("css ghi chu co kieu", '.rui-ro' in open('static/css/dashboard.css', encoding='utf-8').read())
print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
