#Requires -Version 5.1
<#
.SYNOPSIS
  Aegis Windows bootstrap: tools, Python/Node deps, LAMMPS, KART, then launch UI.
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step([string]$msg) { Write-Host ("`n=== {0} ===" -f $msg) -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host ("[OK] {0}" -f $msg) -ForegroundColor Green }
function Write-Info([string]$msg) { Write-Host ("[INFO] {0}" -f $msg) -ForegroundColor Gray }
function Write-Warn([string]$msg) { Write-Host ("[WARN] {0}" -f $msg) -ForegroundColor Yellow }

$CacheDir = Join-Path $Root "tools\cache"
$EnvFile = Join-Path $Root "tools\aegis_env.ps1"
New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Root "tools") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Root "third_party") | Out-Null

# Load prior env if present
if (Test-Path $EnvFile) { . $EnvFile }

# Load .env (KEY=VALUE) without committing secrets
$DotEnv = Join-Path $Root ".env"
if (Test-Path $DotEnv) {
  Get-Content $DotEnv | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    if ($_ -match '^\s*([^=]+)=(.*)$') {
      $k = $Matches[1].Trim()
      $v = $Matches[2].Trim().Trim('"').Trim("'")
      [Environment]::SetEnvironmentVariable($k, $v, "Process")
    }
  }
}

function Refresh-Path {
  $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $user = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = "$user;$machine"
}

function Ensure-WingetPackage([string]$Id, [string]$Name, [string]$CheckCommand) {
  Refresh-Path
  Write-Info ("Checking {0}..." -f $Name)
  if ($CheckCommand) {
    $existing = Get-Command $CheckCommand -ErrorAction SilentlyContinue
    if ($existing) {
      Write-Ok ("{0} already on PATH: {1}" -f $Name, $existing.Source)
      return
    }
  }
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) {
    Write-Warn ("winget not found - install {0} manually if missing." -f $Name)
    return
  }
  $list = & winget list --id $Id -e 2>$null | Out-String
  if ($list -match [regex]::Escape($Id)) {
    Write-Ok ("{0} already installed (winget)" -f $Name)
    return
  }
  Write-Info ("Installing {0} via winget ({1})..." -f $Name, $Id)
  & winget install --id $Id -e --accept-package-agreements --accept-source-agreements
  Refresh-Path
}

function Find-Lammps {
  if ($env:AEGIS_LAMMPS_BIN -and (Test-Path $env:AEGIS_LAMMPS_BIN)) {
    return (Resolve-Path $env:AEGIS_LAMMPS_BIN).Path
  }
  Refresh-Path
  $cmd = Get-Command lmp -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $cmd = Get-Command lmp.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }

  # Fast, shallow search only (avoid scanning all of AppData)
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "LAMMPS"),
    (Join-Path $env:LOCALAPPDATA "Programs\LAMMPS"),
    (Join-Path ${env:ProgramFiles} "LAMMPS"),
    (Join-Path ${env:ProgramFiles(x86)} "LAMMPS"),
    (Join-Path $env:USERPROFILE "LAMMPS")
  )
  foreach ($dir in $candidates) {
    if (-not (Test-Path $dir)) { continue }
    $hit = Get-ChildItem -Path $dir -Filter "lmp.exe" -Recurse -Depth 4 -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if ($hit) { return $hit.FullName }
  }
  return $null
}

function Download-File([string]$Url, [string]$OutFile) {
  Write-Info ("Downloading: {0}" -f $Url)
  $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
  if ($curl) {
    & curl.exe -L --retry 5 --retry-all-errors --connect-timeout 30 -o $OutFile $Url
    if ($LASTEXITCODE -ne 0) { throw "curl exit $LASTEXITCODE for $Url" }
    return
  }
  # Fallback
  Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing
}

