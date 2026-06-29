"""
train.py - Huấn luyện lại toàn bộ model Bingo18

Chạy:
    python train.py                  # Train HybridModel + LSTM (mặc định)
    python train.py --model hybrid   # Chỉ train HybridModel (không cần TensorFlow)
    python train.py --model lstm     # Chỉ train LSTM (cần: pip install tensorflow)
    python train.py --draws 1000     # Dùng 1000 kỳ gần nhất

Kết quả:
    model_store/hybrid_model.pkl     ← HybridModel (Markov + Cold + ML Ensemble)
    models/lstm_bingo18.keras        ← LSTM model
"""

import argparse
import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def train_hybrid(n_draws: int = 500) -> bool:
    """
    Huấn luyện HybridModel (Markov + ColdNumber + MLEnsemble).
    Không cần TensorFlow. Kết quả lưu tại model_store/hybrid_model.pkl
    """
    logger.info("=" * 50)
    logger.info("BƯỚC 1/2 – Train HybridModel")
    logger.info("=" * 50)

    try:
        from database import DatabaseManager
        from models import HybridModel
        import config

        db = DatabaseManager()
        logger.info("Đang tải %d kỳ gần nhất từ database...", n_draws)
        df = db.get_recent_draws(n_draws)

        if df.empty:
            logger.error("❌ Không có dữ liệu trong database. Hãy import lịch sử trước.")
            logger.error("   Chạy: python import_history.py 500")
            return False

        logger.info("✅ Tải được %d kỳ (draw #%d → #%d)",
                    len(df),
                    int(df['draw_number'].min()),
                    int(df['draw_number'].max()))

        if len(df) < 50:
            logger.warning("⚠️  Chỉ có %d kỳ — cần ít nhất 50 để train hiệu quả.", len(df))

        os.makedirs(config.MODELS_PATH, exist_ok=True)
        save_path = os.path.join(config.MODELS_PATH, "hybrid_model.pkl")

        logger.info("Đang train HybridModel...")
        t0 = time.time()
        model = HybridModel()
        model.train(df)
        model.save(save_path)
        elapsed = time.time() - t0

        logger.info("✅ HybridModel train xong (%.1f giây) → %s", elapsed, save_path)
        return True

    except ImportError as e:
        logger.error("❌ Import lỗi: %s", e)
        logger.error("   Hãy chạy: pip install -r requirements.txt")
        return False
    except Exception as e:
        logger.exception("❌ Lỗi train HybridModel: %s", e)
        return False


def train_lstm(n_draws: int = 2000) -> bool:
    """
    Huấn luyện LSTM model.
    Yêu cầu: pip install tensorflow==2.15.0
    Kết quả lưu tại models/lstm_bingo18.keras
    """
    logger.info("=" * 50)
    logger.info("BƯỚC 2/2 – Train LSTM")
    logger.info("=" * 50)

    try:
        import tensorflow as tf
        # tensorflow-intel (Windows) dùng stub module → __version__ có thể không có
        try:
            tf_ver = tf.__version__
        except AttributeError:
            try:
                import importlib.metadata
                tf_ver = importlib.metadata.version("tensorflow-intel")
            except Exception:
                tf_ver = "unknown"
        logger.info("TensorFlow version: %s", tf_ver)
    except ImportError:
        logger.warning("⚠️  TensorFlow chưa được cài. Bỏ qua train LSTM.")
        logger.warning("   Để train LSTM: pip install tensorflow==2.15.0")
        return False

    try:
        from lstm_model import load_draws, train as lstm_train, MODEL_PATH

        logger.info("Đang tải %d kỳ từ SQLite...", n_draws)
        draws = load_draws(n_draws)

        if not draws:
            logger.error("❌ Không tải được dữ liệu cho LSTM.")
            return False

        if len(draws) < 30:
            logger.error("❌ Chỉ có %d kỳ — LSTM cần ít nhất 30.", len(draws))
            return False

        logger.info("✅ Tải được %d kỳ — bắt đầu train LSTM...", len(draws))
        t0 = time.time()
        model, history = lstm_train(draws)
        elapsed = time.time() - t0

        val_loss = history.history.get('val_loss', [None])[-1]
        val_acc  = history.history.get('val_accuracy', [None])[-1]

        logger.info("✅ LSTM train xong (%.1f giây)", elapsed)
        logger.info("   Val Loss: %.4f | Val Accuracy: %s",
                    val_loss or 0,
                    f"{val_acc:.4f}" if val_acc else "N/A")
        logger.info("   Model lưu tại: %s", MODEL_PATH)
        return True

    except Exception as e:
        logger.exception("❌ Lỗi train LSTM: %s", e)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Huấn luyện lại model Bingo18",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  python train.py                    # Train cả HybridModel lẫn LSTM
  python train.py --model hybrid     # Chỉ train HybridModel (nhanh, không cần TF)
  python train.py --model lstm       # Chỉ train LSTM (cần TensorFlow)
  python train.py --draws 1000       # Dùng 1000 kỳ gần nhất
        """
    )
    parser.add_argument(
        "--model", choices=["hybrid", "lstm", "all"], default="all",
        help="Model cần train (mặc định: all)"
    )
    parser.add_argument(
        "--draws", type=int, default=500,
        help="Số kỳ lịch sử dùng để train HybridModel (mặc định: 500)"
    )
    parser.add_argument(
        "--lstm-draws", type=int, default=2000,
        help="Số kỳ lịch sử dùng để train LSTM (mặc định: 2000)"
    )
    args = parser.parse_args()

    logger.info("╔══════════════════════════════════════════╗")
    logger.info("║     BINGO 18 – Model Training Script     ║")
    logger.info("╚══════════════════════════════════════════╝")
    logger.info("Chế độ: %s | HybridModel draws: %d | LSTM draws: %d",
                args.model.upper(), args.draws, args.lstm_draws)

    ok_hybrid = ok_lstm = True

    if args.model in ("hybrid", "all"):
        ok_hybrid = train_hybrid(args.draws)

    if args.model in ("lstm", "all"):
        ok_lstm = train_lstm(args.lstm_draws)

    logger.info("")
    logger.info("══ KẾT QUẢ ════════════════════════════════")
    logger.info("HybridModel : %s", "✅ Thành công" if ok_hybrid else "❌ Thất bại / Bỏ qua")
    logger.info("LSTM        : %s", "✅ Thành công" if ok_lstm   else "⚠️  Cần TensorFlow / Thất bại")
    logger.info("═══════════════════════════════════════════")

    if not ok_hybrid:
        logger.error("Train HybridModel thất bại. Kiểm tra database và thử lại.")
        sys.exit(1)

    logger.info("Bước tiếp theo: khởi động lại server để load model mới.")
    sys.exit(0)


if __name__ == "__main__":
    main()


# ── Ghi chú sau khi train ─────────────────────────────────────────────────────
# Nếu DB có kỳ chưa có prediction, chạy thêm:
#   python sync_predictions.py --limit 2376
# để điền retroactive predictions và cập nhật win rate stats chính xác.
