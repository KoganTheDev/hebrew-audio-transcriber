@echo off
REM Simple batch script to run the Speech-to-Text Transcriber
REM This script automatically sets up the Python path and runs the app

setlocal enabledelayedexpansion
cd /d "%~dp0"

REM cmd.exe inherits the system's default code page (often 862/1255 on a
REM Hebrew locale, 437/1252 elsewhere), not UTF-8 - the app's DEBUG log
REM prints Hebrew segment text straight to stdout, and on a non-UTF-8 page
REM that renders as mojibake or "?" instead of readable Hebrew. Switch to
REM UTF-8 (65001) for the run and switch back after, so we don't leave the
REM user's console in a different state than we found it. "chcp" normally
REM echoes "Active code page: ..." on both calls; >nul suppresses that so a
REM normal launch prints nothing extra.
for /f "tokens=2 delims=:" %%p in ('chcp') do set "_prev_codepage=%%p"
set "_prev_codepage=%_prev_codepage: =%"
chcp 65001 >nul

REM Check the program files are actually here before handing over to Python.
REM Without this the failure is a bare "can't open file 'src\app.py'", or
REM worse a ModuleNotFoundError from halfway through startup. That is what an
REM incomplete copy looks like - a half-finished OneDrive sync, a partial
REM download, or a folder copied while files were open - and neither message
REM tells a user anything they can act on.
if not exist "%~dp0src\app.py" (
    echo.
    echo ERROR: This copy of the app is incomplete - the program files are missing.
    echo.
    if exist "%~dp0src\speech_to_text" (
        echo This folder still has the old "src\speech_to_text" layout. The
        echo modules moved up to "src\" directly, so this copy is from before
        echo that change and only half-updated - a "git pull" that could not
        echo overwrite a file, most likely.
    ) else (
        echo Expected to find: %~dp0src\app.py
    )
    echo.
    echo To fix it, get a fresh copy of the whole folder:
    echo   - If you downloaded a ZIP, download it again and extract ALL of it.
    echo   - If OneDrive is still syncing, wait for it to finish, then try again.
    echo   - If you use git: run "git pull" inside this folder.
    echo.
    pause
    exit /b 1
)

REM app.py puts src/ on sys.path itself; this covers what it SPAWNS - the
REM worker process inherits the environment, not an in-process edit.
set "PYTHONPATH=%~dp0src"

if /i "%~1"=="setup" goto :setup_venv
goto :after_setup

:setup_venv
echo Setting up .venv...

REM "py -3" hands back whatever the default 3.x is, and pyproject needs
REM >=3.10. The venv builds fine on 3.9, so without this check the failure
REM lands one step later out of pip, reading like a broken project rather
REM than a stale interpreter.
where py >nul 2>nul
if %errorlevel%==0 (
    set "_boot=py -3"
) else (
    set "_boot=python"
)
for /f "delims=" %%v in ('%_boot% -c "import sys; print('%%d.%%d' %% sys.version_info[:2])" 2^>nul') do set "_pyver=%%v"
if not defined _pyver (
    echo.
    echo ERROR: No working Python found ^(checked "py" and "python"^).
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
for /f "tokens=1,2 delims=." %%a in ("%_pyver%") do (
    set "_pymajor=%%a"
    set "_pyminor=%%b"
)
if !_pymajor! lss 3 goto :old_python
if !_pymajor! equ 3 if !_pyminor! lss 10 goto :old_python
goto :python_ok

:old_python
echo.
echo ERROR: This project needs Python 3.10 or newer, but the Python on this
echo machine is %_pyver%.
echo.
echo Install a current Python from https://www.python.org/downloads/
echo ^(tick "Add python.exe to PATH" in the installer^), then run
echo "run.bat setup" again.
echo.
pause
exit /b 1

:python_ok
echo Using Python %_pyver%

REM "python -m venv" onto a half-created .venv repairs some of it and
REM leaves the rest, so start clean instead.
if exist "%~dp0.venv" if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Removing an incomplete .venv from an earlier attempt...
    rmdir /s /q "%~dp0.venv"
)

