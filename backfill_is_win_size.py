"""
backfill_is_win_size.py
Update is_win_size cho tất cả prediction_results cũ chưa có giá trị.
Chạy 1 lần: python backfill_is_win_size.py
"""
import json
import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

def size_cat(numbers):
    s = sum(numbers)
    return "NHO" if s <= 9 else ("HOA" if s <= 11 else "LON")

conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=15)
cur  = conn.cursor()

cur.execute("""
    SELECT pr.id, p.predicted_numbers, pr.actual_numbers
    FROM prediction_results pr
    JOIN predictions p ON p.id = pr.prediction_id
    WHERE pr.is_win_size IS NULL
      AND pr.actual_numbers IS NOT NULL
""")
rows = cur.fetchall()
print(f"Records cần update: {len(rows)}")

updated = 0
batch   = 0
for rid, pred_raw, actual_raw in rows:
    try:
        pred   = json.loads(pred_raw)   if isinstance(pred_raw,   str) else pred_raw
        actual = json.loads(actual_raw) if isinstance(actual_raw, str) else actual_raw
        if len(pred) == 3 and len(actual) == 3:
            win_size = size_cat(pred) == size_cat(actual)
            cur.execute("UPDATE prediction_results SET is_win_size=%s WHERE id=%s",
                        (win_size, rid))
            updated += 1
    except Exception as e:
        print(f"  Skip id={rid}: {e}")

    batch += 1
    if batch % 1000 == 0:
        conn.commit()
        print(f"  Progress: {batch}/{len(rows)} ({updated} updated)")

conn.commit()
print(f"DONE: {updated}/{len(rows)} records updated.")
cur.close()
conn.close()
