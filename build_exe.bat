@echo off
title Build LibraryApp.exe
cd /d "%~dp0"

rem ------------------------------------------------------------------
rem  Builds LibraryApp.exe into the dist folder.
rem  Needs Python 3.11 or 3.12 installed on this PC.
rem  Double-click it; it does everything else itself.
rem ------------------------------------------------------------------

echo.
echo   Building LibraryApp.exe
echo   -----------------------
echo.

if not exist ".venv\Scripts\python.exe" (
    echo   Creating the virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :fail
)

echo   Installing the app's requirements...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 goto :fail

echo   Installing the build tool...
".venv\Scripts\python.exe" -m pip install --quiet pyinstaller
if errorlevel 1 goto :fail

echo.
echo   Building - this takes a few minutes. Please wait.
echo.
".venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm library-app.spec
if errorlevel 1 goto :fail

echo.
echo   Done.
echo.
echo   Your app is:   dist\LibraryApp.exe
echo   That one file is all you need - copy it anywhere you like.
echo.
pause
exit /b 0

:fail
echo.
echo   The build failed. The messages above say why.
echo.
pause
exit /b 1
