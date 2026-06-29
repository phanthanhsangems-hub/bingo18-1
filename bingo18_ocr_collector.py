# -*- coding: utf-8 -*-
"""
Bingo18 OCR Fraud Detector
- Tự động chụp màn hình mỗi 5 phút
- OCR đọc tiền cược (Windows built-in OCR, không cần Tesseract)
- Tính combo nhà cái muốn/sợ nhất
- Lưu SQLite, báo cáo sau 50+ phiên
"""
import sys, io, asyncio, re, json, time, sqlite3, ctypes
from datetime import datetime, timezone
from pathlib import Path
from itertools import combinations_with_replacement

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import win32gui, win32con
import mss
from PIL import Image, ImageEnhance

# Load .env cho Supabase connection
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ── Cấu hình ──────────────────────────────────────────────────────────────────
DB_FILE   = "bingo18_fraud_data.db"
SS_DIR    = Path("screenshots_auto")
SS_DIR.mkdir(exist_ok=True)
INTERVAL  = 300   # giây giữa 2 lần chụp (~5 phút, trước mỗi phiên)

# Toạ độ board (từ session 2026-06-01: Vietlott window ở 606,0→1547,537)
BOARD_RECT = (606, 0, 1547, 537)   # (x1, y1, x2, y2) trên màn hình 1920x1080

TY_LE_TONG = {3:120,4:40,5:30,6:12,7:8,8:5.5,
              9:4.7,10:4.4,11:4.4,12:4.7,13:5.5,
              14:8,15:12,16:20,17:40,18:120}
TY_LE_SIZE = {"NHO":1.5,"HOA":2.0,"LON":1.5}
TY_LE_TRIPLE     = 120
TY_LE_TRIPLE_ANY = 20
TY_LE_DOUBLE     = 7.5

# ── Windows OCR ───────────────────────────────────────────────────────────────
async def _ocr_image_async(img_path: str) -> str:
    import winsdk.windows.media.ocr as ocr_win
    import winsdk.windows.graphics.imaging as wgi
    import winsdk.windows.storage as storage

    p = Path(img_path).resolve()
    file   = await storage.StorageFile.get_file_from_path_async(str(p))
    stream = await file.open_async(0)
    dec    = await wgi.BitmapDecoder.create_async(stream)
    bmp    = await dec.get_software_bitmap_async()
    eng    = ocr_win.OcrEngine.try_create_from_user_profile_languages()
    result = await eng.recognize_async(bmp)
    return result.text

def ocr_image(img_path: str) -> str:
    return asyncio.run(_ocr_image_async(img_path))

# ── Screenshot ────────────────────────────────────────────────────────────────
def find_cmd_windows():
    """Tìm tất cả cửa sổ cần minimize: CMD + Telegram (che board)."""
    wins = []
    def cb(hwnd, _):
        t = win32gui.GetWindowText(hwnd)
        if any(x in t for x in ['Casino fraud','PowerShell','Command Prompt','Git CMD',
                                  'BINGO18 @','Trans sporter','Telegram','TelegramDesktop']):
            if win32gui.IsWindowVisible(hwnd):
                r = win32gui.GetWindowRect(hwnd)
                if r[2]-r[0] > 50:
                    wins.append(hwnd)
    win32gui.EnumWindows(cb, None)
    return wins

def close_popups():
    """Đóng các popup Tencent/Androws đang che board."""
    POPUP_TITLES = ['用户帮助中心', '诊断日志', 'Androws', '腾讯', 'Helper', 'WinRAR', '游戏下载']
    def cb(hwnd, _):
        t = win32gui.GetWindowText(hwnd)
        for pt in POPUP_TITLES:
            if pt in t and win32gui.IsWindowVisible(hwnd):
                r = win32gui.GetWindowRect(hwnd)
                w, h = r[2]-r[0], r[3]-r[1]
                if 100 < w < 900 and 100 < h < 700:
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    win32gui.EnumWindows(cb, None)

def find_vietlott_window():
    """Tìm handle cửa sổ Vietlott SMS."""
    result = []
    def cb(hwnd, _):
        t = win32gui.GetWindowText(hwnd)
        if 'Vietlott SMS' in t or 'BINGO18' in t:
            r = win32gui.GetWindowRect(hwnd)
            w = r[2]-r[0]; h = r[3]-r[1]
            if w > 100 and h > 100:
                result.append((hwnd, t, r))
    win32gui.EnumWindows(cb, None)
    return result

