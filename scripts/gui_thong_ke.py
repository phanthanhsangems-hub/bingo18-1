"""P301: gửi một tin tự soạn tới Telegram từ máy nhà. Token đọc từ .env, KHÔNG in ra.

Chạy (qua scripts\\gui_thong_ke.bat):  py -3.11 scripts\\gui_thong_ke.py [file_noi_dung]
Mặc định đọc scripts\\thong_ke.txt. Nội dung là HTML của Telegram (<b>, <i>).
"""
import os
import re
import sys

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIOI_HAN = 4096
_MAU = re.compile(r'\d{5,}:[A-Za-z0-9_-]{20,}')


def doc_env(ten: str) -> str:
    from dotenv import dotenv_values
    return (dotenv_values(os.path.join(GOC, '.env')).get(ten) or '').strip().strip('"').strip("'").strip()


def gui(tok: str, chat: str, noi_dung: str, goi=None) -> tuple:
    """(True, None) nếu Telegram nhận; (False, lý do không chứa token)."""
    if goi is None:
        import requests
        goi = lambda url, data: requests.post(url, json=data, timeout=15)
    try:
        r = goi(f"https://api.telegram.org/bot{tok}/sendMessage",
                {'chat_id': chat, 'text': noi_dung, 'parse_mode': 'HTML',
                 'disable_web_page_preview': True})
        j = r.json()
    except Exception as e:
        return False, f"không kết nối được Telegram: {type(e).__name__}"
    if j.get('ok'):
        return True, None
    return False, f"HTTP {r.status_code} {j.get('description')}"


def main(argv) -> int:
    duong = argv[0] if argv else os.path.join(GOC, 'scripts', 'thong_ke.txt')
    if not os.path.exists(duong):
        print(f"[LOI] Không thấy file nội dung: {duong}")
        print("      Tạo file đó (dán nội dung tin vào, lưu UTF-8) rồi chạy lại.")
        return 1
    with open(duong, encoding='utf-8-sig') as f:
        noi_dung = f.read().strip()
    if not noi_dung:
        print("[LOI] File nội dung trống.")
        return 1
    if len(noi_dung) > GIOI_HAN:
        print(f"[LOI] Nội dung {len(noi_dung)} ký tự, Telegram chỉ nhận {GIOI_HAN}. Rút gọn lại.")
        return 1
    tok = doc_env('TELEGRAM_BOT_TOKEN')
    chat = doc_env('TELEGRAM_CHAT_ID')
    if not tok or not chat:
        print("[LOI] .env thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID.")
        return 1
    ok, ly_do = gui(tok, chat, noi_dung)
    if ok:
        print(f"[OK] Đã gửi {len(noi_dung)} ký tự tới Telegram.")
        return 0
    print(f"[LOI] Telegram từ chối: {_MAU.sub('***', ly_do)}")
    if 'Unauthorized' in ly_do:
        print("      -> token trong .env sai/đã thu hồi: chạy py -3.11 scripts\\kiem_tra_telegram.py")
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
