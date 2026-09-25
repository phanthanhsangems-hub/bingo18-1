"""P222: cảnh báo LỖ HỔNG kỳ ở phía server.

Vì sao cần bộ test này: hệ thống ĐÃ có _check_sync_lag() bắn Telegram khi dữ
liệu cũ, gọi mỗi 6 phút từ /api/predict. Nhưng cả bốn sự cố tháng 9 đều là lỗ
hổng Ở GIỮA trong khi kỳ mới vẫn về đều — lag ≈ 0 nên nó không bao giờ bắn, và
lần nào người dùng cũng phát hiện trước. Test đầu tiên dưới đây khoá đúng chỗ
đó lại: dựng cảnh 22/09 thật (thiếu #187690-#187700, kỳ mới nhất #187707) rồi
đòi hàm mới PHẢI bắn.
"""
import os, sys, types, importlib
from unittest import mock

os.environ.setdefault('DATABASE_URL', '')
os.environ.pop('APP_USER', None)

import app as A

DAT = HONG = 0
def kiem(ten, dieu_kien, chi_tiet=''):
    global DAT, HONG
    if dieu_kien:
        DAT += 1; print(f"  DAT  {ten}")
    else:
        HONG += 1; print(f"  HONG {ten}" + (f"  -> {chi_tiet}" if chi_tiet else ''))

class GiaCursor:
    def __init__(self, dns): self.dns = dns
    def execute(self, *a, **k): pass
    def fetchall(self): return [(n,) for n in sorted(self.dns, reverse=True)]
    def close(self): pass

class GiaConn:
    def __init__(self, dns): self.dns = dns; self.da_dong = False
    def cursor(self): return GiaCursor(self.dns)
    def close(self): self.da_dong = True

def chay(dns, gio_vn=14, reset=True):
    """Chạy _check_draw_gap_alert với danh sách kỳ dựng sẵn. Trả về list tin đã gửi."""
    if reset:
        A._last_gap_alert_ts = 0.0
        A._last_gap_alert_sig = ''
    tin = []
    conn = GiaConn(dns)
    bot = mock.MagicMock()
    bot.send_message.side_effect = lambda m, *a, **k: tin.append(m)
    gia_tb = types.ModuleType('telegram_bot')
    gia_tb.TelegramBot = lambda *a, **k: bot
    from datetime import datetime as _dt, timezone as _tz
    class GiaNow(_dt):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 22, gio_vn, 30, tzinfo=tz)
    with mock.patch.dict(sys.modules, {'telegram_bot': gia_tb}), \
         mock.patch.object(A.db, 'get_connection', return_value=conn), \
         mock.patch.object(A, 'datetime', GiaNow):
        A._check_draw_gap_alert()
    return tin, conn

print("=== 1. GOM DOAN ===")
kiem("[5,6,7,10] -> [(5,7),(10,10)]", A._gom_doan([5,6,7,10]) == [(5,7),(10,10)],
     str(A._gom_doan([5,6,7,10])))
kiem("rong -> rong", A._gom_doan([]) == [])
kiem("mot so -> mot doan 1 ky", A._gom_doan([9]) == [(9,9)])
kiem("khong theo thu tu van gom dung", A._gom_doan([3,1,2]) == [(1,3)])

print("\n=== 2. CANH THAT 22/09: thieu #187690-#187700, ky moi van ve ===")
dns = [n for n in range(187600, 187708) if not (187690 <= n <= 187700)]
tin, conn = chay(dns)
kiem("PHAI ban canh bao (day la ca _check_sync_lag bo sot)", len(tin) == 1, f"{len(tin)} tin")
if tin:
    kiem("neu dung 11 ky", "11 kỳ" in tin[0], tin[0][:90])
    kiem("neu dung doan #187690-#187700", "#187690-#187700" in tin[0], tin[0][:120])
    kiem("muc CRITICAL vi >= 10 ky", "CRITICAL" in tin[0])
    kiem("chi ro cach bu", "--mode gaps" in tin[0])
    kiem("noi ro bang dang tinh sai", "SAI" in tin[0])
kiem("connection duoc dong", conn.da_dong)

