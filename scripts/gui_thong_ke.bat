@echo off
REM P301: gui mot tin tu soan toi Telegram tu may nha.
REM   1. Dan noi dung tin vao scripts\thong_ke.txt (UTF-8, co the dung <b> <i>).
REM   2. Chay:  scripts\gui_thong_ke.bat
REM   Gui file khac:  scripts\gui_thong_ke.bat duong_dan\file.txt
REM Token doc tu .env, khong hien ra man hinh.
setlocal
cd /d "%~dp0\.."
call "%~dp0chon_python.bat"
%PY% scripts\gui_thong_ke.py %*
echo.
pause
