@echo off
rem Saher hands-free trial with the Fasee7 voice. Separate from saher-app and saher-voice; uses port 8770.
cd /d "%~dp0"
python server.py
pause
