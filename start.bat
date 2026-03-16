@echo off
chcp 65001 >nul
title 好壁纸下载器

echo ========================================
echo   好壁纸下载器 - 一键启动
echo ========================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: 检查并安装依赖
echo [1/3] 检查 Python 依赖...
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo      正在安装依赖，请稍等...
    pip install -r requirements.txt -q
)
echo      依赖就绪 ✓

:: 检查 Node.js 和前端
echo [2/3] 检查前端...
node --version >nul 2>&1
if errorlevel 1 (
    echo      [提示] 未检测到 Node.js，将跳过前端构建
    echo      后端服务仍可正常使用，API 地址: http://localhost:8000
    goto start_backend
)

if not exist "frontend\dist" (
    echo      正在构建前端，请稍等...
    cd frontend
    call npm install -q
    call npm run build
    cd ..
    echo      前端构建完成 ✓
) else (
    echo      前端已构建 ✓
)

:start_backend
echo [3/3] 启动后端服务...
echo.
echo ========================================
echo   服务地址: http://localhost:8000
echo   按 Ctrl+C 停止服务
echo ========================================
echo.

:: 从项目根目录启动，确保模块路径正确
python -m backend.main

pause
