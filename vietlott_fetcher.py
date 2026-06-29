"""
Vietlott Fetcher – Lấy kết quả Bingo18 từ vietlott.vn

Có 2 phương thức lấy dữ liệu (tự động fallback):
  1. AjaxPro API  (ưu tiên) – JSON trả về, nhanh, ít bị block
  2. HTML Scraping (fallback) – parse HTML, dùng khi API lỗi

Nguồn phân tích:
  - core.js:      AjaxPro.ID = "AjaxPro" → header "X-AjaxPro-Method"
                  AjaxPro.token = ""     → không cần token
                  Content-Type: text/plain; charset=utf-8
                  Body: AjaxPro.toJSON(args) → JSON object
  - prototype.js: url = '/ajaxpro/GameBingo18Box,Vietlott.PlugIn.ashx'
  - Converter.js: Response format: {"value": ..., "error": ...}

Lỗi URL cũ: "trò-chơi" chưa encode → 404.
URL đúng:   /vi/tr%C3%B2-ch%C6%A1i/bingo18/ket-qua-trung-thuong
"""

import json
import logging
import re
import time
from typing import Dict, List, Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

TIMEOUT = 15

# ── Headers chung ─────────────────────────────────────────────
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_BASE_HEADERS = {"User-Agent": _UA, "Referer": "https://vietlott.vn/"}

# ── AjaxPro API ───────────────────────────────────────────────
# Từ prototype.js: url = '/ajaxpro/GameBingo18Box,Vietlott.PlugIn.ashx'
# Từ core.js:      header = "X-AjaxPro-Method", token = "" (không cần)
AJAXPRO_URL = (
    "https://vietlott.vn/ajaxpro/"
    "Vietlott.PlugIn.WebParts.GameBingo18Box,Vietlott.PlugIn.ashx"
)
_AJAXPRO_HEADERS = {
    **_BASE_HEADERS,
    # Từ core.js: Content-Type luôn là text/plain; charset=utf-8
    "Content-Type": "text/plain; charset=utf-8",
    "Accept":       "*/*",
    # X-AjaxPro-Token: "" → bỏ qua (AjaxPro.token = "")
}

# ── HTML URL – encode đúng ký tự tiếng Việt ──────────────────
# Lỗi cũ: "trò-chơi" viết thẳng → server trả 404
# Đúng:   %C3%B2 (ò) và %C6%A1i (ơi)
_HTML_PATH   = "/vi/tr\u00f2-ch\u01a1i/bingo18/ket-qua-trung-thuong"
_HTML_URL    = "https://vietlott.vn" + quote(_HTML_PATH, safe="/-")
_HTML_HEADERS = {**_BASE_HEADERS, "Accept": "text/html,*/*;q=0.9"}


# ═══════════════════════════════════════════════════════════════
# 1. AjaxPro API (phương thức chính)
# ═══════════════════════════════════════════════════════════════

