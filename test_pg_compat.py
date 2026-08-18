"""P195: kiểm tra lớp dịch SQL Postgres → SQLite.

Không chỉ kiểm tra "chạy được" mà so sánh GIÁ TRỊ với đáp án đúng — dịch sai
âm thầm còn nguy hiểm hơn báo lỗi.
"""
import sqlite3
import sys

from pg_compat import to_sqlite


def _db():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE d (draw_number INT, draw_time TIMESTAMP, "
              "numbers TEXT, created_at TIMESTAMP, n INT, dd INT)")
    c.execute("INSERT INTO d VALUES (1,'2026-08-17 03:00:00','[1, 2, 6]',"
              "'2026-08-17 03:00:00',7,2)")
    c.execute("INSERT INTO d VALUES (2,'2026-08-17 03:06:00','[3, 3, 3]',"
              "'2026-08-17 03:06:00',9,3)")
    return c


CASES = [
    ("tổng từ json",
     "SELECT (SELECT SUM(v::int) FROM json_array_elements_text(d.numbers::json) v) "
     "FROM d WHERE draw_number = 2", 9),
    ("ngày VN (03:00 UTC → 17/08)",
     "SELECT (draw_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Ho_Chi_Minh')::date "
     "FROM d WHERE draw_number = 1", "2026-08-17"),
    ("giờ VN (03:00 UTC → 10h)",
     "SELECT EXTRACT(HOUR FROM (draw_time AT TIME ZONE 'UTC' "
     "AT TIME ZONE 'Asia/Ho_Chi_Minh')) FROM d WHERE draw_number = 1", 10),
    ("NOW() AT TIME ZONE không vỡ",
     "SELECT COUNT(*) FROM d WHERE (draw_time AT TIME ZONE 'UTC' "
     "AT TIME ZONE 'Asia/Ho_Chi_Minh')::date "
     "<= (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date", 2),
    ("INTERVAL",
     "SELECT COUNT(*) FROM d WHERE created_at > NOW() - INTERVAL '100 years'", 2),
    ("chia kiểu float",
     "SELECT n::float / dd::int FROM d WHERE draw_number = 1", 3.5),
    ("SUM(...)::int",
     "SELECT SUM(n)::int FROM d", 16),
    ("TO_CHAR tháng",
     "SELECT TO_CHAR(draw_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Ho_Chi_Minh',"
     " 'YYYY-MM') FROM d WHERE draw_number = 1", "2026-08"),
    ("EXTRACT(EPOCH) → 6 phút",
     "SELECT EXTRACT(EPOCH FROM (draw_time - LAG(draw_time) "
     "OVER (ORDER BY draw_number))) / 60 FROM d ORDER BY draw_number DESC LIMIT 1", 6.0),
    ("bí danh dạng AS x(num)",
     "SELECT COUNT(*) FROM (SELECT numbers FROM d WHERE draw_number = 2) sub, "
     "json_array_elements_text(sub.numbers::json) AS x(num) WHERE x.num::int = 3", 3),
    ("placeholder %s → ?",
     "SELECT COUNT(*) FROM d WHERE n = %s", 1),
]

# Những cấu trúc CỐ Ý không dịch — phải báo lỗi chứ không được trả kết quả sai.
PHAI_BAO_LOI = [
    ("array_agg", "SELECT array_agg(n) FROM d"),
    ("json_object_keys", "SELECT json_object_keys(numbers) FROM d"),
]


def main():
    c = _db()
    fails = []

    print("=" * 62)
    print("Dịch + chạy + so sánh giá trị đúng")
    print("=" * 62)
    for ten, sql, mong in CASES:
        out = to_sqlite(sql)
        try:
            got = list(c.execute(out, (7,) if "?" in out else ()))[0][0]
        except Exception as e:
            fails.append(f"{ten}: lỗi {e}")
            print(f"  LỖI  {ten:32s} {e}")
            continue
        if isinstance(mong, float):
            ok = abs(got - mong) < 1e-6
        else:
            ok = got == mong
        print(f"  {'OK  ' if ok else 'SAI '} {ten:32s} = {got!r} (mong {mong!r})")
        if not ok:
            fails.append(f"{ten}: được {got!r}, mong {mong!r}")

    print("\n" + "=" * 62)
    print("Cấu trúc cố ý KHÔNG dịch — phải báo lỗi, không được trả sai")
    print("=" * 62)
    for ten, sql in PHAI_BAO_LOI:
        try:
            list(c.execute(to_sqlite(sql)))
            print(f"  SAI  {ten:32s} chạy được — đáng lẽ phải báo lỗi")
            fails.append(f"{ten}: dịch nhầm thành công")
        except Exception:
            print(f"  OK   {ten:32s} báo lỗi đúng như mong đợi")

    print("\n" + "=" * 62)
    print(f"RESULTS: {len(CASES) + len(PHAI_BAO_LOI) - len(fails)} passed, "
          f"{len(fails)} failed")
    print("=" * 62)
    if fails:
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
