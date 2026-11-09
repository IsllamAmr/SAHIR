@echo off
rem Saher hands-free with the fastest voice already on this laptop: Piper ar_JO-kareem (CPU). Port 8771.
cd /d "%~dp0"
set SAHER_TTS=piper
set SAHER_PORT=8771
python server.py
pause
