@echo off
cd /d "%~dp0"
rem REAL: Saher with approved sending through YOUR Gmail (n8n workflow "Saher - send approved Gmail", scope gmail.send).
rem Nothing is sent until you press the approval button on the exact message. Needs n8n running (start-n8n.bat)
rem and the send credential connected (see SEND_SETUP.md). Page on http://127.0.0.1:8772
set SAHER_SEND=gmail
set SAHER_AGENT_MAIL=gmail
set SAHER_PORT=8772
python server.py
pause
