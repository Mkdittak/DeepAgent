@echo off
title DeepAgent Launcher
echo ============================================
echo        DeepAgent - Starting All Services
echo ============================================
echo.

:: Navigate to project directory
cd /d "%~dp0"

:: Start Temporal Server
echo [1/4] Starting Temporal Server...
start "Temporal Server" cmd /k "temporal server start-dev --db-filename %~dp0.temporal.db"
timeout /t 3 /nobreak >nul

:: Start Temporal Worker
echo [2/4] Starting Temporal Worker...
start "Temporal Worker" cmd /k "cd /d "%~dp0" && python -m temporal.worker"
timeout /t 2 /nobreak >nul

:: Start FastAPI Backend
echo [3/4] Starting FastAPI Backend...
start "FastAPI Backend" cmd /k "cd /d "%~dp0" && python -m backend.main"
timeout /t 2 /nobreak >nul

:: Start React Frontend
echo [4/4] Starting React Frontend...
start "React Frontend" cmd /k "cd /d "%~dp0\frontend" && npm run dev"
timeout /t 5 /nobreak >nul

:: Open browser
echo.
echo All services started! Opening browser...
start http://localhost:3000

echo.
echo ============================================
echo   DeepAgent is running!
echo   App:       http://localhost:3000
echo   API:       http://localhost:8000
echo   Temporal:  http://localhost:8233
echo ============================================
echo.
echo Close this window anytime - services will
echo keep running in their own windows.
echo To stop everything, close all 4 cmd windows.
pause