print("\n=== 3. CANH THAT 23/09: thieu #187881 va #187884-#187886 ===")
dns2 = [n for n in range(187800, 187890) if n not in (187881, 187884, 187885, 187886)]
tin, _ = chay(dns2)
kiem("co ban canh bao", len(tin) == 1)
if tin:
    kiem("neu ca hai doan", "#187881" in tin[0] and "#187884-#187886" in tin[0], tin[0][:140])
    kiem("muc WARNING vi chi 4 ky", "WARNING" in tin[0] and "CRITICAL" not in tin[0])

print("\n=== 4. LIEN MACH thi KHONG ban ===")
tin, _ = chay(list(range(187600, 187708)))
kiem("khong tin nao", len(tin) == 0, f"{len(tin)} tin")

print("\n=== 5. CHONG SPAM: cung lo hong thi khong ban lai ===")
A._last_gap_alert_ts = 0.0; A._last_gap_alert_sig = ''
tin1, _ = chay(dns, reset=False)
tin2, _ = chay(dns, reset=False)
kiem("lan dau ban", len(tin1) == 1)
kiem("lan hai IM (con cooldown)", len(tin2) == 0, f"{len(tin2)} tin")

print("\n=== 6. LO HONG MOI thi ban NGAY, cooldown khong duoc che ===")
A._last_gap_alert_ts = 0.0; A._last_gap_alert_sig = ''
tin1, _ = chay(dns, reset=False)
dns_moi = [n for n in dns if n != 187705]      # them mot lo moi
tin2, _ = chay(dns_moi, reset=False)
kiem("lan dau ban", len(tin1) == 1)
kiem("lo hong MOI ban ngay du con cooldown", len(tin2) == 1, f"{len(tin2)} tin")
if tin2:
    kiem("tin moi neu ca lo moi", "#187705" in tin2[0], tin2[0][:140])

print("\n=== 7. HOI PHUC: bao mot tin dut diem roi thoi ===")
A._last_gap_alert_ts = 0.0; A._last_gap_alert_sig = ''
chay(dns, reset=False)
tin_hp, _ = chay(list(range(187600, 187708)), reset=False)
kiem("bao da lien mach", len(tin_hp) == 1 and "liền mạch" in tin_hp[0],
     tin_hp[0][:80] if tin_hp else 'khong co tin')
tin_im, _ = chay(list(range(187600, 187708)), reset=False)
kiem("lien mach tiep thi IM", len(tin_im) == 0, f"{len(tin_im)} tin")

print("\n=== 8. NGOAI GIO XO (22h-6h) thi KHONG ban ===")
for g in (23, 3, 5):
    tin, _ = chay(dns, gio_vn=g)
    kiem(f"{g}h khong ban", len(tin) == 0, f"{len(tin)} tin")
tin, _ = chay(dns, gio_vn=6)
kiem("6h CO ban (bien duoi cua gio xo)", len(tin) == 1)
tin, _ = chay(dns, gio_vn=21)
kiem("21h CO ban (bien tren)", len(tin) == 1)

print("\n=== 9. KHONG DUOC LAM CHET VONG DU DOAN ===")
with mock.patch.object(A.db, 'get_connection', side_effect=RuntimeError('DB sap')):
    try:
        A._check_draw_gap_alert(); ok = True
    except Exception as e:
        ok = False
    kiem("DB sap -> nuot loi, khong nem ra", ok)
tin, _ = chay([187700])
kiem("chi 1 ky trong DB -> khong ban, khong chet", len(tin) == 0)
tin, _ = chay([])
kiem("DB rong -> khong ban, khong chet", len(tin) == 0)

print("\n=== 10. DOAN THIEU QUA NHIEU thi rut gon tin ===")
dns_nhieu = [n for n in range(187500, 187708) if n % 7 != 0]   # ~30 doan
tin, _ = chay(dns_nhieu)
kiem("co ban", len(tin) == 1)
if tin:
    kiem("co rut gon '+N doan nua'", "đoạn nữa" in tin[0], tin[0][:200])
    kiem("tin khong qua dai (< 1200 ky tu)", len(tin[0]) < 1200, f"{len(tin[0])} ky tu")

print("\n" + "=" * 52)
print(f"DAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
