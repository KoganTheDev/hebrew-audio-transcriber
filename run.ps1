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

    # Check the program files are actually here before handing over to Python.
    # Without this the failure is a bare "can't open file 'src\main.py'", or
    # worse a ModuleNotFoundError from halfway through startup. That is what
    # an incomplete copy looks like - a half-finished OneDrive sync, a partial
    # download, or a folder copied while files were open - and neither message
    # tells a user anything they can act on.
    $entryPoint = Join-Path $root 'src\main.py'
    if (-not (Test-Path $entryPoint)) {
        $stale = Join-Path $root 'src\speech_to_text'
        $hint = if (Test-Path $stale) {
            "This folder still has the old 'src\speech_to_text' layout. The modules moved up to 'src\' directly, so this copy is from before that change and only half-updated - a 'git pull' that could not overwrite a file, most likely."
        } else {
            "Expected to find: $entryPoint"
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

    $venvDir = Join-Path $root '.venv'

    if ($Setup) {
        Write-Host 'Setting up .venv...' -ForegroundColor Green

        # Pick the interpreter that will BUILD the venv, then check its
        # version before using it. pyproject requires >=3.10, but "py -3"
        # hands back whatever the machine's default 3.x is - on an older
        # install that is 3.8 or 3.9. The venv itself creates fine on those,
        # so the failure lands one step later, out of pip, as "package
        # requires a different Python version", which reads like a broken
        # project rather than a stale interpreter.
        $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
        if ($pyLauncher) {
            $bootExe = $pyLauncher.Source
            $bootArgs = @('-3')
        }
        else {
            $python = Get-Command python -ErrorAction SilentlyContinue
            if (-not $python -or $python.Source -like '*\WindowsApps\*') {
                Fail "No Python installation found (checked 'py' and 'python'). Install Python 3.10+ from https://www.python.org/downloads/"
            }
            $bootExe = $python.Source
            $bootArgs = @()
        }

        # stderr is folded in so a failing interpreter reports WHY in the
        # error below rather than just an exit code, and the version is then
        # pulled out by pattern rather than by reading the whole stream -
        # 'py' prints its own warnings there ("Python from the Microsoft
        # Store...", venv deprecation notices), and treating those as the
        # version number would reject a perfectly good 3.12.
        $bootOutput = (& $bootExe @bootArgs -c "import sys; print('PYVER %d.%d' % sys.version_info[:2])" 2>&1 | Out-String)
        $match = [regex]::Match($bootOutput, 'PYVER (\d+)\.(\d+)')
        if ($LASTEXITCODE -ne 0 -or -not $match.Success) {
            Fail "Could not run Python ($bootExe) to check its version. Output was:`n$bootOutput"
        }
        $bootVersion = "$($match.Groups[1].Value).$($match.Groups[2].Value)"
        if ([int]$match.Groups[1].Value -lt 3 -or ([int]$match.Groups[1].Value -eq 3 -and [int]$match.Groups[2].Value -lt 10)) {
            Fail @"
This project needs Python 3.10 or newer, but the Python on this machine is $bootVersion ($bootExe).

Install a current Python from https://www.python.org/downloads/ (tick
"Add python.exe to PATH" in the installer), then run 'run.ps1 -Setup' again.
"@
        }
        Write-Host "Using Python $bootVersion from $bootExe" -ForegroundColor DarkGray

        # A .venv folder with no python.exe in it is a half-created one - an
        # interrupted setup, or an interpreter that has since been
        # uninstalled. 'python -m venv' onto that path repairs some of it and
        # leaves the rest, so clear it out and start clean instead.
        if ((Test-Path $venvDir) -and -not (Test-Path $venvPython)) {
            Write-Host 'Removing an incomplete .venv from an earlier attempt...' -ForegroundColor DarkGray
            Remove-Item -Recurse -Force $venvDir -ErrorAction SilentlyContinue
        }

        & $bootExe @bootArgs -m venv $venvDir
        if (-not (Test-Path $venvPython)) {
            Fail "Creating .venv failed - see the output above."
        }

        # A fresh venv ships whatever pip was bundled with the interpreter.
        # On Python 3.11.0 that is pip 22.3, and pip 22.x has a Windows bug
        # where the build-tracker directory it keeps under %TEMP% disappears
        # part way through a long install, ending the run with
        #   ERROR: Could not install packages due to an OSError: [Errno 2]
        #   No such file or directory: '...\pip-build-tracker-xxxx\<hash>'
        # This project pulls ~120 MB of wheels (PyQt5-Qt5 alone is 50 MB), so
        # an install here runs for minutes and sits squarely in that window.
        # Upgrading pip first is the fix, and it also brings a resolver that
        # understands the metadata newer wheels publish.
        & $venvPython -m pip install --upgrade pip setuptools wheel
        if ($LASTEXITCODE -ne 0) {
            Fail "Upgrading pip inside .venv failed (exit code $LASTEXITCODE) - see the output above."
        }

        # Give pip its own scratch directory next to the venv instead of
        # %TEMP%. The tracker failure above is triggered by something else
        # emptying %TEMP% mid-install - Storage Sense, Disk Cleanup, or an
        # antivirus scanner - which a newer pip does not prevent. A folder
        # inside the project is not a target for any of them. Removed after.
        $pipTemp = Join-Path $venvDir 'pip-tmp'
        New-Item -ItemType Directory -Force -Path $pipTemp | Out-Null
        $prevTemp = $env:TEMP
        $prevTmp = $env:TMP
        try {
            $env:TEMP = $pipTemp
            $env:TMP = $pipTemp
            & $venvPython -m pip install -e $root
        }
        finally {
            $env:TEMP = $prevTemp
            $env:TMP = $prevTmp
            Remove-Item -Recurse -Force $pipTemp -ErrorAction SilentlyContinue
        }
        if ($LASTEXITCODE -ne 0) {
            Fail "Installing dependencies into .venv failed (exit code $LASTEXITCODE) - see the output above."
        }

        # pip reporting success is not the same as the app being able to
        # start: a wheel can unpack without its DLLs landing, which surfaces
        # much later as an ImportError from inside the GUI. Import every
        # top-level dependency now, while the setup output is still on screen
        # and the user is expecting setup problems.
        & $venvPython -c "import PyQt5, faster_whisper, sherpa_onnx, av, psutil, tqdm"
        if ($LASTEXITCODE -ne 0) {
            Fail "Setup finished but the installed packages do not import (exit code $LASTEXITCODE) - see the error above. Deleting the .venv folder and running 'run.ps1 -Setup' again usually clears this."
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

    Write-Host "Using: $exe $($exeArgs -join ' ') $entryPoint" -ForegroundColor DarkGray

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
    # config/, core/ and gui/ live in src/, which is not on sys.path just
    # because the repo root is the working directory. Pointing PYTHONPATH at
    # it keeps this launcher a double-click affair with no install step.
    # main.py puts its own directory on sys.path too, so this is
    # belt-and-braces for anything it spawns (the transcription worker
    # inherits the environment, not main.py's in-process edit).
    # $root, not $PSScriptRoot: the two are the same from a terminal, but
    # $PSScriptRoot is empty in some double-click hosts, and Join-Path on an
    # empty path throws - turning a working launch into a parameter-binding
    # error reported as if the app itself had failed. $root already has the
    # fallback for that case.
    $env:PYTHONPATH = Join-Path $root 'src'

    $prevOutputEncoding = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        & $exe @exeArgs $entryPoint
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
