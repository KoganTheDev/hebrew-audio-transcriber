@echo off
REM Simple batch script to run the Speech-to-Text Transcriber
REM This script automatically sets up the Python path and runs the app

setlocal enabledelayedexpansion
cd /d "%~dp0"
REM Prefer the Windows "py" launcher: on machines where PATH's "python" is
REM the Microsoft Store alias, "python -m ..." fails instantly.
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m speech_to_text.main
) else (
    python -m speech_to_text.main
)
REM Hold the window open only when something actually failed - a normal
REM close of the app (exit code 0) should let the console go away too.
if %errorlevel% neq 0 (
    echo.
    echo The app exited with an error - see the messages above or speech_to_text.log
    pause
)
