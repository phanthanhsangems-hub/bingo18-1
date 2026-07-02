"""
sync_to_supabase.py  —  v4.1
====================================
Bảng: public.draw_history
  - draw_number  (INTEGER PRIMARY KEY)
  - draw_time    (TIMESTAMP)
  - numbers      (TEXT, dạng '[3, 4, 4]')
  - size_category (TEXT: 'LON'/'HOA'/'NHO')
  - sum_value    (INTEGER)
  - created_at   (TIMESTAMP)

Cách dùng:
  python sync_to_supabase.py --mode test    # kiểm tra kết nối
  python sync_to_supabase.py --mode bulk    # sync toàn bộ kỳ còn thiếu
  python sync_to_supabase.py --mode watch   # chạy liên tục mỗi 60s
"""
import argparse, logging, os, sys, time, re, threading, subprocess
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv()

import requests
from bs4 import BeautifulSoup
import psycopg2
from vietlott_fetcher import fetch_from_github

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('sync.log', encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
DB_CONFIG = {
    'host':            os.environ.get('DB_HOST', ''),
    'port':            int(os.environ.get('DB_PORT') or 5432),
    'dbname':          os.environ.get('DB_NAME', 'postgres'),
    'user':            os.environ.get('DB_USER', ''),
    'password':        os.environ.get('DB_PASSWORD', ''),
    'sslmode':         'require',
    'connect_timeout': 15,
}
TABLE          = '"public"."draw_history"'
FETCH_INTERVAL = 10   # giây

CLOUD_RUN_URL  = os.environ.get('CLOUD_RUN_URL', '')
TRIGGER_SECRET = os.environ.get('TRIGGER_SECRET', '').strip()

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT  = os.environ.get('TELEGRAM_CHAT_ID', '')
# #18: chỉ announce khi conf >= ngưỡng (0.0 = luôn announce)
ANNOUNCE_MIN_CONF = float(os.environ.get('ANNOUNCE_MIN_CONF', '0.0'))

BASE_URL    = "https://vietlott.vn"
HOME_URL    = f"{BASE_URL}/"
DETAIL_URL  = f"{BASE_URL}/vi/trung-thuong/ket-qua-trung-thuong/view-detail-bingo18-result"
HEADERS     = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'vi,en-US;q=0.7,en;q=0.3',
}
# ──────────────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════════════
#  VIETLOTT FETCHER
# ══════════════════════════════════════════════════════════════

_session = requests.Session()
_session.headers.update(HEADERS)


def _parse_bingo18(html: str) -> list:
    """Parse HTML → list of draw dicts."""
    soup    = BeautifulSoup(html, 'lxml')
    results = []

    for div in soup.find_all('div', class_='CssDivBingo'):
        balls = div.find_all('span', class_='bong_tron_bingo')
        nums  = []
        for b in balls:
            try:
                n = int(b.get_text(strip=True))
                if 1 <= n <= 18:
                    nums.append(n)
            except ValueError:
                pass
        if not nums:
            continue

        tr = div.find_parent('tr')
        if not tr:
            continue

        draw_id   = None
        draw_date = None

        for link in tr.find_all('a', href=True):
            m = re.search(r'[?&]id=(\d+)', link['href'])
            if m:
                draw_id = int(m.group(1))
                break

        if not draw_id:
            m = re.search(r'#0*(\d+)', tr.get_text())
            if m:
                draw_id = int(m.group(1))

        tds = tr.find_all('td')
        if tds:
            m2 = re.search(r'(\d{2}/\d{2}/\d{4})', tds[0].get_text())
            if m2:
                d, mo, y = m2.group(1).split('/')
                draw_date = f"{y}-{mo}-{d}"  # date only; time assigned by caller

        total = None
        size  = None
        if len(tds) >= 4:
            try:
                total = int(tds[2].get_text(strip=True))
            except:
                pass
            size = tds[3].get_text(strip=True)

        if nums:
            results.append({
                'draw_id':   draw_id,
                'numbers':   nums,
                'draw_date': draw_date or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'total':     total,
                'size':      size,
            })

    return results


def fetch_homepage() -> list:
    try:
        r = _session.get(HOME_URL, timeout=15)
        if r.status_code == 200:
            return _parse_bingo18(r.text)
    except Exception as e:
        logger.warning(f"Homepage fetch: {e}")
    return []


def fetch_detail(draw_id: int) -> dict | None:
    url = f"{DETAIL_URL}?nocatche=1&id={draw_id:07d}"
    try:
        r = _session.get(url, timeout=15)
        if r.status_code == 200:
            results = _parse_bingo18(r.text)
            if results:
                result = results[0]
                if not result.get('draw_id'):
                    result['draw_id'] = draw_id
                return result
    except Exception as e:
        logger.debug(f"Detail #{draw_id}: {e}")
    return None


def get_latest() -> dict | None:
    results = fetch_homepage()
    if not results:
        return None
    return max(results, key=lambda x: x['draw_id'])


def get_new_since(last_id: int) -> list:
    """
    Lấy kỳ mới hơn last_id.
    Bước 1: thử homepage (nhanh, HTML tĩnh)
    Bước 2: nếu không thấy → poll tuần tự từng kỳ bằng fetch_detail
    """
    # Bước 1: homepage
    results = fetch_homepage()
    new = [r for r in results if r['draw_id'] > last_id]
    if new:
        return sorted(new, key=lambda x: x['draw_id'])

    # Bước 2: poll detail từng kỳ (tối đa 5, dừng khi miss 2 liên tiếp)
    polled = []
    next_id = last_id + 1
    consecutive_miss = 0

    for _ in range(5):
        detail = fetch_detail(next_id)
        if detail:
            polled.append(detail)
            logger.info(f"Poll ✅ #{next_id}: {detail['numbers']}")
            next_id += 1
            consecutive_miss = 0
        else:
            consecutive_miss += 1
            logger.debug(f"Poll ⏳ #{next_id}: chưa có (miss={consecutive_miss})")
            if consecutive_miss >= 2:
                break
            next_id += 1

    return polled


# ══════════════════════════════════════════════════════════════
#  SUPABASE
# ══════════════════════════════════════════════════════════════

def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def get_last_draw_id(conn) -> int:
    cur = conn.cursor()
    cur.execute(f"SELECT MAX(draw_number) FROM {TABLE};")
    row = cur.fetchone()
    return row[0] if row and row[0] else 0


def size_to_category(size_text: str) -> str:
    """Unused — prefer computing from sum. Kept for reference only."""
    if not size_text:
        raise ValueError("size_to_category: empty text — compute from sum instead")
    s = size_text.strip().lower()
    if 'l' in s and 'n' not in s[:2]:
        return 'LON'
    if 'nh' in s or 'nho' in s:
        return 'NHO'
    if 'ho' in s:
        return 'HOA'
    raise ValueError(f"size_to_category: unrecognised text '{size_text}' — compute from sum instead")


