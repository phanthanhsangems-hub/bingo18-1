"""P266: bang bat/tat the nhanh o goc tren, dung chung du lieu voi Cai dat hien thi."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))
H = open('templates/dashboard.html', encoding='utf-8').read()
J = open('static/js/dashboard.js', encoding='utf-8').read()
C = open('static/css/dashboard.css', encoding='utf-8').read()
print("=== 1. nut va bang o goc tren ===")
kiem("co nut mo o thanh tren (#the-nhanh-mo) dat ngay canh nut doi giao dien",
     H.index('id="the-nhanh-mo"') > H.index('id="theme-btn"') and H.index('id="the-nhanh-mo"') < H.index('<div class="wrap">'))
kiem("bang co role=dialog va mac dinh an", 'id="the-nhanh" role="dialog"' in H and 'id="the-nhanh" role="dialog" aria-label="Bật tắt thẻ" hidden' in H)
kiem("co nut dong ✕", 'id="the-nhanh-dong"' in H)
kiem("aria-expanded + aria-controls", 'aria-controls="the-nhanh"' in H and 'aria-expanded="false"' in H)
print("=== 2. dung chung du lieu ===")
kiem("ca hai luoi dung class cd-luoi-dung", H.count('cd-luoi-dung') >= 2)
kiem("cd-luoi (cuoi trang) van co id cho test cu", 'id="cd-luoi"' in H)
kiem("cdDungBang ve moi .cd-luoi-dung", "document.querySelectorAll('.cd-luoi-dung')" in J)
kiem("bo chon o ca hai noi deu doc danh sach chung", "document.querySelectorAll('.cd-luoi-dung input[data-cd]')" in J)
kiem("luu van qua cdLuu (cung may chu + bo nho dem)", "cdLuu(an);" in J)
print("=== 3. hanh vi ===")
kiem("mo bang -> ve lai danh sach", "if (mo) cdDungBang();" in J)
kiem("Esc dong bang", "e.key === 'Escape'" in J)
kiem("bam ra ngoai dong bang (tru chinh nut mo)", "bang.contains(e.target) || nut.contains(e.target)" in J)
kiem("khoi tao duoc goi trong cdKhoiTao dang chay", "theNhanhKhoiTao();   // P266" in J)
print("=== 4. CSS ===")
kiem("dinh vi co dinh goc phai", '.the-nhanh{' in C and 'position:fixed' in C and 'right:12px' in C)
kiem("khong tran man hinh hep", 'calc(100vw - 24px)' in C and 'max-height:70vh' in C)
kiem("nam tren thanh (z-index > topbar)", 'z-index:60' in C)
print("=== 5. phien ban tai file moi ===")
kiem("css/js ?v=p266", 'dashboard.css?v=p266' in H and 'dashboard.js?v=p267' in H)
print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
