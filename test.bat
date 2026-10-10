@echo off
cd /d "%~dp0"
echo === auto_answerer self-test ===
if exist ".venv\Scripts\python.exe" (echo [OK] venv python found) else (echo [FAIL] venv python missing)
if not exist ".browsers\chromium-1234" (echo [WARN] chromium not found) else (echo [OK] chromium found)
".venv\Scripts\python.exe" -c "import sys; print(\"python\", sys.version.split()[0])"
".venv\Scripts\python.exe" -c "import playwright, openai; print(\"libs OK\", getattr(openai, \"__version__\", \"?\"))"
echo === test done. If you see [OK] and libs OK, the environment is ready. ===
pause
