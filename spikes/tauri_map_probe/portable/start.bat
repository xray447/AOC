@echo off
setlocal
cd /d "%~dp0"

rem Usage: double-click this file, or run  .\start.bat
rem Do NOT run it with python (python start.bat -> SyntaxError).
rem ASCII-only on purpose: non-ASCII text in .bat breaks cmd parsing
rem under some console code pages.

if not exist "%~dp0server.py" (
  echo [ERROR] server.py not found. The zip was probably not fully extracted.
  pause
  exit /b 2
)

set "PY="
for %%C in ("py -3" "python" "python3") do (
  if not defined PY (
    %%~C -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=%%~C"
  )
)

if not defined PY (
  echo [ERROR] No usable Python 3.10+ found.
  echo         Install it with "Add python.exe to PATH" checked:
  echo         https://www.python.org/downloads/
  echo         Chinese notes: see README.txt
  pause
  exit /b 2
)

echo Using interpreter: %PY%
%PY% server.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [ERROR] Server exited with code %RC%
  echo         Try another port: python server.py --port 5299
  pause
)
endlocal & exit /b %RC%
