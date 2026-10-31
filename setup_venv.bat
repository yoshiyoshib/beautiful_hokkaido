@echo off
setlocal
cd /d "%~dp0"
echo === venv setup (Python 3.11) ===
py -3.11 -m venv .venv
if errorlevel 1 (
  echo.
  echo Python 3.11 not found. Install from https://www.python.org/downloads/
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 goto :err
echo.
echo Done. Edit .env then run run_evaluate.bat or run_publish.bat
pause
exit /b 0
:err
echo.
echo FAILED. See message above.
pause
exit /b 1
