@echo off
rem Stops whatever is listening on 127.0.0.1:5678 (n8n) and its task runners. Leaves other Saher apps alone.
powershell -NoProfile -Command "$c = Get-NetTCPConnection -LocalPort 5678 -State Listen -ErrorAction SilentlyContinue; if ($c) { $c | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { taskkill /PID $_ /T /F | Out-Null; Write-Host ('Stopped n8n (PID ' + $_ + ')') } } else { Write-Host 'n8n is not running.' }"
