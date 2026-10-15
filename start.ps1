# Ollama Monitor - PowerShell launcher
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Ollama Monitor - launcher" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Python not found in PATH." -ForegroundColor Red
    exit 1
}

if (Test-Path ".venv\Scripts\python.exe") {
    $py = ".venv\Scripts\python.exe"
    Write-Host "Using virtual environment: .venv"
} else {
    $py = "python"
    Write-Host "Using system Python."
}

& $py -c "import fastapi, uvicorn, httpx, sqlalchemy, aiosqlite, pydantic_settings, psutil" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Dependencies missing. Installing..." -ForegroundColor Yellow
    & $py -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Failed to install dependencies." -ForegroundColor Red; exit 1 }
}

Write-Host ""
Write-Host "Starting Ollama Monitor at http://localhost:8881" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""

& $py main.py
