@echo off
setlocal
cd /d "%~dp0"
where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%~dp0StrataBench.pyw"
    exit /b
)
where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%~dp0StrataBench.pyw"
    exit /b
)
echo Install Python 3.11 or newer from python.org, including the Python launcher.
echo Then double-click this file again.
pause
