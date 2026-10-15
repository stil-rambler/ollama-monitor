@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  Ollama Monitor - launcher
echo ============================================

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo Install Python 3.11+ and add it to PATH.
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    echo Using virtual environment: .venv
) else (
    set "PY=python"
    echo Using system Python.
)

echo.
echo Checking dependencies...
%PY% -c "import fastapi, uvicorn, httpx, sqlalchemy, aiosqlite, pydantic_settings, psutil" >nul 2>nul
if errorlevel 1 (
    echo Dependencies missing. Installing...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
)

echo.
echo Starting Ollama Monitor at http://localhost:8881
echo Press Ctrl+C to stop.
echo.
%PY% main.py

pause
