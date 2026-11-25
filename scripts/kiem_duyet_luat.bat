@echo off
REM P305: cong kiem duyet luat du doan moi - chay RIENG, khong dung toi app / DB dang chay.
REM   scripts\kiem_duyet_luat.bat --luat nong_30
REM   scripts\kiem_duyet_luat.bat --luat duong\dan\luat_cua_toi.py:ten_ham --so-phep-thu 20
REM   scripts\kiem_duyet_luat.bat --danh-sach
REM Ma thoat: 0 = qua cong, 1 = khong qua, 2 = khong chay duoc. Xem chi tiet o dau file kiem_duyet_luat.py.
setlocal
cd /d "%~dp0\.."
call "%~dp0chon_python.bat"
%PY% kiem_duyet_luat.py %*
echo.
pause
