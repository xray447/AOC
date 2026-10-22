<#
.SYNOPSIS
    Full build of the AOC desktop project (Windows).

.DESCRIPTION
    Builds every artefact this repository can produce on a Windows machine:

      1. prerequisites      python / node / dotnet / cargo / MSVC check
      2. python deps        pip install -r requirements.txt -r requirements-server.txt
      3. apps/client        -> apps/client/dist            (tsc --noEmit + vite build)
      4. apps/admin-web     -> apps/admin-web/dist         (M3 admin console)
      5. apps/simlink       -> apps/simlink/bin/Release/net8.0/win-x64
                              (dotnet publish -r win-x64; this exact folder is a
                               Tauri bundle resource, do not change it)
      6. apps/client/src-tauri -> out/AOC-<ver>-x64-setup.exe (NSIS)
                                  out/AOC-<ver>-x64.msi       (MSI)
      7. portable zip       -> out/AOC-portable-<ver>-win64.zip
      8. checks             -> ruff (F,E9) + pytest
      9. server image       -> docker build (skipped when docker is absent)

    Every step can be turned off with -Skip* switches; -Clean wipes previous
    outputs first. A transcript is written to out/build-<timestamp>.log.

.PARAMETER Clean
    Remove previous build outputs (both dist folders, tauri bundle, portable
    staging folder) before building.

.PARAMETER Reinstall
    Force npm ci / pip install even when node_modules or the python packages
    are already present.

.PARAMETER SkipPythonDeps
    Do not touch the python environment.

.PARAMETER SkipClient
    Skip the React SPA build.

.PARAMETER SkipAdmin
    Skip the admin web build.

.PARAMETER SkipSimlink
    Skip the .NET SimLink publish.

.PARAMETER SkipTauri
    Skip the NSIS/MSI installers (no Rust/MSVC needed then).

.PARAMETER SkipPortable
    Skip out/AOC-portable-<ver>-win64.zip.

.PARAMETER SkipTests
    Skip ruff + pytest.

.PARAMETER SkipDocker
    Skip the server image build.

.PARAMETER Smoke
    Also run tools/smoke_m1.py, smoke_m2.py and smoke_m3.py (slow, spawns
    simlink/aoc-core processes).

.PARAMETER Bundles
    Comma separated Tauri bundles, default "nsis,msi".

.PARAMETER PythonExe
    Python executable to use, default "python".

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools/build.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools/build.ps1 -Clean -SkipDocker

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools/build.ps1 -SkipTauri -SkipDocker -SkipTests
#>
[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$Reinstall,
    [switch]$SkipPythonDeps,
    [switch]$SkipClient,
    [switch]$SkipAdmin,
    [switch]$SkipSimlink,
    [switch]$SkipTauri,
    [switch]$SkipPortable,
    [switch]$SkipTests,
    [switch]$SkipDocker,
    [switch]$Smoke,
    [string]$Bundles = "nsis,msi",
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -Path $Root

$OutDir = Join-Path $Root "out"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$Version = "0.0.0"
$TauriConf = Join-Path $Root "apps/client/src-tauri/tauri.conf.json"
if (Test-Path $TauriConf) {
    $Version = (Get-Content -Path $TauriConf -Raw | ConvertFrom-Json).version
}

$LogPath = Join-Path $OutDir ("build-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$TotalTimer = [System.Diagnostics.Stopwatch]::StartNew()
$script:StepIndex = 0
$script:Produced = New-Object System.Collections.ArrayList

function Add-Produced {
    param([Parameter(Mandatory = $true)][string]$Path)
    [void]$script:Produced.Add($Path)
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = $Root
    )
    $preview = "$FilePath $($Arguments -join ' ')"
    Write-Host "  > $preview" -ForegroundColor DarkGray
    Push-Location -Path $WorkingDirectory
    $code = 1
    try {
        & $FilePath @Arguments
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($code -ne 0) {
        throw "exit code $code from: $preview"
    }
}

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Body
    )
    $script:StepIndex++
    Write-Host ""
    Write-Host ("--- step {0}: {1}" -f $script:StepIndex, $Name) -ForegroundColor Cyan
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    & $Body
    Write-Host ("    ok ({0:n1}s)" -f $timer.Elapsed.TotalSeconds) -ForegroundColor DarkGray
}

