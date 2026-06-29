"""
Backfill các kỳ bị miss vào Supabase từ GitHub source.
Chạy 1 lần: python backfill_gaps.py
"""
import logging
import os
import sys
import time
from dotenv import load_dotenv
import psycopg2
from vietlott_fetcher import fetch_from_github

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "")
TABLE = '"public"."draw_history"'


def get_missing(conn) -> set:
    cur = conn.cursor()
    cur.execute(f"SELECT draw_number FROM {TABLE} ORDER BY draw_number")
    rows = [r[0] for r in cur.fetchall()]
    if len(rows) < 2:
        return set()
    missing = set()
    for i in range(1, len(rows)):
        for n in range(rows[i - 1] + 1, rows[i]):
            missing.add(n)
    return missing


def upsert_draw(conn, draw: dict) -> bool:
    nums = draw["numbers"]
    total = sum(nums)
    s = total
    cat = "NHO" if s <= 9 else ("HOA" if s <= 11 else "LON")
    draw_time = draw.get("draw_time") or "2000-01-01 00:00:00"
    nums_str = str(nums)
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            INSERT INTO {TABLE}
                (draw_number, draw_time, numbers, size_category, sum_value, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (draw_number) DO NOTHING
            """,
            (draw["draw_number"], draw_time, nums_str, cat, total),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        logger.error("Upsert #%s: %s", draw.get("draw_number"), e)
        return False


def main():
    conn = psycopg2.connect(DB_URL)
    logger.info("Kết nối Supabase OK")

    logger.info("Đang tìm gaps trong 1000 kỳ gần nhất...")
    missing = get_missing(conn)
    if not missing:
        logger.info("Không có gap nào, DB đã đầy đủ!")
        conn.close()
        return

    logger.info("Phát hiện %d kỳ bị miss. Đang fetch từ GitHub...", len(missing))

    all_draws = fetch_from_github(limit=0)  # lấy toàn bộ
    if not all_draws:
        logger.error("Không fetch được dữ liệu từ GitHub!")
        conn.close()
        sys.exit(1)

    github_map = {d["draw_number"]: d for d in all_draws}
    to_fill = sorted(n for n in missing if n in github_map)
    not_in_github = missing - set(github_map.keys())

    logger.info("Tìm thấy %d/%d kỳ trong GitHub (thiếu %d kỳ GitHub không có)",
                len(to_fill), len(missing), len(not_in_github))
    if not_in_github:
        logger.warning("GitHub không có các kỳ: %s", sorted(not_in_github)[:20])

    inserted = skipped = 0
    for i, dn in enumerate(to_fill, 1):
        ok = upsert_draw(conn, github_map[dn])
        if ok:
            inserted += 1
        else:
            skipped += 1
        if i % 100 == 0:
            logger.info("Progress: %d/%d (inserted=%d, skipped=%d)", i, len(to_fill), inserted, skipped)

    logger.info("XONG! inserted=%d  skipped(conflict)=%d  not_in_github=%d",
                inserted, skipped, len(not_in_github))
    conn.close()


if __name__ == "__main__":
    main()
