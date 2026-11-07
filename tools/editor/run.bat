@echo off
setlocal
cd /d "%~dp0..\.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "tools\editor\server.py" %*
) else (
  python "tools\editor\server.py" %*
)