def _ajaxpro_call(method: str, params: dict) -> Optional[dict]:
    """
    Gọi AjaxPro theo đúng protocol từ core.js:
      POST /ajaxpro/...ashx
      Header: X-AjaxPro-Method: <method>
      Body:   JSON string (AjaxPro.toJSON format)
    """
    headers = {**_AJAXPRO_HEADERS, "X-AjaxPro-Method": method}
    try:
        resp = requests.post(
            AJAXPRO_URL,
            headers=headers,
            data=json.dumps(params),   # AjaxPro.toJSON(args)
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            logger.debug("AjaxPro %s → HTTP %d", method, resp.status_code)
            return None
        # Response format từ core.js createResponse():
        # {"value": <result>, "error": null} hoặc {"error": {...}}
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            logger.debug("AjaxPro %s error: %s", method, data["error"])
            return None
        return data.get("value") if isinstance(data, dict) else data
    except Exception as e:
        logger.debug("AjaxPro %s exception: %s", method, e)
        return None


def _extract_numbers(data) -> Optional[List[int]]:
    """Trích xuất 3 số thắng từ AjaxPro response (nhiều format)."""
    if not data:
        return None

    # Format list trực tiếp: [2, 5, 1]
    if isinstance(data, list):
        nums = [int(n) for n in data if str(n).strip().isdigit()]
        nums = [n for n in nums if 1 <= n <= 6]
        if len(nums) >= 3:
            return nums[:3]

    if not isinstance(data, dict):
        return None

    # Format dict – thử các key phổ biến
    for key in ("LotteryResult", "Numbers", "WinNumbers",
                "Result", "numbers", "result", "winNumbers"):
        val = data.get(key)
        if isinstance(val, list) and len(val) >= 3:
            nums = [int(n) for n in val if str(n).strip().isdigit()]
            nums = [n for n in nums if 1 <= n <= 6]
            if len(nums) >= 3:
                return nums[:3]
        if isinstance(val, str):
            nums = [int(x) for x in re.findall(r'\d+', val) if 1 <= int(x) <= 6]
            if len(nums) >= 3:
                return nums[:3]

    return None


def _fetch_via_ajaxpro(draw_id: int) -> Optional[Dict]:
    """
    Thử các method name của GameBingo18Box.
    Tên method không được public – thử theo thứ tự phổ biến nhất.
    """
    candidates = [
        # Tên method thường gặp trong ASP.NET WebParts
        ("GetDrawResult",         {"drawId": draw_id}),
        ("GetResult",             {"drawId": draw_id}),
        ("Process",               {"gameDrawId": str(draw_id).zfill(7)}),
        ("GetLotteryResult",      {"gameDrawId": draw_id}),
        ("GetResultByDrawId",     {"drawId": draw_id}),
        ("GetBingo18Result",      {"drawId": draw_id}),
    ]
    for method, params in candidates:
        result = _ajaxpro_call(method, params)
        if result is None:
            continue
        nums = _extract_numbers(result)
        if nums:
            logger.info("AjaxPro OK: method='%s' draw=#%d → %s",
                        method, draw_id, nums)
            return {"draw_number": draw_id, "numbers": nums}

    return None


# ═══════════════════════════════════════════════════════════════
# 2. HTML Scraping (fallback)
# ═══════════════════════════════════════════════════════════════

def _fetch_html(draw_id: int = None) -> Optional[str]:
    """
    Fetch trang HTML kết quả Bingo18.
    URL đã encode đúng: /vi/tr%C3%B2-ch%C6%A1i/bingo18/...
    """
    url = f"{_HTML_URL}?gameDrawId={draw_id}" if draw_id else _HTML_URL
    try:
        resp = requests.get(url, headers=_HTML_HEADERS, timeout=TIMEOUT)
        if resp.status_code == 200:
            return resp.text
        logger.warning("HTML fetch HTTP %d (url=%s)", resp.status_code, url)
        return None
    except Exception as e:
        logger.debug("HTML fetch error: %s", e)
        return None


def _parse_numbers_html(html: str) -> Optional[List[int]]:
    try:
        soup = BeautifulSoup(html, "lxml")
        for sel in ("span.bong_tron_bingo", ".bong_tron_bingo", ".bong_tron"):
            balls = soup.select(sel)
            if balls:
                nums = [int(b.get_text(strip=True))
                        for b in balls[:3]
                        if b.get_text(strip=True).isdigit()]
                if len(nums) == 3 and all(1 <= n <= 6 for n in nums):
                    return nums
    except Exception as e:
        logger.debug("HTML parse error: %s", e)
    return None


def _parse_draw_id_html(html: str) -> Optional[int]:
    try:
        for pat in [
            r'gameDrawId["\s:=]+(\d{5,7})',
            r'draw[_-]?id["\s:=]+(\d{5,7})',
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                return int(m.group(1))
        soup = BeautifulSoup(html, "lxml")
        for sel in (".draw-id", ".ky-quay", "#drawId", "[data-draw-id]"):
            el = soup.select_one(sel)
            if el:
                text = el.get_text(strip=True).replace("#", "").strip()
                if text.isdigit():
                    return int(text)
    except Exception:
        pass
    return None


def _fetch_via_html(draw_id: int) -> Optional[Dict]:
    html = _fetch_html(draw_id)
    if not html:
        return None
    nums = _parse_numbers_html(html)
    return {"draw_number": draw_id, "numbers": nums} if nums else None


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def fetch_draw_by_id(draw_id: int) -> Optional[Dict]:
    """
    Lấy kết quả một kỳ cụ thể.
    Ưu tiên: AjaxPro API → fallback HTML scraping.
    """
    result = _fetch_via_ajaxpro(draw_id)
    if result:
        return result
    logger.debug("AjaxPro failed draw #%d → HTML fallback", draw_id)
    return _fetch_via_html(draw_id)


def get_latest_result() -> Optional[Dict]:
    """Lấy kỳ mới nhất. Ưu tiên HTML (trang không param) → AjaxPro."""
    html = _fetch_html()   # trang mặc định = kỳ mới nhất
    if html:
        nums    = _parse_numbers_html(html)
        draw_id = _parse_draw_id_html(html)
        if nums:
            logger.info("Latest result: #%s → %s", draw_id, nums)
            return {"draw_number": draw_id, "numbers": nums}
    return None


def poll_draw_by_id(
    draw_id: int,
    timeout: int = 90,
    retry_interval: int = 3,
) -> Optional[List[int]]:
    """Poll cho đến khi có kết quả hoặc hết timeout."""
    deadline = time.time() + timeout
    attempt  = 0
    while time.time() < deadline:
        attempt += 1
        result = fetch_draw_by_id(draw_id)
        if result and result.get("numbers"):
            logger.info("poll #%d OK after %d attempt(s)", draw_id, attempt)
            return result["numbers"]
        remaining = deadline - time.time()
        if remaining > 0:
            time.sleep(min(retry_interval, remaining))
    logger.warning("poll #%d timeout (%ds, %d attempts)", draw_id, timeout, attempt)
    return None


def scan_recent_draws(start_id: int, count: int = 20) -> List[Dict]:
    """Quét `count` kỳ liên tiếp từ start_id trở về trước."""
    results = []
    for draw_id in range(start_id, start_id - count, -1):
        result = fetch_draw_by_id(draw_id)
        if result:
            results.append(result)
            logger.info("Scanned #%d: %s", draw_id, result["numbers"])
        time.sleep(0.3)
    return results


# ═══════════════════════════════════════════════════════════════
# GitHub Data Source (nguồn ổn định nhất – cập nhật hàng ngày)
# ═══════════════════════════════════════════════════════════════

GITHUB_JSONL_URL = (
    "https://raw.githubusercontent.com/vietvudanh/vietlott-data"
    "/main/data/bingo18.jsonl"
)


def fetch_from_github(limit: int = 100) -> List[Dict]:
    """
    Tải kết quả Bingo18 từ GitHub (vietvudanh/vietlott-data).
    Cập nhật hàng ngày, đáng tin cậy hơn scraping vietlott.vn.
    Trả về list {'draw_number': int, 'numbers': [...], 'draw_time': str}.
    """
    try:
        resp = requests.get(
            GITHUB_JSONL_URL,
            headers=_BASE_HEADERS,
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning("GitHub fetch HTTP %d", resp.status_code)
            return []

        results = []
        for line in resp.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj  = json.loads(line)
                nums = obj.get("result", [])
                if not (isinstance(nums, list) and len(nums) == 3):
                    continue
                if not all(1 <= int(n) <= 6 for n in nums):
                    continue
                results.append({
                    "draw_number": int(obj["id"]),
                    "numbers":     [int(n) for n in nums],
                    "draw_time":   obj.get("date", ""),
                })
            except Exception:
                continue

        results.sort(key=lambda x: x["draw_number"])
        logger.info("GitHub: loaded %d draws", len(results))
        return results[-limit:] if limit else results

    except Exception as e:
        logger.warning("GitHub fetch error: %s", e)
        return []


# ═══════════════════════════════════════════════════════════════
# VietlottFetcher – wrapper class (dùng bởi sync_to_supabase.py)
# ═══════════════════════════════════════════════════════════════

class VietlottFetcher:
    """
    Wrapper class cho các hàm fetch.
    Thứ tự ưu tiên: GitHub → AjaxPro → HTML scraping.
    """

    def get_latest(self) -> Optional[Dict]:
        """Lấy kỳ mới nhất."""
        # GitHub cập nhật hàng ngày → thử lấy kỳ cuối
        draws = fetch_from_github(limit=1)
        if draws:
            return draws[-1]
        return get_latest_result()

    def fetch_by_id(self, draw_id: int) -> Optional[Dict]:
        """Lấy một kỳ cụ thể theo draw_id."""
        return fetch_draw_by_id(draw_id)

    def fetch_bulk_from_github(self, limit: int = 500) -> List[Dict]:
        """Tải nhiều kỳ từ GitHub (dùng cho import hàng loạt)."""
        return fetch_from_github(limit=limit)