function Ensure-Lammps {
  Write-Step "LAMMPS (Windows)"
  $existing = Find-Lammps
  if ($existing) {
    Write-Ok ("LAMMPS already present: {0}" -f $existing)
    $env:AEGIS_LAMMPS_BIN = $existing
    return
  }

  $urls = @()
  if ($env:AEGIS_LAMMPS_URL) { $urls += $env:AEGIS_LAMMPS_URL }
  $urls += @(
    "https://download.lammps.org/static/LAMMPS-Win10-x64-GUI-latest.exe",
    "https://download.lammps.org/static/LAMMPS-Win10-64bit-GUI-stable.exe",
    "https://github.com/lammps/lammps/releases/download/stable_22Jul2025_update4/LAMMPS-Win10-64bit-GUI-22Jul2025_update4.exe"
  )

  $installer = $null
  foreach ($url in $urls) {
    $name = Split-Path $url -Leaf
    $dest = Join-Path $CacheDir $name
    try {
      if ((Test-Path $dest) -and ((Get-Item $dest).Length -gt 50MB)) {
        Write-Ok ("Using cached installer: {0}" -f $dest)
        $installer = $dest
        break
      }
      Download-File $url $dest
      if ((Test-Path $dest) -and ((Get-Item $dest).Length -gt 50MB)) {
        $installer = $dest
        break
      }
      Write-Warn ("Download too small or missing: {0}" -f $dest)
    } catch {
      Write-Warn ("Download failed ({0}): {1}" -f $url, $_)
    }
  }

  if (-not $installer) {
    Write-Warn "Could not download LAMMPS installer. Continuing without it (Aegis dry-run still works)."
    Write-Warn "Install manually from https://download.lammps.org/static/ then re-run."
    return
  }

  Write-Info "Running installer (silent if supported)..."
  try {
    $p = Start-Process -FilePath $installer -ArgumentList "/S" -PassThru -Wait
    if ($p.ExitCode -ne 0) {
      Write-Warn ("Silent install returned {0}; launching interactive installer..." -f $p.ExitCode)
      Start-Process -FilePath $installer -Wait
    }
  } catch {
    Write-Warn ("Installer launch failed: {0}" -f $_)
    return
  }

  Refresh-Path
  Start-Sleep -Seconds 2
  $existing = Find-Lammps
  if ($existing) {
    Write-Ok ("LAMMPS installed: {0}" -f $existing)
    $env:AEGIS_LAMMPS_BIN = $existing
  } else {
    Write-Warn "LAMMPS installer finished but lmp.exe not found on PATH yet."
    Write-Warn "Open a new shell or set AEGIS_LAMMPS_BIN after install. Continuing (dry-run still works)."
  }
}

function Find-KartBinary([string]$KartRoot) {
  if ($env:AEGIS_KART_BIN -and (Test-Path $env:AEGIS_KART_BIN)) {
    return (Resolve-Path $env:AEGIS_KART_BIN).Path
  }
  $candidates = @(
    (Join-Path $KartRoot "kart.exe"),
    (Join-Path $KartRoot "kart"),
    (Join-Path $KartRoot "bin\kart.exe"),
    (Join-Path $KartRoot "bin\kart"),
    (Join-Path $KartRoot "build\kart.exe"),
    (Join-Path $KartRoot "build\kart")
  )
  foreach ($c in $candidates) {
    if (Test-Path $c) { return (Resolve-Path $c).Path }
  }
  $which = Get-Command kart -ErrorAction SilentlyContinue
  if ($which) { return $which.Source }
  return $null
}

function Ensure-Kart {
  Write-Step "KART (k-ART)"
  $commit = if ($env:AEGIS_KART_COMMIT) { $env:AEGIS_KART_COMMIT } else { "62d66adf" }
  $kartRoot = if ($env:AEGIS_KART_ROOT) { $env:AEGIS_KART_ROOT } else { Join-Path $Root "third_party\kart" }
  $env:AEGIS_KART_ROOT = $kartRoot
  $env:AEGIS_KART_COMMIT = $commit

  $bin = Find-KartBinary $kartRoot
  if ((Test-Path (Join-Path $kartRoot ".git")) -and $bin) {
    Write-Ok ("KART already cloned and binary found: {0}" -f $bin)
    $env:AEGIS_KART_BIN = $bin
    return
  }

  if (-not (Test-Path (Join-Path $kartRoot ".git"))) {
    Write-Info ("Cloning groupe_mousseau/kart at commit {0} ..." -f $commit)
    $token = $env:GITLAB_TOKEN
    if ($token) {
      $remote = "https://oauth2:{0}@gitlab.com/groupe_mousseau/kart.git" -f $token
    } else {
      $remote = "git@gitlab.com:groupe_mousseau/kart.git"
    }
    $parent = Split-Path $kartRoot -Parent
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    try {
      if (Test-Path $kartRoot) { Remove-Item -Recurse -Force $kartRoot }
      git clone $remote $kartRoot
      if ($LASTEXITCODE -ne 0) { throw "git clone exited $LASTEXITCODE" }
      Push-Location $kartRoot
      git checkout $commit
      Pop-Location
      Write-Ok ("KART sources cloned to {0}" -f $kartRoot)
    } catch {
      Write-Warn ("KART clone failed: {0}" -f $_)
      Write-Warn "Membership required. Set GITLAB_TOKEN in .env or configure SSH, then re-run."
      Write-Warn "See engines\kart\SETUP.md"
      return
    }
  } else {
    Write-Ok ("KART sources already present at {0}" -f $kartRoot)
    Push-Location $kartRoot
    git fetch --quiet 2>$null
    git checkout $commit 2>$null
    Pop-Location
  }

  $bin = Find-KartBinary $kartRoot
  if ($bin) {
    Write-Ok ("KART binary: {0}" -f $bin)
    $env:AEGIS_KART_BIN = $bin
    return
  }

  $wsl = Get-Command wsl -ErrorAction SilentlyContinue
  if ($wsl) {
    Write-Info "Attempting KART build via WSL (recommended on Windows)..."
    $wslPath = (& wsl wslpath -a $kartRoot 2>$null)
    if ($wslPath) {
      $buildCmd = 'cd "{0}" && (test -f CMakeLists.txt && mkdir -p build && cd build && cmake .. && cmake --build . -j2) || (test -f Makefile && make -j2) || true' -f $wslPath
      try {
        & wsl bash -lc $buildCmd
      } catch {
        Write-Warn ("WSL build attempt failed: {0}" -f $_)
      }
    }
  } else {
    Write-Warn "No KART binary yet and WSL not found. Sources are cloned; build per engines\kart\SETUP.md"
  }

  $bin = Find-KartBinary $kartRoot
  if ($bin) {
    Write-Ok ("KART binary ready: {0}" -f $bin)
    $env:AEGIS_KART_BIN = $bin
  } else {
    Write-Warn "KART anneal will stub until a binary is built. Clone is ready under third_party\kart when clone succeeded."
  }
}

