@echo off
REM P261: tu khoi dong watcher khi dang nhap Windows + tu chay lai neu thoat.
REM Dang ky mot lan (PowerShell, trong thu muc bingo18-moi):
REM   schtasks /Create /TN Bingo18Watcher /SC ONLOGON /F /TR "%CD%\scripts\start_watcher.bat"
REM   powercfg /change standby-timeout-ac 0
REM   powercfg /change hibernate-timeout-ac 0
REM Chay ngay khong can dang xuat:  schtasks /Run /TN Bingo18Watcher
cd /d "%~dp0\.."
:loop
echo [%date% %time%] khoi dong watcher>> watcher_restart.log
python sync_to_supabase.py --mode watch
echo [%date% %time%] watcher thoat, chay lai sau 30s>> watcher_restart.log
timeout /t 30 /nobreak >nul
goto loop
