# Laptop fallback for the demo (plan 6.6): the phones talk to this laptop instead of the server.
#
#   powershell -ExecutionPolicy Bypass -File scripts\fallback.ps1                  # start
#   powershell -ExecutionPolicy Bypass -File scripts\fallback.ps1 -ResetDemoUsers  # also new demo passwords
#
# 1. Phone and laptop on one network: switch on the laptop's Mobile hotspot (the laptop is then
#    192.168.137.1) or join the laptop to the phone's hotspot.
# 2. Run this script; it starts the dev database (real roll) and the API on port 8000, and prints
#    the addresses to type.
# 3. On the phone (DEBUG build only): Login screen > Server > Change > type e.g. 192.168.137.1:8000.
#
# Data: the laptop's dev database, not the server's. Changes made here do not reach the server,
# and the logins are the laptop's (jansetu-private/demo_users.txt). Stop with Ctrl+C.
param([switch]$ResetDemoUsers, [int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root '.venv\Scripts\python.exe'

Write-Host '== dev database'
docker compose -f (Join-Path $root 'deploy\docker-compose.dev.yml') up -d
if ($LASTEXITCODE -ne 0) { throw 'docker compose failed: is Docker Desktop running?' }
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    $state = docker inspect -f '{{.State.Health.Status}}' jansetu-dev-db-1 2>$null
    if ($state -eq 'healthy') { $ok = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $ok) { throw 'the dev database did not become healthy' }

if ($ResetDemoUsers) {
    Write-Host '== demo users: new temporary passwords (jansetu-private\demo_users.txt), phones back to waiting'
    & $py (Join-Path $root 'scripts\create_demo_users.py') --reset
}

Write-Host '== networks'
$public = Get-NetConnectionProfile | Where-Object { $_.NetworkCategory -eq 'Public' }
foreach ($p in $public) {
    Write-Warning ("Network '{0}' is Public: Windows Firewall may block the phones. Settings > Network > {0} > Private network." -f $p.Name)
}
$addrs = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.InterfaceAlias -notmatch 'vEthernet|WSL|Loopback' }
Write-Host 'Type one of these on the phone (Login > Server > Change):'
foreach ($a in $addrs) {
    $hint = if ($a.IPAddress -eq '192.168.137.1') { '   <- laptop Mobile hotspot' } else { '' }
    Write-Host ("   {0}:{1}   ({2}){3}" -f $a.IPAddress, $Port, $a.InterfaceAlias, $hint)
}
Write-Host ("Check from the phone's browser first: http://<address>:{0}/api/v1/health" -f $Port)

Write-Host "== API on port $Port (Ctrl+C to stop)"
Push-Location (Join-Path $root 'backend')
try {
    & $py -m uvicorn app.main:app --host 0.0.0.0 --port $Port
} finally {
    Pop-Location
}
