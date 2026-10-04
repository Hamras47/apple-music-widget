@echo off
rem Start the Apple Music widget in the background (no console window).
setlocal
set "HERE=%~dp0"
if not exist "%HERE%.venv\Scripts\pythonw.exe" (
  echo.
  echo   The widget virtualenv is missing. Set it up once with:
  echo.
  echo     cd /d "%HERE%"
  echo     py -3.14 -m venv .venv
  echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)
start "" "%HERE%.venv\Scripts\pythonw.exe" "%HERE%app.py"
