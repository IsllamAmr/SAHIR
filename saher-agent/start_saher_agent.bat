@echo off
cd /d "%~dp0"
rem Saher agent on http://127.0.0.1:8769 . Tools work only inside ..\workspace\ . Mail: real Gmail if n8n is running, otherwise mock.
python server.py
pause