def insert_draw(conn, draw: dict) -> bool:
    try:
        cur      = conn.cursor()
        nums_str = str(draw['numbers'])
        total    = draw.get('total') or sum(draw['numbers'])
        cat      = 'NHO' if total <= 9 else ('HOA' if total <= 11 else 'LON')

        cur.execute(f"""
            INSERT INTO {TABLE}
                (draw_number, draw_time, numbers, size_category, sum_value, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (draw_number) DO NOTHING;
        """, (
            draw['draw_id'],
            draw.get('draw_date') or datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            nums_str,
            cat,
            total,
        ))
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        logger.error(f"Insert #{draw.get('draw_id')}: {e}")
        return False


# ══════════════════════════════════════════════════════════════
#  TRIGGER PREDICTION (Cloud Run)
# ══════════════════════════════════════════════════════════════

def trigger_prediction():
    """Gọi Cloud Run tạo dự đoán mới và gửi Telegram."""
    try:
        r = requests.post(
            f"{CLOUD_RUN_URL}/api/trigger-prediction",
            headers={"X-Trigger-Secret": TRIGGER_SECRET},
            timeout=30,
        )
        if r.status_code == 200:
            logger.info("🤖 Trigger prediction ✅")
            return True
        logger.warning(f"Trigger prediction HTTP {r.status_code}: {r.text[:100]}")
    except Exception as e:
        logger.warning(f"Trigger prediction lỗi: {e}")
    return False


# ══════════════════════════════════════════════════════════════
#  TELEGRAM
# ══════════════════════════════════════════════════════════════

def send_telegram(draw: dict):
    nums  = draw['numbers']
    total = draw.get('total') or sum(nums)
    cat   = 'NHO' if total <= 9 else ('HOA' if total <= 11 else 'LON')
    nums_str = " - ".join(str(n) for n in nums)

    is_triple = len(set(nums)) == 1
    if is_triple:
        triple_val = nums[0]
        header = f"🎰🎰🎰 TRIPLE {triple_val}-{triple_val}-{triple_val} 🎰🎰🎰\n"
        note   = f"\n⚡ Xác suất: 1/36 (~2.78%) | Trung bình 36 kỳ mới ra 1 lần!"
    else:
        header = ""
        note   = ""

    msg = (
        f"{header}"
        f"🎯 Bingo18 #{draw['draw_id']}\n"
        f"📅 {draw.get('draw_date','')}\n"
        f"🔢 {nums_str}\n"
        f"📊 Tổng {total} | {cat}"
        f"{note}"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": msg},
            timeout=5
        )
        if is_triple:
            logger.info(f"🎰 TRIPLE alert sent: {nums[0]}-{nums[0]}-{nums[0]}")
    except Exception as e:
        logger.warning(f"Telegram: {e}")


def check_and_alert_hot_combo(conn, draw: dict, alerted: dict):
    """
    Sau mỗi insert, kiểm tra xem bộ số vừa ra đã ra ≥3 lần hôm nay chưa.
    Nếu có và chưa alert hôm nay → gửi Telegram + ghi nhớ để tránh spam.
    alerted: dict keyed by (date_vn, combo_key) → True
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return

    nums = draw['numbers']
    # sort để canonical key (3-4-4 == 4-3-4)
    combo_key = "-".join(str(n) for n in sorted(nums))

    try:
        cur = conn.cursor()
        # Count occurrences of any permutation of this multiset today
        sorted_nums = sorted(nums)
        cur.execute("""
            SELECT COUNT(*) FROM draw_history
            WHERE (SELECT array_agg(x::int ORDER BY x::int)
                   FROM jsonb_array_elements_text(numbers::jsonb) AS x)
                  = %s::int[]
              AND (draw_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
                  = (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
        """, (sorted_nums,))
        row = cur.fetchone()
        cur.close()
        count = row[0] if row else 0
    except Exception as e:
        logger.warning(f"check_hot_combo query: {e}")
        conn.rollback()
        return

    if count < 3:
        return

    # Dùng ngày VN làm key để auto-reset hàng ngày
    date_vn = datetime.now(timezone.utc).astimezone(
        ZoneInfo('Asia/Ho_Chi_Minh')
    ).strftime('%Y-%m-%d')
    alert_key = (date_vn, combo_key)

    if alerted.get(alert_key):
        return  # đã alert rồi, bỏ qua

    alerted[alert_key] = True
    nums_str = " - ".join(str(n) for n in nums)
    total = sum(nums)
    cat   = 'NHO' if total <= 9 else ('HOA' if total <= 11 else 'LON')
    fire  = '🔥' * min(count - 2, 3)
    msg = (
        f"{fire} BỘ NÓNG HÔM NAY {fire}\n"
        f"🎯 {nums_str} ra lần thứ {count} hôm nay!\n"
        f"📊 Tổng {total} | {cat}\n"
        f"⚠️ Xác suất ra lại tiếp theo tăng cao — theo dõi sát!"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": msg},
            timeout=5
        )
        logger.info(f"🔥 Hot combo alert: {combo_key} ×{count} hôm nay")
    except Exception as e:
        logger.warning(f"Telegram hot_combo: {e}")


def _tg_send(text: str):
    """Gửi tin nhắn Telegram đơn giản (plain text)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": text},
            timeout=5,
        )
    except Exception as e:
        logger.warning(f"Telegram send: {e}")


def _tg_html(text: str):
    """Gửi tin nhắn Telegram với HTML formatting."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
        if not r.ok:
            import re as _re
            _tg_send(_re.sub(r'<[^>]+>', '', text))
    except Exception as e:
        logger.warning(f"Telegram html: {e}")


def announce_prediction(conn, draw_number: int):
    """
    #2 — Đợi Cloud Run compute xong (~8s) rồi fetch dự đoán mới nhất và gửi Telegram.
    """
    time.sleep(10)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT predicted_numbers, model_name, confidence,
                   CASE WHEN (SELECT SUM(v::int) FROM jsonb_array_elements_text(predicted_numbers::jsonb) v) <= 9  THEN 'NHO'
                        WHEN (SELECT SUM(v::int) FROM jsonb_array_elements_text(predicted_numbers::jsonb) v) <= 11 THEN 'HOA'
                        ELSE 'LON' END AS pred_size
            FROM predictions
            WHERE draw_number = %s
            ORDER BY prediction_time DESC
            LIMIT 1
        """, (draw_number + 1,))
        row = cur.fetchone()
        cur.close()
        if not row:
            logger.info("announce_prediction: chưa có dự đoán cho kỳ %d", draw_number + 1)
            return
        pred_nums, model_name, conf, pred_size = row
        if isinstance(pred_nums, str):
            import json as _json
            pred_nums = _json.loads(pred_nums)
        conf_val = float(conf) if conf else 0.0
        # #18: smart announce — bỏ qua nếu confidence dưới ngưỡng
        if ANNOUNCE_MIN_CONF > 0 and conf_val < ANNOUNCE_MIN_CONF:
            logger.info("announce_prediction: skip kỳ #%d conf=%.2f < threshold=%.2f",
                        draw_number + 1, conf_val, ANNOUNCE_MIN_CONF)
            return
        nums_str = " - ".join(str(n) for n in pred_nums)
        conf_pct = f"{round(conf_val*100)}%" if conf else "?"
        sz_emoji = {"NHO": "🟢", "HOA": "🟡", "LON": "🔴"}.get(pred_size, "⚪")
        conf_star = "⭐" if conf_val >= 0.7 else "🔸" if conf_val >= 0.55 else ""
        msg = (
            f"🤖 Dự đoán kỳ #{draw_number + 1} {conf_star}\n"
            f"🔢 {nums_str}\n"
            f"{sz_emoji} {pred_size} · model: {model_name} · conf: {conf_pct}"
        )
        _tg_send(msg)
        logger.info("📢 Announced prediction kỳ #%d: %s conf=%.2f", draw_number + 1, nums_str, conf_val)
    except Exception as e:
        logger.warning(f"announce_prediction: {e}")


