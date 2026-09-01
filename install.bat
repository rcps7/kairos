@echo off
REM Kairos installer - one-time setup.
echo Installing KAIROS...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found on PATH.
    echo Install Python from https://www.python.org/ and check "Add Python to PATH".
    pause
    exit /b 1
)
python install.py
pause