function Test-Tool {
    param([Parameter(Mandatory = $true)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Assert-Tool {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Hint
    )
    if (-not (Test-Tool $Name)) {
        throw "missing prerequisite '$Name' - $Hint"
    }
}

function Invoke-NodeBuild {
    param([Parameter(Mandatory = $true)][string]$RelativeDir)
    $dir = Join-Path $Root $RelativeDir
    $nodeModules = Join-Path $dir "node_modules"
    if ($Reinstall -or -not (Test-Path $nodeModules)) {
        if (Test-Path (Join-Path $dir "package-lock.json")) {
            Invoke-Native "npm.cmd" @("ci", "--no-audit", "--no-fund") $dir
        } else {
            Invoke-Native "npm.cmd" @("install", "--no-audit", "--no-fund") $dir
        }
    } else {
        Write-Host "  node_modules present: $RelativeDir"
    }
    Invoke-Native "npm.cmd" @("run", "build") $dir
}

function Test-PythonDeps {
    $probe = "import fastapi, uvicorn, pydantic, numpy, scipy, httpx, pytest, sqlalchemy, alembic"
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $PythonExe -c $probe *> $null
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Test-PythonModule {
    param([Parameter(Mandatory = $true)][string]$Module)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $PythonExe -m $Module --version *> $null
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Format-Size {
    param([long]$Bytes)
    if ($Bytes -ge 1MB) { return ("{0:n2} MB" -f ($Bytes / 1MB)) }
    return ("{0:n0} KB" -f ($Bytes / 1KB))
}

$started = $false
try {
    Start-Transcript -Path $LogPath -Force | Out-Null
    $started = $true
} catch {
    Write-Host "transcript disabled: $($_.Exception.Message)" -ForegroundColor Yellow
}

$failed = $false
try {
    Write-Host ""
    Write-Host "  AOC full build" -ForegroundColor White
    Write-Host "  root    : $Root"
    Write-Host "  version : $Version"
    Write-Host "  python  : $PythonExe"
    Write-Host "  bundles : $(if ($SkipTauri) { '(skipped)' } else { $Bundles })"
    Write-Host "  out     : $OutDir"

    Invoke-Step "Prerequisites" {
        Assert-Tool $PythonExe "install Python 3.10+ and make sure it is on PATH"
        $pyVer = (& $PythonExe -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
        Write-Host "  python $pyVer"
        if ([version]$pyVer -lt [version]"3.10") {
            throw "Python 3.10+ required, found $pyVer"
        }

        if ((-not $SkipClient) -or (-not $SkipAdmin) -or (-not $SkipTauri)) {
            Assert-Tool "npm.cmd" "install Node.js 18+ (npm) for the web builds"
            $nodeVer = (& node -v).Trim()
            Write-Host "  node $nodeVer"
        }

        if ((-not $SkipSimlink) -or (-not $SkipTauri)) {
            Assert-Tool "dotnet" "install the .NET 8 SDK"
            $dotnetVer = (& dotnet --version).Trim()
            Write-Host "  dotnet $dotnetVer"
        }

        if (-not $SkipTauri) {
            Assert-Tool "cargo" "install Rustup (stable-x86_64-pc-windows-msvc)"
            $cargoVer = (& cargo --version).Trim()
            Write-Host "  $cargoVer"
            $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio/Installer/vswhere.exe"
            if (Test-Path $vswhere) {
                $vsPath = (& $vswhere -latest -products * -property installationPath | Select-Object -First 1)
                if ([string]::IsNullOrWhiteSpace($vsPath)) {
                    Write-Host "  WARNING: vswhere found no Visual Studio / Build Tools installation" -ForegroundColor Yellow
                } else {
                    Write-Host "  msvc    : $vsPath"
                }
            } else {
                Write-Host "  WARNING: vswhere.exe not found, MSVC toolchain not verified" -ForegroundColor Yellow
            }
        }
    }

    if ($Clean) {
        Invoke-Step "Clean previous outputs" {
            $targets = @(
                "apps/client/dist",
                "apps/admin-web/dist",
                "apps/client/src-tauri/target/release/bundle",
                "out/AOC-portable-$Version",
                ".pytest_cache",
                ".ruff_cache"
            )
            foreach ($target in $targets) {
                $path = Join-Path $Root $target
                if (Test-Path $path) {
                    Write-Host "  rm $target"
                    Remove-Item -Path $path -Recurse -Force
                }
            }
        }
    }

    if (-not $SkipPythonDeps) {
        Invoke-Step "Python dependencies" {
            if ((-not $Reinstall) -and (Test-PythonDeps)) {
                Write-Host "  requirements already importable, pip skipped"
            } else {
                Invoke-Native $PythonExe @(
                    "-m", "pip", "install",
                    "-r", "requirements.txt",
                    "-r", "requirements-server.txt"
                )
            }
        }
    }

    if (-not $SkipClient) {
        Invoke-Step "Client SPA (apps/client)" {
            Invoke-NodeBuild "apps/client"
            if (-not (Test-Path (Join-Path $Root "apps/client/dist/index.html"))) {
                throw "apps/client/dist/index.html was not produced"
            }
            Add-Produced "apps/client/dist"
        }
    }

    if (-not $SkipAdmin) {
        Invoke-Step "Admin web (apps/admin-web)" {
            Invoke-NodeBuild "apps/admin-web"
            if (-not (Test-Path (Join-Path $Root "apps/admin-web/dist/index.html"))) {
                throw "apps/admin-web/dist/index.html was not produced"
            }
            Add-Produced "apps/admin-web/dist"
        }
    }

    if (-not $SkipSimlink) {
        Invoke-Step "SimLink (.NET 8 publish)" {
            $publishDir = Join-Path $Root "apps/simlink/bin/Release/net8.0/win-x64"
            Invoke-Native "dotnet" @(
                "publish", "apps/simlink",
                "-c", "Release",
                "-r", "win-x64",
                "--self-contained", "false",
                "-o", $publishDir
            )
            $exe = Join-Path $publishDir "aoc-simlink.exe"
            if (-not (Test-Path $exe)) {
                throw "expected $exe - the Tauri bundle resources point at that folder"
            }
            Add-Produced "apps/simlink/bin/Release/net8.0/win-x64/aoc-simlink.exe"
        }
    }

    if (-not $SkipTauri) {
        Invoke-Step "Tauri installers ($Bundles)" {
            $clientDir = Join-Path $Root "apps/client"
            if (-not (Test-Path (Join-Path $clientDir "dist/index.html"))) {
                Invoke-NodeBuild "apps/client"
            }
            $simlinkExe = Join-Path $Root "apps/simlink/bin/Release/net8.0/win-x64/aoc-simlink.exe"
            if (-not (Test-Path $simlinkExe)) {
                Write-Host "  WARNING: simlink publish folder missing, tauri bundle resources may fail" -ForegroundColor Yellow
            }

            $bundleList = @($Bundles.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
            foreach ($bundle in $bundleList) {
                Invoke-Native "npm.cmd" @("run", "tauri", "build", "--", "--bundles", $bundle) $clientDir
            }

            $bundleRoot = Join-Path $Root "apps/client/src-tauri/target/release/bundle"
            if ($bundleList -contains "nsis") {
                $nsis = Get-ChildItem -Path (Join-Path $bundleRoot "nsis") -Filter "*-setup.exe" -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime -Descending | Select-Object -First 1
                if ($nsis) {
                    $dst = Join-Path $OutDir "AOC-$Version-x64-setup.exe"
                    Copy-Item -Path $nsis.FullName -Destination $dst -Force
                    Write-Host "  -> $dst"
                    Add-Produced $dst
                } else {
                    Write-Host ("  WARNING: no nsis setup.exe found under " + (Join-Path $bundleRoot "nsis")) -ForegroundColor Yellow
                }
            }
            if ($bundleList -contains "msi") {
                $msi = Get-ChildItem -Path (Join-Path $bundleRoot "msi") -Filter "*.msi" -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime -Descending | Select-Object -First 1
                if ($msi) {
                    $dst = Join-Path $OutDir "AOC-$Version-x64.msi"
                    Copy-Item -Path $msi.FullName -Destination $dst -Force
                    Write-Host "  -> $dst"
                    Add-Produced $dst
                } else {
                    Write-Host ("  WARNING: no msi found under " + (Join-Path $bundleRoot "msi")) -ForegroundColor Yellow
                }
            }
        }
    }

    if (-not $SkipPortable) {
        Invoke-Step "Portable package" {
            Invoke-Native $PythonExe @("-X", "utf8", "tools/make_portable.py")
            $zip = Get-ChildItem -Path $OutDir -Filter "AOC-portable-*-win64.zip" -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if (-not $zip) {
                throw "portable zip was not produced in $OutDir"
            }
            Add-Produced $zip.FullName
        }
    }

    if (-not $SkipTests) {
        Invoke-Step "Static checks and tests" {
            if (Test-PythonModule "ruff") {
                Invoke-Native $PythonExe @(
                    "-m", "ruff", "check",
                    "packages", "apps", "tests", "tools",
                    "--select", "F,E9"
                )
            } else {
                Write-Host "  ruff not installed, skipped" -ForegroundColor Yellow
            }

            if (Test-PythonModule "pytest") {
                Invoke-Native $PythonExe @("-m", "pytest")
            } else {
                Write-Host "  pytest not installed, skipped" -ForegroundColor Yellow
            }
        }
    }

    if ($Smoke) {
        Invoke-Step "Smoke tests (M1 / M2 / M3)" {
            foreach ($script in @("tools/smoke_m1.py", "tools/smoke_m2.py", "tools/smoke_m3.py")) {
                Invoke-Native $PythonExe @("-X", "utf8", $script)
            }
        }
    }

    if (-not $SkipDocker) {
        Invoke-Step "Server image (docker)" {
            if (-not (Test-Tool "docker")) {
                Write-Host "  docker not found, skipped" -ForegroundColor Yellow
                return
            }
            Invoke-Native "docker" @(
                "build",
                "-f", "deploy/Dockerfile",
                "-t", "aoc-server:$Version",
                "."
            )
        }
    }
} catch {
    $failed = $true
    Write-Host ""
    Write-Host ("BUILD FAILED: " + $_.Exception.Message) -ForegroundColor Red
} finally {
    if ($started) {
        try { Stop-Transcript | Out-Null } catch { }
    }
}

if ($failed) {
    Write-Host "log: $LogPath" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "=== artefacts" -ForegroundColor Cyan
if ($script:Produced.Count -eq 0) {
    Write-Host "  (nothing was built)"
}
foreach ($item in $script:Produced) {
    $path = $item
    if (-not [System.IO.Path]::IsPathRooted($path)) { $path = Join-Path $Root $path }
    if (-not (Test-Path $path)) { continue }
    $info = Get-Item -Path $path
    $shown = $path
    if ($shown.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)) {
        $shown = "." + $shown.Substring($Root.Length)
    }
    if ($info.PSIsContainer) {
        Write-Host ("  {0}" -f $shown)
    } else {
        Write-Host ("  {0}  ({1})" -f $shown, (Format-Size $info.Length))
    }
}

Write-Host ""
Write-Host ("BUILD OK in {0:n1}s" -f $TotalTimer.Elapsed.TotalSeconds) -ForegroundColor Green
Write-Host "log: $LogPath"
exit 0
