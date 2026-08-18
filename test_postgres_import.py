"""P198: kiểm tra app import được ở nhánh PostgreSQL.

Vì sao cần: mọi test khác chạy với SQLite (không có DATABASE_URL), nên nhánh
`if USE_POSTGRES:` trong database.py chưa từng được chạy trước khi deploy.
P195 thêm hai class ở cấp module kế thừa sqlite3.Cursor/Connection, trong khi
`import sqlite3` lại nằm trong nhánh else — trên Cloud Run là NameError ngay
lúc import, container không khởi động nổi. Test cục bộ pass hết vì local luôn
là SQLite.

Test này giả lập psycopg2 rồi import với DATABASE_URL đã đặt, tức đi đúng
nhánh mà Cloud Run đi.
"""
import os
import sys
import types


def _stub_psycopg2():
    """psycopg2 không có trong requirements của CI — dựng module giả."""
    pg = types.ModuleType("psycopg2")

    class Error(Exception):
        pass

    def connect(*a, **k):
        raise Error("stub: không kết nối thật")

    pg.Error = Error
    pg.connect = connect

    extras = types.ModuleType("psycopg2.extras")
    extras.RealDictCursor = type("RealDictCursor", (), {})
    extras.Json = type("Json", (), {"__init__": lambda self, *a, **k: None})

    pool = types.ModuleType("psycopg2.pool")
    pool.ThreadedConnectionPool = type(
        "ThreadedConnectionPool", (), {"__init__": lambda self, *a, **k: None})

    pg.extras, pg.pool = extras, pool
    sys.modules["psycopg2"] = pg
    sys.modules["psycopg2.extras"] = extras
    sys.modules["psycopg2.pool"] = pool


def main():
    os.environ["DATABASE_URL"] = "postgresql://u:p@db.stub.supabase.co:5432/postgres"
    for m in list(sys.modules):
        if m.split(".")[0] in ("app", "database", "config", "prediction_service"):
            del sys.modules[m]
    _stub_psycopg2()

    fails = []

    import database
    if not database.USE_POSTGRES:
        fails.append("USE_POSTGRES phải là True khi có DATABASE_URL")
    print(f"  OK   import database    (USE_POSTGRES={database.USE_POSTGRES})")

    # sqlite3 phải dùng được kể cả ở nhánh Postgres — hai class compat cần nó
    for ten in ("_PgCompatCursor", "_PgCompatConnection"):
        if not hasattr(database, ten):
            fails.append(f"thiếu {ten}")
        else:
            print(f"  OK   {ten} định nghĩa được ở nhánh Postgres")

    import app
    a = app.create_app()
    n = len(list(a.url_map.iter_rules()))
    print(f"  OK   app.create_app()   ({n} route)")
    if n < 100:
        fails.append(f"chỉ có {n} route — nghi thiếu endpoint")

    c = a.test_client()
    r = c.get("/login")
    print(f"  OK   GET /login         -> {r.status_code}")
    if r.status_code >= 500:
        fails.append(f"/login trả {r.status_code}")

    print("\n" + "=" * 56)
    print(f"RESULTS: {4 + (n >= 100) - len(fails)} passed, {len(fails)} failed")
    print("=" * 56)
    if fails:
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
