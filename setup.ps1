# Goal Coach — one-shot Windows setup.
#
# Run it with:
#   irm https://raw.githubusercontent.com/thebusinessplaybookcontact-netizen/forge/main/setup.ps1 | iex
#
# Installs Python, Node and Git if they're missing, downloads the app, asks for the
# Claude key, builds everything, and starts it. Safe to run again — it skips whatever
# is already done, so if it dies halfway you just run it a second time.
#
# Deliberately does the frontend as a production build served by the backend, so there
# is ONE window and ONE address instead of two of each. Nobody wants to babysit two
# terminals to talk to a to-do list.

$ErrorActionPreference = "Stop"

function Say  ($m) { Write-Host ""; Write-Host "  $m" -ForegroundColor Cyan }
function Ok   ($m) { Write-Host "  $m" -ForegroundColor Green }
function Warn ($m) { Write-Host "  $m" -ForegroundColor Yellow }
function Die  ($m) { Write-Host ""; Write-Host "  $m" -ForegroundColor Red; Write-Host ""; exit 1 }

Write-Host ""
Write-Host "  ===============================" -ForegroundColor White
Write-Host "   Goal Coach - setting things up" -ForegroundColor White
Write-Host "  ===============================" -ForegroundColor White

# --- 0. Prerequisites -------------------------------------------------------

# PATH is only re-read by a shell when it starts, so anything winget installs is
# invisible to this session until we pull it in by hand.
function Refresh-Path {
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user    = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

# `python` on a clean Windows is a stub that opens the Microsoft Store, so "the command
# exists" is not the same as "python is installed". Ask it for a version and believe it
# only if a real one comes back.
function Have ($exe, $versionArg = "--version") {
    try {
        $out = & $exe $versionArg 2>&1 | Out-String
        return ($out -match "\d+\.\d+")
    } catch {
        return $false
    }
}

function Install-With-Winget ($id, $friendly) {
    Say "Installing $friendly. This can take a few minutes - it's a real download."
    winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements | Out-Null
    Refresh-Path
}

Refresh-Path

if (-not (Have "winget" "--version")) {
    Die @"
This laptop doesn't have 'winget', which is the tool Windows uses to install software.

Fix: open the Microsoft Store, search for "App Installer", install it, then run this
again. (On Windows 11 and recent Windows 10 it's normally already there.)
"@
}

if (Have "python") { Ok "Python is already here." } else { Install-With-Winget "Python.Python.3.12" "Python" }
if (Have "node")   { Ok "Node is already here." }   else { Install-With-Winget "OpenJS.NodeJS.LTS" "Node.js" }
if (Have "git")    { Ok "Git is already here." }    else { Install-With-Winget "Git.Git" "Git" }

if (-not (Have "python")) { Die "Python still isn't working after installing. Close PowerShell, open a new one, and run this again." }
if (-not (Have "node"))   { Die "Node still isn't working after installing. Close PowerShell, open a new one, and run this again." }
if (-not (Have "git"))    { Die "Git still isn't working after installing. Close PowerShell, open a new one, and run this again." }

# --- 1. The code ------------------------------------------------------------

$root = Join-Path $HOME "Documents\forge"

if (Test-Path (Join-Path $root ".git")) {
    Say "Updating the app to the latest version..."
    git -C $root pull --ff-only | Out-Null
    Ok "Up to date."
} else {
    Say "Downloading the app into $root ..."
    New-Item -ItemType Directory -Force -Path (Split-Path $root) | Out-Null
    git clone --quiet https://github.com/thebusinessplaybookcontact-netizen/forge.git $root
    Ok "Downloaded."
}

$backend  = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venvPy   = Join-Path $backend ".venv\Scripts\python.exe"

# --- 2. Backend -------------------------------------------------------------

if (-not (Test-Path $venvPy)) {
    Say "Setting up the brain (a private Python sandbox, so nothing collides)..."
    python -m venv (Join-Path $backend ".venv")
}
Say "Installing what the brain needs. Lots of scrolling text is normal."
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -r (Join-Path $backend "requirements.txt")
Ok "Brain ready."

# --- 3. Settings ------------------------------------------------------------

$envFile = Join-Path $backend ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $backend ".env.example") $envFile
}
$settings = Get-Content $envFile -Raw

