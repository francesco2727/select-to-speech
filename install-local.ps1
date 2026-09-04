# Select-to-Speech Windows Local Installer
# Analogue to install-local.sh for Windows environments
# Usage in restricted PowerShell:
#   powershell -ExecutionPolicy Bypass -File .\install-local.ps1

[CmdletBinding()]
param(
    [switch]$ForceDownload,
    [switch]$NoAutoStart,
    [switch]$NoShortcuts
)

$ErrorActionPreference = "Stop"

function Write-Info {
    param([string]$Message)
    Write-Host "[+] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[!] $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "[X] $Message" -ForegroundColor Red
}

$InstallDir = $PSScriptRoot
if (-not (Test-Path "$InstallDir\pyproject.toml")) {
    Write-Err "install-local.ps1 must be run from inside the select-to-speech repository directory."
    exit 1
}

Write-Info "Running Windows local installation mode using: $InstallDir"

# ── 1. Check / Install uv ────────────────────────────────────────────────────────
if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
    Write-Warn "uv is not installed. Attempting to install uv automatically via PowerShell..."
    try {
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
        $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        $env:Path = [System.Environment]::ExpandEnvironmentVariables("$userPath;$machinePath")
    } catch {
        Write-Err "Failed to install uv automatically. Please install it from https://astral.sh/uv"
        exit 1
    }
}

if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
    # Check default astral install location in user profile
    $localUvPath = "$env:USERPROFILE\.local\bin"
    $cargoBinPath = "$env:USERPROFILE\.cargo\bin"
    if (Test-Path "$localUvPath\uv.exe") {
        $env:Path = "$localUvPath;$env:Path"
    } elseif (Test-Path "$cargoBinPath\uv.exe") {
        $env:Path = "$cargoBinPath;$env:Path"
    } else {
        Write-Err "uv executable not found in PATH. Please restart PowerShell and run again."
        exit 1
    }
}

Write-Info "Setting up Python virtual environment with uv..."
uv venv --allow-existing "$InstallDir\.venv"
Write-Info "Synchronizing Python dependencies..."
uv sync --project "$InstallDir"

# ── 2. Download Kokoro TTS Models ────────────────────────────────────────────────
Write-Info "Downloading Kokoro TTS model files (~340 MB)..."
try {
    uv run --project "$InstallDir" select-to-speech-download --model kokoro-v1.0
} catch {
    Write-Warn "Could not complete Kokoro model download during setup."
    Write-Warn "You can download models later by running: uv run select-to-speech-download"
}

# ── 3. Build Flutter Windows UI ──────────────────────────────────────────────────
Write-Info "Setting up Flutter Windows UI..."
$UiDir = "$InstallDir\src\ui"
$UiReleaseDir = "$UiDir\build\windows\x64\runner\Release"
$UiBinary = "$UiReleaseDir\ui.exe"

if (-not (Get-Command "flutter" -ErrorAction SilentlyContinue)) {
    Write-Warn "Flutter SDK was not found in PATH."
    Write-Warn "If you have Flutter installed, make sure it is added to your environment PATH."
    Write-Warn "To install Flutter: winget install Google.Flutter"
} else {
    Write-Info "Building Flutter Windows user interface (Release mode)..."
    Push-Location "$UiDir"
    try {
        flutter pub get
        flutter build windows --release
        Write-Info "Flutter Windows build completed successfully."
    } catch {
        Write-Warn "Flutter build failed. You can still run the debug runner via: flutter run -d windows"
    } finally {
        Pop-Location
    }
}

# ── 4. Create Shortcuts & Launchers ──────────────────────────────────────────────
if (-not $NoShortcuts) {
    try {
        $WshShell = New-Object -ComObject WScript.Shell
        $StartMenuDir = [System.IO.Path]::Combine($env:APPDATA, "Microsoft\Windows\Start Menu\Programs")
        $ShortcutPath = Join-Path $StartMenuDir "Select-to-Speech.lnk"
        $IconPath = "$InstallDir\src\ui\windows\runner\resources\app_icon.ico"
        if (-not (Test-Path $IconPath)) {
            $IconPath = "$InstallDir\src\ui\images\tray_icon.ico"
        }

        $TargetExe = $UiBinary
        if (-not (Test-Path $TargetExe)) {
            $TargetExe = "$InstallDir\bin\select-to-speech-gui.bat"
        }

        $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = $TargetExe
        $Shortcut.WorkingDirectory = $InstallDir
        $Shortcut.Description = "Select-to-Speech Accessibility App"
        if (Test-Path $IconPath) {
            $Shortcut.IconLocation = "$IconPath,0"
        }
        $Shortcut.Save()
        Write-Info "Created Start Menu shortcut: $ShortcutPath"

        # Autostart shortcut if requested
        if (-not $NoAutoStart) {
            $StartupDir = [System.IO.Path]::Combine($env:APPDATA, "Microsoft\Windows\Start Menu\Programs\Startup")
            $StartupShortcutPath = Join-Path $StartupDir "Select-to-Speech.lnk"
            $StartupShortcut = $WshShell.CreateShortcut($StartupShortcutPath)
            $StartupShortcut.TargetPath = $TargetExe
            $StartupShortcut.WorkingDirectory = $InstallDir
            if (Test-Path $IconPath) {
                $StartupShortcut.IconLocation = "$IconPath,0"
            }
            $StartupShortcut.Save()
            Write-Info "Added to Windows Startup: $StartupShortcutPath"
        }
    } catch {
        Write-Warn "Could not create Windows shortcuts: $_"
    }
}

# ── 5. System Check ──────────────────────────────────────────────────────────────
Write-Host ""
Write-Info "Running Windows system dependencies check..."
uv run --project "$InstallDir" select-to-speech-check

Write-Host ""
Write-Info "Installation complete!"
Write-Host ""
Write-Host "  To launch the GUI:       .\bin\select-to-speech-gui.bat (or search in Start Menu)"
Write-Host "  To run daemon only:      uv run select-to-speech"
Write-Host "  To check dependencies:   uv run select-to-speech-check"
Write-Host ""
