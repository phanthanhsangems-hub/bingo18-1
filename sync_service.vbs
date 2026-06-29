Option Explicit

Dim oShell, oWMI, oProcs, oProc
Dim sDir, sPython, sScript

sDir    = "C:\Users\ACER\bingo18"
sPython = "C:\Users\ACER\AppData\Local\Programs\Python\Python311\pythonw.exe"
sScript = "sync_to_supabase.py --mode watch"

' Single-instance guard: thoat neu da co pythonw dang chay sync
Set oWMI   = GetObject("winmgmts:\\.\root\cimv2")
Set oProcs = oWMI.ExecQuery("SELECT * FROM Win32_Process WHERE Name='pythonw.exe'")
For Each oProc In oProcs
    If InStr(oProc.CommandLine, "sync_to_supabase.py") > 0 Then
        WScript.Quit 0  ' Da chay roi, khong khoi dong them
    End If
Next

' Chua co instance nao -> khoi dong
Set oShell = WScript.CreateObject("WScript.Shell")
oShell.CurrentDirectory = sDir
' WindowStyle=0 = hoan toan an, bWaitOnReturn=False = non-blocking
oShell.Run Chr(34) & sPython & Chr(34) & " " & sScript, 0, False

Set oShell = Nothing
Set oWMI   = Nothing
WScript.Quit 0
