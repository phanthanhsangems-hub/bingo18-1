@echo off
REM P298: cai dat MOT LAN de chay app tren may nha (thay Cloud Run).
REM Mo CMD, vao thu muc bingo18 roi go:   scripts\cai_dat_may.bat
REM (Mo CMD bang "Run as administrator" thi file nay mo luon cong 8080 cho dien thoai.)
setlocal
cd /d "%~dp0\.."
echo === 1/4 Cai thu vien (requirements.txt + waitress + tzdata) ===
python -m pip install -r requirements-may.txt
if errorlevel 1 (
  echo LOI cai thu vien - xem thong bao o tren.
  pause
  exit /b 1
)
echo.
echo === 2/4 Kiem tra cai dat + chay thu 1 vong du doan ===
set TZ=UTC0
set PYTHONUTF8=1
python chay_may.py --kiem-tra
if errorlevel 1 (
  echo KIEM TRA CHUA DAT - sua theo thong bao o tren roi chay lai file nay.
  pause
  exit /b 1
)
echo.
echo === 3/4 Tu chay app moi khi dang nhap Windows ===
schtasks /Create /TN Bingo18App /SC ONLOGON /F /TR "\"%CD%\scripts\chay_app_may.bat\""
echo.
echo === 4/4 Mo cong 8080 cho dien thoai cung Wi-Fi (can quyen Administrator) ===
netsh advfirewall firewall delete rule name="Bingo18 App 8080" >nul 2>&1
netsh advfirewall firewall add rule name="Bingo18 App 8080" dir=in action=allow protocol=TCP localport=8080 profile=private >nul 2>&1
if errorlevel 1 (
  echo Khong co quyen Administrator - lan dau chay app, Windows hoi thi bam "Allow access".
) else (
  echo Da mo cong 8080.
)
echo.
echo XONG. Chay app ngay bang lenh:  schtasks /Run /TN Bingo18App
pause
