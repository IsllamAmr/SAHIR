@echo off
cd /d "%~dp0"
rem EXPERIMENT: qwen2.5:7b picks the tools, ALLaM (allam-7b-saher) still writes every reply. Default stays start_saher_agent.bat.
set SAHER_PLANNER_MODEL=qwen2.5:7b
python server.py
pause
