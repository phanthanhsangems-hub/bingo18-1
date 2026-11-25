"""Cổng kiểm duyệt luật mới (kiem_duyet_luat.py): chạy offline trên dữ liệu tổng hợp.

Cổng phải làm đúng HAI việc ngược nhau:
  - CHẶN luật vô nghĩa trên dữ liệu ngẫu nhiên (không được qua dù nghe rất hợp lý);
  - CHO QUA luật có tín hiệu thật khi ta cố tình gieo tín hiệu vào dữ liệu.
Cộng thêm: không rò rỉ tương lai, không nhìn xuyên lỗ hổng id, hiệu chỉnh đa phép thử,
và cờ thoát của dòng lệnh.
"""
import itertools
import json
import os
import tempfile

import numpy as np

import kiem_duyet_luat as K

fails = []
ok_count = 0


def check(cond, msg):
    global ok_count
    if cond:
        ok_count += 1
        print("  OK   " + msg)
    else:
        fails.append(msg)


BO_BA = {0: [], 1: [], 2: []}
for t in itertools.product(range(1, 7), repeat=3):
    BO_BA[int(K.size_cua_tong(sum(t)))].append(t)
NEN3 = np.array([81, 54, 81]) / 216


def sinh(n, giu_nguyen=0.0, seed=1, bat_dau=1000):
    """n kỳ liên tiếp. giu_nguyen = xác suất kỳ sau LẶP LẠI SIZE kỳ trước (0 = độc lập hoàn toàn)."""
    rng = np.random.default_rng(seed)
    kq, size = [], None
    for _ in range(n):
        if size is not None and rng.random() < giu_nguyen:
            s = size
        else:
            s = int(rng.choice(3, p=NEN3))
        size = s
        kq.append(BO_BA[s][rng.integers(len(BO_BA[s]))])
    ids = np.arange(bat_dau, bat_dau + n)
    return ids, np.array(kq)


print("=" * 62)
print("1) Du lieu NGAU NHIEN: cong phai chan moi luat")
ids, kq = sinh(12000, 0.0, seed=11)
for ten in ('luon_lon', 'nong_30', 'cung_ky_truoc', 'ngau_nhien', 'chi_khi_chuoi_3'):
    r = K.kiem_duyet(K.LUAT_MAU[ten], ids, kq, ten=ten, so_phep_thu=5, placebo=30)
    check(not r['dat'], "%s khong qua cong tren du lieu ngau nhien (ly do: %d)" % (ten, len(r['ly_do_that_bai'])))

print("\n2) Du lieu co TIN HIEU gieo san (lap lai SIZE ky truoc 15%)")
ids, kq = sinh(12000, 0.15, seed=12)
r = K.kiem_duyet(K.cung_ky_truoc, ids, kq, ten='cung_ky_truoc', so_phep_thu=5, placebo=30)
check(r['dat'], "luat 'cung ky truoc' QUA cong khi tin hieu co that (thang %s, nen %s)"
      % (r['giu_ra']['ty_le'], r['giu_ra']['nen']))
check(r['giu_ra']['ktc_duoi'] > r['giu_ra']['nen'], "KTC95 giu ra nam han tren nen")
check(r['so_doan_vuot_nen'] == 4, "ca 4 doan giu ra deu vuot nen")
r2 = K.kiem_duyet(K.nguoc_ky_truoc, ids, kq, ten='nguoc_ky_truoc', so_phep_thu=5, placebo=30)
check(not r2['dat'], "luat NGUOC lai bi chan (khong the vua 'cung' vua 'nguoc' deu dung)")

print("\n3) Hieu chinh da phep thu")
check(K.hieu_chinh_p(0.004, 1) == 0.004, "K=1 giu nguyen p")
check(abs(K.hieu_chinh_p(0.004, 20) - 0.08) < 1e-12, "K=20: p 0.004 -> 0.08 (khong con dat < 0.05)")
check(K.hieu_chinh_p(0.2, 50) == 1.0, "p da hieu chinh toi da 1")
check(K.hieu_chinh_p(None, 5) is None, "p None -> None")
rk1 = K.kiem_duyet(K.cung_ky_truoc, ids, kq, so_phep_thu=1, placebo=0)
rk2 = K.kiem_duyet(K.cung_ky_truoc, ids, kq, so_phep_thu=10 ** 17, placebo=0)
check(rk1['giu_ra']['p_hieu_chinh'] < 0.05 and rk2['giu_ra']['p_hieu_chinh'] == 1.0,
      "thu qua nhieu bien the (K lon) thi cung luat do khong con qua")
check(not rk1['dat'] and any('placebo' in x.lower() for x in rk1['ly_do_that_bai']),
      "tat placebo (--placebo 0) thi khong bao gio 'dat'")