if ($settings -match "(?m)^ANTHROPIC_API_KEY=sk-ant-\S{10,}") {
    Ok "Your Claude key is already saved."
} else {
    Write-Host ""
    Write-Host "  Your Claude API key" -ForegroundColor White
    Write-Host "  Get one at https://console.anthropic.com -> API keys. It starts with sk-ant-"
    Write-Host "  (Nothing is sent anywhere except into a file on this laptop.)"
    Write-Host ""
    $key = (Read-Host "  Paste it here and press Enter").Trim()
    if ($key -notmatch "^sk-ant-") { Die "That doesn't look like a Claude key - they all start with sk-ant- . Run this again when you have it." }
    $settings = $settings -replace "(?m)^ANTHROPIC_API_KEY=.*$", "ANTHROPIC_API_KEY=$key"
    Ok "Key saved."
}

# Windows names its zones differently from the rest of the world, so translate the
# common ones. Getting this wrong means the coach thinks tomorrow started at teatime.
$zoneMap = @{
    "Pacific Standard Time"      = "America/Los_Angeles"
    "Mountain Standard Time"     = "America/Denver"
    "US Mountain Standard Time"  = "America/Phoenix"
    "Central Standard Time"      = "America/Chicago"
    "Eastern Standard Time"      = "America/New_York"
    "Alaskan Standard Time"      = "America/Anchorage"
    "Hawaiian Standard Time"     = "Pacific/Honolulu"
    "GMT Standard Time"          = "Europe/London"
    "W. Europe Standard Time"    = "Europe/Berlin"
    "Romance Standard Time"      = "Europe/Paris"
    "Central Europe Standard Time" = "Europe/Warsaw"
    "AUS Eastern Standard Time"  = "Australia/Sydney"
}
$winZone = (Get-TimeZone).Id
$zone    = $zoneMap[$winZone]
if ($zone) {
    $settings = $settings -replace "(?m)^COACH_TIMEZONE=.*$", "COACH_TIMEZONE=$zone"
    Ok "Timezone set to $zone."
} else {
    Warn "Couldn't translate your timezone ('$winZone') automatically - tell Claude and it'll set it by hand."
}

Set-Content -Path $envFile -Value $settings -NoNewline

# --- 4. Frontend ------------------------------------------------------------

Say "Building the screens. This is the slowest part - a few minutes."
Push-Location $frontend
npm install --silent
npm run build
Pop-Location
Ok "Screens built."

# --- 5. A way to start it again ---------------------------------------------

$startScript = Join-Path $root "start.ps1"
@"
# Starts Goal Coach. Close this window to stop it.
Set-Location "$backend"
Start-Process "http://localhost:8000"
& "$venvPy" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
"@ | Set-Content -Path $startScript

$shortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Goal Coach.lnk"
$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut($shortcut)
$lnk.TargetPath  = "powershell.exe"
$lnk.Arguments   = "-ExecutionPolicy Bypass -File `"$startScript`""
$lnk.WorkingDirectory = $backend
$lnk.Description = "Start your Goal Coach"
$lnk.Save()
Ok "Put a 'Goal Coach' shortcut on your desktop for next time."

# --- 6. Go ------------------------------------------------------------------

Say "Adding your four starting goals..."
Push-Location $backend
& $venvPy -m app.seed
Pop-Location

Write-Host ""
Write-Host "  ===============================" -ForegroundColor Green
Write-Host "   Done. Starting it now." -ForegroundColor Green
Write-Host "  ===============================" -ForegroundColor Green
Write-Host ""
Write-Host "   It will open at http://localhost:8000"
Write-Host "   This window IS the app - leave it open while you use it."
Write-Host "   To stop: close this window. To start again: the desktop shortcut."
Write-Host ""

Start-Sleep -Seconds 2
Start-Process "http://localhost:8000"
Push-Location $backend
& $venvPy -m uvicorn app.main:app --host 127.0.0.1 --port 8000
