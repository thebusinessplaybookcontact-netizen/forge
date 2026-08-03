# Goal Coach — one-shot Windows setup.
#
# Run it with:
#   irm https://raw.githubusercontent.com/thebusinessplaybookcontact-netizen/forge/main/setup.ps1 | iex
#
# Installs Python, Node and Git if they're missing, downloads the app, asks for the
# Claude key, builds everything, and starts it. Safe to run again — every step checks
# whether it's already done, so a half-finished attempt is fixed by re-running.
#
# Deliberately serves the production build from the backend rather than running Vite
# alongside it, so there is ONE window and ONE address instead of two of each.

$ErrorActionPreference = "Stop"

# Windows blocks unsigned .ps1 files by default, and npm ships its own PowerShell
# wrapper — so `npm install` dies with "running scripts is disabled on this system"
# even though nothing is wrong. This lifts the block for THIS process only; nothing
# about the machine's settings changes, and it's gone when the window closes.
try { Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force } catch {}

function Say  ($m) { Write-Host ""; Write-Host "  $m" -ForegroundColor Cyan }
function Ok   ($m) { Write-Host "  $m" -ForegroundColor Green }
function Warn ($m) { Write-Host "  $m" -ForegroundColor Yellow }
function Die  ($m) { Write-Host ""; Write-Host "  $m" -ForegroundColor Red; Write-Host ""; exit 1 }

# Running ordinary programs from PowerShell is a minefield, in two opposite directions:
#
#   1. A program that FAILS doesn't stop the script. $ErrorActionPreference has no say
#      over exit codes, so pip can die and the next line cheerfully claims success.
#   2. A program that SUCCEEDS can stop the script. Windows PowerShell turns anything
#      written to the error stream into a real error object, and with "Stop" set that
#      becomes fatal — so pip's warnings, npm's notices, or git's progress can kill a
#      run that was going perfectly well. Even `2>$null` doesn't reliably save you.
#
# So: every external program goes through one of these two, both of which relax the
# preference for the duration and judge the outcome by the exit code alone — the only
# signal that actually means failure.

function Invoke-Native ([scriptblock]$block) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $block } finally { $ErrorActionPreference = $prev }
}

# For commands that must succeed. Output stays visible so failures are legible.
function Run ($what, $exe, [string[]]$exeArgs) {
    Invoke-Native { & $exe @exeArgs }
    if ($LASTEXITCODE -ne 0) { Die "$what failed (exit code $LASTEXITCODE). The error is above. Fix it, or send it to Claude, then run this again." }
}

