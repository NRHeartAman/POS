@echo off
title CraveCast POS
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Setting up for the first time...
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)
.venv\Scripts\python.exe manage.py migrate --noinput
start "" http://127.0.0.1:8001/
echo.
echo  CraveCast POS is running at http://127.0.0.1:8001/
echo  Keep this window open while selling. Close it to stop the POS.
echo.
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001
