# PowerShell script to run the Speech-to-Text Transcriber
# This script automatically sets up the Python path and runs the app

Set-Location $PSScriptRoot
Write-Host "Starting Speech-to-Text Transcriber..." -ForegroundColor Green
python -m speech_to_text.main
