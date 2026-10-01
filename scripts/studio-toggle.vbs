' Runs studio-toggle.ps1 without a console window (the desktop shortcut points here).
Set fso = CreateObject("Scripting.FileSystemObject")
script = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "studio-toggle.ps1")
CreateObject("WScript.Shell").Run "pwsh.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & script & """", 0, False
