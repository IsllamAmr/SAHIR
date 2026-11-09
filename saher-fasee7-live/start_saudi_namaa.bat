@echo off
rem Saher hands-free with the NAMAA Saudi voice (GPU, a few seconds per sentence). Port 8772.
cd /d "%~dp0"
set SAHER_TTS=namaa
set SAHER_PORT=8772
python server.py
pause
