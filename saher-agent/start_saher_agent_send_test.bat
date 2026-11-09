@echo off
cd /d "%~dp0"
rem TEST: Saher with approved sending against a SIMULATED Gmail (mock_gmail.py). Nothing leaves this computer.
rem Page in Modern Standard Arabic on http://127.0.0.1:8772 . Mail reading uses test emails.
rem Test addresses: fail-scope@example.com, bad-request@example.com, timeout-sent@example.com, timeout-lost@example.com, server-error@example.com
start "Saher mock Gmail" /min python mock_gmail.py
set SAHER_SEND=mock
set SAHER_AGENT_MAIL=mock
set SAHER_PORT=8772
python server.py
pause