%_boot% -m venv "%~dp0.venv"
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo.
    echo ERROR: Creating .venv failed - see the output above.
    echo.
    pause
    exit /b 1
)

REM A fresh venv carries the interpreter's bundled pip - 22.3 on Python
REM 3.11.0, which aborts long installs on Windows with "OSError: [Errno 2]
REM ... pip-build-tracker-xxxx". This project pulls ~120 MB of wheels, so it
REM sits in that window every time.
"%~dp0.venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if not !errorlevel!==0 (
    echo.
    echo ERROR: Upgrading pip inside .venv failed - see the output above.
    echo.
    pause
    exit /b 1
)

REM Scratch space outside %%TEMP%%: the tracker failure above is triggered
REM by Storage Sense, Disk Cleanup or antivirus emptying it mid-install,
REM which a newer pip does not prevent.
set "_prev_temp=%TEMP%"
set "_prev_tmp=%TMP%"
mkdir "%~dp0.venv\pip-tmp" 2>nul
set "TEMP=%~dp0.venv\pip-tmp"
set "TMP=%~dp0.venv\pip-tmp"
"%~dp0.venv\Scripts\python.exe" -m pip install -e "%~dp0"
set "_pipcode=!errorlevel!"
set "TEMP=%_prev_temp%"
set "TMP=%_prev_tmp%"
rmdir /s /q "%~dp0.venv\pip-tmp" 2>nul
if not "!_pipcode!"=="0" (
    echo.
    echo ERROR: Installing dependencies into .venv failed - see the output above.
    echo.
    pause
    exit /b 1
)

REM A wheel can unpack without its DLLs landing, which surfaces much later
REM as an ImportError from inside the GUI. Catch it here, while the user is
REM still expecting setup problems.
"%~dp0.venv\Scripts\python.exe" -c "import PyQt5, faster_whisper, sherpa_onnx, av, psutil, tqdm"
if not !errorlevel!==0 (
    echo.
    echo ERROR: Setup finished but the installed packages do not import - see
    echo the error above. Deleting the .venv folder and running "run.bat setup"
    echo again usually clears this.
    echo.
    pause
    exit /b 1
)

echo .venv is ready.
:after_setup

REM The project's own virtual environment is the ONLY interpreter this
REM launcher will run the app on. Without this the launcher could silently
REM fall back to system Python, which has none of the dependencies - the
REM user then sees a "Missing required packages" error from deep inside the
REM app with no indication the real problem is "you never created .venv".
REM No .venv: offer to build one rather than dead-ending. The prompt is
REM delegated to run.ps1 so the app-coloured version exists once, in the one
REM language that can set console colours per line; cmd can only recolour the
REM whole window. Falls back to a plain prompt if PowerShell will not run.
if not exist "%~dp0.venv\Scripts\python.exe" (
    where powershell >nul 2>nul
    if !errorlevel!==0 (
        powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
        set "_setupcode=!errorlevel!"
    ) else (
        echo.
        echo Hebrew Audio Transcriber - first-time setup
        echo.
        echo This needs to download about 120 MB of components.
        echo It runs once, takes a few minutes, and everything
        echo lands in this folder.
        echo.
        echo Press Enter to begin, or close this window to cancel.
        pause >nul
        call "%~dp0run.bat" setup
        set "_setupcode=!errorlevel!"
    )
    if not "!_setupcode!"=="0" exit /b !_setupcode!
    REM run.ps1 launches the app itself once setup finishes, so there is
    REM nothing left for this script to start.
    exit /b 0
)

"%~dp0.venv\Scripts\python.exe" "%~dp0src\app.py"
set "_exitcode=%errorlevel%"
if defined _prev_codepage chcp %_prev_codepage% >nul
REM Hold the window open only when something actually failed - a normal
REM close of the app (exit code 0) should let the console go away too.
REM Checked via %_exitcode%, captured above, rather than %errorlevel% -
REM the chcp restore on the previous line would otherwise overwrite it.
if not "%_exitcode%"=="0" (
    echo.
    echo The app exited with an error - see the messages above or speech_to_text.log
    pause
)
