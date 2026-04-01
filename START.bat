@echo off
title AI File Organizer v2.0
color 0B
echo.
echo  =============================================
echo   AI FILE ORGANIZER v2.0  -  Starting...
echo  =============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found.
    echo  Download from https://python.org  (check "Add to PATH")
    pause & exit /b 1
)

echo  Installing/checking dependencies...
python -m pip install flask flask-cors requests --quiet

echo  Launching server at http://localhost:8765
echo  Your browser will open automatically.
echo  Press Ctrl+C here to stop the server.
echo.
python server.py
pause
