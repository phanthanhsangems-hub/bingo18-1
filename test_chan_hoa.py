"""P262: khong bao gio dua ra du doan HOA (tong 10-11) — cong cuoi truoc khi ghi DB."""
import os, sys, itertools
os.environ.setdefault('DATABASE_URL', '')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prediction_service as P
DAT = HONG = 0
def kiem(t, ok, ct=''):
    global DAT, HONG
    if ok: DAT += 1
    else: HONG += 1
    print(f"  {'DAT ' if ok else 'HONG'} {t}" + ('' if ok else f" -> {ct}"))
def cat(n): s = sum(n); return 'NHO' if s <= 9 else ('HOA' if s <= 11 else 'LON')

print("=== 1. moi bo HOA deu bi doi sang NHO/LON, doi it nhat co the ===")
hoa = [c for c in itertools.combinations_with_replacement(range(1, 7), 3) if 10 <= sum(c) <= 11]
kiem("co 12 bo HOA (khong thu tu) de thu", len(hoa) == 12, len(hoa))
ok_all = True
for c in hoa:
    moi, note = P._chan_hoa(list(c), None, set())
    if cat(moi) == 'HOA' or note is None: ok_all = False; print('   lot:', c, moi)
    # chi doi dung 1 so, lech 1
    khac = sum(1 for a, b in zip(sorted(c), sorted(moi)) if a != b)
    if khac != 1 or abs(sum(moi) - sum(c)) != 1: ok_all = False; print('   doi nhieu:', c, moi)
kiem("12/12 bo HOA -> khong con HOA, chi doi 1 so di 1 don vi", ok_all)
kiem("tong 10 (khong co vote) -> NHO", cat(P._chan_hoa([3,3,4], None, set())[0]) == 'NHO')
kiem("tong 11 (khong co vote) -> LON", cat(P._chan_hoa([3,4,4], None, set())[0]) == 'LON')

print("\n=== 2. theo SIZE da so cua vote ===")
kiem("tong 10 nhung vote LON -> LON", cat(P._chan_hoa([3,3,4], {'majority_size': 'LON'}, set())[0]) == 'LON')
kiem("tong 11 nhung vote NHO -> NHO", cat(P._chan_hoa([3,4,4], {'majority_size': 'NHO'}, set())[0]) == 'NHO')
kiem("vote HOA -> bo qua vote, theo phia gan hon", cat(P._chan_hoa([3,3,4], {'majority_size': 'HOA'}, set())[0]) == 'NHO')

print("\n=== 3. NHO/LON giu nguyen; bo cam ===")
kiem("NHO giu nguyen, khong ghi chu", P._chan_hoa([1,2,3], None, set()) == ([1,2,3], None))
kiem("LON giu nguyen", P._chan_hoa([4,4,6], None, set()) == ([4,4,6], None))
cam = {(2,3,4), (1,3,4), (2,2,4), (2,3,3)}        # moi bo cach 1 buoc tu 3-3-4 ve NHO
moi, note = P._chan_hoa([3,3,4], None, cam)
kiem("bo gan nhat bi cam -> van ra NHO khac, khong cam", cat(moi) == 'NHO' and tuple(moi) not in cam, (moi, note))
kiem("ghi chu co dang HOA_chan:cu->moi(dich)", note and note.startswith('HOA_chan:3-3-4->') and note.endswith('(NHO)'), note)

print("\n=== 4. duoc goi ngay truoc insert_prediction, cho moi mode ===")
src = open('prediction_service.py', encoding='utf-8').read()
i = src.index('numbers, _hoa_note = _chan_hoa(numbers, _vote_info, banned)')
kiem("goi sau hot-adjust, truoc P148 final_size va insert_prediction",
     src.index('_hot_adjust_size(numbers, df, _current_loss_streak, banned)') < i < src.index("_vote_info['final_size']") < src.index('db.insert_prediction(next_draw'))
kiem("ghi vao vote_breakdown de doi chieu", "_vote_info['hoa_chan'] = _hoa_note" in src)
print(f"\nDAT: {DAT}   HONG: {HONG}")
sys.exit(1 if HONG else 0)
