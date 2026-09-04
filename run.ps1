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

    # 1st choice: the Windows "py" launcher - always points at a real Python.
    # 2nd choice: "python" on PATH, unless it is the Store alias.
    # 3rd choice: a python.exe from the standard per-user install location.
    $exe = $null
    $exeArgs = @()

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $exe = $py.Source
        $exeArgs = @('-3')
    }

    if (-not $exe) {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($python -and $python.Source -notlike '*\WindowsApps\*') {
            $exe = $python.Source
        }
    }

    if (-not $exe) {
        $guess = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($guess) { $exe = $guess.FullName }
    }

    if (-not $exe) {
        Fail "No Python installation found (checked 'py', 'python', and $env:LOCALAPPDATA\Programs\Python). Install Python 3.9+ from https://www.python.org/downloads/"
    }

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
