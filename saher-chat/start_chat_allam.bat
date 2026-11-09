@echo off
cd /d "%~dp0"
set SAHER_MODEL=allam-7b-saher
set SAHER_PERSONA=persona_allam_v4.txt
python chat_server.py
pause
