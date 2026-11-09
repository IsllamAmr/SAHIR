@echo off
cd /d "%~dp0"
rem Saher for managers: text chat + your latest 5 unread Gmail emails (read only, through local n8n).
rem Persona v5. Needs Ollama running, and n8n (..\n8n\start-n8n.bat) for email.
set "SAHER_MAIL=gmail"
python server.py
pause
