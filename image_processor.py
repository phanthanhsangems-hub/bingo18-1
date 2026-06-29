"""
Vision-based extraction of Bingo18 betting slip data.
Primary: Groq Vision (llama-4-scout, fast + free)
Fallback: Gemini 2.0 Flash Lite
"""
import base64
import json
import logging
import re
import requests

import config

logger = logging.getLogger(__name__)

GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
GROQ_VISION_URL   = "https://api.groq.com/openai/v1/chat/completions"

OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "meta-llama/llama-3.2-11b-vision-instruct:free"

GEMINI_MODEL = "gemini-2.0-flash-lite"
GEMINI_URL   = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

EXTRACTION_PROMPT = """\
You are a JSON extractor for Vietnamese Bingo18 lottery betting slips. Output ONLY valid JSON — no text, no markdown.
Start your response with { and end with }.

Vietnamese labels on the slip and their JSON field names:
- "KỲ" or "KỲ SỐ" = draw_number (integer)
- "NHỎ" or "NHO" (sum 3-9) = nho_bet
- "HÒA" or "HOA" (sum 10-11) = hoa_bet
- "LỚN" or "LON" (sum 12-18) = lon_bet
- "TỔNG 3" through "TỔNG 18" = tong_3 through tong_18
- "BỘ 3" + number "1-1-1" through "6-6-6" = bo_ba_111 through bo_ba_666
- "ĐÔI" + number or "BỘ ĐÔI" = bo_2_11 through bo_2_66
- "BỘ 3 BẤT KỲ" or "3 BẤT KỲ" = bo_ba_bat_ki
- 3 drawn result numbers (each 1-6) if shown = result_n1, result_n2, result_n3

Amount formats: 10k=10000, 50k=50000, 100k=100000, 1tr=1000000, 1.5tr=1500000
All amounts must be multiples of 1000.

Output this exact JSON structure with actual values (replace 0/null):
{"draw_number":null,"nho_bet":0,"hoa_bet":0,"lon_bet":0,"tong_3":0,"tong_4":0,"tong_5":0,"tong_6":0,"tong_7":0,"tong_8":0,"tong_9":0,"tong_10":0,"tong_11":0,"tong_12":0,"tong_13":0,"tong_14":0,"tong_15":0,"tong_16":0,"tong_17":0,"tong_18":0,"bo_ba_111":0,"bo_ba_222":0,"bo_ba_333":0,"bo_ba_444":0,"bo_ba_555":0,"bo_ba_666":0,"bo_2_11":0,"bo_2_22":0,"bo_2_33":0,"bo_2_44":0,"bo_2_55":0,"bo_2_66":0,"bo_ba_bat_ki":0,"result_n1":null,"result_n2":null,"result_n3":null}
"""

# ── Tỷ lệ trả thưởng chính thức Vietlott (per 10k ticket) ───────────────────
TONG_ODDS = {
    3: 120, 4: 40, 5: 20, 6: 12, 7: 8, 8: 5.5, 9: 4.7,
    10: 4.4, 11: 4.4,
    12: 4.7, 13: 5.5, 14: 8, 15: 12, 16: 20, 17: 40, 18: 120,
}

BO_BA_ODDS     = 120   # Bộ ba cụ thể (3 số giống nhau, chỉ định số)
BO_HAI_ODDS    = 7.5   # Bộ đôi (đúng 2 trong 3 số giống nhau)
BO_BAT_KI_ODDS = 20    # Bộ 3 con bất kì trùng nhau (bất kì số nào)

# Map: số → field bộ ba, field bộ đôi (tên khớp DB: bo_2_XX)
BO_BA_MAP  = {n: f"bo_ba_{n}{n}{n}" for n in range(1, 7)}
BO_HAI_MAP = {n: f"bo_2_{n}{n}"     for n in range(1, 7)}

SIZE_LABEL = {
    **{i: "NHỎ" for i in range(3, 10)},
    10: "HOÀ", 11: "HOÀ",
    **{i: "LỚN" for i in range(12, 19)},
}