def capture_board() -> tuple[Image.Image, str]:
    """Focus Vietlott → minimize CMD → chụp → restore. Trả về (image, timestamp)."""
    # Bước 0: Đóng popup
    close_popups()
    time.sleep(0.3)

    # Bước 1: Tìm và focus cửa sổ Vietlott
    vietlott_wins = find_vietlott_window()
    if vietlott_wins:
        hwnd_vt = vietlott_wins[0][0]
        win32gui.ShowWindow(hwnd_vt, win32con.SW_RESTORE)
        try:
            ctypes.windll.user32.SetForegroundWindow(hwnd_vt)
        except Exception:
            pass
        time.sleep(0.5)

    # Bước 2: Minimize CMD windows
    cmds = find_cmd_windows()
    for h in cmds:
        win32gui.ShowWindow(h, win32con.SW_MINIMIZE)
    time.sleep(0.8)

    # Bước 3: Lấy vị trí chính xác của Vietlott window
    rect = BOARD_RECT
    if vietlott_wins:
        r = win32gui.GetWindowRect(hwnd_vt)
        if r[2]-r[0] > 200:
            # Dùng ĐÚNG vị trí window, không cộng thêm
            rect = (max(0, r[0]), max(0, r[1]), r[2], r[3])

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    with mss.MSS() as sct:
        x1,y1,x2,y2 = rect
        region = {"left":x1,"top":y1,"width":x2-x1,"height":y2-y1}
        shot = sct.grab(region)
        img  = Image.frombytes('RGB', shot.size, shot.bgra, 'raw', 'BGRX')

    # Bước 4: Restore CMD
    for h in cmds:
        win32gui.ShowWindow(h, win32con.SW_RESTORE)
    return img, ts

# ── Parse OCR text ─────────────────────────────────────────────────────────────
def parse_amount(s: str) -> float:
    """'1.670k' → 1670, '760k' → 760, '2.340' → 2340"""
    s = s.strip().replace(',', '.').lower()
    m = re.match(r'(\d[\d.]*)', s)
    if not m: return 0.0
    val = float(m.group(1))
    if len(m.group(1).replace('.','')) <= 3 and '.' not in m.group(1):
        pass  # gia tri nho, giu nguyen
    return val

def split_ocr(img: Image.Image) -> tuple[str, str, str]:
    """
    Tách board thành 3 vùng OCR:
    - size_section: phần NHO/HOA/LON (y 18-50% của board)
    - left: nửa trái (triples + sum 3-10)
    - right: nửa phải (sum 11-18 + doubles)
    Trả về (size_text, left_text, right_text)
    """
    w, h = img.size
    mid  = w // 2

    # SIZE bets: 58-100% chiều ngang, 22-48% chiều cao — chia 3 ô riêng
    y_top   = int(h * 0.22)
    y_bot   = int(h * 0.48)
    x_start = int(w * 0.42)
    cell_w  = (w - x_start) // 3

    def crop_size_cell(i):
        x1 = x_start + i * cell_w
        x2 = x_start + (i+1) * cell_w + (w - x_start - 3*cell_w if i==2 else 0)
        cell = img.crop((x1, y_top, x2, y_bot))
        return ImageEnhance.Contrast(
            cell.resize((cell.width*3, cell.height*3), Image.LANCZOS)).enhance(2.0)

    nho_img = crop_size_cell(0)
    hoa_img = crop_size_cell(1)
    lon_img = crop_size_cell(2)

    # Save SIZE debug images
    img.crop((x_start, y_top, w, y_bot)).save(str(SS_DIR / "_ocr_size.png"))
    nho_img.save(str(SS_DIR / "_ocr_nho.png"))
    hoa_img.save(str(SS_DIR / "_ocr_hoa.png"))
    lon_img.save(str(SS_DIR / "_ocr_lon.png"))

    # Nửa trái/phải (bắt đầu từ 40px — bỏ title bar)
    left  = img.crop((0,    40, mid+80, h))
    right = img.crop((mid-80, 40, w,   h))
    left  = ImageEnhance.Contrast(left.resize((left.width*2,   left.height*2),  Image.LANCZOS)).enhance(1.4)
    right = ImageEnhance.Contrast(right.resize((right.width*2, right.height*2), Image.LANCZOS)).enhance(1.4)

    left_path  = str(SS_DIR / "_ocr_left.png")
    right_path = str(SS_DIR / "_ocr_right.png")
    left.save(left_path); right.save(right_path)

    # OCR từng ô NHO/HOA/LON riêng
    nho_t = ocr_image(str(SS_DIR / "_ocr_nho.png"))
    hoa_t = ocr_image(str(SS_DIR / "_ocr_hoa.png"))
    lon_t = ocr_image(str(SS_DIR / "_ocr_lon.png"))
    size_text = f"NHO_CELL:{nho_t} ||| HOA_CELL:{hoa_t} ||| LON_CELL:{lon_t}"

    return size_text, ocr_image(left_path), ocr_image(right_path)

