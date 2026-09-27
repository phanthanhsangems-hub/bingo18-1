"""P232: bat/tat tung the tren dashboard.

Nguoi dung: "Them chuc nang bat tat vao moi phan" -> chon "tung the tren
dashboard", dieu khien bang "trang cai dat tren dashboard".

Diem de sai nhat o day KHONG phai viec an/hien, ma la:
  - khoa the phai khop giua HTML, JS va danh sach trang trong app.py;
    lech mot khoa la mot the khong bao gio an duoc, im lang
  - khoa phai loc CA LUC DOC, vi khoa cua the da go (ll-*, ts-*) con sot
    trong DB
  - loi doc cai dat phai tra [] (hien du moi the), khong duoc giau mat the
"""
import os, sys, json
from unittest import mock

os.environ.setdefault('DATABASE_URL', '')
os.environ.pop('APP_USER', None)
import app as A
A.limiter.enabled = False

DAT = HONG = 0
def kiem(ten, dk, ct=''):
    global DAT, HONG
    if dk: DAT += 1; print(f"  DAT  {ten}")
    else:  HONG += 1; print(f"  HONG {ten}" + (f"  -> {ct}" if ct else ''))

HTML = open('templates/dashboard.html', encoding='utf-8').read()
JS   = open('static/js/dashboard.js',   encoding='utf-8').read()
CSS  = open('static/css/dashboard.css', encoding='utf-8').read()
APP  = open('app.py',                   encoding='utf-8').read()


def gia_db(gia_tri=None, no=False):
    """Gia lap system_config. gia_tri=None -> chua co ban ghi."""
    luu = {}
    class C:
        def execute(s, q, *a):
            if no: raise RuntimeError('DB die')
            s.a = a[0] if a else ()
            if q.strip().upper().startswith('SELECT'): s.sel = True
            else: luu['an'] = s.a[1]
        def fetchone(s): return None if gia_tri is None else (gia_tri,)
        def close(s): pass
    class K:
        def cursor(s):
            if no: raise RuntimeError('DB die')
            return C()
        def commit(s): pass
        def close(s): pass
    return K(), luu


def doc(gia_tri=None, no=False):
    k, _ = gia_db(gia_tri, no)
    with mock.patch.object(A.db, 'get_connection', return_value=k):
        return A.app.test_client().get('/api/cai-dat/the').get_json()


def ghi(than, gia_tri=None):
    k, luu = gia_db(gia_tri)
    with mock.patch.object(A.db, 'get_connection', return_value=k):
        r = A.app.test_client().post('/api/cai-dat/the', json=than)
    return r, luu


print("=== 1. KHOA PHAI KHOP GIUA HTML, JS VA app.py ===")
import re
khoa_html = set(re.findall(r'data-the="([^"]+)"', HTML))
khoa_js   = set(re.findall(r"^\s*'([a-z0-9-]+)':\s*'", JS, re.M))
khoa_app  = set(A._THE_DASHBOARD)
kiem(f"app.py co dung 14 khoa", len(khoa_app) == 14, str(len(khoa_app)))
kiem("HTML gan du 14 the", len(khoa_html) == 14, str(sorted(khoa_html)))
kiem("HTML khop app.py", khoa_html == khoa_app,
     f"thieu {khoa_app - khoa_html} / thua {khoa_html - khoa_app}")
kiem("JS co ten hien thi cho DU moi khoa", khoa_app <= khoa_js,
     f"JS thieu {khoa_app - khoa_js}")
kiem("khong khoa nao rong", all(k.strip() for k in khoa_app))

print("\n=== 2. DOC CAI DAT ===")
d = doc(None)
kiem("chua co ban ghi -> khong an gi", d['an'] == [])
kiem("tra ve ca danh sach day du", set(d['tat_ca']) == khoa_app)
d = doc('luoi,cau')
kiem("doc dung hai khoa", d['an'] == ['luoi', 'cau'], str(d['an']))
# Day la cai bay that: the ll-* va ts-* da go o P230/P231.
d = doc('luoi,theo-sau,lap-lai,cau')
kiem("LOC LUC DOC: khoa cua the da go bi bo",
     d['an'] == ['luoi', 'cau'], str(d['an']))
d = doc('')
kiem("chuoi rong -> []", d['an'] == [])
kiem("DB chet -> [] (hien du moi the, khong giau mat)",
     doc(no=True)['an'] == [])

print("\n=== 3. GHI CAI DAT ===")
r, luu = ghi({'an': ['luoi', 'cau']})
kiem("ghi thanh cong", r.status_code == 200, str(r.status_code))
kiem("luu dung vao DB", luu.get('an') == 'cau,luoi', str(luu.get('an')))
kiem("tra lai dung cai da luu", r.get_json()['an'] == ['cau', 'luoi'])

