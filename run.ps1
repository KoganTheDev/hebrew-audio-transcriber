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
#   - Never silently launch on system Python: it has none of the project's
#     dependencies, and the user then sees "Missing required packages" from
#     deep inside the app rather than the real cause. With no .venv this
#     offers to build one; with -Setup it skips the prompt.

param(
    [switch]$Setup
)

$ErrorActionPreference = 'Stop'

# Resolve the project folder even in hosts where $PSScriptRoot is empty.
$root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$logFile = Join-Path $root 'launcher-log.txt'

# The app's own palette (gui/theme.py COLORS, Catppuccin Mocha), by role, so
# the setup window and the app it installs look like one product. A Qt window
# is not an option here - PyQt5 is one of the things being installed.
$Palette = @{
    accent    = '250;179;135'  # peach    - headings
    text      = '205;214;244'  # text     - body
    caption   = '147;153;178'  # overlay2 - secondary lines
    success   = '166;227;161'  # green
    error     = '243;139;168'  # red
}
# Console colours to fall back on, in the same roles.
$PaletteFallback = @{
    accent = 'Yellow'; text = 'White'; caption = 'DarkGray'
    success = 'Green'; error = 'Red'
}

# 24-bit ANSI needs ENABLE_VIRTUAL_TERMINAL_PROCESSING, which is not reliably
# on in conhost. Turn it on, and fall back to the 16 console colours if that
# fails - printing raw escapes at a user is worse than printing no colour.
$script:UseAnsi = $false

try {
    if (-not ('VTConsole' -as [type])) {
        Add-Type -Namespace Native -Name VTConsole -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true)]
public static extern IntPtr GetStdHandle(int nStdHandle);
[DllImport("kernel32.dll", SetLastError = true)]
public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);
[DllImport("kernel32.dll", SetLastError = true)]
public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);
'@ -ErrorAction Stop
    }
    $handle = [Native.VTConsole]::GetStdHandle(-11)
    $mode = 0
    if ([Native.VTConsole]::GetConsoleMode($handle, [ref]$mode)) {
        $script:UseAnsi = [Native.VTConsole]::SetConsoleMode($handle, $mode -bor 0x0004)
    }
}
catch {
    $script:UseAnsi = $false
}
# Windows Terminal and most IDE consoles already render VT even when the
# handle call above cannot be made.
if (-not $script:UseAnsi -and ($env:WT_SESSION -or $env:TERM_PROGRAM)) { $script:UseAnsi = $true }

function Write-Themed([string]$text, [string]$role = 'text') {
    if ($script:UseAnsi) {
        $esc = [char]27
        Write-Host "$esc[38;2;$($Palette[$role])m$text$esc[0m"
    }
    else {
        Write-Host $text -ForegroundColor $PaletteFallback[$role]
    }
}

function Fail([string]$message) {
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    try { "$stamp  $message" | Add-Content -Path $logFile -Encoding UTF8 } catch {}
    Write-Host ''
    Write-Host "ERROR: $message" -ForegroundColor Red
    Write-Host "(also written to $logFile)" -ForegroundColor DarkGray
    Read-Host 'Press Enter to close'
    exit 1
}

function Invoke-Setup {
    Write-Host 'Setting up .venv...' -ForegroundColor Green

    # "py -3" hands back whatever the default 3.x is, and pyproject
    # needs >=3.10. The venv builds fine on 3.9, so without this check the
    # failure lands one step later out of pip, reading like a broken
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

    # stderr folded in so a failure reports why, but the version is
    # matched by pattern: 'py' prints its own warnings there, and reading
    # the whole stream would reject a perfectly good 3.12.
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

    # 'python -m venv' onto a half-created .venv repairs some of it and
    # leaves the rest, so start clean instead.
    if ((Test-Path $venvDir) -and -not (Test-Path $venvPython)) {
        Write-Host 'Removing an incomplete .venv from an earlier attempt...' -ForegroundColor DarkGray
        Remove-Item -Recurse -Force $venvDir -ErrorAction SilentlyContinue
    }

    & $bootExe @bootArgs -m venv $venvDir
    if (-not (Test-Path $venvPython)) {
        Fail "Creating .venv failed - see the output above."
    }

    # A fresh venv carries the interpreter's bundled pip - 22.3 on
    # Python 3.11.0, which aborts long installs on Windows with
    # "OSError: [Errno 2] ... pip-build-tracker-xxxx". This project pulls
    # ~120 MB of wheels, so it sits in that window every time.
    & $venvPython -m pip install --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) {
        Fail "Upgrading pip inside .venv failed (exit code $LASTEXITCODE) - see the output above."
    }

    # Scratch space outside %TEMP%: the tracker failure above is
    # triggered by Storage Sense, Disk Cleanup or antivirus emptying it
    # mid-install, which a newer pip does not prevent.
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

    # A wheel can unpack without its DLLs landing, which surfaces much
    # later as an ImportError from inside the GUI. Catch it here, while
    # the user is still expecting setup problems.
    & $venvPython -c "import PyQt5, faster_whisper, sherpa_onnx, av, psutil, tqdm"
    if ($LASTEXITCODE -ne 0) {
        Fail "Setup finished but the installed packages do not import (exit code $LASTEXITCODE) - see the error above. Deleting the .venv folder and running 'run.ps1 -Setup' again usually clears this."
    }

    Write-Host '.venv is ready.' -ForegroundColor Green
}