def parse_k(s: str) -> float:
    """Parse '1.080k' → 1080, '2.350k' → 2350, '880' → 880"""
    s = re.sub(r'[^\d.,]', '', s).replace(',', '.')
    if not s: return 0.0
    # Nếu có dấu chấm và phần sau chấm là 3 chữ số → đây là dấu phân cách ngàn
    parts = s.split('.')
    if len(parts) == 2 and len(parts[1]) == 3:
        return float(parts[0] + parts[1])  # 1.080 → 1080
    try:
        return float(s)
    except:
        return 0.0

def extract_all_amounts(text: str) -> list[float]:
    """Trích xuất tất cả giá trị tiền k từ OCR text."""
    results = []
    # Pattern: N.NNNk hoặc NNNk hoặc N.NNN
    for m in re.finditer(r'(\d{1,2}[.,]\d{3}|\d{3,4})(?:k\b)?', text, re.IGNORECASE):
        try:
            val = parse_k(m.group(1))
            if 10 <= val <= 9999:
                results.append(val)
        except:
            pass
    return results

def parse_size_bets(size_text: str) -> dict:
    """
    Parse riêng phần SIZE bets từ vùng NHO/HOA/LON.
    Pattern từ OCR thực tế:
      'NNNk ... NHO ... x1.5 ... NNNk ... HOA ... x2 ... NNNk ... LON'
    """
    bets = {}
    def first_amount(cell_text: str) -> float:
        """Lấy số tiền đầu tiên hợp lệ từ OCR của 1 ô SIZE."""
        cell_text = re.sub(r'\d{3,4}\*+\d{1,4}', '', cell_text)  # bỏ SĐT
        cell_text = re.sub(r'\d{8,}', '', cell_text)               # bỏ số dài
        for m in re.finditer(r'(\d{1,2}[.,]\d{3}|\d{2,4})', cell_text):
            v = parse_k(m.group(1))
            if 10 <= v <= 9999:
                return v
        return 0.0

    # Parse từng ô riêng (format: "NHO_CELL:... ||| HOA_CELL:... ||| LON_CELL:...")
    nho_part = re.search(r'NHO_CELL:(.*?)(?:\|\|\||$)', size_text, re.DOTALL)
    hoa_part = re.search(r'HOA_CELL:(.*?)(?:\|\|\||$)', size_text, re.DOTALL)
    lon_part = re.search(r'LON_CELL:(.*?)(?:\|\|\||$)', size_text, re.DOTALL)

    if nho_part:
        v = first_amount(nho_part.group(1))
        if v: bets['size_NHO'] = v
    if hoa_part:
        v = first_amount(hoa_part.group(1))
        if v: bets['size_HOA'] = v
    if lon_part:
        v = first_amount(lon_part.group(1))
        if v: bets['size_LON'] = v

    text = size_text.replace('\n', ' ')  # keep text for fallback patterns below

    # Tìm amount gần NHO (×1.5)
    for pat in [
        r'(\d{1,2}[.,]\d{3}|\d{2,4})\s*k?\s*(?:NHÖ|NHO|Nhö|nho)',
        r'(?:NHÖ|NHO|Nhö|nho)\s*(\d{1,2}[.,]\d{3}|\d{2,4})',
        r'(\d{1,2}[.,]\d{3}|\d{2,4})\s*k?\s*x1\.5',  # x1.5 gần NHO
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = parse_k(m.group(1))
            if val >= 10:
                bets['size_NHO'] = val
                break

    # Tìm amount gần HOA (×2)
    for pat in [
        r'(\d{1,2}[.,]\d{3}|\d{2,4})\s*k?\s*(?:HOA|Hoa|hoa)',
        r'(?:HOA|Hoa|hoa)\s*(\d{1,2}[.,]\d{3}|\d{2,4})',
        r'(\d{1,2}[.,]\d{3}|\d{2,4})\s*k?\s*x2\b',
        r'x2\s*(\d{1,2}[.,]\d{3}|\d{2,4})',
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = parse_k(m.group(1))
            if val >= 10:
                bets['size_HOA'] = val
                break

    # Tìm amount gần LON/LỚN (×1.5, lần 2)
    for pat in [
        r'(\d{1,2}[.,]\d{3}|\d{2,4})\s*k?\s*(?:LON|LÖN|Lon|lon|L.N)',
        r'(?:LON|LÖN|Lon|lon|L.N)\s*(\d{1,2}[.,]\d{3}|\d{2,4})',
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = parse_k(m.group(1))
            if val >= 10:
                bets['size_LON'] = val
                break

    # Fallback: lấy 3 số đầu tiên trong khoảng hợp lý (10-9999k)
    # nếu chưa có đủ 3 SIZE values
    if len([k for k in ['size_NHO','size_HOA','size_LON'] if k in bets]) < 3:
        amounts = re.findall(r'(\d{1,2}[.,]\d{3}|\d{2,4})k?', text, re.IGNORECASE)
        vals = []
        for a in amounts:
            v = parse_k(a)
            if 10 <= v <= 9999:
                vals.append(v)
        # 3 giá trị SIZE thường là 3 số đầu trong vùng SIZE (bỏ qua numbers quá giống nhau)
        unique_vals = []
        for v in vals:
            if not any(abs(v - u) < 5 for u in unique_vals):
                unique_vals.append(v)
            if len(unique_vals) >= 3:
                break
        if len(unique_vals) >= 3 and 'size_NHO' not in bets:
            bets.setdefault('size_NHO', unique_vals[0])
            bets.setdefault('size_HOA', unique_vals[1])
            bets.setdefault('size_LON', unique_vals[2])

    return bets

def parse_bets_from_ocr(left_text: str, right_text: str, size_text: str = '') -> dict:
    """
    Parse OCR text dựa trên pattern thực tế:
    - 'NNNk N' → amount sum_N
    - 'NNNk ooo' → triple amount
    - 'NNNk x7.5' hoặc gần MÖT/HAI → double/single amount
    """
    full = (left_text + " " + right_text).replace('\n', ' ')
    bets = {}

    # Parse SIZE bets từ vùng riêng
    if size_text:
        size_bets = parse_size_bets(size_text)
        bets.update(size_bets)
        if size_bets:
            print(f"  SIZE: {size_bets}")

    # Chuẩn hoá
    full = re.sub(r'\s+', ' ', full)

    # ── 1. Sum bets: pattern "NNNk N" hoặc "N NNNk" với N là số 3-18 ──
    # Tìm tất cả amounts trong text
    amt_pattern = r'(\d{1,2}[.,]\d{3}|\d{2,4})k?'

    # Tìm pattern "amount số" hoặc "số amount" cho sum 3-18
    for s in range(3, 19):
        # Pattern: "Nk S" hoặc "N.NNNk S" với S là số tổng
        # Dùng word boundary để tránh match sai
        for pat in [
            rf'(\d{{1,2}}[.,]\d{{3}}|\d{{2,4}})[k\s]{{0,3}}\b{s}\b',
            rf'\b{s}\b[k\s]{{0,3}}(\d{{1,2}}[.,]\d{{3}}|\d{{2,4}})',
        ]:
            m = re.search(pat, full)
            if m:
                val_str = m.group(1) if m.lastindex >= 1 and m.group(1) else ''
                if val_str:
                    val = parse_k(val_str)
                    if val >= 10:  # ít nhất 10k
                        bets[f'sum_{s}'] = val
                        break

    # ── 2. Triples: pattern "NNNk ooo" hoặc "ooo NNNk" ──
    triple_matches = re.findall(
        r'(?:(\d{1,2}[.,]\d{3}|\d{2,4})k?\s*(?:ooo?|oo0|o0o|000)|(?:ooo?|oo0|o0o|000)\s*(\d{1,2}[.,]\d{3}|\d{2,4})k?)',
        full, re.IGNORECASE)
    triple_vals = []
    for m in triple_matches:
        val_str = m[0] or m[1]
        if val_str:
            val = parse_k(val_str)
            if val >= 10:
                triple_vals.append(val)
    for i, val in enumerate(triple_vals[:6], 1):
        bets[f'triple_{i}'] = val

    # ── 3. SIZE bets: NHO/HOA/LON ──
    for label, key in [('NHO','size_NHO'),('HOA','size_HOA'),('LON','size_LON')]:
        for pat in [
            rf'(\d{{1,2}}[.,]\d{{3}}|\d{{3,4}})\s*k?\s*{label}',
            rf'{label}\s*(\d{{1,2}}[.,]\d{{3}}|\d{{3,4}})',
        ]:
            m = re.search(pat, full, re.IGNORECASE)
            if m:
                val = parse_k(m.group(1))
                if val >= 10:
                    bets[key] = val
                    break

    # ── 4. Doubles: x7.5 ──
    double_matches = re.findall(r'(\d{1,2}[.,]\d{3}|\d{2,4})k?\s*(?:x7\.5|×7\.5)', full, re.IGNORECASE)
    for i, m in enumerate(double_matches[:6], 1):
        val = parse_k(m)
        if val >= 10:
            bets[f'double_{i}'] = val

    # ── 5. Singles (MÖT/HAI/BA/BÖN/NÄM/SÁU) ──
    single_map = [('M.T|MOT|MÖT','single_1'),('HAI','single_2'),('BA','single_3'),
                  ('B.N|BON|BÖN','single_4'),('NAM|NÄM','single_5'),('SAU|SÁU','single_6')]
    for label_pat, key in single_map:
        m = re.search(rf'(\d{{1,2}}[.,]\d{{3}}|\d{{2,4}})k?\s*(?:{label_pat})|(?:{label_pat})\s*(\d{{1,2}}[.,]\d{{3}}|\d{{2,4}})',
                      full, re.IGNORECASE)
        if m:
            val_str = m.group(1) or (m.group(2) if m.lastindex >= 2 else '')
            if val_str:
                val = parse_k(val_str)
                if val >= 5:
                    bets[key] = val

    bets['_ocr_left']  = left_text[:300]
    bets['_ocr_right'] = right_text[:300]

    n_parsed = sum(1 for k in bets if not k.startswith('_'))
    print(f"  Parsed {n_parsed} bet values: {[k for k in bets if not k.startswith('_')][:10]}")
    return bets

# ── Tính toán 56 combo ────────────────────────────────────────────────────────
def tinh_loi(bets: dict, combo: tuple) -> float:
    a, b, c = combo
    tong = a + b + c
    dem  = {i: combo.count(i) for i in range(1,7)}
    size = "NHO" if tong<=9 else ("HOA" if tong<=11 else "LON")

    pool = sum(v for k,v in bets.items()
               if isinstance(v,(int,float)) and not k.startswith('_'))
    tra  = 0.0
    tra += bets.get(f'size_{size}', 0) * TY_LE_SIZE[size]
    tra += bets.get(f'sum_{tong}',  0) * TY_LE_TONG.get(tong,1)
    if a == b == c:
        tra += bets.get(f'triple_{a}', 0) * TY_LE_TRIPLE
        tra += bets.get('triple_any',  0) * TY_LE_TRIPLE_ANY
    for n in range(1,7):
        if dem[n] == 2:
            tra += bets.get(f'double_{n}', 0) * TY_LE_DOUBLE
    return pool - tra

def rank_all(bets: dict) -> list:
    results = []
    for combo in combinations_with_replacement(range(1,7), 3):
        loi = tinh_loi(bets, combo)
        results.append({'combo': combo, 'loi': loi})
    results.sort(key=lambda x: -x['loi'])
    return results

# ── Database ──────────────────────────────────────────────────────────────────
def init_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_FILE)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS captures (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at  TEXT,
            img_path     TEXT,
            ocr_left     TEXT,
            ocr_right    TEXT,
            bets_json    TEXT,
            pool_k       REAL,
            best_combo   TEXT,
            best_loi_k   REAL,
            worst_combo  TEXT,
            worst_loi_k  REAL,
            -- Kết quả (cập nhật sau)
            result_n1    INTEGER,
            result_n2    INTEGER,
            result_n3    INTEGER,
            result_tong  INTEGER,
            result_size  TEXT,
            result_rank  INTEGER
        );
    """)
    con.commit()
    return con

def save_capture(con, ts, img_path, left_text, right_text, bets, ranking, size_text=''):
    pool = sum(v for k,v in bets.items()
               if isinstance(v,(int,float)) and not k.startswith('_'))
    best  = ranking[0]
    worst = ranking[-1]
    bets_clean = {k:v for k,v in bets.items() if not k.startswith('_')}
    con.execute("""
        INSERT INTO captures
        (captured_at, img_path, ocr_left, ocr_right, bets_json,
         pool_k, best_combo, best_loi_k, worst_combo, worst_loi_k)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        ts, img_path,
        left_text[:500], right_text[:500],
        json.dumps(bets_clean),
        pool,
        str(best['combo']),  best['loi'],
        str(worst['combo']), worst['loi'],
    ))
    con.commit()

