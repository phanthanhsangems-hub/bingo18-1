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
call "%~dp0chon_python.bat"
:loop
>> logs\app_restart.log echo [%date% %time%] khoi dong app bang %PY%
%PY% chay_may.py
set MA=%errorlevel%
REM ">> file" dat TRUOC echo: "ma 2>> file" se bi CMD hieu la chuyen huong luong 2
>> logs\app_restart.log echo [%date% %time%] app thoat ma %MA%
REM ma 3 = cong 8080 dang co app khac chay -> cua so nay thoi, khong chay chong
if "%MA%"=="3" goto het
echo App thoat ma %MA% - chay lai sau 30 giay. Dong cua so de dung han.
timeout /t 30 /nobreak >nul
goto loop
:het
echo Cong 8080 dang ban - cua so nay dung lai sau 60 giay.
timeout /t 60 /nobreak >nul
