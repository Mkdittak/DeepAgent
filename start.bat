@echo off
title DeepAgent Launcher
echo ============================================
echo        DeepAgent - Starting All Services
echo ============================================
echo.

:: Always run from the project directory (handles spaces in the path)
cd /d "%~dp0"

:: Prefer the project venv; fall back to system python if it's missing
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [warn] .venv not found - falling back to system "python"
  set "PY=python"
)

:: [1/4] Temporal dev server (durable workflow backend + UI on :8233)
echo [1/4] Starting Temporal Server...
start "Temporal Server" cmd /k "temporal server start-dev --db-filename "%~dp0.temporal.db" --ip 127.0.0.1 --port 7233 --ui-port 8233"
timeout /t 4 /nobreak >nul

:: [2/4] Temporal worker (polls deep-agent-queue)
echo [2/4] Starting Temporal Worker...
start "Temporal Worker" cmd /k "cd /d "%~dp0" && "%PY%" -m temporal.worker"
timeout /t 2 /nobreak >nul

:: [3/4] FastAPI backend on :8000 (uvicorn, no auto-reload - stable for a demo)
echo [3/4] Starting FastAPI Backend...
start "FastAPI Backend" cmd /k "cd /d "%~dp0" && "%PY%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log"
timeout /t 2 /nobreak >nul

:: [4/4] React frontend on :3000 (Vite)
echo [4/4] Starting React Frontend...
start "React Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"
timeout /t 6 /nobreak >nul

:: Open the app
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
echo Each service runs in its own window.
echo To stop everything, close all 4 service windows.
pause
