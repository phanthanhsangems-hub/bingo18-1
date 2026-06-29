"""
Thu thập dữ liệu tiền cược NHỎ/HÒA/LỚN từ màn hình LonelyScreen
Chạy sau khi iPhone đã AirPlay sang PC qua LonelyScreen

Bước 1: python collect_bet_data.py --calibrate   (chọn vùng màn hình)
Bước 2: python collect_bet_data.py --collect      (thu thập tự động)
Bước 3: python collect_bet_data.py --analyze      (phân tích kết quả)
"""
import sys
import time
import json
import re
import os
import csv
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ImageGrab, ImageEnhance, ImageFilter
    import pytesseract
except ImportError:
    print("Thiếu thư viện. Chạy: pip install pillow pytesseract")
    sys.exit(1)

# Tesseract path trên Windows
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

DATA_FILE = Path(__file__).parent / "bet_data.csv"
CONFIG_FILE = Path(__file__).parent / "ocr_config.json"

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"Config đã lưu: {CONFIG_FILE}")

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return None

def capture_region(bbox):
    """Chụp vùng màn hình bbox=(left, top, right, bottom)"""
    img = ImageGrab.grab(bbox=bbox)
    return img

def preprocess_for_ocr(img):
    """Tăng contrast để OCR đọc số tốt hơn"""
    img = img.convert('L')  # grayscale
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(3.0)
    img = img.filter(ImageFilter.SHARPEN)
    return img

def read_number(img):
    """OCR đọc số từ ảnh, trả về số nguyên (đơn vị nghìn đồng)"""
    img = preprocess_for_ocr(img)
    text = pytesseract.image_to_string(img, config='--psm 7 -c tessedit_char_whitelist=0123456789.,k')
    text = text.strip().lower()
    # Parse: "220k" → 220000, "1,040k" → 1040000, "220" → 220000
    text = text.replace(',', '').replace('.', '')
    if 'k' in text:
        text = text.replace('k', '')
        try: return int(float(text) * 1000)
        except: return None
    try: return int(text) * 1000  # assume đơn vị là nghìn
    except: return None

def calibrate():
    """Hướng dẫn người dùng chọn vùng màn hình"""
    print("\n=== CALIBRATION ===")
    print("Đảm bảo LonelyScreen đang hiện màn hình Bingo18")
    print("Nhập tọa độ (left, top, right, bottom) cho mỗi vùng số tiền")
    print("Tip: Dùng Snipping Tool → hover chuột để xem tọa độ pixel\n")

    config = {}
    for label in ['NHO', 'HOA', 'LON', 'DRAW_ID']:
        print(f"Vùng {label} (ví dụ: 100 200 180 220):", end=' ')
        coords = input().strip().split()
        config[label] = [int(x) for x in coords]
        # Test ngay
        img = capture_region(tuple(config[label]))
        img_p = preprocess_for_ocr(img)
        text = pytesseract.image_to_string(img_p, config='--psm 7')
        print(f"  OCR đọc được: '{text.strip()}'")

    save_config(config)
    print("\nCalibration xong! Chạy: python collect_bet_data.py --collect")

def collect_once(config):
    """Thu thập 1 lần, trả về dict hoặc None"""
    try:
        nho_img = capture_region(tuple(config['NHO']))
        hoa_img = capture_region(tuple(config['HOA']))
        lon_img = capture_region(tuple(config['LON']))
        draw_img = capture_region(tuple(config['DRAW_ID']))

        nho = read_number(nho_img)
        hoa = read_number(hoa_img)
        lon = read_number(lon_img)

        draw_text = pytesseract.image_to_string(preprocess_for_ocr(draw_img), config='--psm 7')
        draw_id = re.sub(r'[^0-9]', '', draw_text.strip())

        if not all([nho, hoa, lon, draw_id]):
            return None

        return {
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'draw_id': draw_id,
            'nho': nho,
            'hoa': hoa,
            'lon': lon,
            'min_bet': min(nho, hoa, lon),
            'min_outcome': ['NHO', 'HOA', 'LON'][[nho, hoa, lon].index(min(nho, hoa, lon))]
        }
    except Exception as e:
        print(f"Lỗi: {e}")
        return None