def check_size_streak(conn, alerted_streak: dict):
    """
    #4 — Alert khi chuỗi size (NHO/HOA/LON) ra ≥4 lần liên tiếp.
    alerted_streak: {streak_key: True} — tự reset khi streak vỡ.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT size_category FROM draw_history
            ORDER BY draw_number DESC LIMIT 6
        """)
        rows = [r[0] for r in cur.fetchall()]
        cur.close()
    except Exception as e:
        logger.warning(f"check_size_streak query: {e}")
        return

    if not rows:
        return

    # Đếm chuỗi đầu tiên (mới nhất)
    current = rows[0]
    streak  = 1
    for sz in rows[1:]:
        if sz == current:
            streak += 1
        else:
            break

    streak_key = f"{current}_{streak}"

    # Reset các key cũ của size này nếu streak vỡ
    for k in list(alerted_streak.keys()):
        if k.startswith(current + "_") and k != streak_key:
            del alerted_streak[k]

    if streak < 4 or alerted_streak.get(streak_key):
        return

    alerted_streak[streak_key] = True
    sz_emoji = {"NHO": "🟢", "HOA": "🟡", "LON": "🔴"}.get(current, "⚪")
    msg = (
        f"📊 CHUỖI SIZE #{streak} liên tiếp!\n"
        f"{sz_emoji} {current} × {streak} kỳ liên tiếp\n"
        f"⚠️ Xác suất đảo chiều sang kỳ tới tăng dần!"
    )
    _tg_send(msg)
    logger.info("📊 Size streak alert: %s ×%d", current, streak)


def check_wr_alert(conn, wr_alerted: dict):
    """#42 Alert khi WR 20 kỳ gần nhất < 30% (dưới baseline xa)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT pr.is_win_size
            FROM predictions p
            JOIN prediction_results pr ON pr.prediction_id = p.id
            WHERE pr.is_win_size IS NOT NULL
            ORDER BY p.draw_number DESC
            LIMIT 20
        """)
        rows = [bool(r[0]) for r in cur.fetchall()]
        cur.close()
    except Exception as e:
        logger.warning("check_wr_alert: %s", e)
        return
    if len(rows) < 20:
        return
    wins = sum(rows)
    wr   = wins / len(rows)
    if wr < 0.30 and not wr_alerted.get('low'):
        wr_alerted['low'] = True
        wr_alerted.pop('recovered', None)
        _tg_send(
            f"📉 *WR THẤP!*\n"
            f"20 kỳ gần nhất: *{wins}/20 ({wr*100:.0f}%)*\n"
            f"Baseline: 37.5% — đang dưới xa\n"
            f"⚠️ Cân nhắc kiểm tra model"
        )
        logger.info("#42 WR low alert: %d/20 = %.0f%%", wins, wr * 100)
    elif wr >= 0.375 and wr_alerted.get('low') and not wr_alerted.get('recovered'):
        wr_alerted['recovered'] = True
        wr_alerted.pop('low', None)
        _tg_send(f"✅ WR phục hồi: {wins}/20 ({wr*100:.0f}%) ≥ baseline")
        logger.info("#42 WR recovered: %d/20 = %.0f%%", wins, wr * 100)


def check_hoa_reeval(conn, reeval_state: dict):
    """#49 Monthly re-evaluation of HOA block (P142).
    Compares recent HOA actual rate vs historical — alerts if HOA is trending up."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    import time as _t
    now = _t.time()
    if now - reeval_state.get('last_ts', 0) < 86400 * 30:  # 30 days
        return
    reeval_state['last_ts'] = now
    try:
        cur = conn.cursor()
        # Recent 30d HOA rate
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE size_category='HOA')::float / NULLIF(COUNT(*),0) AS hoa_recent,
                COUNT(*) AS n_recent
            FROM draw_history
            WHERE draw_time >= NOW() - INTERVAL '30 days'
        """)
        r30 = cur.fetchone()
        # All-time HOA rate
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE size_category='HOA')::float / NULLIF(COUNT(*),0) AS hoa_all,
                COUNT(*) AS n_all
            FROM draw_history
        """)
        rall = cur.fetchone()
        cur.close()

        hoa_30  = round((r30[0] or 0) * 100, 1)
        n_30    = r30[1] or 0
        hoa_all = round((rall[0] or 0) * 100, 1)
        n_all   = rall[1] or 0
        delta   = round(hoa_30 - hoa_all, 1)

        # P142 was blocked when HOA WR ≈ 18-24%. Alert if HOA frequency rebounds
        if n_30 >= 100 and delta >= 3.0:
            _tg_send(
                f"📊 *HOA Re-evaluation (#49)*\n"
                f"HOA 30 ngày gần: *{hoa_30}%* (n={n_30})\n"
                f"HOA lịch sử: {hoa_all}% (n={n_all})\n"
                f"Delta: *+{delta}%* — HOA đang tăng tần suất\n"
                f"⚠️ Cân nhắc đánh giá lại block P142"
            )
            logger.info("#49 HOA reeval: recent=%.1f%% all=%.1f%% delta=+%.1f%% → alert sent", hoa_30, hoa_all, delta)
        else:
            logger.info("#49 HOA reeval: recent=%.1f%% all=%.1f%% delta=%.1f%% → block OK", hoa_30, hoa_all, delta)
    except Exception as e:
        logger.warning("check_hoa_reeval: %s", e)


def check_system_health_alert(conn, sh_alerted: dict):
    """Alert khi system health thay đổi sang warn/bad dựa trên WR50."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    now = time.time()
    if now - sh_alerted.get('last_check', 0) < 1800:  # check mỗi 30 phút
        return
    sh_alerted['last_check'] = now
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COALESCE(is_win_size, is_win, FALSE)
            FROM prediction_results ORDER BY id DESC LIMIT 50
        """)
        rows = [bool(r[0]) for r in cur.fetchall()]
        cur.close()
    except Exception as e:
        logger.warning("check_system_health_alert: %s", e)
        return
    if len(rows) < 20:
        return
    wr50 = sum(rows) / len(rows)
    status = 'BAD' if wr50 < 0.30 else ('WARN' if wr50 < 0.34 else 'GOOD')
    prev   = sh_alerted.get('status', 'GOOD')
    if status == prev:
        return
    sh_alerted['status'] = status
    if status == 'GOOD':
        _tg_send(f"✅ *System Health phục hồi*\nWR 50 kỳ: *{wr50*100:.1f}%* ≥ 34%")
        logger.info("System health recovered: WR50=%.1f%%", wr50 * 100)
    else:
        icon = '❌' if status == 'BAD' else '⚠️'
        msg  = 'Cần kiểm tra model ngay!' if status == 'BAD' else 'Đang dưới baseline, theo dõi.'
        _tg_send(
            f"{icon} *System Health: {status}*\n"
            f"WR 50 kỳ: *{wr50*100:.1f}%*\n{msg}"
        )
        logger.info("System health %s: WR50=%.1f%%", status, wr50 * 100)


def check_confidence_gap(conn, gap_alerted: dict):
    """#47 Alert khi avg confidence - actual WR > 15% trong 20 kỳ đã đánh giá."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT p.confidence, pr.is_win_size
            FROM predictions p
            JOIN prediction_results pr ON pr.prediction_id = p.id
            WHERE pr.is_win_size IS NOT NULL AND p.confidence IS NOT NULL
            ORDER BY p.draw_number DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        logger.warning("check_confidence_gap: %s", e)
        return
    if len(rows) < 20:
        return
    avg_conf = sum(float(r[0]) for r in rows) / len(rows)
    wr       = sum(1 for r in rows if r[1]) / len(rows)
    gap      = avg_conf - wr
    if gap > 0.15 and not gap_alerted.get('active'):
        gap_alerted['active'] = True
        _tg_send(
            f"⚠️ *Confidence Gap (#47)*\n"
            f"20 kỳ gần nhất:\n"
            f"Avg confidence: *{avg_conf*100:.1f}%*\n"
            f"Actual WR: *{wr*100:.1f}%*\n"
            f"Gap: *+{gap*100:.1f}%* > 15% — model đang overcalibrated"
        )
        logger.info("#47 Conf gap: conf=%.1f%% wr=%.1f%% gap=+%.1f%%",
                    avg_conf * 100, wr * 100, gap * 100)
    elif gap <= 0.10 and gap_alerted.get('active'):
        gap_alerted.pop('active', None)
        logger.info("#47 Conf gap resolved: conf=%.1f%% wr=%.1f%%", avg_conf * 100, wr * 100)


