@echo off
rem Doble clic aqui para usar el asistente en Windows.
rem Todo el trabajo lo hace launcher.py; esto solo busca un Python.
setlocal
cd /d "%~dp0"

set PYTHON=
py -3 --version >nul 2>&1
if not errorlevel 1 set PYTHON=py -3
if not defined PYTHON (
    python --version >nul 2>&1
    if not errorlevel 1 set PYTHON=python
)

if not defined PYTHON (
    echo.
    echo No encuentro Python instalado.
    echo Descargalo de https://python.org ^(version 3.11 o superior^) y marca
    echo la casilla "Add Python to PATH" durante la instalacion.
    echo.
    pause
    exit /b 1
)

%PYTHON% launcher.py %*
set CODE=%ERRORLEVEL%
if not "%CODE%"=="0" (
    echo.
    pause
)
exit /b %CODE%
