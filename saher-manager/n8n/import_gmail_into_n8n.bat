@echo off
rem Imports Saher's read-only unread-Gmail workflow and the empty Gmail credential into the local n8n.
rem Stop n8n first (stop-n8n.bat). Safe to run again: it overwrites the same workflow and credential IDs,
rem so run it again only before you have connected Gmail, or you will clear the connection.
cd /d "%~dp0"
set "N8N_USER_FOLDER=%~dp0..\..\n8n\data"
set "N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=false"
set "N8N_DIAGNOSTICS_ENABLED=false"
set "N8N=%~dp0..\..\n8n\app\node_modules\.bin\n8n.cmd"
call "%N8N%" import:credentials --input=gmail-credential-empty.json || goto :fail
call "%N8N%" import:workflow --input=saher-gmail-workflow.json || goto :fail
call "%N8N%" publish:workflow --id=saherGmail5RO001 || goto :fail
echo Done. Start n8n again with start-n8n.bat
exit /b 0
:fail
echo Import failed.
exit /b 1
