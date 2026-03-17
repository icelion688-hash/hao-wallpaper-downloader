@echo off
setlocal
chcp 65001 >nul
title HaoWallpaper Downloader

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

echo ========================================
echo   HaoWallpaper Downloader - Start
echo ========================================
echo.

set "PYTHON_EXE=python"
set "DEPS_OK=1"

%PYTHON_EXE% --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10+ was not found.
    pause
    exit /b 1
)

echo [1/3] Checking Python dependencies...
for %%M in (fastapi uvicorn sqlalchemy httpx yaml multipart aiofiles Crypto PIL tzdata imageio imageio_ffmpeg) do (
    %PYTHON_EXE% -c "import %%M" >nul 2>&1
    if errorlevel 1 set "DEPS_OK=0"
)

if "%DEPS_OK%"=="0" (
    echo      Missing dependencies detected. Installing requirements.txt ...
    pip install -r "requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Failed to install Python dependencies.
        pause
        exit /b 1
    )
) else (
    echo      Python dependencies are ready.
)

echo [2/3] Checking frontend...
node --version >nul 2>&1
if errorlevel 1 (
    echo      [INFO] Node.js was not found. Frontend build will be skipped.
    echo      Backend API is still available at: http://localhost:8000
    goto start_backend
)

if not exist "frontend\dist" (
    echo      Building frontend...
    cd /d "%ROOT_DIR%frontend"
    call npm install -q
    if errorlevel 1 (
        echo [ERROR] Failed to install frontend dependencies.
        pause
        exit /b 1
    )
    call npm run build
    if errorlevel 1 (
        echo [ERROR] Frontend build failed.
        pause
        exit /b 1
    )
    cd /d "%ROOT_DIR%"
    echo      Frontend build completed.
) else (
    echo      Frontend is already built.
)

:start_backend
echo [3/3] Starting backend service...
echo.
echo ========================================
echo   URL: http://localhost:8000
echo   Press Ctrl+C to stop
echo ========================================
echo.

%PYTHON_EXE% -m backend.main

pause