function Ensure-PythonDeps {
  Write-Step "Python API deps"
  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) { throw "Python not found after tool install" }
  $venvPy = Join-Path $Root ".venv\Scripts\python.exe"
  if (-not (Test-Path $venvPy)) {
    Write-Info "Creating .venv..."
    python -m venv (Join-Path $Root ".venv")
  } else {
    Write-Ok ".venv already exists"
  }
  & $venvPy -m pip install --upgrade pip | Out-Null
  & $venvPy -m pip install -r (Join-Path $Root "apps\api\requirements.txt") -e (Join-Path $Root "packages\schema")
  Write-Ok "Python packages installed"
}

function Ensure-NodeDeps {
  Write-Step "Node UI deps"
  $npm = Get-Command npm -ErrorAction SilentlyContinue
  if (-not $npm) { throw "npm not found after tool install" }
  $modules = Join-Path $Root "apps\web\node_modules"
  if (Test-Path $modules) {
    Write-Ok "node_modules already present"
  } else {
    Write-Info "npm install..."
  }
  Push-Location (Join-Path $Root "apps\web")
  npm install
  Pop-Location
  Write-Ok "Web dependencies ready"
}

function Save-EnvFile {
  $lines = @(
    "# Auto-generated by setup_and_run.cmd - local only",
    ("`$env:AEGIS_LAMMPS_BIN = '{0}'" -f $env:AEGIS_LAMMPS_BIN),
    ("`$env:AEGIS_KART_ROOT = '{0}'" -f $env:AEGIS_KART_ROOT),
    ("`$env:AEGIS_KART_BIN = '{0}'" -f $env:AEGIS_KART_BIN),
    ("`$env:AEGIS_KART_COMMIT = '{0}'" -f $env:AEGIS_KART_COMMIT)
  )
  Set-Content -Path $EnvFile -Value ($lines -join "`n") -Encoding UTF8
  Write-Ok ("Wrote {0}" -f $EnvFile)
}

function Start-Aegis {
  Write-Step "Launching Aegis"
  $venvPy = Join-Path $Root ".venv\Scripts\python.exe"
  $apiJob = Start-Process -FilePath $venvPy -ArgumentList @(
    "-m", "uvicorn", "aegis_api.main:app", "--host", "127.0.0.1", "--port", "8000"
  ) -WorkingDirectory (Join-Path $Root "apps\api") -PassThru -WindowStyle Minimized

  Start-Sleep -Seconds 2
  $npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue)
  if (-not $npmCmd) { $npmCmd = Get-Command npm }
  $webJob = Start-Process -FilePath $npmCmd.Source -ArgumentList @(
    "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"
  ) -WorkingDirectory (Join-Path $Root "apps\web") -PassThru -WindowStyle Minimized

  Start-Sleep -Seconds 4
  Start-Process "http://127.0.0.1:5173"

  Write-Ok ("API pid={0}  UI pid={1}" -f $apiJob.Id, $webJob.Id)
  Write-Host ""
  Write-Host "  Opened http://127.0.0.1:5173" -ForegroundColor Green
  Write-Host "  API    http://127.0.0.1:8000/api/health" -ForegroundColor Green
  Write-Host ""
  Write-Host "Press Ctrl+C to stop both servers..." -ForegroundColor Yellow

  try {
    while ($true) {
      if ($apiJob.HasExited -or $webJob.HasExited) {
        Write-Warn ("A process exited (API={0} UI={1})" -f $apiJob.HasExited, $webJob.HasExited)
        break
      }
      Start-Sleep -Seconds 2
    }
  } finally {
    if (-not $apiJob.HasExited) { Stop-Process -Id $apiJob.Id -Force -ErrorAction SilentlyContinue }
    if (-not $webJob.HasExited) { Stop-Process -Id $webJob.Id -Force -ErrorAction SilentlyContinue }
  }
}

# ---- main ----
Write-Step "Developer tools"
Ensure-WingetPackage "Python.Python.3.12" "Python 3.12" "python"
Ensure-WingetPackage "OpenJS.NodeJS.LTS" "Node.js LTS" "node"
Ensure-WingetPackage "Git.Git" "Git" "git"
Refresh-Path

Ensure-PythonDeps
Ensure-NodeDeps

try { Ensure-Lammps } catch { Write-Warn ("LAMMPS step error (continuing): {0}" -f $_) }
try { Ensure-Kart } catch { Write-Warn ("KART step error (continuing): {0}" -f $_) }

Save-EnvFile
Start-Aegis
