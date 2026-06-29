# setup_sync_watchdog.ps1
# Tạo Windows Task Scheduler task chạy sync_service.vbs mỗi 5 phút
# Chạy 1 lần: powershell -ExecutionPolicy Bypass -File setup_sync_watchdog.ps1

$TaskName   = "Bingo18SyncWatchdog"
$VbsPath    = "C:\Users\ACER\bingo18\sync_service.vbs"
$WScript    = "C:\Windows\System32\wscript.exe"

# Xóa task cũ nếu tồn tại
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Action  = New-ScheduledTaskAction -Execute $WScript -Argument "`"$VbsPath`""
$Trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) `
               -Once -At (Get-Date)
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action   $Action `
    -Trigger  $Trigger `
    -Settings $Settings `
    -Force | Out-Null

Write-Host "Task '$TaskName' da duoc dang ky." -ForegroundColor Green
Write-Host "Sync se tu dong restart neu chet, kiem tra lai moi 5 phut." -ForegroundColor Green
Write-Host ""
Write-Host "Kiem tra task: Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "Xoa task:      Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