def check_triple_number(draw: dict, triple_alerted: dict):
    """#32 — Alert khi kết quả có 3 số giống nhau [x,x,x]."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        nums = draw.get('numbers', [])
        if isinstance(nums, str):
            import json as _j
            nums = _j.loads(nums)
        nums = [int(x) for x in nums]
        if len(nums) == 3 and nums[0] == nums[1] == nums[2]:
            draw_id = draw.get('draw_id', '?')
            if triple_alerted.get(draw_id):
                return
            triple_alerted[draw_id] = True
            n = nums[0]
            s = sum(nums)
            size_vi = 'NHO' if s <= 9 else ('HOA' if s <= 11 else 'LON')
            _tg_html(
                f"🎰  <b>TRIPLE RA ROI! KY #{draw_id}</b>\n"
                f"────────────────────\n"
                f"     <b>{n}  ·  {n}  ·  {n}</b>\n"
                f"     Tong <b>{s}</b>   <b>{size_vi}</b>\n"
                f"────────────────────\n"
                f"Xac suat: 0.45% — trung binh 220 ky moi ra 1 lan"
            )
            logger.info("Triple alert ky #%s: %s-%s-%s", draw_id, n, n, n)
    except Exception as e:
        logger.warning("check_triple_number: %s", e)


def check_pair_triple_drought(conn, drought_alerted: dict):
    """Alert khi triple hoặc pair chưa ra trong nhiều kỳ liên tiếp (GAN RA)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        import json as _j
        cur = conn.cursor()
        cur.execute("""
            SELECT numbers FROM draw_history
            ORDER BY draw_number DESC LIMIT 120
        """)
        rows = [r[0] for r in cur.fetchall()]
        cur.close()

        def parse(raw):
            if isinstance(raw, list): return [int(x) for x in raw]
            return [int(x) for x in _j.loads(raw)]

        # Đếm kỳ liên tiếp gần nhất KHÔNG có triple / pair
        triple_drought = pair_drought = 0
        for raw in rows:
            nums = parse(raw)
            from collections import Counter as _C
            mc = max(_C(nums).values())
            if mc == 3:
                break
            triple_drought += 1
        for raw in rows:
            nums = parse(raw)
            from collections import Counter as _C
            mc = max(_C(nums).values())
            if mc >= 2:
                break
            pair_drought += 1

        # ── Tìm triple lạnh nhất (chưa ra lâu nhất) ──────────────
        cur2 = conn.cursor()
        cur2.execute("""
            SELECT draw_number, numbers FROM draw_history
            ORDER BY draw_number DESC LIMIT 2000
        """)
        history = [(r[0], parse(r[1])) for r in cur2.fetchall()]
        cur2.close()

        triples_all = [(v, v, v) for v in range(1, 7)]
        triple_last_seen = {}  # value → draws ago
        max_dn = history[0][0] if history else 0
        for v in range(1, 7):
            last = next(
                (max_dn - dn for dn, nums in history if nums[0] == nums[1] == nums[2] == v),
                9999
            )
            triple_last_seen[v] = last

        coldest_triple_val = max(triple_last_seen, key=triple_last_seen.get)
        coldest_ago        = triple_last_seen[coldest_triple_val]
        coldest_str        = f"{coldest_triple_val}·{coldest_triple_val}·{coldest_triple_val}"
        coldest_s          = coldest_triple_val * 3
        coldest_size       = 'NHO' if coldest_s <= 9 else 'LON'

        # Bảng tất cả 6 triples với số kỳ vắng mặt
        triple_table = "  ".join(
            f"{v}·{v}·{v}({triple_last_seen[v]}k)" for v in range(1, 7)
        )

        # ── TRIPLE drought ─────────────────────────────────────
        for threshold in (50, 80):
            key = f'triple_d{threshold}'
            if triple_drought >= threshold:
                if not drought_alerted.get(key):
                    drought_alerted[key] = True
                    _tg_html(
                        f"⚠️  <b>TRIPLE CHUA RA {triple_drought} KY!</b>\n"
                        f"────────────────────\n"
                        f"🎯  Goi y choi:  <b>{coldest_str}</b>  ({coldest_size})  — vang <b>{coldest_ago} ky</b>\n"
                        f"────────────────────\n"
                        f"Tat ca 6 triple (vang mat):\n"
                        f"{triple_table}"
                    )
                    logger.info("Triple drought alert: %d ky — coldest: %s (%d k)",
                                triple_drought, coldest_str, coldest_ago)
            else:
                drought_alerted.pop(key, None)  # reset khi triple da ra

        # ── PAIR drought ───────────────────────────────────────
        PAIR_THRESH = 6   # avg=2.4 ky; alert khi qua 6 (1 lan) va 9
        for threshold in (6, 9):
            key = f'pair_d{threshold}'
            if pair_drought >= threshold:
                if not drought_alerted.get(key):
                    drought_alerted[key] = True
                    _tg_html(
                        f"⚠️  <b>BO DOI CHUA RA {pair_drought} KY!</b>\n"
                        f"────────────────────\n"
                        f"Trung binh 2.4 ky/lan — dang kho han\n"
                        f"Xac suat co bo doi ky tiep: ~42%"
                    )
                    logger.info("Pair drought alert: %d ky", pair_drought)
            else:
                drought_alerted.pop(key, None)

    except Exception as e:
        logger.warning("check_pair_triple_drought: %s", e)


