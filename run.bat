@echo off
REM run.bat - launches Kairos and its watchdog.
cd /d "%~dp0"
echo Launching Kairos AI Agent...
if not exist venv (
    echo [ERROR] Virtual environment 'venv' not found.
    echo Please run install.bat first.
    pause
    exit /b
)
call venv\Scripts\activate.bat

REM Start the watchdog in a separate window (kill switch + heartbeat monitor).
start "Kairos Watchdog" cmd /k python -m kairos.watchdog

REM Run Kairos in the foreground.
python -m kairos.main
pause
