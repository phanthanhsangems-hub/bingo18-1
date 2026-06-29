"""
ai_predictor.py - Bingo18 AI Predictor
- OpenRouter (chính) → Groq → Gemini (fallback)
- Tự động tải dữ liệu từ web
- Fix SSL Windows (CRYPT_E_NO_REVOCATION_CHECK)

CLI:
    python ai_predictor.py --openrouter-key sk-or-v1-xxx
    python ai_predictor.py --no-telegram
"""

import argparse, json, logging, os, re, sqlite3, ssl, sys, time
from datetime import datetime
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── Cấu hình ────────────────────────────────────────────────────────────────
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY",       "")
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY",     "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

GROQ_MODEL         = "llama-3.3-70b-versatile"
GEMINI_MODEL       = "gemini-2.0-flash"
OPENROUTER_MODEL   = "meta-llama/llama-3.3-70b-instruct:free"  # miễn phí

# Danh sách model :free — tự fallback nếu model đầu bị rate limit
# Cập nhật 2026-04: dùng openrouter/free làm ưu tiên 1 (tự chọn model còn sống)
OPENROUTER_FREE_MODELS = [
    "openrouter/auto",                         # Auto-router — tự chọn model tốt nhất còn free
    "meta-llama/llama-3.3-70b-instruct:free",  # Llama 3.3 70B
    "google/gemma-3-27b-it:free",              # Gemma 3 27B
    "microsoft/phi-4:free",                     # Microsoft Phi-4
    "qwen/qwen2.5-72b-instruct:free",           # Qwen 2.5 72B
]

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")  # set trong .env
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID",   "")  # set trong .env

HIGH_CONFIDENCE    = 70
DEFAULT_SQLITE     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "bingo18.db")


# ── SSL context (Windows-compatible) ─────────────────────────────────────────
def _ssl_ctx():
    """Trả về SSL context. Trên Windows có thể gặp CRYPT_E_NO_REVOCATION_CHECK."""
    import platform
    ctx = ssl.create_default_context()
    if platform.system() == "Windows":
        # Windows đôi khi lỗi CRYPT_E_NO_REVOCATION_CHECK với CRL check
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
    return ctx


# ── HTTP helpers (không cần requests) ────────────────────────────────────────
def _http_post(url: str, payload: dict, headers: dict, timeout: int = 30) -> dict:
    import urllib.request
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get(url: str, headers: dict, timeout: int = 30) -> str:
    import urllib.request
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ── 1. Tự động tải dữ liệu từ GitHub (vietvudanh/vietlott-data) ──────────────
GITHUB_JSONL_URL = (
    "https://raw.githubusercontent.com/vietvudanh/vietlott-data"
    "/main/data/bingo18.jsonl"
)