COMBINATIONS = {
    3:  [[1,1,1]],
    4:  [[1,1,2]],
    5:  [[1,1,3],[1,2,2]],
    6:  [[1,1,4],[1,2,3],[2,2,2]],
    7:  [[1,1,5],[1,2,4],[1,3,3],[2,2,3]],
    8:  [[1,1,6],[1,2,5],[1,3,4],[2,2,4],[2,3,3]],
    9:  [[1,2,6],[1,3,5],[1,4,4],[2,2,5],[2,3,4],[3,3,3]],
    10: [[1,3,6],[1,4,5],[2,2,6],[2,3,5],[2,4,4],[3,3,4]],
    11: [[1,4,6],[1,5,5],[2,3,6],[2,4,5],[3,3,5],[3,4,4]],
    12: [[1,5,6],[2,4,6],[2,5,5],[3,3,6],[3,4,5],[4,4,4]],
    13: [[1,6,6],[2,5,6],[3,4,6],[3,5,5],[4,4,5]],
    14: [[2,6,6],[3,5,6],[4,4,6],[4,5,5]],
    15: [[3,6,6],[4,5,6],[5,5,5]],
    16: [[4,6,6],[5,5,6]],
    17: [[5,6,6]],
    18: [[6,6,6]],
}


def _compress_image(image_bytes: bytes, max_px: int = 768) -> tuple[bytes, str]:
    """Resize image so longest edge ≤ max_px — preserves OCR legibility."""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        if max(w, h) > max_px:
            ratio = max_px / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return image_bytes, "image/jpeg"


def _fix_llm_json(content: str) -> str:
    """Sửa các lỗi JSON thường gặp từ LLM output."""
    # 1. Strip markdown fences
    content = re.sub(r"```(?:json)?", "", content).strip().strip("`")
    # 2. Shorthand số tiền: 1590k → 1590000, 1.5tr → 1500000
    def _expand_k(m):
        return str(int(float(m.group(1)) * 1_000))
    def _expand_tr(m):
        return str(int(float(m.group(1)) * 1_000_000))
    content = re.sub(r'(\d+(?:\.\d+)?)[kK](?=[,\}\s\n\]])', _expand_k, content)
    content = re.sub(r'(\d+(?:\.\d+)?)[tT][rR](?=[,\}\s\n\]])', _expand_tr, content)
    # 3. Leading zeros: 0165544 → 165544
    content = re.sub(r'(?<=[:\[,\s])0+([1-9])', r'\1', content)
    return content


def _parse_vision_text(raw: str) -> dict:
    content = _fix_llm_json(raw)
    logger.debug("Fixed JSON content: %s", content[:400].replace("\n", "↵"))
    # Dùng raw_decode để tìm JSON object hợp lệ đầu tiên (bỏ qua preamble text)
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", content):
        try:
            obj, _ = decoder.raw_decode(content, m.start())
            if isinstance(obj, dict):
                return _normalize(obj)
        except json.JSONDecodeError:
            continue
    raise ValueError(f"Không tìm thấy JSON hợp lệ: {content[:300]}")


def _extract_groq(b64: str, mime: str) -> dict:
    groq_key = getattr(config, "GROQ_API_KEY", "") or ""
    if not groq_key:
        raise RuntimeError("No GROQ_API_KEY")
    resp = requests.post(
        GROQ_VISION_URL,
        headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
        json={
            "model": GROQ_VISION_MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACTION_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }],
            "max_tokens": 512,
            "temperature": 0,
        },
        timeout=15,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"].strip()
    logger.info("Groq Vision raw: %s", raw[:600].replace("\n", "↵"))
    return _parse_vision_text(raw)


def _extract_openrouter(b64: str, mime: str) -> dict:
    key = getattr(config, "OPENROUTER_API_KEY", "") or ""
    if not key:
        raise RuntimeError("No OPENROUTER_API_KEY")
    resp = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": EXTRACTION_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]}],
            "max_tokens": 512,
            "temperature": 0,
        },
        timeout=15,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"].strip()
    logger.info("OpenRouter Vision raw: %s", raw[:600].replace("\n", "↵"))
    return _parse_vision_text(raw)


