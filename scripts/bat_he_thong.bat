@echo off
REM P300: BAT he thong Bingo18 tren may nha = app (du doan + dashboard + bao cao 23:55)
REM       va watcher (lay ket qua Vietlott + tin Telegram moi ky).
REM Go trong CMD hoac PowerShell, tai thu muc bingo18:   scripts\bat_he_thong.bat
REM Cai nao dang chay roi thi khong mo them.
setlocal
cd /d "%~dp0\.."
call "%~dp0dem_tien_trinh.bat" chay_may.py
if errorlevel 1 (
  echo [BAT] App dang chay roi - khong mo them.
) else (
  start "Bingo18 App" "%~dp0chay_app_may.bat"
  echo [BAT] Da mo app - cua so "Bingo18 App", de nguyen dung dong.
)
call "%~dp0dem_tien_trinh.bat" sync_to_supabase
if errorlevel 1 (
  echo [BAT] Watcher dang chay roi - khong mo them.
) else (
  schtasks /Run /TN Bingo18Watcher >nul 2>&1
  if errorlevel 1 start "Bingo18 Watcher" "%~dp0start_watcher.bat"
  echo [BAT] Da mo watcher.
)
echo.
echo Khoang 1 phut sau go:  scripts\trang_thai.bat   de kiem tra.
