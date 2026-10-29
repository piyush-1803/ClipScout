@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo             ClipScout MVP Launcher
echo ===================================================
echo.

cd /d "%~dp0"

:: 1. Detect Python
set PYTHON_CMD=
py --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON_CMD=py
) else (
    python --version >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        set PYTHON_CMD=python
    ) else (
        echo [ERROR] Neither 'py' nor 'python' was found on your system.
        echo Please install Python 3.13 or 3.14 from https://www.python.org/
        pause
        exit /b 1
    )
)

echo [1/3] Using Python: %PYTHON_CMD%
%PYTHON_CMD% --version

:: 2. Check & Install Backend Requirements
echo.
echo [2/3] Checking backend requirements...
%PYTHON_CMD% -m pip install -r backend\requirements.txt --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Pip install had issues. Attempting to proceed...
)

:: 3. Check & Install Frontend Requirements
echo.
echo [3/3] Checking frontend dependencies...
if not exist "frontend\node_modules\" (
    echo Installing frontend packages with npm...
    cd frontend
    call npm install
    cd ..
)

echo.
echo ===================================================
echo  Starting Backend (port 8000) and Frontend (port 5173)
echo ===================================================
echo.

:: Launch Backend in its own window
start "ClipScout Backend (Port 8000)" cmd /k "cd /d %~dp0 && set PYTHONPATH=. && %PYTHON_CMD% -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload"

:: Launch Frontend in its own window
start "ClipScout Frontend (Port 5173)" cmd /k "cd /d %~dp0frontend && npm run dev"

echo Waiting 3 seconds for services to initialize...
timeout /t 3 >nul

echo Opening browser at http://localhost:5173...
start http://localhost:5173

echo.
echo ClipScout is running! Keep the backend and frontend terminal windows open.
echo To stop ClipScout, simply close the opened windows.
echo.
pause
