Option Explicit

Dim oShell, oWMI, oProcs, oProc
Dim sDir, sPython, sScript

' Thu muc CUA CHINH FILE NAY, khong ghi cung.
' Truoc day dong nay la "C:\Users\ACER\bingo18". Ai chep repo sang thu muc
' khac (vi du bingo18-moi) van bi vbs do chay code o thu muc CU — watcher
' trong thu muc moi khong bao gio duoc khoi dong, ma khong co loi nao bao.
sDir    = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\") - 1)
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
