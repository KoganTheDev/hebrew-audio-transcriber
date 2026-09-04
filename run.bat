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

REM src-layout: the package lives in src/, which is not on sys.path just
REM because the repo root is the working directory. Pointing PYTHONPATH at
REM it keeps this launcher a double-click affair with no install step.
set "PYTHONPATH=%~dp0src"

REM Prefer the Windows "py" launcher: on machines where PATH's "python" is
REM the Microsoft Store alias, "python -m ..." fails instantly.
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m speech_to_text.main
) else (
    python -m speech_to_text.main
)
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
