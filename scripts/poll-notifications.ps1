# Poll Phone Link notifications via WinRT (works in Windows PowerShell 5.1+).
# Outputs one JSON object per line: {"sender","body","app"}
param(
    [string[]]$AppNames = @("Phone Link", "Your Phone"),
    [string]$SenderMatch = "",
    [string]$SeenFile = ""
)

$ErrorActionPreference = "Stop"

function Wait-AsyncOperation {
    param($AsyncOp)
    [void][Windows.Foundation.AsyncStatus, Windows.Foundation, ContentType = WindowsRuntime]
    while ($AsyncOp.Status -eq [Windows.Foundation.AsyncStatus]::Started) {
        Start-Sleep -Milliseconds 40
    }
    if ($AsyncOp.Status -eq [Windows.Foundation.AsyncStatus]::Completed) {
        return $AsyncOp.GetResults()
    }
    if ($AsyncOp.Status -eq [Windows.Foundation.AsyncStatus]::Error) {
        throw $AsyncOp.ErrorCode
    }
    throw "Async operation was canceled"
}

Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.UI.Notifications.Management.UserNotificationListener, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.UI.Notifications.Management.UserNotificationListenerAccessStatus, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null

$listener = [Windows.UI.Notifications.Management.UserNotificationListener]::Current
$access = $listener.GetAccessStatus()
if ($access.ToString() -ne "Allowed") {
    # Interactive grant (run listen once from a visible terminal if this fails)
    try {
        $access = Wait-AsyncOperation ($listener.RequestAccessAsync())
    } catch {
        $access = $listener.GetAccessStatus()
    }
}
if ($access.ToString() -ne "Allowed") {
    Write-Error "Notification access not allowed. Settings > Privacy > Notifications > allow PowerShell/Terminal."
    exit 2
}

if (-not $SeenFile) {
    $SeenFile = Join-Path $env:TEMP "telelink-notif-seen.txt"
}
$seen = @{}
if (Test-Path $SeenFile) {
    Get-Content $SeenFile -ErrorAction SilentlyContinue | ForEach-Object {
        $line = $_.Trim()
        if ($line) { $seen[$line] = $true }
    }
}

# NotificationKinds.Toast = 1
$notifications = Wait-AsyncOperation ($listener.GetNotificationsAsync(1))

foreach ($n in $notifications) {
    $appName = $n.AppInfo.DisplayInfo.DisplayName
    $aumid = $n.AppInfo.AppUserModelId
    $match = $false
    foreach ($name in $AppNames) {
        if ($appName -like "*$name*" -or $aumid -like "*YourPhone*") { $match = $true; break }
    }
    if (-not $match) { continue }

    $title = ""
    $body = ""
    try {
        foreach ($binding in $n.Notification.Visual.Bindings) {
            $texts = @()
            foreach ($el in $binding.GetTextElements()) {
                if ($el.Text) { $texts += $el.Text.Trim() }
            }
            if ($texts.Count -gt 0) {
                if (-not $title) { $title = $texts[0] }
                if ($texts.Count -gt 1) { $body = ($texts[1..($texts.Count - 1)] -join " ") }
                elseif (-not $body) { $body = $texts[0] }
            }
        }
    } catch { }

    $text = if ($body) { $body } else { $title }
    if (-not $text) { continue }

    $haystack = "$title $body"
    if ($SenderMatch -and ($haystack -notlike "*$SenderMatch*")) { continue }

    $noteId = 0
    try { $noteId = [int]$n.Id } catch { }
    $fp = [System.BitConverter]::ToString(
        [System.Security.Cryptography.SHA256]::Create().ComputeHash(
            [Text.Encoding]::UTF8.GetBytes(("{0}|{1}" -f $title.Trim(), $text.Trim()))
        )
    ).Replace("-", "").Substring(0, 24).ToLower()
    $slot = "$aumid|$noteId"
    $key = "$slot|$fp"
    if ($seen.ContainsKey($key)) { continue }
    $seen[$key] = $true
    $seenDir = Split-Path -Parent $SeenFile
    if ($seenDir -and -not (Test-Path $seenDir)) { New-Item -ItemType Directory -Path $seenDir -Force | Out-Null }
    Add-Content -Path $SeenFile -Value $key -Encoding utf8

    $obj = [ordered]@{
        sender = if ($title -and $title -ne $text) { $title } else { "" }
        body   = $text
        app    = $appName
    }
    ($obj | ConvertTo-Json -Compress)
}