def collect_loop(config, interval=300):
    """Thu thập tự động mỗi interval giây (mặc định 5 phút = trước kỳ quay)"""
    print(f"Bắt đầu thu thập, lưu vào {DATA_FILE}")
    print("Nhấn Ctrl+C để dừng\n")

    if not DATA_FILE.exists():
        with open(DATA_FILE, 'w', newline='') as f:
            csv.writer(f).writerow(['time', 'draw_id', 'nho', 'hoa', 'lon', 'min_bet', 'min_outcome'])

    while True:
        data = collect_once(config)
        if data:
            with open(DATA_FILE, 'a', newline='') as f:
                csv.writer(f).writerow(list(data.values()))
            print(f"{data['time']} | Kỳ {data['draw_id']} | NHO={data['nho']//1000}k HOA={data['hoa']//1000}k LON={data['lon']//1000}k | MIN={data['min_outcome']}")
        else:
            print(f"{datetime.now().strftime('%H:%M:%S')} | Không đọc được — kiểm tra LonelyScreen")

        time.sleep(interval)

def analyze():
    """Phân tích: cược ít nhất có thường thắng hơn không?"""
    if not DATA_FILE.exists():
        print("Chưa có data. Chạy --collect trước.")
        return

    import pandas as pd
    from dotenv import load_dotenv
    load_dotenv()
    from database import DatabaseManager

    df = pd.read_csv(DATA_FILE)
    print(f"Tổng số kỳ đã thu thập: {len(df)}")

    # Join với kết quả thực tế từ DB
    db = DatabaseManager()
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT draw_number::text, size_category FROM draw_history ORDER BY draw_number")
    results = {r[0]: r[1] for r in cur.fetchall()}
    conn.close()

    df['actual'] = df['draw_id'].map(results)
    df = df.dropna(subset=['actual'])
    print(f"Kỳ có kết quả thực tế: {len(df)}")

    if len(df) < 10:
        print("Cần thêm data. Tiếp tục chạy --collect")
        return

    # Phân tích: min_outcome == actual bao nhiêu lần?
    df['house_picked_min'] = df['min_outcome'] == df['actual']
    rate = df['house_picked_min'].mean() * 100
    expected = 33.3  # ngẫu nhiên

    print(f"\n=== KẾT QUẢ PHÂN TÍCH ===")
    print(f"Tỉ lệ nhà cái chọn outcome ÍT CỬA NHẤT: {rate:.1f}%")
    print(f"Kỳ vọng ngẫu nhiên: {expected:.1f}%")

    if rate > expected + 5:
        print(f"*** ĐÁNG NGỜ: Outcome ít cược thắng nhiều hơn kỳ vọng {rate-expected:.1f}%!")
    elif rate < expected - 5:
        print(f"Outcome ít cược thắng ÍT hơn kỳ vọng — không có dấu hiệu gian lận theo hướng này")
    else:
        print(f"Kết quả trong phạm vi ngẫu nhiên — không có dấu hiệu gian lận rõ ràng")

    # Chi-square test
    from scipy import stats
    obs = df['house_picked_min'].sum()
    n = len(df)
    chi2, p = stats.binom_test(obs, n, 1/3), None
    p = stats.binom_test(obs, n, 1/3)
    print(f"p-value (binomial test): {p:.4f}")
    if p < 0.05:
        print("*** p < 0.05: Có ý nghĩa thống kê!")

if __name__ == '__main__':
    if '--calibrate' in sys.argv:
        calibrate()
    elif '--collect' in sys.argv:
        config = load_config()
        if not config:
            print("Chưa có config. Chạy: python collect_bet_data.py --calibrate")
        else:
            collect_loop(config)
    elif '--analyze' in sys.argv:
        analyze()
    else:
        print("Usage:")
        print("  python collect_bet_data.py --calibrate   # Chọn vùng màn hình")
        print("  python collect_bet_data.py --collect     # Thu thập tự động")
        print("  python collect_bet_data.py --analyze     # Phân tích kết quả")