def check_cold_numbers(conn, cold_alerted: dict):
    """
    #6 — Alert khi một số (1-6) không xuất hiện trong ≥30 kỳ liên tiếp.
    cold_alerted: {num: last_alert_draw} để tránh spam.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT draw_number, numbers FROM draw_history
            ORDER BY draw_number DESC LIMIT 60
        """)
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        logger.warning(f"check_cold_numbers query: {e}")
        return

    if not rows:
        return

    import json as _json
    latest_draw = rows[0][0]

    # Tìm draw cuối mỗi số xuất hiện
    last_seen: dict = {}
    for draw_number, numbers_raw in rows:
        try:
            nums = _json.loads(numbers_raw) if isinstance(numbers_raw, str) else numbers_raw
        except Exception:
            continue
        for n in nums:
            if n not in last_seen:
                last_seen[n] = draw_number

    for num in range(1, 7):
        seen_at = last_seen.get(num)
        if seen_at is None:
            gap = 60  # không thấy trong 60 kỳ mẫu
        else:
            gap = latest_draw - seen_at

        if gap < 30:
            # Reset alert nếu số đã xuất hiện lại
            cold_alerted.pop(num, None)
            continue

        last_alerted_at = cold_alerted.get(num, 0)
        if latest_draw - last_alerted_at < 10:
            continue  # alert lại sau ≥10 kỳ để tránh spam

        cold_alerted[num] = latest_draw
        msg = (
            f"❄️ SỐ LẠNH: {num}\n"
            f"Số {num} chưa ra trong {gap} kỳ liên tiếp!\n"
            f"(kỳ gần nhất: {'#' + str(seen_at) if seen_at else 'không rõ'})\n"
            f"⚠️ Có thể sắp xuất hiện trở lại."
        )
        _tg_send(msg)
        logger.info("❄️ Cold number alert: %d chưa ra %d kỳ", num, gap)


def check_size_bias(conn, bias_alerted: dict):
    """
    #27 — Alert khi SIZE phân bố hôm nay lệch mạnh: một SIZE chiếm >65% draws.
    Chỉ alert khi có ≥20 kỳ hôm nay để tránh false positive sáng sớm.
    bias_alerted: {bias_key: True} — reset khi bias hết.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT size_category, COUNT(*) AS cnt
            FROM draw_history
            WHERE (draw_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
                  = (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
            GROUP BY size_category
        """)
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        logger.warning(f"check_size_bias query: {e}")
        return

    total = sum(r[1] for r in rows)
    if total < 20:
        return  # chưa đủ sample

    for size_cat, cnt in rows:
        ratio = cnt / total
        if ratio < 0.65:
            bias_alerted.pop(size_cat, None)  # reset nếu bias hết
            continue
        if bias_alerted.get(size_cat):
            continue  # đã alert rồi

        bias_alerted[size_cat] = True
        sz_emoji = {"NHO": "🟢", "HOA": "🟡", "LON": "🔴"}.get(size_cat, "⚪")
        msg = (
            f"📊 SIZE BIAS ALERT {sz_emoji}\n"
            f"{size_cat} chiếm {round(ratio*100)}% hôm nay ({cnt}/{total} kỳ)!\n"
            f"Phân bố bất thường — xem xét bet ngược chiều."
        )
        _tg_send(msg)
        logger.info("📊 Size bias: %s %.0f%% (%d/%d)", size_cat, ratio*100, cnt, total)


def check_draw_gap(last_draw_time_utc, gap_alerted: dict):
    """
    #24 — Alert khi không có draw mới >15 phút trong giờ hoạt động (7-23h VN).
    gap_alerted: {'alerted_at': timestamp} để tránh spam (re-alert sau 60 phút).
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    now_vn = datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Ho_Chi_Minh'))
    hour_vn = now_vn.hour
    if not (7 <= hour_vn <= 23):
        return  # ngoài giờ hoạt động

    if last_draw_time_utc is None:
        return
    elapsed = (datetime.now(timezone.utc) - last_draw_time_utc).total_seconds() / 60
    if elapsed < 15:
        gap_alerted.pop('alerted_at', None)  # reset khi draw lại bình thường
        return

    last_alerted = gap_alerted.get('alerted_at', 0)
    if time.time() - last_alerted < 3600:  # chỉ alert 1 lần mỗi giờ
        return

    gap_alerted['alerted_at'] = time.time()
    msg = (
        f"⚠️ DRAW GAP ALERT\n"
        f"Không có kỳ mới trong {int(elapsed)} phút!\n"
        f"Kỳ cuối: {last_draw_time_utc.strftime('%H:%M:%S UTC')}\n"
        f"Kiểm tra vietlott.vn hoặc kết nối mạng."
    )
    _tg_send(msg)
    logger.warning("⚠️ Draw gap: %.1f phút không có kỳ mới", elapsed)


def send_morning_digest(conn):
    """
    #9 — Tóm tắt 24h qua: tổng kỳ, size phân bố, combo nóng, win rate.
    Được gọi từ mode_morning_digest().
    """
    try:
        cur = conn.cursor()

        # Kỳ trong 24h qua (VN)
        cur.execute("""
            SELECT COUNT(*), size_category
            FROM draw_history
            WHERE draw_time >= NOW() - INTERVAL '24 hours'
            GROUP BY size_category
        """)
        size_rows = cur.fetchall()
        total_draws = sum(r[0] for r in size_rows)
        size_dist = {r[1]: r[0] for r in size_rows}

        # Combo nóng 24h
        cur.execute("""
            SELECT numbers, COUNT(*) AS cnt
            FROM draw_history
            WHERE draw_time >= NOW() - INTERVAL '24 hours'
            GROUP BY numbers
            HAVING COUNT(*) >= 2
            ORDER BY cnt DESC LIMIT 5
        """)
        hot_rows = cur.fetchall()

        # Win rate 24h
        cur.execute("""
            SELECT COUNT(*), SUM(CASE WHEN pr.is_win_size THEN 1 ELSE 0 END)
            FROM prediction_results pr
            JOIN draw_history dh ON dh.draw_number = pr.draw_number
            WHERE dh.draw_time >= NOW() - INTERVAL '24 hours'
              AND pr.is_win_size IS NOT NULL
        """)
        wr_row = cur.fetchone()
        cur.close()

        wr_total, wr_wins = (wr_row[0] or 0), (wr_row[1] or 0)
        wr_pct = f"{round(wr_wins/wr_total*100)}%" if wr_total > 0 else "N/A"

        nho = size_dist.get('NHO', 0)
        hoa = size_dist.get('HOA', 0)
        lon = size_dist.get('LON', 0)

        hot_lines = ""
        for numbers_raw, cnt in hot_rows:
            import json as _json
            try:
                nums = _json.loads(numbers_raw) if isinstance(numbers_raw, str) else numbers_raw
            except Exception:
                nums = [numbers_raw]
            hot_lines += f"  🔥 {'-'.join(str(n) for n in nums)} ×{cnt}\n"

        date_vn = datetime.now(timezone.utc).astimezone(
            ZoneInfo('Asia/Ho_Chi_Minh')
        ).strftime('%d/%m/%Y')

        msg = (
            f"☀️ DIGEST SÁNG {date_vn}\n"
            f"{'─'*26}\n"
            f"📊 24h qua: {total_draws} kỳ\n"
            f"  🟢 NHO: {nho} ({round(nho/total_draws*100) if total_draws else 0}%)\n"
            f"  🟡 HOA: {hoa} ({round(hoa/total_draws*100) if total_draws else 0}%)\n"
            f"  🔴 LON: {lon} ({round(lon/total_draws*100) if total_draws else 0}%)\n"
            f"🎯 Win rate: {wr_wins}/{wr_total} = {wr_pct}\n"
        )
        if hot_lines:
            msg += f"🔥 Bộ ra ≥2 lần:\n{hot_lines}"

        _tg_send(msg)
        logger.info("☀️ Morning digest sent")
    except Exception as e:
        logger.warning(f"send_morning_digest: {e}")


def mode_morning_digest():
    """#9 — Chạy 1 lần, gửi digest sáng rồi thoát."""
    conn = get_conn()
    send_morning_digest(conn)
    conn.close()


