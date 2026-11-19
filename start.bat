@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0StrataBench.pyw" (
    echo Extract the complete StrataBench download before running start.bat.
    echo StrataBench.pyw must be in the same folder as this launcher.
    pause
    exit /b 1
)
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
where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%~dp0StrataBench.pyw"
    exit /b
)
where python >nul 2>nul
if not errorlevel 1 (
    python "%~dp0StrataBench.pyw"
    exit /b
)
echo Install Python 3.11 or newer from python.org, including the Python launcher.
echo Then double-click this file again.
pause
