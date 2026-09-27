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

print("\n" + "=" * 54)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
