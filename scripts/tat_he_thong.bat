@echo off
REM P300: TAT he thong Bingo18 tren may nha. Chi tat dung tien trinh cua Bingo18 (tim theo
REM dong lenh) - KHONG dung "taskkill /IM python.exe".
REM   scripts\tat_he_thong.bat            tat ca app lan watcher
REM   scripts\tat_he_thong.bat app        chi tat app
REM   scripts\tat_he_thong.bat watcher    chi tat watcher
REM Tat cua so vong lap (.bat) TRUOC roi moi tat Python, de no khong tu chay lai sau 30 giay.
REM Lan dang nhap Windows sau app + watcher tu chay lai nhu thuong.
setlocal
set "AI=%~1"
if /i "%AI%"=="app" goto chi_app
if /i "%AI%"=="watcher" goto chi_watcher
call :tat chay_app_may.bat chay_may.py
call :tat start_watcher.bat sync_to_supabase
goto xong
:chi_app
call :tat chay_app_may.bat chay_may.py
goto xong
:chi_watcher
call :tat start_watcher.bat sync_to_supabase
goto xong
:tat
powershell -NoProfile -Command "$ds = @(Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*%~1*') -or ($_.Name -like 'py*' -and $_.CommandLine -like '*%~2*') }); if ($ds.Count -eq 0) { '[TAT] %~2 khong chay' } else { $ds | Sort-Object { if ($_.Name -eq 'cmd.exe') { 0 } else { 1 } } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; '[TAT] ' + $_.Name + ' PID ' + $_.ProcessId } }"
exit /b 0
:xong
echo.
echo Bat lai:  scripts\bat_he_thong.bat
