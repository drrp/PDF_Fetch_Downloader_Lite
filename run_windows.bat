@echo off
title Library App
cd /d "%~dp0"

rem ---------------------------------------------------------------
rem  Double-click this file to start the library app on Windows.
rem  It opens your browser once the server is ready.
rem ---------------------------------------------------------------

rem Run locally without Google sign-in, so you can use the app
rem straight away. Delete this line if you want the login page.
set DEV_NO_LOGIN=true

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   No virtual environment found in this folder.
    echo.
    echo   Set it up once by running these two commands here:
    echo.
    echo       python -m venv .venv
    echo       .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" run_app.py

echo.
echo   The app has stopped.
pause
