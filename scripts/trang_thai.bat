@echo off
REM P300: xem he thong Bingo18 tren may nha co dang chay khong.
REM Go trong CMD hoac PowerShell, tai thu muc bingo18:   scripts\trang_thai.bat
setlocal
cd /d "%~dp0\.."
echo === Tien trinh ===
powershell -NoProfile -Command "$ds = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' }); foreach ($t in @('chay_may.py', 'sync_to_supabase')) { $c = @($ds | Where-Object { $_.CommandLine -like ('*' + $t + '*') }); $ten = if ($t -eq 'chay_may.py') { 'App    ' } else { 'Watcher' }; if ($c.Count -eq 0) { $ten + ': TAT' } else { $ten + ': DANG CHAY, ' + $c.Count + ' tien trinh, tu ' + $c[0].CreationDate } }"
echo.
echo === App tren may ===
curl -s -m 5 http://127.0.0.1:8080/whoami >nul 2>&1 && echo App tra loi OK - mo dashboard: http://localhost:8080 || echo App KHONG tra loi
echo.
echo === 3 lan watcher goi du doan gan nhat - phai co chu "may nha" ===
powershell -NoProfile -Command "Get-Content sync.log -Tail 400 -Encoding UTF8 | Select-String 'Trigger prediction' | Select-Object -Last 3 | ForEach-Object { $_.Line }"
echo.
echo Bat:  scripts\bat_he_thong.bat      Tat:  scripts\tat_he_thong.bat  [app / watcher]