# For commands whose failure is the answer, not a problem — "is this thing installed?",
# "does this sandbox work?". Silent, never throws, returns true/false.
function Probe ($exe, [string[]]$exeArgs) {
    try {
        Invoke-Native { & $exe @exeArgs 2>&1 | Out-Null }
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

Write-Host ""
Write-Host "  ===============================" -ForegroundColor White
Write-Host "   Goal Coach - setting things up" -ForegroundColor White
Write-Host "  ===============================" -ForegroundColor White

# --- 0. Prerequisites -------------------------------------------------------

# PATH is only read when a shell starts, so anything winget installs is invisible to
# this session until we pull it in by hand.
function Refresh-Path {
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user    = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

# `python` on a clean Windows is a stub that opens the Microsoft Store, so "the command
# exists" is not the same as "it's installed". Ask for a version and believe it only if
# a real one comes back.
function Have ($exe, $versionArg = "--version") {
    try {
        $out = Invoke-Native { & $exe $versionArg 2>&1 | Out-String }
        return ($out -match "\d+\.\d+")
    } catch { return $false }
}

function Install-With-Winget ($id, $friendly) {
    Say "Installing $friendly. This can take a few minutes - it's a real download."
    Invoke-Native {
        winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
    }
    Refresh-Path
}

Refresh-Path

if (-not (Have "winget" "--version")) {
    Die @"
This laptop doesn't have 'winget', which is how Windows installs software.

Fix: open the Microsoft Store, search for "App Installer", install it, then run this
again. (On Windows 11 and recent Windows 10 it's normally already there.)
"@
}

# --- Python: a SPECIFIC version, not whatever happens to be on PATH ----------
#
# This is the thing that broke first time round. The libraries here ship prebuilt for
# Python 3.11-3.13; on a newer Python (3.14 shipped in late 2025) pip finds no prebuilt
# pydantic-core, falls back to compiling it from Rust source, and dies. So don't trust
# `python` — go and find 3.12 specifically, installing it if needed. Having several
# Pythons side by side is normal and harmless; the app gets its own sandbox anyway.

function Resolve-Python312 {
    # The `py` launcher is the reliable way to ask for one particular version.
    try {
        $found = Invoke-Native { & py -3.12 -c "import sys; print(sys.executable)" 2>$null }
        if ($LASTEXITCODE -eq 0 -and $found) {
            $path = ($found | Select-Object -Last 1 | Out-String).Trim()
            if ($path -and (Test-Path $path)) { return $path }
        }
    } catch {}
    foreach ($guess in @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        "C:\Python312\python.exe"
    )) { if (Test-Path $guess) { return $guess } }
    return $null
}

$python = Resolve-Python312
if ($python) {
    Ok "Found Python 3.12."
} else {
    Install-With-Winget "Python.Python.3.12" "Python 3.12"
    $python = Resolve-Python312
}
if (-not $python) { Die "Couldn't get Python 3.12 working. Close PowerShell, open a new one, and run this again - a fresh window often fixes it." }

if (-not (Have "node")) { Install-With-Winget "OpenJS.NodeJS.LTS" "Node.js" }
if (-not (Have "git"))  { Install-With-Winget "Git.Git" "Git" }
if (-not (Have "node")) { Die "Node still isn't working. Close PowerShell, open a new one, and run this again." }
if (-not (Have "git"))  { Die "Git still isn't working. Close PowerShell, open a new one, and run this again." }
Ok "Node and Git are ready."

# npm.ps1 is the blocked one; npm.cmd does the same job and isn't a PowerShell script.
$npm = "npm.cmd"

# --- 1. The code ------------------------------------------------------------

$root = Join-Path $HOME "Documents\forge"

if (Test-Path (Join-Path $root ".git")) {
    Say "Updating the app to the latest version..."
    Run "Update" "git" @("-C", $root, "pull", "--ff-only")
    Ok "Up to date."
} else {
    Say "Downloading the app into $root ..."
    New-Item -ItemType Directory -Force -Path (Split-Path $root) | Out-Null
    Run "Download" "git" @("clone", "--quiet", "https://github.com/thebusinessplaybookcontact-netizen/forge.git", $root)
    Ok "Downloaded."
}

$backend  = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venvDir  = Join-Path $backend ".venv"
$venvPy   = Join-Path $venvDir "Scripts\python.exe"

# --- 2. Backend -------------------------------------------------------------

# A sandbox built by the wrong Python is worse than none, because everything downstream
# fails confusingly. Test it by actually importing the app's libraries; rebuild if not.
$venvOk = $false
if (Test-Path $venvPy) {
    $venvOk = Probe $venvPy @("-c", "import pydantic, fastapi, anthropic")
    if (-not $venvOk) { Warn "The existing setup is broken - rebuilding it from scratch." }
}

if (-not $venvOk) {
    if (Test-Path $venvDir) { Remove-Item -Recurse -Force $venvDir }
    Say "Setting up the brain (a private Python sandbox, so nothing collides)..."
    Run "Creating the sandbox" $python @("-m", "venv", $venvDir)
    Run "Upgrading pip" $venvPy @("-m", "pip", "install", "--quiet", "--upgrade", "pip")
}

# Always, not just on a fresh sandbox. The requirements change as the app is worked on,
# and a re-run after `git pull` is exactly how those changes are meant to arrive. pip is
# quick when there's nothing to do; skipping it means a stale install that imports fine
# and then fails at runtime on the one library that was added.
Say "Installing what the brain needs. Scrolling text is normal; it takes a minute."
Run "Installing the libraries" $venvPy @("-m", "pip", "install", "--disable-pip-version-check", "-r", (Join-Path $backend "requirements.txt"))

# Say it only once it's true.
if (-not (Probe $venvPy @("-c", "import pydantic, fastapi, anthropic"))) {
    Die "The brain's libraries still aren't importable. Send the errors above to Claude."
}
# Windows has no timezone database of its own, so this is a real thing that can be
# missing — and when it is, every screen in the app returns an error.
if (-not (Probe $venvPy @("-c", "from zoneinfo import ZoneInfo; ZoneInfo('America/Los_Angeles')"))) {
    Die "Python can't read timezones on this machine, which breaks every screen. The tzdata package should have fixed it. Send this to Claude."
}
Ok "Brain ready."

# --- 3. Settings ------------------------------------------------------------

$envFile = Join-Path $backend ".env"
if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $backend ".env.example") $envFile }
$settings = Get-Content $envFile -Raw

if ($settings -match "(?m)^ANTHROPIC_API_KEY=sk-ant-\S{10,}") {
    Ok "Your Claude key is already saved."
} else {
    Write-Host ""
    Write-Host "  Your Claude API key" -ForegroundColor White
    Write-Host "  Get one at https://console.anthropic.com -> API keys. It starts with sk-ant-"
    Write-Host "  (It goes into a file on this laptop and nowhere else.)"
    Write-Host ""
    $key = (Read-Host "  Paste it here and press Enter").Trim()
    if ($key -notmatch "^sk-ant-") { Die "That doesn't look like a Claude key - they start with sk-ant- . Run this again when you have it." }
    $settings = $settings -replace "(?m)^ANTHROPIC_API_KEY=.*$", "ANTHROPIC_API_KEY=$key"
    Ok "Key saved."
}

# Windows names its timezones differently from everyone else, so translate the common
# ones. Getting this wrong means the coach thinks tomorrow started at teatime.
$zoneMap = @{
    "Pacific Standard Time"        = "America/Los_Angeles"
    "Mountain Standard Time"       = "America/Denver"
    "US Mountain Standard Time"    = "America/Phoenix"
    "Central Standard Time"        = "America/Chicago"
    "Eastern Standard Time"        = "America/New_York"
    "Alaskan Standard Time"        = "America/Anchorage"
    "Hawaiian Standard Time"       = "Pacific/Honolulu"
    "GMT Standard Time"            = "Europe/London"
    "W. Europe Standard Time"      = "Europe/Berlin"
    "Romance Standard Time"        = "Europe/Paris"
    "Central Europe Standard Time" = "Europe/Warsaw"
    "AUS Eastern Standard Time"    = "Australia/Sydney"
}
$winZone = (Get-TimeZone).Id
$zone    = $zoneMap[$winZone]
if ($zone) {
    $settings = $settings -replace "(?m)^COACH_TIMEZONE=.*$", "COACH_TIMEZONE=$zone"
    Ok "Timezone set to $zone."
} else {
    Warn "Couldn't translate your timezone ('$winZone') - tell Claude and it'll set it by hand."
}

Set-Content -Path $envFile -Value $settings -NoNewline

# --- 4. Frontend ------------------------------------------------------------

Say "Building the screens. This is the slowest part - a few minutes."
Push-Location $frontend
try {
    Run "Installing the screen libraries" $npm @("install", "--no-audit", "--no-fund")
    Run "Building the screens" $npm @("run", "build")
} finally { Pop-Location }

# The backend only serves the app if this file exists; without it every page is a bare
# 404 and the cause is nowhere near the symptom. Check rather than assume.
if (-not (Test-Path (Join-Path $frontend "dist\index.html"))) {
    Die "The screens didn't actually build - there's no frontend\dist\index.html. Send the output above to Claude."
}
Ok "Screens built."

# --- 5. A way to start it again ---------------------------------------------

$startScript = Join-Path $root "start.ps1"
@"
# Starts Goal Coach. Close this window to stop it.
#
# The browser is opened by a background job that waits for the server to answer first.
# Opening it up front races the server and lands on a connection error.
Set-Location "$backend"
Start-Job {
    for (`$i = 0; `$i -lt 90; `$i++) {
        try {
            Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8000/api/health" -TimeoutSec 2 | Out-Null
            Start-Process "http://localhost:8000"
            return
        } catch { Start-Sleep -Milliseconds 500 }
    }
} | Out-Null
& "$venvPy" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
"@ | Set-Content -Path $startScript

$shortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Goal Coach.lnk"
$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut($shortcut)
$lnk.TargetPath       = "powershell.exe"
$lnk.Arguments        = "-ExecutionPolicy Bypass -File `"$startScript`""
$lnk.WorkingDirectory = $backend
$lnk.Description      = "Start your Goal Coach"
$lnk.Save()
Ok "Put a 'Goal Coach' shortcut on your desktop for next time."

# --- 6. Go ------------------------------------------------------------------

Say "Adding your four starting goals..."
Push-Location $backend
try { Run "Seeding your goals" $venvPy @("-m", "app.seed") } finally { Pop-Location }

Write-Host ""
Write-Host "  ===============================" -ForegroundColor Green
Write-Host "   Done. Starting it now." -ForegroundColor Green
Write-Host "  ===============================" -ForegroundColor Green
Write-Host ""
Write-Host "   It will open at http://localhost:8000"
Write-Host "   This window IS the app - leave it open while you use it."
Write-Host "   To stop: close this window. To start again: the desktop shortcut."
Write-Host ""

Set-Location $backend

# Wait for the server to actually answer before opening the browser. Opening it first
# races a process that hasn't started yet, and you get a connection error on a setup
# that worked perfectly.
Start-Job {
    for ($i = 0; $i -lt 90; $i++) {
        try {
            Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8000/api/health" -TimeoutSec 2 | Out-Null
            Start-Process "http://localhost:8000"
            return
        } catch { Start-Sleep -Milliseconds 500 }
    }
} | Out-Null

# uvicorn logs to the error stream by design, so this must not run under "Stop" either.
Invoke-Native { & $venvPy -m uvicorn app.main:app --host 127.0.0.1 --port 8000 }
