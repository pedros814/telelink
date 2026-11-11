' ZeroNoShow - relance du pont iPhone (tache Windows, toutes les 5 min et a l'ouverture de session).
' Invisible : ne fait rien si le pont tourne deja ; sinon le relance dans une fenetre reduite.
Option Explicit
Dim fso, dir, wmi, procs, sh
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT ProcessId FROM Win32_Process WHERE Name='python.exe' AND CommandLine LIKE '%telelink zns run%'")
If procs.Count = 0 Then
  Set sh = CreateObject("WScript.Shell")
  sh.CurrentDirectory = dir
  sh.Run "cmd /c start ""ZeroNoShow - pont iPhone"" /min cmd /c zeronoshow-bridge.bat", 0, False
End If
