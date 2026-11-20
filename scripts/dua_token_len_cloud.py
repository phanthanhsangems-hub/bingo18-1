"""P298f: đưa TELEGRAM_BOT_TOKEN trong .env lên Cloud Run — token KHÔNG hiện ra màn hình.

20/11: gõ token thẳng vào lệnh gcloud rồi dán cả lệnh vào chat -> lộ token lần nữa.
Script này đọc token từ .env, gọi gcloud với --update-env-vars (KHÔNG BAO GIỜ
--set-env-vars: lệnh đó xoá sạch DATABASE_URL, secret... của service) và chỉ in
kết quả đã che token.

Chạy (trong thư mục bingo18, sau khi đã sửa .env):
    py -3.11 scripts\\dua_token_len_cloud.py
"""
import os
import re
import shutil
import subprocess
import sys

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAU = re.compile(r'\d{5,}:[A-Za-z0-9_-]{20,}')
DICH_VU = ['run', 'services', 'update', 'bingo18', '--region', 'asia-southeast1',
           '--project', 'bingo18-predictor']


def doc_token(duong_dan: str) -> str:
    from dotenv import dotenv_values
    return (dotenv_values(duong_dan).get('TELEGRAM_BOT_TOKEN') or '').strip().strip('"').strip("'").strip()


def token_hop_le(tok: str):
    """(True, ten bot) nếu Telegram nhận token (getMe), ngược lại (False, lý do — không chứa token)."""
    import requests
    try:
        r = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=15)
        j = r.json()
    except Exception as e:
        return False, f"khong ket noi duoc Telegram: {type(e).__name__}"
    if j.get('ok'):
        return True, '@' + str((j.get('result') or {}).get('username'))
    return False, f"HTTP {r.status_code} {j.get('description')}"


def main() -> int:
    tok = doc_token(os.path.join(GOC, '.env'))
    if not re.fullmatch(r'\d{5,}:[A-Za-z0-9_-]{30,}', tok or ''):
        print("[LOI] TELEGRAM_BOT_TOKEN trong .env trong hoac sai dang -> sua .env truoc "
              "(chay py -3.11 scripts\\kiem_tra_telegram.py de kiem tra)")
        return 1
    # P298g: 20/11 đưa lên cả token đã bị thu hồi (kiem_tra_telegram báo 401) -> Cloud Run
    # cũng hỏng theo. Hỏi Telegram trước; token không dùng được thì KHÔNG đưa lên.
    hop_le, ly_do = token_hop_le(tok)
    if not hop_le:
        print(f"[LOI] Telegram khong nhan token trong .env ({ly_do}) -> KHONG dua len Cloud Run.")
        print("      Lay token dang dung: Telegram -> @BotFather -> /mybots -> chon bot -> API Token,")
        print("      sua .env, chay py -3.11 scripts\\kiem_tra_telegram.py thay [OK] roi moi chay lai file nay.")
        return 1
    gcloud = shutil.which('gcloud') or shutil.which('gcloud.cmd')
    if not gcloud:
        print("[LOI] Khong tim thay lenh gcloud tren may")
        return 1
    print("Dang cap nhat TELEGRAM_BOT_TOKEN tren Cloud Run (token lay tu .env, khong in ra)...", flush=True)
    r = subprocess.run([gcloud] + DICH_VU + ['--update-env-vars', f'TELEGRAM_BOT_TOKEN={tok}', '--quiet'],
                       capture_output=True, text=True)
    ra = _MAU.sub('***', (r.stdout or '') + (r.stderr or ''))
    print('\n'.join(l for l in ra.splitlines() if l.strip())[-1500:])
    print("XONG - Cloud Run da dung token trong .env" if r.returncode == 0 else f"[LOI] gcloud tra ma {r.returncode}")
    return 0 if r.returncode == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
