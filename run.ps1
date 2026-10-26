<#
.SYNOPSIS
    Set up the Python environment if needed, then start the calculator GUI.

.DESCRIPTION
    Keeps a private environment in .venv next to this script:
      * first run: creates .venv from a Python 3.10+ interpreter
        (-Python, else the py launcher / python on PATH, else conda/miniforge with python 3.12)
      * whenever requirements.txt changes: installs it into .venv
      * a broken .venv (e.g. its base Python was uninstalled) is rebuilt
    Then launches main.py with pythonw (no console window).

.PARAMETER Python
    Path to the python.exe (3.10+) to build .venv from.

.PARAMETER Reinstall
    Delete .venv and build it again.

.PARAMETER SetupOnly
    Prepare the environment but do not start the GUI.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\run.ps1

.EXAMPLE
    .\run.ps1 -Python C:\Python312\python.exe -Reinstall
#>
[CmdletBinding()]
param(
    [string]$Python,
    [switch]$Reinstall,
    [switch]$SetupOnly
)

# Native tools (pip, conda) write progress to stderr; check exit codes instead of
# letting PowerShell turn stderr into terminating errors.
$ErrorActionPreference = 'Continue'

$Root = $PSScriptRoot
$EnvDir = Join-Path $Root '.venv'
$Requirements = Join-Path $Root 'requirements.txt'
$Stamp = Join-Path $EnvDir '.requirements.sha256'
$MainScript = Join-Path $Root 'main.py'
$MinVersion = [version]'3.10'
$CondaPythonVersion = '3.12'
$PreferredVersions = @('3.12', '3.13', '3.11', '3.10')

# Launched as its own console ("Run with PowerShell" / powershell -File): keep the
# window open on errors so the message can be read.
$OwnConsole = ([Environment]::GetCommandLineArgs() -join ' ') -match [regex]::Escape((Split-Path -Leaf $PSCommandPath))

