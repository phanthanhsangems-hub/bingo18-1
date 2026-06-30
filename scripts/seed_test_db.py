"""Seed a local SQLite DB with synthetic draws for local/dev/CI testing.

Usage: python scripts/seed_test_db.py [n_draws]

Refuses to run if config.DATABASE_URL is set, to guarantee it can never
write synthetic data into a real Postgres/production database.
"""
import os
import sys
import random
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import config
from database import DatabaseManager


def main():
    if config.DATABASE_URL:
        print("ERROR: DATABASE_URL is set — refusing to seed synthetic draws into a "
              "real database. This script is for the local SQLite fallback only.")
        sys.exit(1)

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    db = DatabaseManager()
    rng = random.Random(7)
    base = datetime.datetime.now() - datetime.timedelta(minutes=6 * n)
    for i in range(1, n + 1):
        nums = sorted(rng.randint(1, 6) for _ in range(3))
        db.insert_draw(i, nums, draw_time=base + datetime.timedelta(minutes=6 * i))
    print(f"Seeded {n} synthetic draws into local DB")


if __name__ == "__main__":
    main()
