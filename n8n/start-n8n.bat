@echo off
rem Starts n8n locally on http://localhost:5678 (local only, no telemetry).
rem n8n listens on 127.0.0.1; loopback6.js adds [::1] so "localhost" (IPv6 first here) also connects. Both are loopback only.
set "N8N_ROOT=%~dp0"
set "N8N_USER_FOLDER=%N8N_ROOT%data"
set "N8N_HOST=localhost"
set "N8N_LISTEN_ADDRESS=127.0.0.1"
set "N8N_PORT=5678"
set "N8N_PROTOCOL=http"
rem The OAuth callback n8n shows (and Entra accepts) is http://localhost:5678/rest/oauth2-credential/callback
set "N8N_EDITOR_BASE_URL=http://localhost:5678/"
set "WEBHOOK_URL=http://localhost:5678/"
set "N8N_SECURE_COOKIE=false"
set "N8N_DIAGNOSTICS_ENABLED=false"
set "N8N_VERSION_NOTIFICATIONS_ENABLED=false"
set "N8N_TEMPLATES_ENABLED=false"
set "N8N_PERSONALIZATION_ENABLED=false"
set "N8N_HIRING_BANNER_ENABLED=false"
set "N8N_RUNNERS_ENABLED=true"
set "N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=false"
set "GENERIC_TIMEZONE=Asia/Riyadh"
title n8n (localhost:5678)
start "n8n localhost forwarder" /min node "%N8N_ROOT%loopback6.js"
echo Starting n8n at http://localhost:5678  (close this window or run stop-n8n.bat to stop)
"%N8N_ROOT%app\node_modules\.bin\n8n.cmd" start
