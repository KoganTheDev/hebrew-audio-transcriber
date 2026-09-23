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

REM Check the package is actually here before handing over to Python. Without
REM this the failure is "ImportError: cannot import name 'config' from
REM 'speech_to_text' (unknown location)", which means Python found a DIRECTORY
REM called speech_to_text with no __init__.py and treated it as a namespace
REM package. That is what an incomplete copy looks like - a half-finished
REM OneDrive sync, a partial download, or a folder copied while files were
REM open - and the raw traceback tells a user nothing.
if not exist "%~dp0src\speech_to_text\__init__.py" (
    echo.
    echo ERROR: This copy of the app is incomplete - the program files are missing.
    echo.
    if exist "%~dp0speech_to_text" (
        echo There is an old "speech_to_text" folder here from a previous version,
        echo but the current "src\speech_to_text" is missing.
    ) else (
        echo Expected to find: %~dp0src\speech_to_text\__init__.py
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

REM src-layout: the package lives in src/, which is not on sys.path just
REM because the repo root is the working directory. Pointing PYTHONPATH at
REM it keeps this launcher a double-click affair with no install step.
set "PYTHONPATH=%~dp0src"

if /i "%~1"=="setup" goto :setup_venv
goto :after_setup

:setup_venv
echo Setting up .venv...

REM Pick the interpreter that will BUILD the venv, then check its version
REM before using it. pyproject requires >=3.10, but "py -3" hands back
REM whatever the machine's default 3.x is - on an older install that is 3.8
REM or 3.9. The venv itself creates fine on those, so the failure lands one
REM step later, out of pip, as "package requires a different Python version",
REM which reads like a broken project rather than a stale interpreter.
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

REM A .venv folder with no python.exe in it is a half-created one - an
REM interrupted setup, or an interpreter that has since been uninstalled.
REM "python -m venv" onto that path repairs some of it and leaves the rest,
REM so clear it out and start clean instead.
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

REM A fresh venv ships whatever pip was bundled with the interpreter. On
REM Python 3.11.0 that is pip 22.3, and pip 22.x has a Windows bug where the
REM build-tracker directory it keeps under %%TEMP%% disappears part way
REM through a long install, ending the run with
REM   ERROR: Could not install packages due to an OSError: [Errno 2]
REM   No such file or directory: '...\pip-build-tracker-xxxx\<hash>'
REM This project pulls ~120 MB of wheels (PyQt5-Qt5 alone is 50 MB), so an
REM install here runs for minutes and sits squarely in that window.
REM Upgrading pip first is the fix, and it also brings a resolver that
REM understands the metadata newer wheels publish.
"%~dp0.venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if not !errorlevel!==0 (
    echo.
    echo ERROR: Upgrading pip inside .venv failed - see the output above.
    echo.
    pause
    exit /b 1
)

REM Give pip its own scratch directory next to the venv instead of %%TEMP%%.
REM The tracker failure above is triggered by something else emptying
REM %%TEMP%% mid-install - Storage Sense, Disk Cleanup, or an antivirus
REM scanner - which a newer pip does not prevent. A folder inside the project
REM is not a target for any of them. Removed after.
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

REM pip reporting success is not the same as the app being able to start: a
REM wheel can unpack without its DLLs landing, which surfaces much later as
REM an ImportError from inside the GUI. Import every top-level dependency
REM now, while the setup output is still on screen and the user is expecting
REM setup problems.
"%~dp0.venv\Scripts\python.exe" -c "import speech_to_text, PyQt5, faster_whisper, sherpa_onnx, av, psutil, tqdm"
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
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo.
    echo ERROR: No .venv found for this project - the app has not been set up yet.
    echo.
    echo To fix it, from this folder run:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -e .
    echo.
    echo Or let this launcher do it for you:
    echo   run.bat setup
    echo.
    pause
    exit /b 1
)

"%~dp0.venv\Scripts\python.exe" -m speech_to_text.main
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