# ── Lấy kết quả từ Supabase ──────────────────────────────────────────────────
def fetch_and_save_results(con: sqlite3.Connection):
    """
    Lấy các draw mới nhất từ Supabase, ghép với captures chưa có kết quả.
    Mỗi capture khớp với draw xảy ra TRONG VÒNG 6 phút SAU khi capture.
    """
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from database import DatabaseManager
        db = DatabaseManager()
        recent = db.get_recent_draws(50)   # lấy 50 draw gần nhất
    except Exception as e:
        print(f"  [result] Không lấy được từ Supabase: {e}")
        return 0

    # Captures chưa có kết quả hoặc có result nhưng chưa có rank
    pending = con.execute("""
        SELECT id, captured_at, bets_json FROM captures
        WHERE (result_n1 IS NULL OR result_rank IS NULL) AND pool_k > 500
        ORDER BY id DESC LIMIT 20
    """).fetchall()

    if not pending:
        return 0

    updated = 0
    for cap_id, cap_at_str, bets_json in pending:
        try:
            cap_at = datetime.fromisoformat(cap_at_str.replace('Z','+00:00'))
            if cap_at.tzinfo is None:
                from datetime import timezone as _tz
                cap_at = cap_at.replace(tzinfo=_tz.utc)
        except Exception:
            continue

        # Tìm draw xảy ra 0-7 phút sau khi capture
        for _, row in recent.iterrows():
            try:
                draw_time_str = str(row['draw_time'])
                draw_at = datetime.fromisoformat(draw_time_str.replace('Z','+00:00'))
                if draw_at.tzinfo is None:
                    from datetime import timezone as _tz
                    draw_at = draw_at.replace(tzinfo=_tz.utc)

                diff = (draw_at - cap_at).total_seconds()
                if 0 <= diff <= 420:   # 0–7 phút sau capture
                    nums = row['numbers']
                    if isinstance(nums, str):
                        import ast
                        nums = ast.literal_eval(nums)
                    n1, n2, n3 = sorted(nums)
                    tong = n1+n2+n3
                    size = row.get('size_category', 'NHO' if tong<=9 else ('HOA' if tong<=11 else 'LON'))

                    # Tính rank: vị trí combo thực tế trong danh sách lợi nhuận nhà cái
                    rank = None
                    if bets_json:
                        try:
                            bets = json.loads(bets_json)
                            ranking = rank_all(bets)
                            combo = tuple(sorted([n1, n2, n3]))
                            rank = next((i+1 for i, r in enumerate(ranking)
                                         if r['combo'] == combo), 56)
                        except Exception:
                            pass

                    con.execute("""
                        UPDATE captures SET
                            result_n1=?, result_n2=?, result_n3=?,
                            result_tong=?, result_size=?, result_rank=?
                        WHERE id=?
                    """, (n1, n2, n3, tong, size, rank, cap_id))
                    con.commit()
                    updated += 1
                    print(f"  [result] cap#{cap_id} → {n1}-{n2}-{n3} ({size}) rank#{rank} draw#{row['draw_number']}")
                    break
            except Exception:
                continue

    return updated


