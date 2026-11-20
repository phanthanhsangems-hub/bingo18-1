@echo off
REM P298: chay app Bingo18 TREN MAY NHA (thay Cloud Run) + tu chay lai neu thoat.
REM Cai dat lan dau (mot lan):  scripts\cai_dat_may.bat
REM Dung app: DONG CUA SO NAY. KHONG dung "taskkill /F /IM python.exe" (chet ca watcher).
cd /d "%~dp0\.."
title Bingo18 App - may nha
REM Ma viet cho Cloud Run (gio he thong = UTC) -> bat buoc chay voi gio UTC
set TZ=UTC0
set PYTHONUTF8=1
if not exist logs mkdir logs
:loop
echo [%date% %time%] khoi dong app>> logs\app_restart.log
python chay_may.py
set MA=%errorlevel%
echo [%date% %time%] app thoat ma %MA%, chay lai sau 30s>> logs\app_restart.log
echo App thoat ma %MA% - chay lai sau 30 giay. Dong cua so de dung han.
timeout /t 30 /nobreak >nul
goto loop
