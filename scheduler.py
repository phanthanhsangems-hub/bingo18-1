"""
Scheduler - Tự động chạy dự đoán mỗi 6 phút
Luồng đúng:
  1. Dự đoán kỳ TIẾP THEO → gửi Telegram
  2. Chờ kết quả kỳ đó từ vietlott.vn
  3. Xử lý kết quả → gửi Telegram
  4. Lặp lại
"""

import schedule
import time
import json
import logging
import threading
import os
from datetime import datetime, timedelta
from typing import List, Optional
from collections import Counter, defaultdict
import traceback

import config
from database import DatabaseManager, USE_POSTGRES
from models import MarkovModel, ColdNumberModel, MLEnsembleModel, HybridModel, ModelSelector
from telegram_bot import TelegramBot
from feature_engineering import FeatureEngineer
from sync_to_supabase import SupabaseSync, VietlottFetcher
from vietlott_fetcher import poll_draw_by_id, get_latest_result

logger = logging.getLogger(__name__)

MODEL_SAVE_PATH = os.path.join(config.MODELS_PATH, "hybrid_model.pkl")
ALL_MODEL_NAMES = ['markov_order_2', 'cold_number_window_30', 'ml_ensemble', 'hybrid_model', 'lstm']


def _parse_numbers(val):
    """Chuyển numbers từ DB (string hoặc list) thành List[int]"""
    if isinstance(val, list):
        return [int(x) for x in val]
    if isinstance(val, str):
        try:
            return [int(x) for x in json.loads(val)]
        except Exception:
            return []
    return []