def backfill_ranks(con: sqlite3.Connection) -> int:
    """Tính result_rank cho captures đã có result_n1/n2/n3 nhưng chưa có rank."""
    rows = con.execute("""
        SELECT id, bets_json, result_n1, result_n2, result_n3
        FROM captures
        WHERE result_n1 IS NOT NULL AND result_rank IS NULL AND bets_json IS NOT NULL
    """).fetchall()

    updated = 0
    for cap_id, bets_json, n1, n2, n3 in rows:
        try:
            bets = json.loads(bets_json)
            ranking = rank_all(bets)
            combo = tuple(sorted([n1, n2, n3]))
            rank = next((i+1 for i, r in enumerate(ranking)
                         if r['combo'] == combo), 56)
            con.execute("UPDATE captures SET result_rank=? WHERE id=?", (rank, cap_id))
            updated += 1
        except Exception:
            continue
    con.commit()
    if updated:
        print(f"  [backfill] Đã tính rank cho {updated} capture cũ")
    return updated

# ── Báo cáo gian lận ──────────────────────────────────────────────────────────
def fraud_report(con):
    rows = con.execute("""
        SELECT bets_json, result_n1, result_n2, result_n3
        FROM captures
        WHERE result_n1 IS NOT NULL AND bets_json IS NOT NULL
    """).fetchall()

    if len(rows) < 10:
        print(f"  Cần ít nhất 10 phiên có kết quả (hiện có {len(rows)})")
        return

    total = len(rows)
    rank_sum = 0
    top10_count = 0

    for bets_json, n1, n2, n3 in rows:
        try:
            bets = json.loads(bets_json)
            combo = tuple(sorted([n1, n2, n3]))
            ranking = rank_all(bets)
            rank = next((i+1 for i,r in enumerate(ranking)
                         if r['combo'] == combo), 56)
            rank_sum += rank
            if rank <= 10:
                top10_count += 1
        except Exception:
            total -= 1

    if total == 0: return
    avg_rank = rank_sum / total
    top10_pct = top10_count / total * 100

    print(f"\n{'='*50}")
    print(f"BÁO CÁO GIAN LẬN — {total} phiên có kết quả")
    print(f"{'='*50}")
    print(f"  Rank trung bình: {avg_rank:.1f}  (ngẫu nhiên: ~28.5)")
    print(f"  Top-10 rate:    {top10_pct:.1f}%  (ngẫu nhiên: ~17.9%)")

    if avg_rank < 20 and top10_pct > 30:
        print(f"\n  ⚠️  NGHI NGỜ GIAN LẬN CAO!")
    elif avg_rank < 24:
        print(f"\n  ⚠️  Có dấu hiệu lệch nhẹ — cần thêm dữ liệu")
    else:
        print(f"\n  ✅ Chưa phát hiện gian lận rõ ràng")