def _extract_gemini(b64: str, mime: str) -> dict:
    api_key = getattr(config, "GEMINI_API_KEY", "") or ""
    if not api_key:
        raise RuntimeError("No GEMINI_API_KEY")
    resp = requests.post(
        GEMINI_URL,
        params={"key": api_key},
        json={
            "contents": [{"parts": [
                {"text": EXTRACTION_PROMPT},
                {"inline_data": {"mime_type": mime, "data": b64}},
            ]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 1024},
        },
        timeout=15,
    )
    resp.raise_for_status()
    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    logger.info("Gemini Vision raw: %s", raw[:600].replace("\n", "↵"))
    return _parse_vision_text(raw)


def _majority_merge(results: list[dict]) -> dict:
    """P56: Merge multiple vision extractions by majority vote per field.
    Numeric fields: most common non-zero value wins; ties → max.
    Integer fields (draw_number, result_n*): most common non-null wins.
    """
    if len(results) == 1:
        return results[0]

    bet_keys = [
        "nho_bet", "hoa_bet", "lon_bet",
        "tong_3", "tong_4", "tong_5", "tong_6", "tong_7", "tong_8", "tong_9",
        "tong_10", "tong_11", "tong_12", "tong_13", "tong_14", "tong_15",
        "tong_16", "tong_17", "tong_18",
        "bo_ba_111", "bo_ba_222", "bo_ba_333", "bo_ba_444", "bo_ba_555", "bo_ba_666",
        "bo_2_11", "bo_2_22", "bo_2_33", "bo_2_44", "bo_2_55", "bo_2_66",
        "bo_ba_bat_ki",
    ]
    int_keys = ["draw_number", "result_n1", "result_n2", "result_n3"]

    merged = {}

    for key in bet_keys:
        vals = [r.get(key, 0) or 0 for r in results]
        nonzero = [v for v in vals if v > 0]
        if not nonzero:
            merged[key] = 0
        else:
            counts = {}
            for v in nonzero:
                counts[v] = counts.get(v, 0) + 1
            merged[key] = max(counts, key=lambda v: (counts[v], v))

    for key in int_keys:
        vals = [r.get(key) for r in results]
        valid = [v for v in vals if v is not None]
        if not valid:
            merged[key] = None
        else:
            counts = {}
            for v in valid:
                counts[v] = counts.get(v, 0) + 1
            merged[key] = max(counts, key=lambda v: (counts[v], v))

    # Recompute actual_result/actual_numbers from merged result numbers
    nums = [merged.get(k) for k in ("result_n1", "result_n2", "result_n3")]
    if all(n is not None and 1 <= n <= 6 for n in nums):
        tong = sum(nums)
        merged["actual_result"]  = tong if 3 <= tong <= 18 else None
        merged["actual_numbers"] = nums
    else:
        merged["actual_result"]  = None
        merged["actual_numbers"] = None

    merged["_consensus_n"] = len(results)
    return merged


def extract_from_image(image_bytes: bytes) -> dict:
    """P56: All 3 providers run in parallel with majority vote on results.
    Waits up to 25s for all to complete, then merges with _majority_merge.
    Falls back to first-success if only 1 provider responds."""
    compressed, mime = _compress_image(image_bytes)
    b64 = base64.b64encode(compressed).decode()

    import concurrent.futures as _cf
    import requests as _req

    def _groq_with_retry(b64, mime):
        try:
            return _extract_groq(b64, mime)
        except (_req.exceptions.SSLError, _req.exceptions.ConnectionError):
            logger.warning("Groq SSL/Connection error, retrying once...")
            return _extract_groq(b64, mime)

    providers = {
        "Groq":       lambda: _groq_with_retry(b64, mime),
        "Gemini":     lambda: _extract_gemini(b64, mime),
        "OpenRouter": lambda: _extract_openrouter(b64, mime),
    }
    ex = _cf.ThreadPoolExecutor(max_workers=3)
    try:
        futures = {ex.submit(fn): name for name, fn in providers.items()}
        successes = []
        last_err  = None
        # Collect all results within 25s window
        for fut in _cf.as_completed(futures, timeout=25):
            try:
                result = fut.result()
                logger.info("Vision success via %s", futures[fut])
                successes.append(result)
            except Exception as e:
                logger.warning("%s failed: %s", futures[fut], e)
                last_err = e

        if not successes:
            raise last_err or RuntimeError("All vision APIs failed")

        merged = _majority_merge(successes)
        logger.info("Vision merge: %d/%d providers succeeded", len(successes), len(providers))
        return merged
    finally:
        ex.shutdown(wait=False)


def _normalize(data: dict) -> dict:
    bet_keys = [
        "nho_bet", "hoa_bet", "lon_bet",
        "tong_3", "tong_4", "tong_5", "tong_6", "tong_7", "tong_8", "tong_9",
        "tong_10", "tong_11", "tong_12", "tong_13", "tong_14", "tong_15",
        "tong_16", "tong_17", "tong_18",
        "bo_ba_111", "bo_ba_222", "bo_ba_333", "bo_ba_444", "bo_ba_555", "bo_ba_666",
        "bo_2_11", "bo_2_22", "bo_2_33", "bo_2_44", "bo_2_55", "bo_2_66",
        "bo_ba_bat_ki",
    ]
    out = {}

    # draw_number
    v = data.get("draw_number")
    out["draw_number"] = int(v) if v not in (None, "", "null") else None

    # bet amounts
    for k in bet_keys:
        v = data.get(k)
        try:
            out[k] = float(v) if v not in (None, "", "null") else 0.0
        except (TypeError, ValueError):
            out[k] = 0.0

    # result numbers (1-6 each)
    nums = []
    for k in ("result_n1", "result_n2", "result_n3"):
        v = data.get(k)
        try:
            n = int(v) if v not in (None, "", "null") else None
            if n and 1 <= n <= 6:
                nums.append(n)
            else:
                nums.append(None)
        except (TypeError, ValueError):
            nums.append(None)

    out["result_n1"], out["result_n2"], out["result_n3"] = nums

    # actual_result: tính từ 3 số nếu đủ, fallback về field cũ
    if all(n is not None for n in nums):
        tong = sum(nums)
        out["actual_result"]   = tong if 3 <= tong <= 18 else None
        out["actual_numbers"]  = nums
    else:
        v = data.get("actual_result")
        out["actual_result"]  = int(v) if v not in (None, "", "null") else None
        out["actual_numbers"] = None

    # Validation warnings
    warnings = []
    for k in bet_keys:
        v = out.get(k, 0)
        if v and v % 1000 != 0:
            warnings.append(f"{k}={v} not multiple of 1000")
    dn = out.get("draw_number")
    if dn and not (10000 <= dn <= 9999999):
        warnings.append(f"draw_number={dn} looks wrong")
    if warnings:
        out["_warnings"] = warnings

    return out


def _compute_total_bet(data: dict) -> float:
    """Tổng tất cả tiền cược (nhà cái thu)."""
    total = sum(data.get(k, 0) for k in ["nho_bet", "hoa_bet", "lon_bet"])
    total += sum(data.get(f"tong_{i}", 0) for i in range(3, 19))
    total += sum(data.get(BO_BA_MAP[n], 0) for n in range(1, 7))
    total += sum(data.get(BO_HAI_MAP[n], 0) for n in range(1, 7))
    total += data.get("bo_ba_bat_ki", 0)
    return round(total, 2)


def _compute_payout(data: dict, result_tong: int, actual_numbers: list = None) -> float:
    """Tính nhà cái phải trả.
    actual_numbers: [n1,n2,n3] nếu có → tính bộ ba/đôi chính xác.
    Nếu không có → chỉ tính size + tổng (dùng cho simulation).
    """
    payout = 0.0

    # Size bets
    if 3 <= result_tong <= 9:
        payout += data.get("nho_bet", 0) * 1.5
    elif result_tong in (10, 11):
        payout += data.get("hoa_bet", 0) * 2.0
    elif 12 <= result_tong <= 18:
        payout += data.get("lon_bet", 0) * 1.5

    # Exact sum bets
    payout += data.get(f"tong_{result_tong}", 0) * TONG_ODDS.get(result_tong, 0)

    # Bộ ba / Bộ đôi — chỉ tính khi biết số thực
    if actual_numbers and len(actual_numbers) == 3:
        counts = {}
        for n in actual_numbers:
            counts[n] = counts.get(n, 0) + 1
        for num, cnt in counts.items():
            if cnt == 3:
                payout += data.get(BO_BA_MAP[num], 0) * BO_BA_ODDS
                payout += data.get("bo_ba_bat_ki", 0) * BO_BAT_KI_ODDS
            elif cnt == 2:
                payout += data.get(BO_HAI_MAP[num], 0) * BO_HAI_ODDS

    return round(payout, 2)


def _vnd(v: float) -> str:
    """Format VND: ≥1tr → Xtr, ≥1k → Xk, else Xđ."""
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.2f}tr"
    if abs(v) >= 1_000:
        return f"{v / 1_000:.0f}k"
    return f"{v:.0f}đ"


