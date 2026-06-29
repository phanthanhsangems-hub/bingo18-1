"""
Main entry point - Cloud Run edition
Chỉ chạy Flask server.
Scheduler được thay bằng Cloud Scheduler → POST /api/trigger-prediction
"""

import os
import sys
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config


def setup_logging():
    log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s – %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(log_level)
    ch.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(log_level)
    root.addHandler(ch)

    # Ghi file log nếu chạy local (không phải Cloud Run)
    if not os.environ.get("K_SERVICE"):
        os.makedirs("logs", exist_ok=True)
        fh = logging.FileHandler("logs/bingo18.log", encoding="utf-8")
        fh.setLevel(log_level)
        fh.setFormatter(fmt)
        root.addHandler(fh)

    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 50)
    logger.info("BINGO 18 PREDICTOR – Cloud Run Edition")
    logger.info("Started at: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("PORT: %d", config.DASHBOARD_PORT)
    logger.info("DB: %s", "PostgreSQL" if config.DATABASE_URL else f"SQLite ({config.DB_PATH})")
    logger.info("GCS: %s", config.GCS_BUCKET_NAME or "disabled (local only)")
    logger.info("=" * 50)

    from database import DatabaseManager
    db    = DatabaseManager()
    stats = db.get_statistics()
    logger.info("Database ready – %d draws recorded", stats.get("total_draws", 0))

    try:
        import admin_interface  # noqa – đăng ký routes admin
    except Exception as e:
        logger.warning("Could not load admin_interface: %s", e)

    from app import app
    logger.info("Starting Flask on 0.0.0.0:%d", config.DASHBOARD_PORT)
    app.run(
        host=config.DASHBOARD_HOST,
        port=config.DASHBOARD_PORT,
        debug=False,
        threaded=True
    )


if __name__ == "__main__":
    main()
