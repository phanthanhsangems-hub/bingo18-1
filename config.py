"""
Cấu hình hệ thống - Cloud Run edition
Tất cả secrets lấy từ environment variables
"""
import os

# ── Telegram ─────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")   # REQUIRED: set in env
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID",   "")   # REQUIRED: set in env

# ── Admin ────────────────────────────────────────────────────
ADMIN_SECRET_KEY = os.environ.get("ADMIN_SECRET_KEY", "")  # REQUIRED: set in env

# ── PostgreSQL (Supabase) ─────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ── Google Cloud Storage ──────────────────────────────────────
GCS_BUCKET_NAME  = os.environ.get("GCS_BUCKET_NAME",  "")
GCS_MODEL_PREFIX = os.environ.get("GCS_MODEL_PREFIX", "models/")

# ── Cloud Run trigger auth ────────────────────────────────────
TRIGGER_SECRET     = os.environ.get("TRIGGER_SECRET", "")      # REQUIRED: set in env
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")   # LLM AI
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY",     "")   # Vision AI (image processing)
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY",       "")   # LLM AI (fast, free tier)

# ── Bingo 18 ─────────────────────────────────────────────────
BINGO_INTERVAL_MINUTES = 6
DRAWS_PER_DAY          = 240   # 24h x 60min / 6min
START_TIME             = "00:00"
END_TIME               = "23:54"

# ── Model ────────────────────────────────────────────────────
MIN_HISTORY_FOR_PREDICTION = 100
WIN_RATE_WINDOW_MIN        = 100
WIN_RATE_WINDOW_MAX        = 300
MARKOV_ORDERS              = [1, 2, 3]
COLD_NUMBER_WINDOWS        = [10, 20, 30, 50]
AUTO_RETRAIN_INTERVAL      = int(os.environ.get("AUTO_RETRAIN_INTERVAL", "20"))    # Retrain sau mỗi 20 kỳ (~2 giờ)

# ── Win threshold ─────────────────────────────────────────────────────────────
# 1 = ít nhất 1/3 khớp → baseline random = 87.5% (không phân biệt được model tốt/xấu)
# 2 = ít nhất 2/3 khớp → baseline random = 35.6% (có ý nghĩa thống kê hơn nhiều)
WIN_THRESHOLD = int(os.environ.get("WIN_THRESHOLD", "1"))

# ── Size categories ──────────────────────────────────────────
SIZE_SMALL  = (3,  9)   # NHO
SIZE_MEDIUM = (10, 11)  # HOA
SIZE_LARGE  = (12, 18)  # LON

# ── Dashboard ────────────────────────────────────────────────
DASHBOARD_PORT = int(os.environ.get("PORT", 8080))
DASHBOARD_HOST = "0.0.0.0"

# ── Logging ──────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# ── Local SQLite fallback (không có DATABASE_URL) ────────────
DB_PATH     = os.environ.get("DB_PATH", "data/bingo18.db")
BACKUP_PATH = os.environ.get("BACKUP_PATH", "data/backups/")
MODELS_PATH ='multiset_markov'

import sys as _sys
if DATABASE_URL and not ADMIN_SECRET_KEY:
    print("WARNING: ADMIN_SECRET_KEY is not set — all admin endpoints are unprotected!", file=_sys.stderr)
if DATABASE_URL and not TRIGGER_SECRET:
    print("WARNING: TRIGGER_SECRET is not set — trigger endpoint is unprotected!", file=_sys.stderr)

MAX_RETRIES = 3
RETRY_DELAY = 30
# Combo Filter Mode
COMBO_TOP_N  = int(os.environ.get("COMBO_TOP_N",  "4"))
COMBO_WINDOW = int(os.environ.get("COMBO_WINDOW", "50"))	