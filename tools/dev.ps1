# 开发模式：构建前端 → 起 SimLink（可选）→ 起 aoc-core 并打开浏览器
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path "apps\client\node_modules")) {
    Push-Location apps\client
    npm.cmd install
    Pop-Location
}
Push-Location apps\client
npm.cmd run build
Pop-Location

$home = Join-Path $env:LOCALAPPDATA "AOC"
New-Item -ItemType Directory -Force $home | Out-Null

$simlink = "apps\simlink\bin\Debug\net8.0\aoc-simlink.exe"
if (Test-Path $simlink) {
    Start-Process -FilePath (Resolve-Path $simlink) -ArgumentList @("--demo", "--demo-speed", "12", "--port", "0", "--home", $home) -WindowStyle Minimized
} else {
    Write-Host "SimLink 未构建：cd apps/simlink; dotnet build" -ForegroundColor Yellow
}

python -X utf8 apps\aoc-core\main.py --port 0 --home $home --static-dir apps\client\dist --open