# ── Đọc kết quả từ Telegram bot ──────────────────────────────────────────────
def capture_telegram_result() -> tuple[str|None, list[int]|None]:
    """
    Chụp cửa sổ Telegram BINGO18 bot, OCR đọc kết quả phiên vừa xổ.
    Trả về (ky_quay, [n1,n2,n3]) hoặc (None, None)
    """
    # Tìm Telegram BINGO18 window
    tg_hwnd = None
    def cb(hwnd, _):
        nonlocal tg_hwnd
        t = win32gui.GetWindowText(hwnd)
        if 'BINGO18' in t and ('Trans' in t or 'Bot' in t or 'bot' in t.lower()):
            tg_hwnd = hwnd
    win32gui.EnumWindows(cb, None)
    if not tg_hwnd:
        return None, None

    rect = win32gui.GetWindowRect(tg_hwnd)
    # Chỉ capture phần hiển thị (tránh off-screen)
    if rect[0] < -1000 or rect[1] < -1000:
        return None, None

    with mss.MSS() as sct:
        x1,y1,x2,y2 = rect
        region = {"left":max(0,x1),"top":max(0,y1),
                  "width":min(x2-x1,800),"height":min(y2-y1,600)}
        shot = sct.grab(region)
        img  = Image.frombytes('RGB', shot.size, shot.bgra, 'raw', 'BGRX')

    tg_path = str(SS_DIR / "_tg_capture.png")
    img.save(tg_path)

    try:
        text = ocr_image(tg_path)
        # Tìm pattern kết quả: "1-3-5" hoặc "1 - 3 - 5" hoặc "Kết quả: 1, 3, 5"
        m = re.search(r'(\d)\s*[-–]\s*(\d)\s*[-–]\s*(\d)', text)
        if m:
            nums = [int(m.group(1)), int(m.group(2)), int(m.group(3))]
            if all(1 <= n <= 6 for n in nums):
                return None, nums
    except Exception:
        pass
    return None, None

