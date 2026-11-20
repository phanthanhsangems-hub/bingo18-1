@echo off
REM P300: tra errorlevel 1 neu dang co tien trinh Python chay "%1" (chay_may.py / sync_to_supabase).
REM Dung trong bat_he_thong.bat. Tim theo DONG LENH, khong dung "taskkill /IM python.exe".
powershell -NoProfile -Command "if (Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'py*' -and $_.CommandLine -like '*%~1*' }) { exit 1 } else { exit 0 }"