# ══════════════════════════════════════════════════════════════
#  FILL GAPS (GitHub source)
# ══════════════════════════════════════════════════════════════

def fill_gaps(conn, lookback: int = 500) -> int:
    """
    Upsert `lookback` kỳ gần nhất từ GitHub vào DB (safety net khi PC offline).
    Draw_number Vietlott không liên tục nên không dùng sequential gap detection.
    Trả về số kỳ đã insert mới.
    """
    try:
        github_draws = fetch_from_github(limit=lookback)
        if not github_draws:
            logger.warning("fill_gaps: GitHub không trả về dữ liệu")
            return 0

        github_map = {d["draw_number"]: d for d in github_draws}

        cur = conn.cursor()
        cur.execute(
            f"SELECT draw_number FROM {TABLE} WHERE draw_number = ANY(%s)",
            (list(github_map.keys()),),
        )
        already_in_db = set(r[0] for r in cur.fetchall())
        to_insert = {dn: d for dn, d in github_map.items() if dn not in already_in_db}

        if not to_insert:
            return 0

        logger.info("fill_gaps: %d kỳ GitHub chưa có trong DB, đang insert...", len(to_insert))

        # Group by date and sort within each day → assign 6-min offsets
        from collections import defaultdict
        by_date: dict = defaultdict(list)
        for dn, draw in to_insert.items():
            date_str = (draw.get("draw_time") or "")[:10]  # "YYYY-MM-DD"
            by_date[date_str].append((dn, draw))

        # Within each date group, we also need existing DB draws to compute correct offsets
        all_dates = list(by_date.keys())
        date_offsets: dict = {}  # date_str → {draw_number: offset}
        if all_dates:
            cur.execute(
                f"SELECT draw_number, draw_time FROM {TABLE} "
                f"WHERE draw_time::date = ANY(%s::date[]) ORDER BY draw_number",
                (all_dates,),
            )
            existing_by_date: dict = defaultdict(list)
            for dn_ex, dt_ex in cur.fetchall():
                existing_by_date[str(dt_ex)[:10]].append(dn_ex)

            for date_str, items in by_date.items():
                existing_nums = sorted(existing_by_date.get(date_str, []))
                new_nums      = sorted(dn for dn, _ in items)
                all_nums      = sorted(set(existing_nums + new_nums))
                date_offsets[date_str] = {dn: pos for pos, dn in enumerate(all_nums)}

        inserted = 0
        for dn, draw in sorted(to_insert.items()):
            nums = draw["numbers"]
            total = sum(nums)
            cat = "NHO" if total <= 9 else ("HOA" if total <= 11 else "LON")
            date_str = (draw.get("draw_time") or "")[:10]
            if date_str and date_str in date_offsets and dn in date_offsets[date_str]:
                pos = date_offsets[date_str][dn]
                base = datetime.strptime(date_str, "%Y-%m-%d")
                draw_time = (base + timedelta(minutes=pos * 6)).strftime("%Y-%m-%d %H:%M:%S")
            else:
                draw_time = draw.get("draw_time") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            try:
                cur.execute(
                    f"""
                    INSERT INTO {TABLE}
                        (draw_number, draw_time, numbers, size_category, sum_value, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (draw_number) DO NOTHING
                    """,
                    (dn, draw_time, str(nums), cat, total),
                )
                if cur.rowcount > 0:
                    inserted += 1
                    logger.info("fill_gaps: insert #%d %s", dn, nums)
            except Exception as e:
                conn.rollback()
                logger.error("fill_gaps insert #%d: %s", dn, e)
                continue
        conn.commit()
        logger.info("fill_gaps: xong, inserted=%d", inserted)
        return inserted
    except Exception as e:
        logger.error("fill_gaps lỗi: %s", e)
        return 0


# ══════════════════════════════════════════════════════════════
#  MODES
# ══════════════════════════════════════════════════════════════

def mode_test():
    conn = get_conn()
    print("✅  Kết nối Supabase thành công!")
    last = get_last_draw_id(conn)
    print(f"✅  Bảng: {TABLE}")
    print(f"✅  Kỳ cuối trong DB: #{last}")

    cur = conn.cursor()
    cur.execute(f"SELECT draw_number, draw_time, numbers, size_category, sum_value FROM {TABLE} ORDER BY draw_number DESC LIMIT 3")
    print("\nCác kỳ mới nhất trong DB:")
    for row in cur.fetchall():
        print(f"  #{row[0]}  {row[1]}  {row[2]}  {row[3]}  tổng={row[4]}")
    conn.close()

    print("\n--- Fetch Vietlott ---")
    results = fetch_homepage()
    if results:
        print(f"✅  Lấy được {len(results)} kỳ từ trang chủ:")
        for r in results:
            print(f"  #{r['draw_id']}  {r['numbers']}  {r.get('size')}  tổng={r.get('total')}")
    else:
        print("❌  Không lấy được từ trang chủ")

    print("\n--- Test trigger Cloud Run ---")
    trigger_prediction()


