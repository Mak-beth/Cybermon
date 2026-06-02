@echo off
cd /d "%~dp0"
if not exist venv\Scripts\activate.bat (
    echo Creating virtual environment...
    py -m venv venv
)
call venv\Scripts\activate.bat
echo Installing dependencies...
pip install -r requirements.txt -q
echo Starting Cybermon...
venv\Scripts\python.exe main.py --auth-log logs/live/auth.log --web-log logs/live/access.log
