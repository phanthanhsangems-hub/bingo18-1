"""P298e: kiểm tra token Telegram trong .env — KHÔNG BAO GIỜ in token ra màn hình.

Chạy (trong thư mục bingo18):   py -3.11 scripts\\kiem_tra_telegram.py
In ra: token có đúng dạng không, Telegram có nhận token không (getMe), và gửi thử
một tin tới TELEGRAM_CHAT_ID. Kết quả dán cho người khác xem được (đã che token).
"""
import os
import re
import sys

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAU = re.compile(r'bot\d{5,}:[A-Za-z0-9_-]{20,}|\d{5,}:[A-Za-z0-9_-]{20,}')


def che(s) -> str:
    return _MAU.sub('***', str(s))


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(GOC, '.env'))
    except ImportError:
        print("Thieu python-dotenv -> chay scripts\\cai_dat_may.bat")
        return 2
    import requests
    tok = (os.environ.get('TELEGRAM_BOT_TOKEN') or '').strip().strip('"').strip("'")
    chat = (os.environ.get('TELEGRAM_CHAT_ID') or '').strip().strip('"').strip("'")
    if not tok:
        print("[LOI] .env khong co TELEGRAM_BOT_TOKEN")
        return 1
    dung_dang = re.fullmatch(r'\d{5,}:[A-Za-z0-9_-]{30,}', tok) is not None
    print(f"[{'OK' if dung_dang else 'LOI'}] Token dai {len(tok)} ky tu, "
          + ("dung dang <so>:<chuoi>" if dung_dang else "SAI DANG (thieu/du ky tu, co dau cach hay dau ngoac?)"))
    print(f"[{'OK' if chat else 'LOI'}] TELEGRAM_CHAT_ID " + ("co" if chat else "chua co trong .env"))
    s = requests.Session()
    try:
        r = s.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=15)
        j = r.json()
    except Exception as e:
        print(f"[LOI] Khong ket noi duoc Telegram: {type(e).__name__}: {che(e)[:200]}")
        print("      -> mang may nha / phan mem diet virus chan api.telegram.org")
        return 1
    if not j.get('ok'):
        print(f"[LOI] Telegram tu choi token: HTTP {r.status_code} {j.get('description')}")
        if r.status_code == 401:
            print("      -> token trong .env la token CU (da /revoke) hoac go sai. Lay token moi:")
            print("         Telegram -> @BotFather -> /mybots -> chon bot -> API Token")
        return 1
    print(f"[OK] Token hop le: bot @{j['result'].get('username')}")
    if not chat:
        return 1
    try:
        r = s.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                   json={'chat_id': chat, 'text': 'Kiem tra Telegram tu may nha: OK'}, timeout=15)
        j = r.json()
    except Exception as e:
        print(f"[LOI] Gui thu loi: {type(e).__name__}: {che(e)[:200]}")
        return 1
    if j.get('ok'):
        print("[OK] Da gui thu 1 tin - kiem tra Telegram xem co nhan duoc khong")
        return 0
    print(f"[LOI] Gui thu bi tu choi: HTTP {r.status_code} {j.get('description')}")
    if r.status_code in (400, 403):
        print("      -> TELEGRAM_CHAT_ID sai, hoac chua bam Start voi bot moi / bot bi go khoi nhom")
    return 1


if __name__ == '__main__':
    sys.exit(main())
