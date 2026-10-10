@echo off
cd /d "%~dp0"
echo If you have not started the debug browser yet, first double-click start_edge_debug.bat.
echo Then open the quiz page in Edge and press Enter in THIS window.
".venv\Scripts\python.exe" main.py %*
echo.
echo finished.
pause
