@echo off
REM P298: cai dat MOT LAN de chay app tren may nha (thay Cloud Run).
REM Mo CMD, vao thu muc bingo18 roi go:   scripts\cai_dat_may.bat
REM Mo CMD bang "Run as administrator" thi file nay mo luon cong 8080 cho dien thoai.
setlocal
cd /d "%~dp0\.."
call "%~dp0chon_python.bat"
echo Dung Python: %PY%
%PY% --version
echo.
echo === 1/5 Cai thu vien (requirements.txt + waitress + tzdata) ===
%PY% -m pip install -r requirements-may.txt
if errorlevel 1 (
  echo LOI cai thu vien - xem thong bao o tren.
  pause
  exit /b 1
)
echo.
echo === 2/5 Kiem tra cai dat + chay thu 1 vong du doan ===
set TZ=UTC0
set PYTHONUTF8=1
%PY% chay_may.py --kiem-tra
if errorlevel 1 (
  echo KIEM TRA CHUA DAT - sua theo thong bao o tren roi chay lai file nay.
  pause
  exit /b 1
)
echo.
echo === 3/5 Tu chay app moi khi dang nhap Windows ===
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
schtasks /Create /TN Bingo18App /SC ONLOGON /F /TR "\"%CD%\scripts\chay_app_may.bat\"" >nul 2>&1
if errorlevel 1 goto startup
if exist "%STARTUP%\Bingo18App.bat" del "%STARTUP%\Bingo18App.bat"
echo Da dang ky tac vu Bingo18App.
goto tuong_lua
:startup
> "%STARTUP%\Bingo18App.bat" echo @start "Bingo18 App" "%CD%\scripts\chay_app_may.bat"
echo Khong co quyen Administrator - da dat Bingo18App.bat vao thu muc Startup cua Windows.
:tuong_lua
echo.
echo === 4/5 Mo cong 8080 cho dien thoai cung Wi-Fi ===
netsh advfirewall firewall delete rule name="Bingo18 App 8080" >nul 2>&1
netsh advfirewall firewall add rule name="Bingo18 App 8080" dir=in action=allow protocol=TCP localport=8080 profile=private >nul 2>&1
if errorlevel 1 (
  echo Khong co quyen Administrator - lan dau chay app, Windows hoi thi bam "Allow access".
) else (
  echo Da mo cong 8080.
)
echo.
echo === 5/5 Chay app ngay ===
start "Bingo18 App" "%CD%\scripts\chay_app_may.bat"
echo XONG. Cua so "Bingo18 App" vua mo ra - de nguyen, KHONG dong.
pause