try {
    Set-Location $root
    Write-Host 'Starting Hebrew Audio Transcriber...' -ForegroundColor Green

    # Check the program files are actually here before handing over to Python.
    # Without this the failure is a bare "can't open file 'src\app.py'", or
    # worse a ModuleNotFoundError from halfway through startup. That is what
    # an incomplete copy looks like - a half-finished OneDrive sync, a partial
    # download, or a folder copied while files were open - and neither message
    # tells a user anything they can act on.
    $entryPoint = Join-Path $root 'src\app.py'
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

    if ($Setup) { Invoke-Setup }

    # No .venv: offer to build one rather than dead-ending. This used to be a
    # hard failure with instructions, which is correct and still leaves a
    # non-technical user stuck - the app is for people transcribing audio, not
    # for people who want to read about virtual environments.
    if (-not (Test-Path $venvPython)) {
        # A non-interactive host cannot answer, and Read-Host there either
        # throws or blocks forever. Keep the old failure for that case.
        if (-not [Environment]::UserInteractive -or [Console]::IsInputRedirected) {
            Fail @"
No .venv found for this project - the app has not been set up yet.

To set it up, from this folder run:
  run.ps1 -Setup
"@
        }

        Write-Host ''
        Write-Themed 'Hebrew Audio Transcriber - first-time setup' 'accent'
        Write-Host ''
        Write-Themed 'This needs to download about 120 MB of components.' 'text'
        Write-Themed 'It runs once, takes a few minutes, and everything' 'text'
        Write-Themed 'lands in this folder.' 'text'
        Write-Host ''
        Write-Themed 'Press Enter to begin, or close this window to cancel.' 'caption'
        [void](Read-Host)
        Write-Host ''
        Invoke-Setup
    }

    # pythonw.exe, not python.exe: pythonw is the GUI-subsystem interpreter,
    # so Windows attaches no console and the end user never sees a black
    # window they cannot interpret. Falls back to python.exe if a venv somehow
    # lacks it - a visible console beats not starting at all.
    #
    # Startup failures stay visible without it: app.py's fatal() raises a
    # native message box for anything that goes wrong before Qt exists, and
    # gui/crash_handler.py covers everything after. Nothing is allowed to fail
    # silently just because nobody is watching a console.
    $venvPythonw = Join-Path (Split-Path $venvPython -Parent) 'pythonw.exe'
    $exe = if (Test-Path $venvPythonw) { $venvPythonw } else { $venvPython }
    $exeArgs = @()

    Write-Host "Using: $exe $($exeArgs -join ' ') $entryPoint" -ForegroundColor DarkGray

    # The [Console]::OutputEncoding dance that used to sit here is gone with
    # the console it existed for: it forced UTF-8 so the app's Hebrew DEBUG
    # lines did not render as mojibake on a legacy code page. Nothing prints
    # to a console any more, and the log file was always written in UTF-8
    # independently of it.
    #
    # app.py puts src/ on sys.path itself; this covers what it SPAWNS - the
    # worker process inherits the environment, not an in-process edit.
    # $root, not $PSScriptRoot: the latter is empty in some double-click
    # hosts, and Join-Path then throws.
    $env:PYTHONPATH = Join-Path $root 'src'

    # Start-Process without -Wait, not the call operator: "& $exe ..." blocks
    # until the app exits, which would hold this console open for the whole
    # session - exactly the window this change exists to get rid of. Handing
    # off and returning lets the launcher close as soon as the app is up.
    #
    # The cost is that $LASTEXITCODE can no longer be checked here, and that
    # check is deliberately not replaced: it could only ever be READ by
    # someone watching a console, and there is no longer one to watch. app.py's
    # fatal() shows startup failures in a native message box and
    # gui/crash_handler.py shows later ones, both of which reach the user
    # whether or not a launcher is still running.
    $startArgs = @()
    $startArgs += $exeArgs
    $startArgs += $entryPoint
    Start-Process -FilePath $exe -ArgumentList $startArgs -WorkingDirectory $root
}
catch {
    Fail $_.Exception.Message
}