r, luu = ghi({'an': ['luoi', 'rac', '<script>', 'cau']})
kiem("LOC LUC GHI: khoa la bi bo", r.get_json()['an'] == ['cau', 'luoi'])
kiem("bao lai khoa nao bi bo qua",
     set(r.get_json()['bo_qua']) == {'rac', '<script>'},
     str(r.get_json()['bo_qua']))
kiem("khong ghi rac vao DB", 'rac' not in luu.get('an', ''))

r, _ = ghi({'an': ['luoi', 'luoi', 'luoi']})
kiem("trung lap -> gop lai mot", r.get_json()['an'] == ['luoi'])

r, luu = ghi({'an': []})
kiem("mang rong = hien lai tat ca", r.get_json()['an'] == [])
kiem("DB luu chuoi rong", luu.get('an') == '')

print("\n=== 4. DAU VAO XAU -> KHONG CHET ===")
for xau, ten in [({'an': 'luoi'}, "chuoi thay vi mang"),
                 ({'an': 123},    "so thay vi mang"),
                 ({},             "thieu truong 'an'"),
                 ({'an': None},   "an=null")]:
    r, _ = ghi(xau)
    kiem(f"{ten} -> 400 chu khong 500", r.status_code == 400, str(r.status_code))
r, _ = ghi({'an': [1, 2, None, {'a': 1}]})
kiem("mang chua thu la -> loc sach, van 200",
     r.status_code == 200 and r.get_json()['an'] == [])

print("\n=== 5. GIAO DIEN ===")
kiem("co the cai dat", 'id="cd-luoi"' in HTML)
kiem("co nut mo/dong", 'id="cd-mo"' in HTML and 'id="cd-than"' in HTML)
kiem("co nut hien lai tat ca", 'id="cd-reset"' in HTML)
kiem("than dong san (hidden)", 'id="cd-than" hidden' in HTML)
kiem("co aria-expanded cho nut gap", 'aria-expanded' in HTML)
kiem("co aria-controls tro dung than", 'aria-controls="cd-than"' in HTML)
kiem("vung trang thai co aria-live", 'aria-live="polite"' in HTML)
kiem("grid2 co data-nhom (an ca hai the bieu do thi an luon khung)",
     'data-nhom="1"' in HTML)
kiem("JS an ca khung khi moi con deu an", 'data-nhom' in JS and '.every(' in JS)
kiem("JS dung localStorage lam BO NHO DEM chong chop",
     'CD_DEM_KEY' in JS and 'localStorage' in JS)
kiem("JS boc try/catch quanh localStorage (che do rieng tu)",
     JS.count('catch (e) { return []; }') >= 1)
kiem("JS goi POST de luu", "method: 'POST'" in JS)
kiem("JS bao khi CHUA luu duoc len may chu", 'Chưa lưu được' in JS)
kiem("may chu thang khi doi chieu", '/api/cai-dat/the' in JS)
kiem("CSS co .cd-luoi", '.cd-luoi' in CSS)
kiem("o tick du to de bam tren dien thoai",
     'width: 17px' in CSS or 'width:17px' in CSS)

print("\n=== 6. DANG KY & AN TOAN ===")
ds = open('scripts/endpoints_readonly.txt', encoding='utf-8').read()
kiem("GET da dang ky vao bo quet", '/api/cai-dat/the' in ds)
kiem("endpoint nam SAU cong dang nhap (khong vao _PUBLIC_PATHS)",
     '/api/cai-dat/the' not in str(getattr(A, '_PUBLIC_PATHS', '')))
kiem("khong vao _CRON_PATHS",
     '/api/cai-dat/the' not in str(getattr(A, '_CRON_PATHS', '')))
kiem("co gioi han toc do", "@limiter.limit(\"60 per minute\")" in APP)
kiem("co danh sach trang trong app.py", '_THE_DASHBOARD' in APP)

print("\n=== 7. PHONG TO / THU NHO (P233) ===")
kiem("nac tu 80% den 200%", A._NAC_PHONG[0] == 0.8 and A._NAC_PHONG[-1] == 2.0)
kiem("1.0 nam trong thang", 1.0 in A._NAC_PHONG)
for vao, ra in [(1.25, 1.25), (1.3, 1.25), (0.1, 0.8), (99, 2.0), ('1.5', 1.5),
                ('abc', 1.0), (None, 1.0), (float('nan'), 1.0),
                (float('inf'), 1.0), (-5, 0.8)]:
    kiem(f"_gan_nac({vao!r}) = {ra}", A._gan_nac(vao) == ra, str(A._gan_nac(vao)))

