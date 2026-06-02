# Shortcut: .\telelink.ps1  (shell)  or  .\telelink.ps1 listen
$Root = $PSScriptRoot
if ($args.Count -eq 0) {
    & "$Root\.venv\Scripts\python.exe" -m telelink
} else {
    & "$Root\.venv\Scripts\python.exe" -m telelink @args
}
