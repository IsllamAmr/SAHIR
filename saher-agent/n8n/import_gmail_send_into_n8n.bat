@echo off
rem Imports Saher's two send workflows and the EMPTY "Gmail - Saher (send only)" credential into the local n8n.
rem Stop n8n first (stop-n8n.bat). The read-only Gmail credential and workflow are not touched.
rem Running it again re-imports the send credential EMPTY (you would have to sign in to Google again).
cd /d "%~dp0"
set "N8N_USER_FOLDER=%~dp0..\..\n8n\data"
if not "%SAHER_N8N_DATA%"=="" set "N8N_USER_FOLDER=%SAHER_N8N_DATA%"
set "N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=false"
set "N8N_DIAGNOSTICS_ENABLED=false"
set "N8N=%~dp0..\..\n8n\app\node_modules\.bin\n8n.cmd"
call "%N8N%" import:credentials --input=gmail-send-credential-empty.json || goto :fail
call "%N8N%" import:workflow --input=saher-send-workflow.json || goto :fail
call "%N8N%" import:workflow --input=saher-sent-check-workflow.json || goto :fail
call "%N8N%" publish:workflow --id=saherGmailSend001 || goto :fail
call "%N8N%" publish:workflow --id=saherGmailSentChk1 || goto :fail
echo Done. Start n8n again with start-n8n.bat
exit /b 0
:fail
echo Import failed.
exit /b 1
