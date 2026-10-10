@echo off
cd /d "%~dp0"
echo ============================================================
echo  Step 1/2: This will CLOSE all Edge windows now, then restart
echo  Edge with a debug channel for the answer tool to attach to.
echo  Your bookmarks/history/logins are copied and preserved.
echo ============================================================
pause
taskkill /F /IM msedge.exe >nul 2>&1
timeout /t 2 /nobreak >nul
if not exist "profiles\edge_copy\Local State" (
  echo [first run] Copying your Edge profile, please wait a few minutes...
  robocopy "%LOCALAPPDATA%\Microsoft\Edge\User Data" "%~dp0profiles\edge_copy" /E /XD Cache "Code Cache" GPUCache Crashpad /R:1 /W:1 /NFL /NDL
)
start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="%~dp0profiles\edge_copy" --restore-last-session
echo.
echo Step 2/2: Edge opened with debug channel (port 9222).
echo Now open the quiz page inside THIS Edge, then run probe.bat or run.bat.
echo.
echo Note: if you need to re-sync your newest bookmarks/logins later,
echo delete the folder profiles\edge_copy and run this file again.
pause
