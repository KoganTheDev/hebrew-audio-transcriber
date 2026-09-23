# Launcher for the Hebrew Audio Transcriber.
# Works both from a terminal (.\run.ps1) and from double-click.
#
# Design rules:
#   - Never fail invisibly: every failure is printed in red, the window is
#     held open with a Read-Host, and the reason is appended to
#     launcher-log.txt next to this script.
#   - Never trust PATH's "python" blindly: on many machines it is the
#     Microsoft Store alias (under \WindowsApps\), which only prints an ad
#     and exits.
#   - Never silently launch on system Python when .venv is missing. That used
#     to fall through to "py"/PATH python/a guessed per-user install, which
#     has none of the project's dependencies - the user then sees a
#     "Missing required packages" error from deep inside the app with no
#     indication the real problem is "you never created .venv". Missing
#     .venv is now a loud, immediate failure with setup instructions, unless
#     -Setup is passed.

param(
    [switch]$Setup
)

$ErrorActionPreference = 'Stop'

# Resolve the project folder even in hosts where $PSScriptRoot is empty.
$root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$logFile = Join-Path $root 'launcher-log.txt'

function Fail([string]$message) {
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    try { "$stamp  $message" | Add-Content -Path $logFile -Encoding UTF8 } catch {}
    Write-Host ''
    Write-Host "ERROR: $message" -ForegroundColor Red
    Write-Host "(also written to $logFile)" -ForegroundColor DarkGray
    Read-Host 'Press Enter to close'
    exit 1
}

try {
    Set-Location $root
    Write-Host 'Starting Hebrew Audio Transcriber...' -ForegroundColor Green

    # Check the package is actually here before handing over to Python.
    # Without this the failure is "ImportError: cannot import name 'config'
    # from 'speech_to_text' (unknown location)", which means Python found a
    # DIRECTORY called speech_to_text with no __init__.py in it and treated it
    # as a namespace package. That is what an incomplete copy looks like - a
    # half-finished OneDrive sync, a partial download, or a folder copied
    # while files were open - and the raw traceback tells a user nothing.
    $pkgInit = Join-Path $root 'src\speech_to_text\__init__.py'
    if (-not (Test-Path $pkgInit)) {
        $stale = Join-Path $root 'speech_to_text'
        $hint = if (Test-Path $stale) {
            "There is an old 'speech_to_text' folder here from a previous version, but the current 'src\speech_to_text' is missing."
        } else {
            "Expected to find: $pkgInit"
        }
        Fail @"
This copy of the app is incomplete - the program files are missing.

$hint

To fix it, get a fresh copy of the whole folder:
  - If you downloaded a ZIP, download it again and extract ALL of it.
  - If OneDrive is still syncing, wait for it to finish (the folder icon
    should be a green tick, not blue arrows), then try again.
  - If you use git: run 'git pull' inside this folder.
"@
    }

    # The project's own virtual environment is the ONLY interpreter this
    # launcher will run the app on. Without this the launcher could pick a
    # system Python that has none of the dependencies, and the failure is
    # bewildering: the startup check only reports missing packages, several
    # layers removed from the real cause ("you never created .venv"). A user
    # who followed the README and made a .venv gets every dependency sitting
    # right there; anyone else is told to do that, loudly, right now -
    # never silently handed a system Python instead.
    $venvPython = Join-Path $root '.venv\Scripts\python.exe'

    if ($Setup) {
        Write-Host 'Setting up .venv...' -ForegroundColor Green
        $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
        if ($pyLauncher) {
            & $pyLauncher.Source -3 -m venv (Join-Path $root '.venv')
        }
        else {
            $python = Get-Command python -ErrorAction SilentlyContinue
            if (-not $python -or $python.Source -like '*\WindowsApps\*') {
                Fail "No Python installation found (checked 'py' and 'python'). Install Python 3.9+ from https://www.python.org/downloads/"
            }
            & $python.Source -m venv (Join-Path $root '.venv')
        }
        if (-not (Test-Path $venvPython)) {
            Fail "Creating .venv failed - see the output above."
        }
        & $venvPython -m pip install -e $root
        if ($LASTEXITCODE -ne 0) {
            Fail "Installing dependencies into .venv failed (exit code $LASTEXITCODE) - see the output above."
        }
        Write-Host '.venv is ready.' -ForegroundColor Green
    }

    if (-not (Test-Path $venvPython)) {
        Fail @"
No .venv found for this project - the app has not been set up yet.

To fix it, from this folder run:
  python -m venv .venv
  .venv\Scripts\pip install -e .

Or let this launcher do it for you:
  run.ps1 -Setup
"@
    }

    $exe = $venvPython
    $exeArgs = @()

    Write-Host "Using: $exe $($exeArgs -join ' ') -m speech_to_text.main" -ForegroundColor DarkGray

    # The console's output code page defaults to the system's legacy one
    # (often 862/1255 on a Hebrew locale, 437/1252 elsewhere), not UTF-8 -
    # the app's DEBUG log prints Hebrew segment text straight to this
    # console, and on a non-UTF-8 page that renders as mojibake or "?".
    # Setting [Console]::OutputEncoding is PowerShell's equivalent of
    # run.bat's "chcp 65001": on Windows it calls SetConsoleOutputCP under
    # the hood, so it changes the same thing chcp changes, without shelling
    # out to chcp.com or its "Active code page: ..." echo. Restored in
    # finally so the launcher doesn't leave the user's console in a
    # different state than it found it.
    # src-layout: the package lives in src/, which is not on sys.path just
    # because the repo root is the working directory. Pointing PYTHONPATH at
    # it keeps this launcher a double-click affair with no install step.
    $env:PYTHONPATH = Join-Path $PSScriptRoot 'src'

    $prevOutputEncoding = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        & $exe @exeArgs -m speech_to_text.main
    }
    finally {
        [Console]::OutputEncoding = $prevOutputEncoding
    }

    if ($LASTEXITCODE -ne 0) {
        Fail "The app exited with code $LASTEXITCODE - scroll up or check speech_to_text.log for details."
    }
}
catch {
    Fail $_.Exception.Message
}
