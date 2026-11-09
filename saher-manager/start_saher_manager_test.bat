@echo off
cd /d "%~dp0"
rem Same as start_saher_manager.bat, plus a picker for MOCK inboxes (made-up emails for testing).
set SAHER_TEST=1
python server.py
pause