def doc_phong(bang):
    """bang: {config_key: value} gia lap system_config."""
    class C:
        def execute(s, q, *a): s.k = a[0][0] if a and a[0] else None
        def fetchone(s): v = bang.get(s.k); return None if v is None else (v,)
        def close(s): pass
    class K:
        def cursor(s): return C()
        def close(s): pass
    with mock.patch.object(A.db, 'get_connection', return_value=K()):
        return A.app.test_client().get('/api/cai-dat/the').get_json()

d = doc_phong({})
kiem("chua luu gi -> ca hai 1.0", d['phong'] == {'trang': 1.0, 'bang': 1.0}, str(d['phong']))
kiem("tra ve danh sach nac cho giao dien", d['nac'] == list(A._NAC_PHONG))
d = doc_phong({'dashboard_phong_trang': '1.5', 'dashboard_phong_bang': '1.25'})
kiem("doc dung muc da luu", d['phong'] == {'trang': 1.5, 'bang': 1.25}, str(d['phong']))
d = doc_phong({'dashboard_phong_trang': '9999'})
kiem("gia tri la trong DB -> nan ve nac gan nhat", d['phong']['trang'] == 2.0)
d = doc_phong({'dashboard_phong_trang': 'rac'})
kiem("rac trong DB -> 1.0, khong chet", d['phong']['trang'] == 1.0)
with mock.patch.object(A.db, 'get_connection', side_effect=RuntimeError('DB die')):
    d = A.app.test_client().get('/api/cai-dat/the').get_json()
kiem("DB chet -> 1.0 (co thuong, khong phong bua)",
     d['phong'] == {'trang': 1.0, 'bang': 1.0})

r, luu = ghi({'phong': {'trang': 1.5}})
kiem("ghi RIENG phong (khong gui 'an') -> 200", r.status_code == 200, str(r.status_code))
kiem("tra lai muc da luu", r.get_json().get('phong') == {'trang': 1.5})
kiem("KHONG dung toi danh sach the an", 'an' not in r.get_json())
r, _ = ghi({'phong': {'trang': 7, 'bang': 'x'}})
kiem("muc la -> nan lai (7->2.0, 'x'->1.0)",
     r.get_json()['phong'] == {'trang': 2.0, 'bang': 1.0}, str(r.get_json()))
r, _ = ghi({'phong': {'rac': 1.5}})
kiem("khoa la trong phong -> bo qua", r.get_json()['phong'] == {})
r, _ = ghi({'phong': [1, 2]})
kiem("phong khong phai doi tuong -> 400", r.status_code == 400)
r, _ = ghi({'an': ['luoi'], 'phong': {'bang': 1.25}})
kiem("gui ca hai cung luc -> luu ca hai",
     r.get_json().get('an') == ['luoi'] and r.get_json().get('phong') == {'bang': 1.25})

kiem("html: nut A-/A+ cho ca trang", 'id="pt-giam"' in HTML and 'id="pt-tang"' in HTML)
kiem("html: nut A-/A+ cho bang", 'id="pb-giam"' in HTML and 'id="pb-tang"' in HTML)
kiem("html: muc hien thi co aria-live", 'id="pt-muc" role="status" aria-live' in HTML)
kiem("css: zoom .wrap chu KHONG zoom body (topbar sticky)",
     '.wrap { zoom: var(--ty-le-trang); }' in CSS and 'body { zoom' not in CSS)
kiem("css: bang zoom rieng", 'zoom: var(--ty-le-bang)' in CSS)
kiem("css: diem ngat theo be ngang hieu dung (hep-*)", 'html.hep-640' in CSS)
kiem("css: .cd-luoi co duoc (min(240px,100%))", 'minmax(min(240px, 100%), 1fr)' in CSS)
kiem("css: .tiles co duoc (minmax(0,1fr))", 'repeat(4,minmax(0,1fr))' in CSS)
kiem("js: tinh be ngang HIEU DUNG = innerWidth / muc phong",
     'window.innerWidth / (_phong.trang' in JS)
kiem("js: gan nut ⛶ cho moi the", 'the-to-nut' in JS and "querySelectorAll('[data-the]')" in JS)
kiem("js: Esc dong the dang to", "e.key === 'Escape'" in JS)
kiem("js: chi gui muc vua doi, khong gui ca danh sach the",
     "phong: { [ten]: NAC[j] }" in JS)
kiem("js: bat to the KHONG luu (thao tac nhat thoi)",
     'the-to' not in JS.split('async function phongDoi')[1].split('// ── Bật to từng thẻ')[0])

print("\n" + "=" * 54)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