CAPTURE_BEFORE_DRAW = 90   # chụp trước kỳ quay X giây
MIN_WAIT = 60              # chờ tối thiểu sau mỗi capture (giây)
MAX_WAIT = 360             # chờ tối đa nếu không lấy được draw time

def smart_sleep():
    """
    Tính thời gian chờ để chụp đúng lúc — CAPTURE_BEFORE_DRAW giây trước
    kỳ tiếp theo dự kiến, dựa trên interval trung bình của các draw gần đây.
    """
    try:
        from database import DatabaseManager
        db = DatabaseManager()
        recent = db.get_recent_draws(5)
        if len(recent) < 2:
            raise ValueError("Không đủ draws")

        times = []
        for _, r in recent.iterrows():
            t = datetime.fromisoformat(str(r['draw_time']).replace('Z', '+00:00'))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            times.append(t)
        times.sort(reverse=True)

        intervals = [(times[i] - times[i+1]).total_seconds()
                     for i in range(min(4, len(times)-1))
                     if 60 < (times[i] - times[i+1]).total_seconds() < 600]
        avg_interval = sum(intervals) / len(intervals) if intervals else 360

        import datetime as _dt
        last_draw = times[0]
        next_draw_est = last_draw + _dt.timedelta(seconds=avg_interval)
        capture_target = next_draw_est - _dt.timedelta(seconds=CAPTURE_BEFORE_DRAW)

        now = datetime.now(timezone.utc)
        wait = (capture_target - now).total_seconds()
        wait = max(MIN_WAIT, min(wait, MAX_WAIT))

        print(f"  avg interval={avg_interval:.0f}s | next draw ~{next_draw_est.strftime('%H:%M:%S')} UTC")
        print(f"  Chờ {wait:.0f}s (chụp {CAPTURE_BEFORE_DRAW}s trước kỳ)...")
        time.sleep(wait)
    except Exception as e:
        print(f"  [smart_sleep] fallback {INTERVAL}s ({e})")
        time.sleep(INTERVAL)


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    con = init_db()
    print("Bingo18 OCR Fraud Detector khởi động")
    print(f"Board region: {BOARD_RECT}")
    print(f"Chụp {CAPTURE_BEFORE_DRAW}s trước kỳ quay | DB: {DB_FILE}")
    print("Ctrl+C để dừng và xuất báo cáo\n")

    capture_count = 0

    while True:
        try:
            now = datetime.now(timezone.utc)
            ts  = now.strftime("%Y%m%d_%H%M%S")
            print(f"\n[{now.strftime('%H:%M:%S')}] Chụp màn hình #{capture_count+1}...")

            # Chụp
            img, ts = capture_board()
            img_path = str(SS_DIR / f"bingo18_{ts}.png")
            img.save(img_path)
            print(f"  Saved: {Path(img_path).name} ({img.size[0]}x{img.size[1]})")

            # OCR (3 vùng)
            print("  OCR đang xử lý...")
            size_text, left_text, right_text = split_ocr(img)
            print(f"  SIZE: {size_text[:80].replace(chr(10),' ')}")
            print(f"  LEFT: {left_text[:60].replace(chr(10),' ')}")
            print(f"  RIGHT: {right_text[:60].replace(chr(10),' ')}")

            # Parse bets
            bets = parse_bets_from_ocr(left_text, right_text, size_text)

            # Tính ranking
            ranking = rank_all(bets)
            best  = ranking[0]
            worst = ranking[-1]
            pool  = sum(v for k,v in bets.items()
                       if isinstance(v,(int,float)) and not k.startswith('_'))

            print(f"\n  Pool: {pool:,.0f}k đ")
            print(f"  Nhà cái MUỐN: {best['combo']} (lời {best['loi']:,.0f}k)")
            print(f"  Nhà cái SỢ:   {worst['combo']} (lỗ {-worst['loi']:,.0f}k)")

            # Lưu DB (chỉ lưu nếu pool đủ lớn — tránh capture quá sớm)
            if pool >= 500:
                save_capture(con, now.isoformat(), img_path,
                            left_text, right_text, bets, ranking, size_text)
                capture_count += 1
                print(f"  → Lưu capture #{capture_count}")
            else:
                print(f"  → Bỏ qua (pool {pool:.0f}k < 500k — chụp quá sớm)")

            # Backfill rank cho captures đã có result nhưng chưa có rank
            backfill_ranks(con)

            # Lấy kết quả từ Supabase cho các capture cũ chưa có result
            n_updated = fetch_and_save_results(con)
            if n_updated:
                print(f"  → Cập nhật {n_updated} kết quả từ Supabase")

            # Báo cáo định kỳ
            if capture_count > 0 and capture_count % 50 == 0:
                fraud_report(con)

            # Chờ thông minh — chụp gần cuối window đặt cược
            smart_sleep()

        except KeyboardInterrupt:
            print("\n\nDừng — xuất báo cáo cuối...")
            fraud_report(con)
            break
        except Exception as e:
            import traceback
            print(f"  Lỗi: {e}")
            traceback.print_exc()
            time.sleep(30)

if __name__ == "__main__":
    main()
