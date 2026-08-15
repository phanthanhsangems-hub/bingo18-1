"""Sinh APP_PASSWORD_HASH cho đăng nhập dashboard (P183).

Dùng khi không muốn để mật khẩu dạng thô trong biến môi trường Cloud Run.

    python scripts/tao_mat_khau.py

Script hỏi mật khẩu (không hiện lên màn hình), in ra chuỗi hash và câu
lệnh gcloud để dán. Mật khẩu thật không bao giờ rời khỏi máy bạn.
"""
import getpass
import sys

from werkzeug.security import generate_password_hash


def main():
    pw1 = getpass.getpass("Mat khau moi: ")
    if len(pw1) < 8:
        print("Mat khau qua ngan — can it nhat 8 ky tu.")
        sys.exit(1)
    pw2 = getpass.getpass("Nhap lai:     ")
    if pw1 != pw2:
        print("Hai lan nhap khong khop.")
        sys.exit(1)

    h = generate_password_hash(pw1)

    print("\nAPP_PASSWORD_HASH:")
    print(h)
    print("\nDan lenh nay (thay TEN_DANG_NHAP bang ten ban muon):\n")
    print(
        "gcloud run services update bingo18 "
        "--region asia-southeast1 --project bingo18-predictor "
        f'--update-env-vars "APP_USER=TEN_DANG_NHAP,APP_PASSWORD_HASH={h}"'
    )
    print("\nLuu y: neu truoc do da dat APP_PASSWORD dang tho thi go di:")
    print(
        "gcloud run services update bingo18 "
        "--region asia-southeast1 --project bingo18-predictor "
        "--remove-env-vars APP_PASSWORD"
    )


if __name__ == "__main__":
    main()
