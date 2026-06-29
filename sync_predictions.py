"""
sync_predictions.py - Đồng bộ lại predictions cho các kỳ bị thiếu

Lỗi đã sửa: get_recent_draws(300) chỉ trả 300 kỳ MỚI NHẤT toàn cục,
nên khi cần lịch sử trước kỳ #159963 thì trả về rỗng → 2376 lỗi.
Fix: query trực tiếp SQL lấy N kỳ TRƯỚC mỗi draw_number cụ thể.

Chạy:
    python sync_predictions.py              # Đồng bộ tối đa 500 kỳ gần nhất
    python sync_predictions.py --limit 2376 # Đồng bộ toàn bộ gap
    python sync_predictions.py --dry-run    # Xem preview không ghi DB
"""

import argparse
import json
import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def get_draws_before(db, draw_number: int, limit: int = 100):
    """
    Lấy `limit` kỳ NGAY TRƯỚC draw_number (theo thứ tự tăng dần).
    Khác với get_recent_draws() luôn lấy kỳ mới nhất toàn cục.
    """
    import pandas as pd
    ph   = db._ph()
    conn = db.get_connection()
    try:
        df = pd.read_sql_query(
            f"SELECT draw_number, draw_time, numbers, size_category, sum_value "
            f"FROM draw_history "
            f"WHERE draw_number < {ph} "
            f"ORDER BY draw_number DESC LIMIT {ph}",
            conn,
            params=(draw_number, limit)
        )
    finally:
        conn.close()

    if not df.empty:
        df['numbers'] = df['numbers'].apply(
            lambda x: json.loads(x) if isinstance(x, str) else x
        )
        # Trả về thứ tự ASC để model predict đúng chiều thời gian
        df = df.sort_values('draw_number', ascending=True).reset_index(drop=True)
    return df


def run(limit: int = 500, dry_run: bool = False, batch_size: int = 50, min_draw: int = 0):
    from database import DatabaseManager
    from models import HybridModel, ModelSelector
    import config

    db = DatabaseManager()

    # ── Tìm các kỳ có kết quả nhưng chưa có prediction ──────
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        ph = db._ph()
        min_draw_clause = f"AND dh.draw_number >= {min_draw}" if min_draw > 0 else ""
        cur.execute(f"""
            SELECT dh.draw_number, dh.numbers
            FROM draw_history dh
            WHERE NOT EXISTS (
                SELECT 1 FROM predictions p WHERE p.draw_number = dh.draw_number
            )
            {min_draw_clause}
            ORDER BY dh.draw_number ASC
            LIMIT {ph}
        """, (limit,))
        missing = cur.fetchall()
    finally:
        conn.close()

    total_missing = len(missing)
    if total_missing == 0:
        logger.info("✅ Không có kỳ nào bị thiếu prediction.")
        return

    logger.info("Tìm thấy %d kỳ chưa có prediction (limit=%d)", total_missing, limit)

    if dry_run:
        logger.info("DRY RUN – không ghi dữ liệu vào DB")
        for draw_number, _ in missing[:10]:
            df_before = get_draws_before(db, draw_number, limit=100)
            logger.info("  Kỳ #%d → lịch sử trước đó: %d kỳ", draw_number, len(df_before))
        if total_missing > 10:
            logger.info("  ... và %d kỳ nữa", total_missing - 10)
        return

    # ── Load / train model một lần ──────────────────────────
    os.makedirs(config.MODELS_PATH, exist_ok=True)
    model_path = os.path.join(config.MODELS_PATH, "hybrid_model.pkl")

    hybrid = HybridModel()
    loaded = hybrid.load(model_path)
    if not loaded:
        logger.info("Chưa có model, đang train lần đầu...")
        df_init = db.get_recent_draws(500)
        if len(df_init) < 50:
            logger.error("Không đủ dữ liệu để train model")
            return
        hybrid.train(df_init)
        hybrid.save(model_path)

    selector = ModelSelector(db)
    for m in [hybrid, hybrid.markov_model, hybrid.cold_model, hybrid.ml_model]:
        selector.add_model(m)

    # ── Xử lý từng kỳ ───────────────────────────────────────
    ok   = 0
    fail = 0
    skip = 0
    t0   = time.time()

    for i, (draw_number, numbers_raw) in enumerate(missing):
        try:
            actual_numbers = (
                json.loads(numbers_raw) if isinstance(numbers_raw, str)
                else list(numbers_raw)
            )

            # KEY FIX: lấy kỳ TRƯỚC draw_number cụ thể, không lấy global recent
            df_before = get_draws_before(db, draw_number, limit=100)

            if len(df_before) < 10:
                logger.debug("Skip kỳ #%d – chưa đủ lịch sử (%d kỳ)", draw_number, len(df_before))
                skip += 1
                continue

            # Chọn model tốt nhất (hoặc dùng hybrid mặc định)
            try:
                best_name  = selector.select_best_model([100, 200])
                best_model = selector.get_model(best_name) or hybrid
            except Exception:
                best_model = hybrid
                best_name  = hybrid.name

            try:
                preds = best_model.predict(df_before, draw_number)
            except Exception:
                preds = hybrid.predict(df_before, draw_number)

            if not preds:
                fail += 1
                continue

            numbers, confidence = preds[0]

            # Ghi prediction + result vào DB
            pred_id, _ = db.insert_prediction(draw_number, best_name, numbers, confidence)
            if pred_id and pred_id > 0:
                db.update_prediction_result(pred_id, draw_number, actual_numbers)
                ok += 1
            else:
                fail += 1

            # Log tiến độ mỗi batch_size kỳ
            if (i + 1) % batch_size == 0:
                elapsed = time.time() - t0
                rate    = (i + 1) / max(elapsed, 0.001)
                eta     = (total_missing - i - 1) / rate
                logger.info(
                    "Tiến độ: %d/%d (%.0f%%) | ✅ %d  ⏭ %d  ❌ %d | ETA: %.0fs",
                    i + 1, total_missing,
                    (i + 1) / total_missing * 100,
                    ok, skip, fail, eta
                )

        except Exception as e:
            logger.warning("Lỗi kỳ #%d: %s", draw_number, e)
            fail += 1

    # ── Cập nhật model stats ─────────────────────────────────
    if ok > 0:
        ALL = ['markov_order_2', 'cold_number_window_30',
               'ml_ensemble', 'hybrid_model', 'lstm']
        db.refresh_model_stats(ALL)
        logger.info("✅ Đã cập nhật model stats")

    elapsed = time.time() - t0
    logger.info("══════════════════════════════════════")
    logger.info("Hoàn tất: ✅ %d OK  ⏭ %d skip  ❌ %d fail  |  %.1fs",
                ok, skip, fail, elapsed)
    if ok > 0:
        logger.info("Win rate mới sẽ phản ánh đúng hơn sau khi sync xong.")
    logger.info("══════════════════════════════════════")


def main():
    parser = argparse.ArgumentParser(description="Đồng bộ predictions bị thiếu")
    parser.add_argument("--limit",   type=int, default=500,
                        help="Số kỳ tối đa cần xử lý (mặc định: 500)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Chỉ xem, không ghi DB")
    parser.add_argument("--batch",    type=int, default=50,
                        help="Log tiến độ mỗi N kỳ (mặc định: 50)")
    parser.add_argument("--min-draw", type=int, default=0,
                        help="Chỉ xử lý draw_number >= giá trị này (mặc định: 0 = tất cả)")
    args = parser.parse_args()
    run(limit=args.limit, dry_run=args.dry_run, batch_size=args.batch, min_draw=args.min_draw)


if __name__ == "__main__":
    main()
