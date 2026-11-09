@echo off
cd /d "%~dp0"
rem Same app as start_saher.bat, but with persona v5. start_saher.bat still uses v4.
set SAHER_PERSONA=%~dp0..\saher-chat\persona_allam_v5.txt
python server.py
pause
