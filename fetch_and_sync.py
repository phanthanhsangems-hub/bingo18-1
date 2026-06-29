"""
fetch_and_sync.py  —  v2.0
Chạy trên máy Windows (IP Việt Nam) — fetch Vietlott và sync lên Cloud Run.
Lệnh chạy: python fetch_and_sync.py
"""
import logging
import time
import os
import requests
from datetime import datetime

# ──────────────────────────────────────────────────────────────
# CẤU HÌNH
# ──────────────────────────────────────────────────────────────
CLOUD_RUN_URL    = "https://bingo18-predictor-633959711537.asia-southeast1.run.app"
TRIGGER_SECRET   = os.environ.get("TRIGGER_SECRET", "bingo18_trigger_2024")
FETCH_INTERVAL   = 60   # giây
MAX_RETRY        = 3
# ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('fetch_sync.log', encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)

from vietlott_fetcher import VietlottFetcher


def get_last_draw_id_from_cloud() -> int:
    """Lấy kỳ mới nhất đang có trong DB từ Cloud Run."""
    try:
        r = requests.get(
            f"{CLOUD_RUN_URL}/api/recent_draws?limit=1",
            timeout=10
        )
        # /api/recent_draws trả về JSON array trực tiếp (list), field là draw_number
        data = r.json()
        if isinstance(data, list) and data:
            row = data[0]
            # hỗ trợ cả draw_number lẫn draw_id để an toàn
            val = row.get('draw_number') or row.get('draw_id') or 0
            return int(val)
        # nếu server bọc trong dict
        if isinstance(data, dict):
            draws = data.get('draws') or data.get('data') or []
            if isinstance(draws, list) and draws:
                row = draws[0]
                val = row.get('draw_number') or row.get('draw_id') or 0
                return int(val)
    except Exception as e:
        logger.warning(f"Không lấy được last draw_id từ Cloud: {e}")
    return 0


def push_draw_to_cloud(draw: dict) -> bool:
    """Đẩy một kết quả kỳ lên Cloud Run."""
    payload = {
        "draw_id":    draw['draw_id'],
        "numbers":    draw['numbers'],
        "draw_date":  draw.get('draw_date', datetime.now().strftime('%Y-%m-%d')),
        "secret":     TRIGGER_SECRET,
    }
    for attempt in range(1, MAX_RETRY + 1):
        try:
            r = requests.post(
                f"{CLOUD_RUN_URL}/api/add_draw",
                json=payload,
                timeout=15
            )
            if r.status_code in (200, 201):
                logger.info(f"✅ Đã push kỳ {draw['draw_id']} lên Cloud")
                return True
            else:
                logger.warning(f"Push kỳ {draw['draw_id']}: HTTP {r.status_code} | {r.text[:100]}")
        except Exception as e:
            logger.warning(f"Push attempt {attempt}/{MAX_RETRY}: {e}")
        if attempt < MAX_RETRY:
            time.sleep(3)
    return False


def trigger_prediction() -> bool:
    """Kích hoạt Cloud Run tạo dự đoán mới."""
    try:
        r = requests.post(
            f"{CLOUD_RUN_URL}/api/trigger-prediction",
            headers={"X-Trigger-Secret": TRIGGER_SECRET},
            timeout=30
        )
        if r.status_code == 200:
            logger.info("✅ Trigger prediction thành công")
            return True
        logger.warning(f"Trigger prediction: HTTP {r.status_code}")
    except Exception as e:
        logger.warning(f"Trigger prediction error: {e}")
    return False


def main():
    logger.info("=" * 50)
    logger.info("  Bingo18 Fetcher v2.0 đang chạy...")
    logger.info(f"  Fetch mỗi {FETCH_INTERVAL} giây")
    logger.info("=" * 50)

    fetcher = VietlottFetcher()
    consecutive_failures = 0

    while True:
        try:
            # Lấy kỳ cuối trong DB
            last_id = get_last_draw_id_from_cloud()
            logger.info(f"Kỳ mới nhất trong DB: {last_id}")

            # Thử lấy kết quả mới
            new_draws = fetcher.get_results_since(last_id)

            if new_draws:
                consecutive_failures = 0
                logger.info(f"Có {len(new_draws)} kỳ mới: {[d['draw_id'] for d in new_draws]}")
                pushed = 0
                for draw in new_draws:
                    if push_draw_to_cloud(draw):
                        pushed += 1

                if pushed > 0:
                    time.sleep(2)
                    trigger_prediction()
            else:
                consecutive_failures += 1
                logger.warning(
                    f"Không lấy được dữ liệu "
                    f"(lần {consecutive_failures}), thử lại sau {FETCH_INTERVAL}s"
                )

                # Sau 5 lần thất bại liên tiếp, log hướng dẫn
                if consecutive_failures == 5:
                    logger.error(
                        "⚠️  5 lần thất bại liên tiếp!\n"
                        "   → Chạy: python find_ajax_endpoint.py\n"
                        "   → Hoặc mở Chrome DevTools để tìm .ashx endpoint\n"
                        "   → Cập nhật AJAXPRO_ENDPOINT trong vietlott_fetcher.py"
                    )

        except KeyboardInterrupt:
            logger.info("Dừng theo yêu cầu người dùng (Ctrl+C)")
            break
        except Exception as e:
            logger.error(f"Lỗi không mong muốn: {e}", exc_info=True)

        time.sleep(FETCH_INTERVAL)


if __name__ == '__main__':
    main()
