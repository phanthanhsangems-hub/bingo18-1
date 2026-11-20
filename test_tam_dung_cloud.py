"""P298h: dashboard mở qua Cloud Run (*.run.app) rồi để quên -> tự tạm dừng sau 10 phút
không dùng; trang để mở lâu tự tải lại khi có phiên bản giao diện mới (/api/phien-ban).

Hành vi thật đã thử bằng Chromium + đồng hồ giả (Playwright): trang run.app không gọi máy
chủ lần nào trong 10 phút nghỉ, di chuột thì nạp lại ngay; localhost không tạm dừng;
phiên bản khác + không ai dùng -> tải lại đúng 1 lần, đang dùng -> không tải lại.
Test này giữ các điểm đó khỏi bị sửa mất (CI không có trình duyệt).
"""
import os, re, sys, tempfile
os.environ.pop('DATABASE_URL', None)
os.environ['DB_PATH'] = os.path.join(tempfile.mkdtemp(), 't.db')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
config.DB_PATH = os.environ['DB_PATH']

DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))

JS = open('static/js/dashboard.js', encoding='utf-8').read()
H = open('templates/dashboard.html', encoding='utf-8').read()
CSS = open('static/css/dashboard.css', encoding='utf-8').read()
print("=== 1. TAM DUNG KHI MO QUA CLOUD RUN ===")
kiem("chi tam dung tren *.run.app", "const TREN_CLOUD = /\\.run\\.app$/i.test(location.hostname);" in JS)
kiem("10 phut khong dung", 'const NGHI_SAU_MS = 10 * 60 * 1000;' in JS)
kiem("moi setInterval goi may chu deu qua khiHien -> duocGoiMayChu",
     'const khiHien = fn => () => { if (duocGoiMayChu()) fn(); };' in JS
     and not re.search(r"setInterval\((?!khiHien\(|tick)", JS), re.findall(r"setInterval\([^,]+", JS))
kiem("tab an thi van khong goi (giu P286)", "if (document.visibilityState !== 'visible') return false;" in JS)
kiem("cham / di chuot / phim / cuon -> dung lai", all(e in JS for e in ("'pointerdown'", "'pointermove'", "'keydown'", "'touchstart'", "'wheel'", "'scroll'")))
kiem("dung lai -> nap ngay", re.search(r"function _danhThuc\(\)[\s\S]{0,200}refreshAllVaGhiMoc\(\)", JS) is not None)
kiem("quay lai tab = dang dung", "_lanDungCuoi = Date.now();                       // P298h" in JS)
kiem("bang bao tam dung co chu 'tốn phí'", 'tốn phí' in JS and "el.id = 'bang-nghi'" in JS)
kiem("CSS .bang-nghi + [hidden]", '.bang-nghi{' in CSS and '.bang-nghi[hidden]{display:none}' in CSS)

print("=== 2. TU TAI LAI KHI CO PHIEN BAN MOI ===")
kiem("JS doc phien ban cua chinh no tu the <script>", 'document.currentScript.src' in JS)
kiem("hoi /api/phien-ban moi 10 phut", "setInterval(khiHien(kiemTraPhienBan), 600000);" in JS and "J('/api/phien-ban')" in JS)
kiem("chi tai lai khi 1 phut khong ai thao tac", 'd.v !== JS_VER && Date.now() - _lanDungCuoi > 60000) location.reload()' in JS)
v = re.search(r'dashboard\.js\?v=([\w.-]+)', H).group(1)
kiem("css va js cung phien ban", f'dashboard.css?v={v}' in H, v)
import app as A
r = A.app.test_client().get('/api/phien-ban')
kiem("/api/phien-ban tra dung phien ban trong template", r.status_code == 200 and r.get_json() == {'v': v}, (r.status_code, r.data[:80]))
kiem("/api/phien-ban khong cache", r.headers.get('Cache-Control') == 'no-store')

print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