print("\n4) Khong ro ri tuong lai, khong nhin xuyen lo hong")
ids_h = np.concatenate([np.arange(1000, 1700), np.arange(2000, 3000)])   # lo hong id 1700..1999
kq_h = sinh(len(ids_h), 0.0, seed=13)[1]
khoi = K.tach_khoi(ids_h)
check(len(khoi) == 2 and len(khoi[0]) == 700 and len(khoi[1]) == 1000, "tach khoi tai cho khuyet id")
diem = K._diem_danh_gia(khoi, 200)
check(all(ids_h[vt] - ids_h[dau] == vt - dau and vt - dau >= 200 for vt, dau in diem),
      "moi diem danh gia: lich su lien tuc khong xuyen lo hong, du warmup")
check(len(diem) == (700 - 200) + (1000 - 200), "dem dung so diem danh gia")

da_goi = []


def do_tham(ls):
    da_goi.append(ls)
    return 'LON'


K.kiem_duyet(do_tham, ids_h, kq_h, placebo=0)
check(all(ls.base is None for ls in da_goi), "luat nhan BAN SAO (khong .base de voi toi mang goc)")
check(all(len(ls) <= K.MAX_LICH_SU for ls in da_goi), "do dai lich su <= MAX_LICH_SU")
# Luat nhan dung cac ky ngay truoc ky can doan: kiem tra bang ky hieu rieng
kq_mau = np.array(kq_h, dtype=np.int8)
vt0, dau0 = diem[0]
check(da_goi[0].shape == (vt0 - dau0, 3) and np.array_equal(da_goi[0], kq_mau[dau0:vt0]),
      "lich su gui cho luat = dung cac ky [dau khoi, t), khong gom ky t")

print("\n5) Dau vao sai / bien")
def luat_sai(ls):
    return 'XYZ'
try:
    K.kiem_duyet(luat_sai, ids, kq, placebo=0)
    check(False, "luat tra gia tri la phai bi tu choi")
except ValueError:
    check(True, "luat tra gia tri la ('XYZ') bi tu choi")
try:
    K.kiem_duyet(K.luon_lon, ids[:300], kq[:300], placebo=0)
    check(False, "qua it ky phai bao loi")
except ValueError:
    check(True, "qua it ky -> bao loi ro rang thay vi ket luan bua")
check(K.kiem_duyet(lambda ls: None, ids, kq, placebo=0)['dat'] is False, "luat luon bo qua -> khong dat (khong du mau/do phu)")

print("\n6) Dong lenh + tai du lieu")
tmp = tempfile.mkdtemp()
duong = os.path.join(tmp, 'kq.jsonl')
with open(duong, 'w', encoding='utf-8') as f:
    for i, t in zip(ids, kq):
        f.write(json.dumps({"date": "2026-01-01", "id": "%07d" % i, "result": [int(x) for x in t]}) + "\n")
    f.write("khong phai json\n")
    f.write(json.dumps({"id": "9999999", "result": [1, 2, 9]}) + "\n")     # so ngoai 1-6 bi bo qua
i2, k2 = K.tai_du_lieu(duong)
check(len(i2) == len(ids) and np.array_equal(k2, kq), "doc jsonl: bo dong hong va dong sai so, khong mat ky nao")
rc = K.main(['--du-lieu', duong, '--luat', 'cung_ky_truoc', '--placebo', '30', '--json', os.path.join(tmp, 'o.json')])
check(rc == 0, "ma thoat 0 khi moi luat qua cong")
rc = K.main(['--du-lieu', duong, '--luat', 'luon_lon', '--placebo', '0'])
check(rc == 1, "ma thoat 1 khi co luat khong qua")
rc = K.main(['--du-lieu', os.path.join(tmp, 'khong_co.jsonl'), '--luat', 'luon_lon'])
check(rc == 2, "ma thoat 2 khi khong chay duoc (khong doc duoc du lieu)")
rc = K.main(['--du-lieu', duong, '--luat', 'khong_co_luat_nay'])
check(rc == 2, "ma thoat 2 khi ten luat sai")
luat_file = os.path.join(tmp, 'luat_cua_toi.py')
open(luat_file, 'w', encoding='utf-8').write("def dau_tien(ls):\n    return 'LON'\n")
ten, fn = K.nap_luat(luat_file + ':dau_tien')
check(fn(None) == 'LON' and ten == 'luat_cua_toi.py:dau_tien', "nap luat tu file .py:ten_ham")
out = json.load(open(os.path.join(tmp, 'o.json'), encoding='utf-8'))
check(out[0]['luat'] == 'cung_ky_truoc' and out[0]['dat'] is True, "--json ghi ket qua")

print("=" * 62)
print("RESULTS: %d passed, %d failed" % (ok_count, len(fails)))
for f in fails:
    print("  FAIL " + f)
print("=" * 62)
print("ALL TESTS PASSED" if not fails else "TESTS FAILED")
raise SystemExit(1 if fails else 0)