class BingoScheduler:
    def __init__(self):
        self.db       = DatabaseManager()
        self.telegram = TelegramBot()

        self.markov_model  = MarkovModel(order=2)
        self.cold_model    = ColdNumberModel(window_size=30)
        self.ml_model      = MLEnsembleModel()
        self.hybrid_model  = HybridModel()

        self.model_selector = ModelSelector(self.db)
        for m in [self.markov_model, self.cold_model, self.ml_model, self.hybrid_model]:
            self.model_selector.add_model(m)

        self.current_draw       : int           = 0
        self.is_running         : bool          = False
        self.last_prediction_id : Optional[int] = None
        self._lock = threading.Lock()

        self.supabase = SupabaseSync()
        self.fetcher  = VietlottFetcher()

    # ──────────────────────────────────────────────
    # Khởi tạo
    # ──────────────────────────────────────────────
    def initialize(self):
        logger.info("Initializing Bingo 18 Predictor...")

        if self.telegram.test_connection():
            logger.info("Telegram bot connected")
        else:
            logger.warning("Telegram bot connection failed – check token/chat_id")

        df = self.db.get_recent_draws(500)

        if len(df) > 0:
            logger.info("Loaded %d historical draws", len(df))
            self.current_draw = int(df.iloc[0]['draw_number']) + 1
        else:
            logger.warning("No historical data – starting from draw #1")
            self.current_draw = 1

        # Catch-up: kiểm tra xem vietlott.vn có kỳ mới hơn không
        try:
            latest = get_latest_result()
            if latest and latest.get('draw_number'):
                gap = latest['draw_number'] - (self.current_draw - 1)
                if gap > 0:
                    logger.info("CATCH-UP: %d kỳ bị miss", gap)
                    for dn in range(self.current_draw, latest['draw_number'] + 1):
                        r = self.fetcher.fetch_by_id(dn)
                        if r and len(r.get('numbers', [])) == 3:
                            self.db.insert_draw(dn, r['numbers'])
                            self.db.update_cold_numbers(dn, r['numbers'])
                    self.current_draw = latest['draw_number'] + 1
        except Exception as ce:
            logger.warning("Catch-up error: %s", ce)

        # Load hoặc train models
        os.makedirs(config.MODELS_PATH, exist_ok=True)
        if len(df) > 0:
            if not self.hybrid_model.load(MODEL_SAVE_PATH):
                self._train_all_models(df)
            else:
                logger.info("Models loaded from disk – skipping retrain")
        else:
            logger.warning("No historical data – models not trained")

        logger.info("Next draw: #%d", self.current_draw)

        # Sync lịch sử lên Supabase (chỉ có tác dụng khi local SQLite → Postgres)
        logger.info("Syncing history to Supabase...")
        self.supabase.bulk_sync_from_sqlite()

        # Dự đoán kỳ tiếp theo ngay khi khởi động
        logger.info("Making initial prediction for draw #%d", self.current_draw)
        self.make_prediction()

    def _train_all_models(self, df):
        logger.info("Training models...")
        try:
            self.markov_model.train(df)
            logger.info("  Markov trained")
            self.cold_model.train(df)
            logger.info("  Cold Number trained")
            if len(df) >= 100:
                self.ml_model.train(df)
                logger.info("  ML Ensemble trained")
            self.hybrid_model.train(df)
            logger.info("  Hybrid trained")
            self.hybrid_model.save(MODEL_SAVE_PATH)
        except Exception as e:
            logger.error("Training error: %s", e)
            traceback.print_exc()

    # ──────────────────────────────────────────────
    # Dự đoán kỳ TIẾP THEO
    # ──────────────────────────────────────────────
    def make_prediction(self):
        with self._lock:
            logger.info("── Predicting draw #%d ──", self.current_draw)

            df = self.db.get_recent_draws(300)
            if len(df) < 20:
                logger.warning("Not enough history (<20) – skipping")
                return

            # Kiểm tra đã dự đoán kỳ này chưa
            conn = self.db.get_connection()
            try:
                cur = conn.cursor()
                ph = self.db._ph()
                cur.execute(
                    f"SELECT id FROM predictions WHERE draw_number={ph} "
                    f"ORDER BY prediction_time DESC LIMIT 1",
                    (self.current_draw,)
                )
                existing = cur.fetchone()
            finally:
                conn.close()

            if existing:
                logger.info("Draw #%d already predicted – skip", self.current_draw)
                self.last_prediction_id = existing[0]
                return

            best_name  = self.model_selector.select_best_model([100, 200, 300])
            best_model = self.model_selector.get_model(best_name)
            logger.info("Selected model: %s", best_name)

            try:
                if best_name in ['markov_order_2', 'cold_number_window_30']:
                    recent_draws = [
                        _parse_numbers(row)
                        for row in df.head(50)['numbers'].tolist()
                    ]
                    preds = best_model.predict(recent_draws, self.current_draw)
                else:
                    preds = best_model.predict(df, self.current_draw)
            except Exception as e:
                logger.error("Predict error: %s", e)
                traceback.print_exc()
                return

            if not preds:
                logger.warning("No prediction generated")
                return

            predicted_numbers, confidence = preds[0]
            logger.info("Predicted: %s  confidence=%.1f%%",
                        sorted(predicted_numbers), confidence * 100)

            filtered = self._apply_filter(predicted_numbers, confidence, df)
            if filtered:
                predicted_numbers, confidence = filtered
                logger.info("After filter: %s (%.1f%%)",
                            sorted(predicted_numbers), confidence * 100)

            self.last_prediction_id, _ = self.db.insert_prediction(
                self.current_draw, best_name, predicted_numbers, confidence
            )
            self.telegram.send_prediction(
                self.current_draw, best_name, predicted_numbers, confidence
            )
            logger.info("Prediction saved & sent (id=%s)", self.last_prediction_id)

    # ──────────────────────────────────────────────
    # Vòng lặp chính - mỗi 6 phút
    # ──────────────────────────────────────────────
    def run_one_cycle(self):
        """
        Luồng đúng:
        1. Chờ/lấy kết quả kỳ HIỆN TẠI từ vietlott.vn
        2. Xử lý kết quả (win/loss, sync Supabase, Telegram)
        3. Dự đoán kỳ TIẾP THEO → gửi Telegram
        """
        try:
            current = self.current_draw

            # Bước 1: Lấy kết quả kỳ hiện tại
            actual = self._fetch_result_from_db(current)

            if not actual:
                logger.info("Polling vietlott.vn for draw #%d ...", current)
                result = poll_draw_by_id(current, timeout=90, retry_interval=3)
                if result:
                    self.db.insert_draw(current, result)
                    actual = result
                    logger.info("Result fetched #%d: %s", current, actual)

            if actual:
                # Bước 2: Xử lý kết quả
                self.process_result(actual)

                # Bước 3: Dự đoán kỳ tiếp theo (current_draw đã tăng trong process_result)
                self.make_prediction()
            else:
                logger.warning("No result for draw #%d – skipping", current)
                self.current_draw += 1
                self.last_prediction_id = None
                # Vẫn dự đoán kỳ mới
                self.make_prediction()

        except Exception as e:
            logger.error("Cycle error: %s", e)
            traceback.print_exc()
            self.telegram.send_message(f"⚠️ Lỗi chu kỳ: {str(e)}")

    # ──────────────────────────────────────────────
    # Fetch kết quả từ DB
    # ──────────────────────────────────────────────
    def _fetch_result_from_db(self, draw_number: int) -> Optional[List[int]]:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            ph = self.db._ph()
            cursor.execute(
                f"SELECT numbers FROM draw_history WHERE draw_number={ph}", (draw_number,))
            row = cursor.fetchone()
            if row:
                return _parse_numbers(row[0])
            return None
        finally:
            conn.close()

    def notify_result_available(self, draw_number: int):
        logger.info("Admin notified: result for draw #%d available", draw_number)

    # ──────────────────────────────────────────────
    # Xử lý kết quả
    # ──────────────────────────────────────────────
    def process_result(self, actual_numbers: List[int]):
        with self._lock:
            logger.info("── Processing result draw #%d: %s ──",
                        self.current_draw, sorted(actual_numbers))

            self.db.insert_draw(self.current_draw, actual_numbers)
            self.supabase.push(self.current_draw, actual_numbers)
            self.db.update_cold_numbers(self.current_draw, actual_numbers)
            self._update_markov_online(actual_numbers)

            if self.last_prediction_id:
                self.db.update_prediction_result(
                    self.last_prediction_id, self.current_draw, actual_numbers
                )
                self._send_result_telegram(actual_numbers)

            self.db.refresh_model_stats(ALL_MODEL_NAMES)
            self.hybrid_model.update_weights(self.db)
            logger.info("Hybrid weights updated: %s", self.hybrid_model.weights)

            self.current_draw += 1
            self.last_prediction_id = None

            if self.current_draw % 50 == 0:
                logger.info("Periodic retrain (every 50 draws)...")
                df = self.db.get_recent_draws(500)
                self._train_all_models(df)

            logger.info("Result processed ✓")

    def _update_markov_online(self, actual_numbers: List[int]):
        try:
            df = self.db.get_recent_draws(4)
            if len(df) < 3:
                return
            sequences = [tuple(sorted(_parse_numbers(r['numbers'])))
                         for _, r in df.iterrows()]
            if len(sequences) >= 2:
                from_state = json.dumps(list(sequences[1:3]))
                to_state   = str(tuple(sorted(actual_numbers)))
                self.db.update_markov_transition(from_state, to_state)
        except Exception as e:
            logger.warning("Markov online update error: %s", e)

    def _send_result_telegram(self, actual_numbers: List[int]):
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            ph = self.db._ph()
            cursor.execute(
                f"SELECT predicted_numbers, model_name FROM predictions WHERE id={ph}",
                (self.last_prediction_id,))
            row = cursor.fetchone()
        finally:
            conn.close()

        if not row:
            return
        predicted_numbers = _parse_numbers(row[0])
        model_name        = row[1]
        match_count = len(set(predicted_numbers) & set(actual_numbers))
        is_win = Counter(predicted_numbers) == Counter(actual_numbers) if len(predicted_numbers) == 3 and len(actual_numbers) == 3 else False

        logger.info("Match: %d/3 → %s", match_count, "WIN" if is_win else "LOSS")
        self.telegram.send_result(
            self.current_draw - 1, actual_numbers,
            predicted_numbers, model_name, match_count, is_win
        )

    # ──────────────────────────────────────────────
    # Filter kèo đẹp
    # ──────────────────────────────────────────────
    def _apply_filter(self, numbers: List[int], confidence: float, df) -> Optional[tuple]:
        if confidence < 0.4:
            return None
        sorted_nums = sorted(numbers)
        if all(sorted_nums[i+1]-sorted_nums[i]==1 for i in range(len(sorted_nums)-1)):
            return None
        hot_counter = Counter()
        for nums in df.head(20)['numbers']:
            hot_counter.update(_parse_numbers(nums))
        hot = {n for n, _ in hot_counter.most_common(3)}
        if any(n in hot for n in numbers) and any(n not in hot for n in numbers):
            return (numbers, min(1.0, confidence * 1.1))
        return None

    # ──────────────────────────────────────────────
    # Thống kê + Backup
    # ──────────────────────────────────────────────
    def send_daily_statistics(self):
        try:
            stats = self.db.get_statistics()
            conn  = self.db.get_connection()
            try:
                cursor = conn.cursor()
                if USE_POSTGRES:
                    cursor.execute(
                        "SELECT COUNT(*) FROM draw_history "
                        "WHERE draw_time::date = CURRENT_DATE")
                else:
                    cursor.execute(
                        "SELECT COUNT(*) FROM draw_history "
                        "WHERE DATE(draw_time) = DATE('now')")
                stats['today_draws'] = cursor.fetchone()[0]
            finally:
                conn.close()
            # Gửi qua send_message vì send_statistics chưa có
            msg = (
                f"📊 <b>Thống kê ngày {datetime.now().strftime('%d/%m/%Y')}</b>\n"
                f"Tổng kỳ: {stats.get('total_draws', 0)}\n"
                f"Hôm nay:  {stats.get('today_draws', 0)}"
            )
            self.telegram.send_message(msg)
        except Exception as e:
            logger.error("Statistics error: %s", e)

    def auto_backup(self):
        try:
            dest = self.db.backup_database()
            if dest:
                logger.info("Auto backup completed → %s", dest)
        except Exception as e:
            logger.error("Auto backup failed: %s", e)

    # ──────────────────────────────────────────────
    # Start / Stop
    # ──────────────────────────────────────────────
    def start(self):
        self.is_running = True
        logger.info("Starting Bingo 18 Predictor Scheduler")
        logger.info("Interval: %d min | %d draws/day",
                    config.BINGO_INTERVAL_MINUTES, config.DRAWS_PER_DAY)

        self.initialize()

        schedule.every().day.at("03:00").do(self.auto_backup)
        schedule.every().day.at("23:55").do(self.send_daily_statistics)

        while self.is_running:
            try:
                schedule.run_pending()
                _now   = datetime.now()
                _secs  = _now.hour * 3600 + _now.minute * 60 + _now.second
                _idx   = _secs // 360
                _into  = _secs % 360
                if 25 <= _into < 30 and _idx != getattr(self, '_lidx', -1):
                    self._lidx = _idx
                    self.run_one_cycle()
                time.sleep(1)
            except KeyboardInterrupt:
                self.is_running = False
            except Exception as e:
                logger.error("Scheduler loop error: %s", e)
                traceback.print_exc()
                self.telegram.send_message(f"⚠️ Lỗi scheduler: {str(e)}")
                time.sleep(30)

    def stop(self):
        self.is_running = False
        logger.info("Scheduler stopped")


def run_scheduler():
    scheduler = BingoScheduler()
    scheduler.start()


if __name__ == "__main__":
    run_scheduler()