def mode_bulk():
    conn    = get_conn()
    last_id = get_last_draw_id(conn)
    latest  = get_latest()

    if not latest:
        logger.error("Không lấy được kỳ mới nhất từ Vietlott!")
        conn.close()
        sys.exit(1)

    latest_id = latest['draw_id']
    missing   = latest_id - last_id

    logger.info(f"DB cuối: #{last_id}  |  Vietlott mới nhất: #{latest_id}  |  Cần sync: {missing} kỳ")

    if missing <= 0:
        logger.info("✅  DB đã up-to-date!")
        conn.close()
        return

    if missing > 200:
        logger.warning(f"⚠️  Cần sync {missing} kỳ, sẽ mất khoảng {missing * 0.4 / 60:.1f} phút...")

    ins = skip = err = 0
    for draw_id in range(last_id + 1, latest_id + 1):
        draw = fetch_detail(draw_id)
        if draw:
            ok = insert_draw(conn, draw)
            if ok:
                ins += 1
                logger.info(f"  ✅  #{draw_id}  {draw['numbers']}  tổng={draw.get('total')}")
            else:
                skip += 1
        else:
            err += 1
            logger.warning(f"  ❌  #{draw_id}: không fetch được")
        time.sleep(0.35)

    logger.info(f"\n✅  Bulk sync xong!  inserted={ins}  skipped={skip}  errors={err}")
    conn.close()

    # Sau bulk → trigger prediction ngay
    if ins > 0:
        logger.info("Trigger prediction sau bulk sync...")
        trigger_prediction()


def _run_sync_predictions(limit: int = 50, min_draw: int = 0):
    """Backfill predictions for draws inserted by fill_gaps (runs in daemon thread)."""
    try:
        cmd = [sys.executable, 'sync_predictions.py', '--limit', str(limit)]
        if min_draw > 0:
            cmd += ['--min-draw', str(min_draw)]
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            logger.info("sync_predictions backfill OK\n%s", result.stdout[-500:].strip())
        else:
            logger.warning("sync_predictions exit %d\n%s", result.returncode, result.stderr[-300:].strip())
    except Exception as e:
        logger.warning("sync_predictions failed: %s", e)


def _send_play_reminder(conn, draw_number: int):
    """Gửi nhắc nhở ngắn ~2 phút trước kỳ draw_number."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT predicted_numbers, confidence
            FROM predictions
            WHERE draw_number = %s
              AND model_name = 'majority_vote'
            ORDER BY prediction_time DESC LIMIT 1
        """, (draw_number,))
        row = cur.fetchone()
        cur.close()
        if not row:
            return
        pred_nums, conf = row
        if isinstance(pred_nums, str):
            import json as _j
            pred_nums = _j.loads(pred_nums)
        nums = [int(x) for x in pred_nums]
        s = sum(nums)
        size = 'NHO' if s <= 9 else ('HOA' if s <= 11 else 'LON')
        size_vi   = {'NHO': 'NHO', 'HOA': 'HOA', 'LON': 'LON'}[size]
        size_icon = {'NHO': '\U0001f535', 'HOA': '\U0001f7e1', 'LON': '\U0001f534'}[size]
        nums_str = ' · '.join(str(n) for n in nums)
        conf_str = f"{float(conf)*100:.0f}%" if conf else "?"
        msg = (
            f"⏰  <b>SAP RA KY #{draw_number} — CON ~2 PHUT!</b>\n"
            f"────────────────────\n"
            f"     <b>{nums_str}</b>\n"
            f"     Tong <b>{s}</b>  {size_icon}  <b>{size_vi}</b>   ·   {conf_str}\n"
            f"────────────────────"
        )
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=5,
        )
        logger.info("Reminder sent for ky #%d: %s", draw_number, nums_str)
    except Exception as e:
        logger.warning("send_play_reminder: %s", e)


def mode_watch():
    logger.info(f"👀  Watch mode: fetch mỗi {FETCH_INTERVAL}s, fill_gaps mỗi 600s")

    FILL_GAPS_INTERVAL    = 600  # 10 phút
    MISSING_PRED_INTERVAL = 300  # 5 phút — #13 auto-retry missing predictions
    REMINDER_DELAY        = 240  # 4 phút sau kỳ mới → nhắc nhở ~2 phút trước kỳ tiếp
    last_fill_time    = 0
    last_missing_time = 0
    reminder_due_at: float = 0   # timestamp khi cần gửi reminder
    reminder_draw:   int   = 0   # draw_number cần nhắc (kỳ sắp ra)
    hot_combo_alerted: dict = {}  # (date_vn, combo_key) → True; tự reset theo ngày
    streak_alerted:    dict = {}  # streak_key → True
    cold_alerted:      dict = {}  # num → last_alerted_draw_number
    gap_alerted:       dict = {}  # 'alerted_at' → timestamp
    bias_alerted:      dict = {}  # size_cat → True; reset khi bias hết
    triple_alerted:    dict = {}  # draw_id → True (#32)
    hoa_reeval_state:  dict = {}  # {last_ts} (#49)
    wr_alerted:        dict = {}  # {low, recovered} (#42)
    drought_alerted:   dict = {}  # triple_dN / pair_dN → True
    conf_gap_alerted:  dict = {}  # {active} (#47)
    sh_alerted:        dict = {}  # {status, last_check} system health
    last_draw_time_utc       = None  # #24 gap detector

    while True:
        try:
            conn    = get_conn()
            last_id = get_last_draw_id(conn)
            new     = get_new_since(last_id)

            if new:
                inserted = 0
                last_inserted_id = None
                now_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
                for draw in new:
                    draw['draw_date'] = now_utc  # real-time stamp, accurate to ±60s
                    ok = insert_draw(conn, draw)
                    if ok:
                        inserted += 1
                        last_inserted_id = draw['draw_id']
                        logger.info(f"  ✅  #{draw['draw_id']} {draw['numbers']} tổng={draw.get('total')} {draw.get('size')} @ {now_utc}")
                        send_telegram(draw)
                        check_and_alert_hot_combo(conn, draw, hot_combo_alerted)
                        check_triple_number(draw, triple_alerted)  # #32
                        last_draw_time_utc = datetime.now(timezone.utc)  # #24

                # Trigger prediction + announce sau khi có kỳ mới (non-blocking)
                if inserted > 0:
                    threading.Thread(target=trigger_prediction, daemon=True).start()
                    # Đặt reminder 4 phút sau → nhắc nhở ~2 phút trước kỳ tiếp
                    reminder_due_at = time.time() + REMINDER_DELAY
                    reminder_draw   = last_inserted_id + 1
                    logger.info("Reminder scheduled for ky #%d in %ds", reminder_draw, REMINDER_DELAY)
                    # #4: size streak alert
                    check_size_streak(conn, streak_alerted)
                    # #6: cold number alert
                    check_cold_numbers(conn, cold_alerted)
                    # #27: size bias alert
                    check_size_bias(conn, bias_alerted)
                    # #42: WR low alert
                    check_wr_alert(conn, wr_alerted)
                    # #47: confidence gap alert
                    check_confidence_gap(conn, conf_gap_alerted)
                    # system health alert (WR50 trend)
                    check_system_health_alert(conn, sh_alerted)
                    # #49: HOA monthly re-evaluation
                    check_hoa_reeval(conn, hoa_reeval_state)
                    # triple/pair drought alert (GAN RA)
                    check_pair_triple_drought(conn, drought_alerted)
            else:
                logger.info(f"Không có kỳ mới (last=#{last_id})")
                check_draw_gap(last_draw_time_utc, gap_alerted)  # #24

            # fill_gaps mỗi 10 phút
            now = time.time()
            if now - last_fill_time >= FILL_GAPS_INTERVAL:
                filled = fill_gaps(conn, lookback=100)
                if filled > 0:
                    logger.info("fill_gaps: đã bù %d kỳ bị miss — backfill predictions...", filled)
                    threading.Thread(
                        target=_run_sync_predictions,
                        args=(filled + 10,),
                        daemon=True,
                    ).start()
                last_fill_time = now

            # #13: auto-retry draws thiếu prediction mỗi 5 phút
            if now - last_missing_time >= MISSING_PRED_INTERVAL:
                try:
                    cur_m = conn.cursor()
                    cur_m.execute("""
                        SELECT COUNT(*), (SELECT MAX(draw_number) - 200 FROM draw_history)
                        FROM draw_history dh
                        LEFT JOIN predictions p ON p.draw_number = dh.draw_number
                        WHERE p.id IS NULL
                          AND dh.draw_number > (SELECT MAX(draw_number) - 200 FROM draw_history)
                    """)
                    row_m = cur_m.fetchone()
                    missing = row_m[0] or 0
                    min_draw_threshold = row_m[1] or 0
                    cur_m.close()
                    if missing > 0:
                        logger.info("#13 auto-retry: %d kỳ thiếu prediction (draw>%d) — sync...",
                                    missing, min_draw_threshold)
                        threading.Thread(
                            target=_run_sync_predictions,
                            args=(missing + 5, min_draw_threshold),
                            daemon=True,
                        ).start()
                except Exception as e:
                    logger.warning("missing_pred check: %s", e)
                last_missing_time = now

            # Reminder: gửi nhắc nhở ~2 phút trước kỳ tiếp
            if reminder_due_at > 0 and time.time() >= reminder_due_at and reminder_draw > 0:
                _send_play_reminder(conn, reminder_draw)
                reminder_due_at = 0
                reminder_draw   = 0

            conn.close()

        except KeyboardInterrupt:
            logger.info("Dừng (Ctrl+C)")
            break
        except Exception as e:
            logger.error(f"Lỗi: {e}")

        time.sleep(FETCH_INTERVAL)