function Write-Step([string]$Text) {
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Stop-WithError([string]$Text) {
    Write-Host "ERROR: $Text" -ForegroundColor Red
    if ($OwnConsole) {
        Read-Host 'Press Enter to close' | Out-Null
    }
    exit 1
}

# Returns @{ Version; Path; IsConda } when the interpreter runs and is new enough, else $null.
function Test-Interpreter([string]$Exe, [string[]]$PrefixArgs = @()) {
    try {
        $out = & $Exe @PrefixArgs -c "import sys, venv; print('%d.%d' % sys.version_info[:2]); print(sys.executable); print(sys.base_prefix)" 2>$null
    } catch {
        return $null
    }
    if ($LASTEXITCODE -ne 0 -or $null -eq $out -or @($out).Count -lt 3) {
        return $null
    }
    $out = @($out)
    if ([version]$out[0] -lt $MinVersion) {
        return $null
    }
    return @{ Version = $out[0]; Path = $out[1]; IsConda = (Test-Path (Join-Path $out[2] 'conda-meta')) }
}

# A venv built on a conda Python still loads DLLs from that conda install, and conda's
# own Qt (e.g. from a PySide6/pyqt conda package) breaks the PyQt6 wheel. Conda users get
# a fresh conda env instead (see New-Environment), so conda interpreters are skipped here.
function Find-BasePython {
    if (Get-Command py -CommandType Application -ErrorAction SilentlyContinue) {
        foreach ($v in $PreferredVersions) {
            $found = Test-Interpreter 'py' @("-$v")
            if ($found -and -not $found.IsConda) { return $found }
        }
        $found = Test-Interpreter 'py' @('-3')
        if ($found -and -not $found.IsConda) { return $found }
    }

    foreach ($name in @('python', 'python3')) {
        # The Microsoft Store "python.exe" stub fails the probe and is skipped.
        foreach ($cmd in @(Get-Command $name -CommandType Application -All -ErrorAction SilentlyContinue)) {
            $found = Test-Interpreter $cmd.Source
            if ($found -and -not $found.IsConda) { return $found }
        }
    }
    return $null
}

function Find-Conda {
    $candidates = @()
    if ($env:CONDA_EXE) { $candidates += $env:CONDA_EXE }
    foreach ($cmd in @(Get-Command conda.exe -CommandType Application -All -ErrorAction SilentlyContinue)) {
        $candidates += $cmd.Source
    }
    foreach ($base in @($env:USERPROFILE, $env:LOCALAPPDATA, $env:ProgramData)) {
        if (-not $base) { continue }
        foreach ($dist in @('miniforge3', 'mambaforge', 'miniconda3', 'anaconda3')) {
            $candidates += Join-Path $base "$dist\Scripts\conda.exe"
        }
    }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    return $null
}

function Get-EnvExe([string]$Name) {
    # venv layout: .venv\Scripts\python.exe; conda prefix layout: .venv\python.exe
    foreach ($relative in @("Scripts\$Name", $Name)) {
        $path = Join-Path $EnvDir $relative
        if (Test-Path $path) { return $path }
    }
    return $null
}

function New-Environment {
    if ($Python) {
        $base = Test-Interpreter $Python
        if (-not $base) {
            Stop-WithError "'$Python' is not a working Python $MinVersion+ interpreter."
        }
    } else {
        $base = Find-BasePython
    }

    if ($base) {
        Write-Step "Creating .venv with Python $($base.Version) ($($base.Path))"
        & $base.Path -m venv $EnvDir
        if ($LASTEXITCODE -ne 0) { Stop-WithError 'python -m venv failed (see messages above).' }
        return
    }

    $conda = Find-Conda
    if ($conda) {
        Write-Step "No standalone Python $MinVersion+ found; creating .venv with conda ($conda), python=$CondaPythonVersion"
        & $conda create --yes --prefix $EnvDir "python=$CondaPythonVersion" pip
        if ($LASTEXITCODE -ne 0) { Stop-WithError 'conda create failed (see messages above).' }
        return
    }

    Stop-WithError ("No Python $MinVersion+ found. Install Python 3.12 from https://www.python.org/downloads/ " +
        "(or: winget install Python.Python.3.12), then run this script again. " +
        "You can also point to an interpreter with -Python C:\path\to\python.exe")
}

if (-not (Test-Path $Requirements)) {
    Stop-WithError "requirements.txt not found next to $(Split-Path -Leaf $PSCommandPath)."
}

if ($Reinstall -and (Test-Path $EnvDir)) {
    Write-Step 'Removing .venv'
    Remove-Item -Recurse -Force $EnvDir
}

$envPython = Get-EnvExe 'python.exe'
if ($envPython -and -not (Test-Interpreter $envPython)) {
    Write-Step '.venv is broken (its base Python may have moved); rebuilding it'
    Remove-Item -Recurse -Force $EnvDir
    $envPython = $null
}

if (-not $envPython) {
    New-Environment
    $envPython = Get-EnvExe 'python.exe'
    if (-not $envPython) { Stop-WithError "Environment was created but no python.exe was found in $EnvDir." }
}

$wanted = (Get-FileHash -Algorithm SHA256 $Requirements).Hash
$installed = if (Test-Path $Stamp) { (Get-Content $Stamp -Raw).Trim() } else { '' }

if ($wanted -ne $installed) {
    Write-Step 'Installing requirements.txt into .venv'
    & $envPython -m pip install --disable-pip-version-check --no-warn-script-location -r $Requirements
    if ($LASTEXITCODE -ne 0) { Stop-WithError 'pip install failed (see messages above).' }

    & $envPython -c "import PyQt6.QtWidgets, matplotlib, numpy, yfinance, zoneinfo; zoneinfo.ZoneInfo('America/New_York')"
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError ('Packages installed but failed to import (see messages above). ' +
            'If -Python pointed at a conda Python, run again with -Reinstall and without -Python.')
    }

    Set-Content -Path $Stamp -Value $wanted -Encoding Ascii
    Write-Step 'Environment ready'
}

if ($SetupOnly) {
    exit 0
}

$pythonw = Get-EnvExe 'pythonw.exe'
if (-not $pythonw) { Stop-WithError "pythonw.exe not found in $EnvDir." }

Start-Process -FilePath $pythonw -ArgumentList "`"$MainScript`"" -WorkingDirectory $Root
