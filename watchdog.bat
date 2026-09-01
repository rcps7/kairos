@echo off
REM Kairos Watchdog - supervises Kairos and enforces the kill switch.
cd /d "%~dp0"
call venv\Scripts\activate.bat
python -m kairos.watchdog %*