def _vnd_signed(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{_vnd(v)}"


def _ev_stars(ev: float) -> str:
    if ev >= -0.10: return "⭐⭐⭐"
    if ev >= -0.30: return "⭐⭐"
    if ev >= -0.45: return "⭐"
    return ""


def format_result(data: dict, probs: dict = None, window: int = 0) -> str:
    tong_thu = _compute_total_bet(data)
    actual   = data.get("actual_result")
    nums     = data.get("actual_numbers")
    draw_num = data.get("draw_number", "?")

    consensus_n = data.get("_consensus_n", 1)
    consensus_str = f" · {consensus_n}/3 model" if consensus_n > 1 else ""
    lines = [
        f"📊 <b>PHÂN TÍCH KỲ #{draw_num}</b>{consensus_str}",
        f"💰 Tổng thu: <b>{_vnd(tong_thu)}</b>",
    ]

    # P55: show OCR warnings if any suspicious values
    warns = data.get("_warnings")
    if warns:
        lines.append(f"⚠️ <i>OCR cần kiểm tra: {'; '.join(warns[:3])}</i>")

    # ── Bảng cược (chỉ dòng có tiền đặt) ─────────────────────
    def _win_mark(label: str) -> str:
        if not actual:
            return " "
        if label.startswith("NHỎ") and 3 <= actual <= 9:    return "◀"
        if label.startswith("HOÀ") and actual in (10, 11):  return "◀"
        if label.startswith("LỚN") and 12 <= actual <= 18:  return "◀"
        if label.startswith("Tổng"):
            try:
                return "◀" if int(label.split()[1]) == actual else " "
            except (IndexError, ValueError):
                return " "
        if nums:
            counts = {}
            for x in nums: counts[x] = counts.get(x, 0) + 1
            if label.startswith("Bộ ba"):
                n = int(label[-1])
                return "◀" if counts.get(n, 0) == 3 else " "
            if label.startswith("Bộ đôi"):
                n = int(label[-1])
                return "◀" if counts.get(n, 0) == 2 else " "
            if label.startswith("Bất kì"):
                return "◀" if max(counts.values(), default=0) == 3 else " "
        return " "

    bet_rows = []
    for key, label, odds in [
        ("nho_bet",  "NHỎ(3-9)",   1.5),
        ("hoa_bet",  "HOÀ(10-11)", 2.0),
        ("lon_bet",  "LỚN(12-18)", 1.5),
    ]:
        bet = data.get(key, 0)
        if bet:
            bet_rows.append((label, bet, odds, bet * odds, ""))

    for t in range(3, 19):
        bet = data.get(f"tong_{t}", 0)
        if bet:
            odds   = TONG_ODDS[t]
            combos = COMBINATIONS.get(t, [])
            cstr   = "·".join(f"[{','.join(str(n) for n in c)}]" for c in combos[:3])
            if len(combos) > 3: cstr += "…"
            bet_rows.append((f"Tổng {t:2d}", bet, odds, bet * odds, cstr))

    for n in range(1, 7):
        bet = data.get(BO_BA_MAP[n], 0)
        if bet:
            bet_rows.append((f"Bộ ba {n}{n}{n}", bet, BO_BA_ODDS, bet * BO_BA_ODDS, ""))

    for n in range(1, 7):
        bet = data.get(BO_HAI_MAP[n], 0)
        if bet:
            bet_rows.append((f"Bộ đôi {n}{n}", bet, BO_HAI_ODDS, bet * BO_HAI_ODDS, ""))

    bk = data.get("bo_ba_bat_ki", 0)
    if bk:
        bet_rows.append(("Bất kì 3 trùng", bk, BO_BAT_KI_ODDS, bk * BO_BAT_KI_ODDS, ""))

    if bet_rows:
        lines.append("<code>")
        lines.append(f" {'BỘ SỐ':<16} {'CƯỢC':>8} {'HỆ SỐ':>6} {'CHI TRẢ':>9}  TỔ HỢP")
        sep = " " + "─" * 55
        lines.append(sep)
        for label, bet, odds, pout, combo in bet_rows:
            mk = _win_mark(label)
            lines.append(f"{mk}{label:<16} {_vnd(bet):>8} ×{odds:<5} {_vnd(pout):>9}  {combo}")
        lines.append(sep)
        lines.append(f" {'TỔNG':<16} {_vnd(tong_thu):>8}")
        lines.append("</code>")

    # ── Kết quả thực tế ───────────────────────────────────────
    if actual and 3 <= actual <= 18:
        payout    = _compute_payout(data, actual, actual_numbers=nums)
        loi_nhuan = tong_thu - payout
        status    = "✅ LỢI" if loi_nhuan > 0 else ("❌ LỖ" if loi_nhuan < 0 else "⚖️ HOÀ")
        size_lbl  = SIZE_LABEL.get(actual, "")
        nums_str  = f" ({'-'.join(str(n) for n in nums)})" if nums else ""

        lines += ["━━━━━━━━━━━━━━━━",
                  f"🎲 KQ: Tổng <b>{actual}</b>{nums_str} ({size_lbl})"]

        combos = COMBINATIONS.get(actual, [])
        if combos:
            combo_str = "  ·  ".join(f"[{','.join(str(n) for n in c)}]" for c in combos)
            lines.append(f"🎯 Tổ hợp: <code>{combo_str}</code>")

        breakdown = []
        if 3 <= actual <= 9 and data.get("nho_bet", 0):
            bet = data["nho_bet"]
            breakdown.append(f"  NHỎ: {_vnd(bet)} × 1.5 = <b>{_vnd(bet * 1.5)}</b>")
        elif actual in (10, 11) and data.get("hoa_bet", 0):
            bet = data["hoa_bet"]
            breakdown.append(f"  HOÀ: {_vnd(bet)} × 2.0 = <b>{_vnd(bet * 2.0)}</b>")
        elif 12 <= actual <= 18 and data.get("lon_bet", 0):
            bet = data["lon_bet"]
            breakdown.append(f"  LỚN: {_vnd(bet)} × 1.5 = <b>{_vnd(bet * 1.5)}</b>")

        tong_bet = data.get(f"tong_{actual}", 0)
        if tong_bet:
            odds_val = TONG_ODDS[actual]
            breakdown.append(
                f"  Tổng {actual}: {_vnd(tong_bet)} × {odds_val} = <b>{_vnd(tong_bet * odds_val)}</b>")

        if nums:
            counts = {}
            for n in nums: counts[n] = counts.get(n, 0) + 1
            for num, cnt in counts.items():
                if cnt == 3:
                    bo = data.get(BO_BA_MAP[num], 0)
                    if bo:
                        breakdown.append(
                            f"  Bộ ba {num}{num}{num}: {_vnd(bo)} × {BO_BA_ODDS} = <b>{_vnd(bo * BO_BA_ODDS)}</b>")
                    if bk:
                        breakdown.append(
                            f"  Bất kì 3 trùng: {_vnd(bk)} × {BO_BAT_KI_ODDS} = <b>{_vnd(bk * BO_BAT_KI_ODDS)}</b>")
                elif cnt == 2:
                    bo = data.get(BO_HAI_MAP[num], 0)
                    if bo:
                        breakdown.append(
                            f"  Bộ đôi {num}{num}: {_vnd(bo)} × {BO_HAI_ODDS} = <b>{_vnd(bo * BO_HAI_ODDS)}</b>")

        if breakdown:
            lines.append("💵 <b>Chi tiết nhà cái trả:</b>")
            lines += breakdown
        else:
            lines.append("  (không có cược trúng)")

        lines += [
            f"🏦 Tổng trả: <b>{_vnd(payout)}</b>",
            f"📈 Lợi nhuận: <b>{_vnd_signed(loi_nhuan)}</b> {status}",
        ]

    # ── Mô phỏng payout (nhiều → ít) ──────────────────────────
    sim = sorted(
        [(t, _compute_payout(data, t)) for t in range(3, 19)],
        key=lambda x: x[1], reverse=True
    )
    lines.append("━━━━━━━━━━━━━━━━")
    lines.append("📉 <b>NHÀ CÁI TRẢ (nhiều → ít):</b>")
    lines.append("<code>")
    zeros = []
    for t, p in sim:
        if p == 0:
            zeros.append(str(t))
            continue
        loi   = tong_thu - p
        mark  = "▼" if loi < 0 else "▲"
        cur   = " ◀KQ" if t == actual else ""
        combos = COMBINATIONS.get(t, [])
        cshort = "·".join(f"[{','.join(str(n) for n in c)}]" for c in combos[:2])
        if len(combos) > 2: cshort += "…"
        lines.append(f"Tổng {t:2d}: {_vnd(p):>9}  {mark}{_vnd_signed(loi)}{cur}  {cshort}")
    lines.append("</code>")
    if zeros:
        lines.append(f"⚪ Tổng {', '.join(zeros)}: không trả → lời {_vnd(tong_thu)}")

    # ── Xác suất lịch sử + EV ─────────────────────────────────
    if probs:
        win_label = f"{window}" if window else "?"
        lines.append("━━━━━━━━━━━━━━━━")
        lines.append(f"📊 <b>XÁC SUẤT + EV ({win_label} kỳ gần nhất):</b>")
        lines.append("<code>")
        lines.append("T    P%    Odds    EV%")
        for t in range(3, 19):
            p_hist = probs.get(t, 0)
            odds   = TONG_ODDS[t]
            ev     = p_hist * odds - 1
            star   = _ev_stars(ev)
            cur    = "◀" if t == actual else " "
            lines.append(
                f"{t:2d}  {p_hist*100:5.1f}%  x{odds:<5}  {ev*100:+6.1f}%  {cur}{star}"
            )
        lines.append("</code>")

        p_nho  = sum(probs.get(t, 0) for t in range(3, 10))
        p_hoa  = sum(probs.get(t, 0) for t in (10, 11))
        p_lon  = sum(probs.get(t, 0) for t in range(12, 19))
        ev_nho = p_nho * 1.5 - 1
        ev_hoa = p_hoa * 2.0 - 1
        ev_lon = p_lon * 1.5 - 1

        lines.append("<code>")
        lines.append(f"NHỎ  {p_nho*100:.1f}%  x1.5  {ev_nho*100:+.1f}%  {_ev_stars(ev_nho)}")
        lines.append(f"HOÀ  {p_hoa*100:.1f}%  x2.0  {ev_hoa*100:+.1f}%  {_ev_stars(ev_hoa)}")
        lines.append(f"LỚN  {p_lon*100:.1f}%  x1.5  {ev_lon*100:+.1f}%  {_ev_stars(ev_lon)}")
        lines.append("</code>")

        candidates = [("NHỎ", ev_nho), ("HOÀ", ev_hoa), ("LỚN", ev_lon)] + [
            (f"Tổng {t}", probs.get(t, 0) * TONG_ODDS[t] - 1) for t in range(3, 19)
        ]
        candidates.sort(key=lambda x: x[1], reverse=True)
        top3 = candidates[:3]
        suggest_parts = [f"<b>{name}</b> (EV:{ev*100:+.1f}%)" for name, ev in top3]
        lines.append(f"💡 <b>GỢI Ý:</b> {' › '.join(suggest_parts)}")

    # P55: bet concentration summary
    if tong_thu > 0:
        lines.append("━━━━━━━━━━━━━━━━")
        size_total = (data.get("nho_bet", 0) + data.get("hoa_bet", 0) + data.get("lon_bet", 0))
        tong_total = sum(data.get(f"tong_{t}", 0) for t in range(3, 19))
        bo_total   = (sum(data.get(BO_BA_MAP[n], 0) for n in range(1, 7)) +
                      sum(data.get(BO_HAI_MAP[n], 0) for n in range(1, 7)) +
                      data.get("bo_ba_bat_ki", 0))
        parts = []
        if size_total: parts.append(f"Size {size_total/tong_thu:.0%}")
        if tong_total: parts.append(f"Tổng {tong_total/tong_thu:.0%}")
        if bo_total:   parts.append(f"Bộ {bo_total/tong_thu:.0%}")
        if parts:
            lines.append(f"🎯 <b>Phân bổ:</b> {' · '.join(parts)}")
        # Largest single bet
        all_bets = [(k, data.get(k, 0)) for k in
                    ["nho_bet","hoa_bet","lon_bet"] +
                    [f"tong_{t}" for t in range(3,19)] +
                    [BO_BA_MAP[n] for n in range(1,7)] +
                    [BO_HAI_MAP[n] for n in range(1,7)] +
                    ["bo_ba_bat_ki"]]
        top_bet = max(all_bets, key=lambda x: x[1])
        if top_bet[1] > 0:
            conc = top_bet[1] / tong_thu
            conc_warn = " ⚠️ quá tập trung" if conc >= 0.80 else ""
            lines.append(f"📌 Cược lớn nhất: <b>{top_bet[0]}</b> = {_vnd(top_bet[1])} ({conc:.0%}){conc_warn}")

    return "\n".join(lines)
