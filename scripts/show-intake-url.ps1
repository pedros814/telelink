# Print TeleLink intake URL for iPhone Shortcut
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

& $py -c @"
from telelink.config import load_config
from telelink.intake import get_lan_ip
c = load_config()
port = c.get('intake', {}).get('port', 8787)
ip = get_lan_ip()
print('')
print('TeleLink intake URL (iPhone must be on same Wi-Fi):')
print(f'  http://{ip}:{port}/intake')
print('')
print('Run listen first, then use this URL in an iPhone Shortcut.')
print('Guide: assets/iphone-intake.txt')
"@
