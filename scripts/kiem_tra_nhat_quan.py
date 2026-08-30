#!/usr/bin/env python3
"""Kiểm tra tính nhất quán dữ liệu Bingo18 trên production.

Vì sao tồn tại: mọi lần dữ liệu sai trong quá khứ đều do NGƯỜI DÙNG nhìn thấy
trước — trip 333 báo "chưa về 492 kỳ" trong khi thực tế 88, bảng tổng lệch
bảng trip 1 kỳ, tổng 7/14 hiển thị sai. Hệ thống không tự biết.

Các phép kiểm này trước đây nằm dạng heredoc trong diagnose.yml nên KHÔNG
CHẠY THỬ ĐƯỢC — không ai từng chứng minh chúng thật sự bắt lỗi khi dữ liệu
hỏng. Tách ra thành script để vừa chạy theo lịch, vừa test được bằng dữ liệu
cố tình làm sai.

Dùng:
    python scripts/kiem_tra_nhat_quan.py                  # gọi production
    python scripts/kiem_tra_nhat_quan.py --tu-file a.json b.json   # test
"""
import argparse
import json
import os
import sys
import urllib.request

BASE = "https://bingo18-633959711537.asia-southeast1.run.app"


def lay(url: str, secret: str) -> dict:
    req = urllib.request.Request(url, headers={"X-Trigger-Secret": secret})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())


def kiem_tra(board: dict, grid: list) -> list:
    """Trả về danh sách lỗi. Rỗng = mọi thứ nhất quán."""
    loi = []
    sums = {x["sum"]: x for x in board.get("sums", [])}
    trips = {x["combo"]: x for x in board.get("triples", [])}
    if not sums or not trips:
        return ["board-stats thiếu 'sums' hoặc 'triples'"]

    # 1. Lỗ hổng kỳ — nguyên nhân gốc của vụ trip 333
    co = {d["draw_number"] for d in grid}
    if co:
        lo, hi = min(co), max(co)
        thieu = sorted(set(range(lo, hi + 1)) - co)
        if thieu:
            loi.append(f"thiếu {len(thieu)} kỳ trong #{lo}-#{hi}: {thieu[:10]}")

    # 2. Tổng 3 CHỈ ra được từ 111, tổng 18 CHỈ ra được từ 666.
    #    Hai bảng tính bằng hai đường code khác nhau nên đây là phép đối chiếu
    #    chéo mạnh nhất có được.
    for tong, combo in ((3, "111"), (18, "666")):
        a = sums[tong].get("current_gap")
        b = trips[combo].get("current_gap")
        if a != b:
            loi.append(f'"chưa về" tổng {tong}={a} nhưng trip {combo}={b}')
        ma = sums[tong].get("median_gap")
        mb = trips[combo].get("median_gap")
        if ma != mb:
            loi.append(f"trung vị tổng {tong}={ma} nhưng trip {combo}={mb}")

    # 3. Trung vị phải thấp hơn TB — chính là lý do cột đó tồn tại
    for x in board.get("sums", []):
        if x.get("median_gap") and x.get("avg_gap") and x["median_gap"] > x["avg_gap"]:
            loi.append(f"tổng {x['sum']}: trung vị {x['median_gap']} > TB {x['avg_gap']}")

    # 4. Đối chiếu NGƯỢC: trip có thật trong lưới thì bảng phải ghi nhận.
    #    Chiều xuôi (bảng nói gì, lưới có khớp không) không bắt được lỗi bỏ sót.
    for d in grid:
        n = d["numbers"]
        if len(set(n)) == 1:
            c = str(n[0]) * 3
            ghi = trips[c].get("last_draw")
            if ghi is None or ghi < d["draw_number"]:
                loi.append(f"lưới có {c} ở #{d['draw_number']} nhưng bảng ghi lần cuối #{ghi}")

    # 5. Tổng tính từ numbers phải khớp cột sum_value đã lưu
    for d in grid:
        if sum(d["numbers"]) != d["sum"]:
            loi.append(f"#{d['draw_number']}: numbers {d['numbers']} cộng ra "
                       f"{sum(d['numbers'])} nhưng sum_value = {d['sum']}")

    # 6. Mỗi kỳ phải đúng 3 số trong 1..6
    for d in grid:
        n = d["numbers"]
        if len(n) != 3 or any(not (1 <= v <= 6) for v in n):
            loi.append(f"#{d['draw_number']}: numbers không hợp lệ {n}")

    return loi


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tu-file", nargs=2, metavar=("BOARD", "GRID"),
                   help="đọc từ file thay vì gọi production (dùng để test)")
    p.add_argument("--n", type=int, default=200, help="số kỳ lấy về đối chiếu")
    a = p.parse_args()

    if a.tu_file:
        board = json.load(open(a.tu_file[0], encoding="utf-8"))
        grid = json.load(open(a.tu_file[1], encoding="utf-8"))["draws"]
    else:
        secret = os.environ.get("TRIGGER_SECRET", "")
        if not secret:
            print("Thiếu TRIGGER_SECRET", file=sys.stderr)
            return 2
        board = lay(f"{BASE}/api/board-stats", secret)
        grid = lay(f"{BASE}/api/draw-grid?n={a.n}", secret)["draws"]

    dn = [d["draw_number"] for d in grid]
    print(f"Đối chiếu {len(grid)} kỳ  (#{min(dn)} - #{max(dn)}), "
          f"tổng cộng {board.get('total_draws'):,} kỳ trong DB")

    loi = kiem_tra(board, grid)
    if loi:
        print(f"\n>>> PHÁT HIỆN {len(loi)} VẤN ĐỀ:")
        for x in loi:
            print(f"    - {x}")
        return 1
    print("\n>>> Mọi phép đối chiếu đều khớp — dữ liệu nhất quán.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