def auto_update_from_web(db_path: str = None) -> int:
    """
    Tải toàn bộ lịch sử Bingo18 từ GitHub (cập nhật hàng ngày).
    Chỉ import các kỳ chưa có trong DB → nhanh, không trùng lặp.
    """
    db_path = db_path or DEFAULT_SQLITE

    try:
        logger.info("Đang tải dữ liệu từ GitHub (vietvudanh/vietlott-data)...")
        raw = _http_get(GITHUB_JSONL_URL,
                        {"User-Agent": "Mozilla/5.0"}, timeout=30)
        logger.info("Tải về %d ký tự — đang parse...", len(raw))

        # Parse JSONL: mỗi dòng là 1 JSON object
        # Format: {"date":"2024-12-03","id":"0083123","result":[2,6,1],
        #          "total":9,"large_small":"Nhỏ","process_time":"..."}
        data = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj     = json.loads(line)
                draw_id = int(obj["id"])
                nums    = obj["result"]          # [2, 6, 1]
                if not (isinstance(nums, list) and len(nums) == 3):
                    continue
                if not all(1 <= n <= 6 for n in nums):
                    continue
                sum_val  = sum(nums)
                # GitHub dùng "Nhỏ"/"Lớn"/"Hòa" → map sang NHO/LON/HOA
                ls = obj.get("large_small", "")
                if ls == "Nhỏ":
                    category = "NHO"
                elif ls == "Hòa":
                    category = "HOA"
                else:
                    category = "LON"
                data.append({
                    "draw_number":   draw_id,
                    "draw_time":     obj.get("date", ""),
                    "numbers":       nums,
                    "size_category": category,
                    "sum_value":     sum_val,
                })
            except Exception:
                continue

        if not data:
            logger.warning("Không parse được dữ liệu từ GitHub.")
            return 0

        logger.info("Parse xong %d kỳ — đang import vào DB...", len(data))

        # Tạo DB nếu chưa có
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS draw_history (
            draw_number   INTEGER PRIMARY KEY,
            draw_time     TEXT,
            numbers       TEXT,
            size_category TEXT,
            sum_value     INTEGER)""")

        inserted = 0
        for item in sorted(data, key=lambda x: x["draw_number"]):
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO draw_history VALUES (?, ?, ?, ?, ?)",
                    (item["draw_number"], item["draw_time"],
                     json.dumps(item["numbers"]),
                     item["size_category"], item["sum_value"])
                )
                inserted += conn.execute("SELECT changes()").fetchone()[0]
            except Exception:
                pass

        conn.commit()
        conn.close()

        if inserted:
            logger.info("✅ Import thành công %d kỳ mới vào DB (tổng %d kỳ).",
                        inserted, len(data))
        else:
            logger.info("DB đã cập nhật đầy đủ — không có kỳ mới.")
        return inserted

    except Exception as e:
        logger.error("Lỗi tải dữ liệu từ GitHub: %s", e)
        return 0


# ── 2. Load dữ liệu từ DB ─────────────────────────────────────────────────────
def load_recent_draws(n: int = 30, db_path: str = None) -> list:
    path = db_path or DEFAULT_SQLITE
    if not os.path.exists(path):
        logger.error("Không tìm thấy database: %s", path)
        return []
    try:
        conn = sqlite3.connect(path)
        rows = conn.execute(
            "SELECT draw_number, draw_time, numbers, size_category, sum_value "
            "FROM draw_history ORDER BY draw_number DESC LIMIT ?", (n,)
        ).fetchall()
        conn.close()
        rows.reverse()
        return [{
            "draw_number":   r[0],
            "draw_time":     r[1],
            "numbers":       json.loads(r[2]) if isinstance(r[2], str) else r[2],
            "size_category": r[3],
            "sum_value":     r[4],
        } for r in rows]
    except Exception as e:
        logger.error("Đọc DB lỗi: %s", e)
        return []


# ── 3. Build prompts ──────────────────────────────────────────────────────────
def _build_prompts(draws: list) -> tuple:
    history_text = "\n".join(
        f"Kỳ #{d['draw_number']}: {'-'.join(map(str, d['numbers']))} "
        f"→ Tổng={d['sum_value']} ({d['size_category']})"
        for d in draws
    )
    recent10 = draws[-10:]
    counts   = {"NHO": 0, "HOA": 0, "LON": 0}
    for d in recent10:
        cat = d.get("size_category", "")
        if cat in counts:
            counts[cat] += 1

    num_count = {i: 0 for i in range(1, 7)}
    for d in draws:
        for n in d["numbers"]:
            if 1 <= n <= 6:
                num_count[n] += 1

    hot  = [k for k, v in num_count.items() if v >= 8]
    cold = [k for k, v in num_count.items() if v <= 3]

    streak_cat = draws[-1]["size_category"]
    streak = 1
    for d in reversed(draws[-10:-1]):
        if d["size_category"] == streak_cat:
            streak += 1
        else:
            break

    system_prompt = (
        "Bạn là chuyên gia phân tích xổ số Bingo18 Việt Nam.\n"
        "Luật: Mỗi kỳ rút 3 số (1-6). Tổng 3-9=NHO, 10-11=HOA, 12-18=LON.\n"
        "Chỉ trả về đúng JSON, không thêm text hay markdown."
    )
    user_prompt = (
        f"Lịch sử {len(draws)} kỳ gần nhất (cũ→mới):\n{history_text}\n\n"
        f"THỐNG KÊ:\n"
        f"- 10 kỳ gần: NHO={counts['NHO']}, HOA={counts['HOA']}, LON={counts['LON']}\n"
        f"- Tần suất số (30 kỳ): {num_count}\n"
        f"- Hot numbers: {hot}\n"
        f"- Cold numbers: {cold}\n"
        f"- Streak hiện tại: {streak} kỳ {streak_cat} liên tiếp\n\n"
        f"Dự đoán kỳ #{draws[-1]['draw_number'] + 1} theo đúng format JSON (reason tối đa 15 từ, pattern tối đa 8 từ):\n"
        '{"prediction":"NHO","confidence":75,"reason":"lý do ngắn gọn","pattern":"xu hướng"}'
    )
    return system_prompt, user_prompt


def _parse_ai_response(raw: str) -> Optional[dict]:
    raw = raw.replace("```json", "").replace("```", "").strip()
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        raw = m.group(0)
    try:
        result = json.loads(raw)
        if (result.get("prediction") in ("NHO", "HOA", "LON")
                and isinstance(result.get("confidence"), (int, float))):
            result["confidence"] = int(result["confidence"])
            return result
    except Exception:
        pass
    return None


# ── 4. OpenRouter API ─────────────────────────────────────────────────────────
def ask_openrouter(draws: list) -> Optional[dict]:
    """Thử lần lượt các model :free, mỗi model retry 3 lần khi gặp 429."""
    import urllib.request, urllib.error

    if not OPENROUTER_API_KEY:
        return None

    system_prompt, user_prompt = _build_prompts(draws)

    for model in OPENROUTER_FREE_MODELS:
        for attempt, wait in enumerate([0, 30, 60], start=1):
            if wait:
                logger.info("OpenRouter 429 — chờ %ds rồi thử lại (lần %d/3)...", wait, attempt)
                time.sleep(wait)
            try:
                logger.info("Gọi OpenRouter (%s) — lần %d...", model, attempt)
                data = json.dumps({
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt},
                    ],
                    "max_tokens": 500,
                    "temperature": 0.3,
                }).encode("utf-8")
                req = urllib.request.Request(
                    "https://openrouter.ai/api/v1/chat/completions",
                    data=data,
                    headers={
                        "Content-Type":  "application/json",
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "HTTP-Referer":  "https://github.com/bingo18-predictor",
                        "X-Title":       "Bingo18 Predictor",
                    },
                )
                with urllib.request.urlopen(req, timeout=40, context=_ssl_ctx()) as resp:
                    body = json.loads(resp.read().decode("utf-8"))

                # OpenRouter đôi khi trả lỗi trong body với HTTP 200
                if "error" in body:
                    code = body["error"].get("code", 0)
                    msg  = body["error"].get("message", "")
                    if code in (429, "rate_limit_exceeded"):
                        logger.warning("OpenRouter model %s bận — thử model khác...", model)
                        break  # sang model tiếp theo
                    logger.error("OpenRouter lỗi body: [%s] %s", code, msg)
                    return None

                raw    = body["choices"][0]["message"]["content"].strip()
                result = _parse_ai_response(raw)
                if result:
                    logger.info("OpenRouter OK ✅ (model: %s)", model)
                    return result
                logger.error("OpenRouter JSON không hợp lệ: %s", raw[:200])
                break

            except urllib.error.HTTPError as e:
                err_body = e.read().decode()
                if e.code == 429:
                    logger.warning("OpenRouter 429 (model=%s, lần %d)", model, attempt)
                    continue  # retry cùng model
                if e.code == 401:
                    logger.error("OpenRouter 401 — API key không hợp lệ. Kiểm tra lại key tại openrouter.ai/keys")
                    return None  # key sai → không retry
                if e.code == 402:
                    logger.error("OpenRouter 402 — Hết credit. Nạp thêm tại https://openrouter.ai/credits")
                    # Không retry — báo hết credit và thoát hẳn OpenRouter để thử Groq/Gemini
                    logger.warning("OpenRouter hết credit — chuyển sang Groq/Gemini...")
                    return None  # dispatcher sẽ thử Groq rồi Gemini
                if e.code == 404:
                    logger.warning("OpenRouter 404 — model %s không tồn tại, thử model khác...", model)
                    break  # sang model tiếp theo
                logger.error("OpenRouter HTTP %d (model=%s): %s", e.code, model, err_body[:150])
                break
            except Exception as e:
                logger.error("OpenRouter lỗi (model=%s): %s", model, e)
                break
        else:
            logger.warning("OpenRouter model %s: hết 3 lần retry — thử model khác...", model)

    logger.error("OpenRouter: tất cả %d model đều thất bại.", len(OPENROUTER_FREE_MODELS))
    return None


# ── 5. Groq API ───────────────────────────────────────────────────────────────
def ask_groq(draws: list) -> Optional[dict]:
    if not GROQ_API_KEY:
        return None
    system_prompt, user_prompt = _build_prompts(draws)
    for attempt in range(1, 4):
        if attempt > 1:
            wait = 15 * attempt
            logger.info("Groq 429 — chờ %ds (lần %d)...", wait, attempt)
            time.sleep(wait)
        try:
            logger.info("Gọi Groq API (%s) — lần %d...", GROQ_MODEL, attempt)
            body = _http_post(
                url="https://api.groq.com/openai/v1/chat/completions",
                payload={
                    "model": GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt},
                    ],
                    "max_tokens": 500,
                    "temperature": 0.3,
                },
                headers={
                    "Content-Type":  "application/json",
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                },
            )
            raw    = body["choices"][0]["message"]["content"].strip()
            result = _parse_ai_response(raw)
            if result:
                logger.info("Groq OK ✅")
                return result
        except Exception as e:
            err = str(e)
            if "429" in err:
                continue
            if "403" in err or "Forbidden" in err:
                logger.error(
                    "Groq lỗi 403 Forbidden — API key bị revoke hoặc sai.\n"
                    "  Tạo key mới tại: https://console.groq.com/keys\n"
                    "  Dùng: --groq-key gsk_xxx  hoặc set env GROQ_API_KEY=gsk_xxx"
                )
                return None
            logger.error("Groq lỗi: %s", e)
            return None
    return None


# ── 6. Gemini API ─────────────────────────────────────────────────────────────
def ask_gemini(draws: list) -> Optional[dict]:
    if not GEMINI_API_KEY:
        logger.error("Thiếu GEMINI_API_KEY — lấy tại https://aistudio.google.com/app/apikey")
        return None
    system_prompt, user_prompt = _build_prompts(draws)

    for attempt, wait in enumerate([0, 15, 30], start=1):
        if wait:
            logger.info("Gemini 429 — chờ %ds rồi thử lại (lần %d/3)...", wait, attempt)
            time.sleep(wait)
        try:
            logger.info("Gọi Gemini API (%s) — lần %d...", GEMINI_MODEL, attempt)
            body = _http_post(
                url=(
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
                ),
                payload={
                    "contents": [{"parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]}],
                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": 500},
                },
                headers={"Content-Type": "application/json"},
            )
            raw    = body["candidates"][0]["content"]["parts"][0]["text"].strip()
            result = _parse_ai_response(raw)
            if result:
                logger.info("Gemini OK ✅")
                return result
            logger.error("Gemini JSON không hợp lệ: %s", raw[:200])
            return None
        except Exception as e:
            err = str(e)
            if "429" in err:
                logger.warning("Gemini 429 (lần %d)", attempt)
                continue  # retry
            if "403" in err or "Forbidden" in err:
                logger.error(
                    "Gemini lỗi 403 — API key sai hoặc bị vô hiệu.\n"
                    "  Tạo key mới tại: https://aistudio.google.com/app/apikey\n"
                    "  Dùng: --gemini-key AIza...  hoặc set env GEMINI_API_KEY=AIza..."
                )
                return None
            logger.error("Gemini lỗi: %s", e)
            return None
    logger.error("Gemini thất bại sau 3 lần thử (rate limit liên tục).")
    return None


# ── 7. Dispatcher ─────────────────────────────────────────────────────────────
def ask_ai(draws: list) -> Optional[dict]:
    if OPENROUTER_API_KEY:
        result = ask_openrouter(draws)
        if result:
            return result
        logger.warning("OpenRouter thất bại — thử Groq...")

    if GROQ_API_KEY:
        result = ask_groq(draws)
        if result:
            return result
        logger.warning("Groq thất bại — thử Gemini...")

    if GEMINI_API_KEY:
        return ask_gemini(draws)

    logger.error(
        "Không có API nào khả dụng!\n"
        "  Dùng --openrouter-key  (https://openrouter.ai — miễn phí)\n"
        "  Hoặc --gemini-key      (https://aistudio.google.com/app/apikey)"
    )
    return None


# ── 8. Telegram ───────────────────────────────────────────────────────────────
def send_telegram(message: str) -> bool:
    try:
        _http_post(
            url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            payload={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        return True
    except Exception as e:
        logger.error("Telegram lỗi: %s", e)
        return False


def build_telegram_message(next_draw: int, result: dict, draws: list) -> str:
    pred       = result["prediction"]
    confidence = result["confidence"]
    emoji      = {"NHO": "🔵", "HOA": "🟡", "LON": "🔴"}.get(pred, "⚪")
    badge      = "⚡ <b>ĐỘ TIN CẬY CAO</b>\n" if confidence >= HIGH_CONFIDENCE else ""
    recent_str = " ".join(
        {"NHO": "🔵", "HOA": "🟡", "LON": "🔴"}.get(d["size_category"], "⚪")
        for d in draws[-10:]
    )
    return (
        f"{badge}"
        f"🎯 <b>DỰ ĐOÁN KỲ #{next_draw}</b>\n"
        f"{'━'*22}\n"
        f"{emoji} Kết quả: <b>{pred}</b>\n"
        f"📊 Độ tin cậy: <b>{confidence}%</b>\n\n"
        f"💡 <b>Lý do:</b>\n{result.get('reason','')}\n\n"
        f"📈 <b>Xu hướng:</b> {result.get('pattern','')}\n\n"
        f"🕐 10 kỳ gần nhất:\n{recent_str}\n"
        f"{'━'*22}\n"
        f"🕒 {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}"
    )


# ── 9. Main flow ──────────────────────────────────────────────────────────────
def predict_and_notify(
    n_draws: int = 30,
    send_tg: bool = True,
    db_path: str = None,
) -> Optional[dict]:
    db_path = db_path or DEFAULT_SQLITE
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    updated = auto_update_from_web(db_path)
    if updated == 0:
        logger.info("Sử dụng dữ liệu hiện có trong database.")

    draws = load_recent_draws(n=n_draws, db_path=db_path)
    if len(draws) < 15:
        logger.error("Không đủ dữ liệu (có %d kỳ, cần ít nhất 15)", len(draws))
        return None

    logger.info("Gọi AI với %d kỳ lịch sử...", len(draws))
    result = ask_ai(draws)
    if not result:
        return None

    next_draw  = draws[-1]["draw_number"] + 1
    confidence = result["confidence"]

    print("\n" + "=" * 45)
    print(f"  DỰ ĐOÁN KỲ #{next_draw}")
    print("=" * 45)
    print(f"  Kết quả   : {result['prediction']}")
    print(f"  Tin cậy   : {confidence}%")
    print(f"  Lý do     : {result.get('reason', '')}")
    print(f"  Xu hướng  : {result.get('pattern', '')}")
    print("=" * 45 + "\n")

    if send_tg and confidence >= HIGH_CONFIDENCE:
        msg = build_telegram_message(next_draw, result, draws)
        ok  = send_telegram(msg)
        logger.info("Telegram: %s", "✅ OK" if ok else "❌ lỗi")
    elif send_tg:
        logger.info("Bỏ qua Telegram (confidence=%d%% < %d%%)", confidence, HIGH_CONFIDENCE)

    return result


def main():
    parser = argparse.ArgumentParser(description="Bingo18 AI Predictor")
    parser.add_argument("--draws",          type=int, default=30)
    parser.add_argument("--no-telegram",    action="store_true")
    parser.add_argument("--groq-key",       default=None)
    parser.add_argument("--gemini-key",     default=None)
    parser.add_argument("--openrouter-key", default=None)
    parser.add_argument("--db",             default=None)
    args = parser.parse_args()

    if args.groq_key:
        global GROQ_API_KEY
        GROQ_API_KEY = args.groq_key
    if args.gemini_key:
        global GEMINI_API_KEY
        GEMINI_API_KEY = args.gemini_key
    if args.openrouter_key:
        global OPENROUTER_API_KEY
        OPENROUTER_API_KEY = args.openrouter_key

    result = predict_and_notify(
        n_draws=args.draws,
        send_tg=not args.no_telegram,
        db_path=args.db,
    )
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()