def mode_backfill():
    """
    One-time backfill: recalculate draw_time for ALL existing draws.
    Groups draws by UTC date, sorts by draw_number, assigns 6-min offsets.
    Run once after deploying this fix.
    """
    conn = get_conn()
    cur  = conn.cursor()

    cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
    total = cur.fetchone()[0]
    logger.info("Backfill: %d draws to recalculate", total)

    cur.execute(f"""
        UPDATE {TABLE} SET draw_time = sub.new_time
        FROM (
            SELECT
                draw_number,
                date_trunc('day', draw_time) +
                    (ROW_NUMBER() OVER (
                        PARTITION BY date_trunc('day', draw_time)
                        ORDER BY draw_number
                    ) - 1) * INTERVAL '6 minutes'
                AS new_time
            FROM {TABLE}
        ) sub
        WHERE {TABLE}.draw_number = sub.draw_number
    """)
    updated = cur.rowcount
    conn.commit()
    conn.close()
    logger.info("Backfill complete: %d rows updated", updated)
    print(f"\n✅  Backfill done — {updated} draws recalculated (6-min intervals per day)")


def mode_gha():
    """
    GitHub Actions mode: scrape Vietlott → POST lên Cloud Run (không cần DB trực tiếp).
    Cloud Run đã có DATABASE_URL, tự ghi DB và trigger prediction.
    Chỉ cần CLOUD_RUN_URL + TRIGGER_SECRET — không cần DB_HOST/DB_PASSWORD/etc.
    """
    logger.info("=== GHA mode (v2 via Cloud Run API) ===")

    cloud_url = CLOUD_RUN_URL.rstrip('/')
    headers   = {"X-Trigger-Secret": TRIGGER_SECRET, "Content-Type": "application/json"}

    if not cloud_url or not TRIGGER_SECRET:
        logger.error("CLOUD_RUN_URL hoặc TRIGGER_SECRET chưa cấu hình — exit")
        raise SystemExit(1)

    # ── Bước 1: lấy last draw ID từ Cloud Run
    last_id = 0
    try:
        r = requests.get(f"{cloud_url}/api/last-draw-id", headers=headers, timeout=15)
        if r.status_code == 200:
            last_id = r.json().get("draw_number", 0)
            logger.info("Cloud Run last draw: #%d", last_id)
        else:
            logger.warning("last-draw-id returned %d — dùng last_id=0", r.status_code)
    except Exception as e:
        logger.warning("Không lấy được last draw từ Cloud Run: %s — tiếp tục", e)

    # ── Bước 2: scrape Vietlott
    to_send = []
    now_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    try:
        new_draws = get_new_since(last_id)
        for draw in new_draws:
            to_send.append({
                'draw_id':   draw['draw_id'],
                'numbers':   draw['numbers'],
                'draw_date': draw.get('draw_date') or now_utc,
            })
        if to_send:
            logger.info("Vietlott: %d kỳ mới", len(to_send))
    except Exception as e:
        logger.warning("vietlott.vn fetch failed: %s — fallback GitHub", e)

    # ── Bước 3: fallback GitHub JSONL
    if not to_send:
        logger.info("Fallback: GitHub JSONL...")
        try:
            gh_draws = fetch_from_github(limit=30)
            for d in gh_draws:
                if d.get('draw_number', 0) > last_id:
                    to_send.append({
                        'draw_id':   d['draw_number'],
                        'numbers':   d['numbers'],
                        'draw_date': d.get('draw_time', now_utc),
                    })
            if to_send:
                logger.info("GitHub fallback: %d kỳ mới", len(to_send))
        except Exception as e:
            logger.warning("GitHub fallback failed: %s", e)

    if not to_send:
        logger.info("Không có kỳ mới.")
        return

    # ── Bước 4: POST lên Cloud Run để ghi DB + trigger prediction
    try:
        r = requests.post(
            f"{cloud_url}/api/ingest-draws",
            json={"draws": to_send},
            headers=headers,
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json()
            logger.info("GHA sync done — inserted=%d / received=%d",
                        data.get('inserted', 0), data.get('received', 0))
        else:
            logger.error("ingest-draws returned %d: %s", r.status_code, r.text[:200])
            raise SystemExit(1)
    except SystemExit:
        raise
    except Exception as e:
        logger.error("POST ingest-draws failed: %s", e)
        raise SystemExit(1)


# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Bingo18 Sync → Supabase')
    p.add_argument('--mode', choices=['test', 'bulk', 'watch', 'backfill', 'gha', 'morning_digest'], default='watch')
    args = p.parse_args()

    print(f"\n{'='*52}")
    print(f"  Bingo18 Sync v4.3 — mode: {args.mode}")
    print(f"  DB: {DB_CONFIG.get('host') or '(via Cloud Run API)'}")
    print(f"  Table: {TABLE}")
    print(f"{'='*52}\n")

    {'test': mode_test, 'bulk': mode_bulk, 'watch': mode_watch,
     'backfill': mode_backfill, 'gha': mode_gha,
     'morning_digest': mode_morning_digest}[args.mode]()
