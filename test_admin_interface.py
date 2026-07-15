"""test_admin_interface.py — Local pre-deployment verification for the
manual result-entry admin endpoint (/api/admin/submit-result).

Complements test_ensemble.py and test_prediction_service.py.

Safety notes (important if run against a real production DATABASE_URL):
  - Auth and input-validation sub-tests never write to the DB (they return
    before any DB call).
  - The "duplicate draw" sub-test submits a draw_number that already
    exists in draw_history — insert_draw() is a no-op (ON CONFLICT DO
    NOTHING / "already exists" guard) for that case, so it never mutates
    data, on either backend.
  - The happy-path (actually inserts a new draw_history row) sub-test
    only runs when config.DATABASE_URL is empty, i.e. the local SQLite
    fallback is in use. It is skipped (not failed) against a real
    Postgres/production database, since fabricating a real draw_number
    would permanently corrupt draw_history.
"""
import sys

from dotenv import load_dotenv
load_dotenv()

PASS = "OK"
FAIL = "FAIL"
results = []

def check(label, fn):
    try:
        fn()
        print(f"  [{PASS}] {label}")
        results.append((label, True, None))
    except Exception as e:
        print(f"  [{FAIL}] {label}: {e}")
        results.append((label, False, str(e)))

# ── TEST 1: Imports + route registration ──────────────────────────────────────
print("\n" + "="*60)
print("TEST 1: Imports + route registration")
print("="*60)

import config
from app import app, db
import admin_interface  # noqa — registers /api/admin/* routes

client = app.test_client()
WRONG_KEY = "definitely-not-the-real-admin-key-xyz"
REAL_KEY  = config.ADMIN_SECRET_KEY

def _route_registered():
    rules = [r.rule for r in app.url_map.iter_rules()]
    assert "/api/admin/submit-result" in rules, f"Route not registered: {rules}"

check("admin_interface imports + /api/admin/submit-result registered", _route_registered)

# ── TEST 2: Auth ───────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("TEST 2: Auth")
print("="*60)

def _wrong_key_rejected():
    if not REAL_KEY:
        print("         ADMIN_SECRET_KEY not configured — skipping")
        return
    r = client.post("/api/admin/submit-result",
                     json={"draw_number": 999999, "numbers": [1, 2, 3]},
                     headers={"X-Admin-Key": WRONG_KEY})
    assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.get_json()}"

def _missing_key_rejected_when_configured():
    if not REAL_KEY:
        print("         ADMIN_SECRET_KEY not configured in this env — skipping (no-auth-required state)")
        return
    r = client.post("/api/admin/submit-result",
                     json={"draw_number": 999999, "numbers": [1, 2, 3]})
    assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.get_json()}"

check("wrong X-Admin-Key -> 401",            _wrong_key_rejected)
check("missing key -> 401 (if key configured)", _missing_key_rejected_when_configured)

# ── TEST 3: Input validation (no DB writes) ───────────────────────────────────
print("\n" + "="*60)
print("TEST 3: Input validation")
print("="*60)

def _post(payload):
    return client.post("/api/admin/submit-result", json=payload,
                        headers={"X-Admin-Key": REAL_KEY})

def _missing_fields():
    if not REAL_KEY:
        print("         ADMIN_SECRET_KEY not configured — skipping")
        return
    r = _post({"draw_number": 999999})
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.get_json()}"

def _wrong_count():
    if not REAL_KEY:
        print("         ADMIN_SECRET_KEY not configured — skipping")
        return
    r = _post({"draw_number": 999999, "numbers": [1, 2]})
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.get_json()}"

def _out_of_range():
    if not REAL_KEY:
        print("         ADMIN_SECRET_KEY not configured — skipping")
        return
    r = _post({"draw_number": 999999, "numbers": [1, 2, 7]})
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.get_json()}"

check("missing draw_number/numbers -> 400", _missing_fields)
check("wrong number count -> 400",          _wrong_count)
check("number out of [1,6] range -> 400",   _out_of_range)

# ── TEST 4: Duplicate draw_number (no mutation) ───────────────────────────────
print("\n" + "="*60)
print("TEST 4: Duplicate draw_number rejected without mutating data")
print("="*60)

def _duplicate_draw_rejected():
    if not REAL_KEY:
        print("         ADMIN_SECRET_KEY not configured — skipping")
        return
    df = db.get_recent_draws(1)
    if len(df) == 0:
        print("         no existing draws in DB — skipping (nothing to collide with)")
        return
    existing_draw = int(df.iloc[0]["draw_number"])
    r = _post({"draw_number": existing_draw, "numbers": [1, 2, 3]})
    assert r.status_code == 400, f"Expected 400 for existing draw #{existing_draw}, got {r.status_code}"
    print(f"         draw #{existing_draw} correctly rejected as duplicate")

check("submitting an existing draw_number -> 400, no mutation", _duplicate_draw_rejected)

# ── TEST 5: Happy path (mutates DB — local SQLite only) ───────────────────────
print("\n" + "="*60)
print("TEST 5: Happy path (local SQLite only)")
print("="*60)

def _happy_path_local_only():
    if not REAL_KEY:
        print("         ADMIN_SECRET_KEY not configured — skipping")
        return
    if config.DATABASE_URL:
        print("         DATABASE_URL is configured (production Postgres) — "
              "skipping to avoid inserting a fabricated draw")
        return
    df = db.get_recent_draws(1)
    next_draw = (int(df.iloc[0]["draw_number"]) + 1) if len(df) else 1
    r = _post({"draw_number": next_draw, "numbers": [2, 3, 4]})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.get_json()}"
    body = r.get_json()
    assert body.get("success") is True, f"Unexpected body: {body}"
    assert body.get("draw_number") == next_draw
    print(f"         inserted draw #{next_draw} -> {body}")

check("valid new draw -> 200 + success body (local SQLite only)", _happy_path_local_only)

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "="*60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"RESULTS: {n_pass} passed, {n_fail} failed")
if n_fail:
    print("\nFailed tests:")
    for label, ok, err in results:
        if not ok:
            print(f"  - {label}: {err}")
    sys.exit(1)

print("="*60)
print("ALL TESTS PASSED")
print("="*60)
