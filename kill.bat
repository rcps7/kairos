@echo off
REM Kairos Kill Switch - immediately shuts down Kairos.
cd /d "%~dp0"
call venv\Scripts\activate.bat
python -m kairos.watchdog --kill
