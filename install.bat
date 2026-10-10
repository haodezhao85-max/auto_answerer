@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  auto_answerer 安装脚本（只需运行一次）
echo ============================================

if exist ".venv\Scripts\python.exe" (
  echo [跳过] 虚拟环境已存在
  goto deps
)

echo [1/3] 创建虚拟环境 .venv ...
python -m venv .venv 2>nul
if not exist ".venv\Scripts\python.exe" (
  echo   ^> python 不可用，尝试 py -3.13 ...
  if exist ".venv" rmdir /s /q .venv
  py -3.13 -m venv .venv 2>nul
)
if not exist ".venv\Scripts\python.exe" (
  echo [错误] 创建虚拟环境失败。请安装 Python 3.9+（python.org 或微软商店版）
  echo        安装时务必勾选 "Add Python to PATH"。
  pause
  exit /b 1
)

:deps
echo [2/3] 安装依赖 playwright + openai ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [错误] 依赖安装失败，请检查网络后重试。
  pause
  exit /b 1
)

echo [3/3] 下载浏览器内核 chromium（约 130MB，需几分钟）...
set PLAYWRIGHT_BROWSERS_PATH=%~dp0.browsers
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 (
  echo [错误] 浏览器下载失败，请检查网络后重试。
  pause
  exit /b 1
)

echo.
echo 安装完成！
echo  1) 先复制 .env.example 为 .env 并填入 DeepSeek API Key
echo  2) 双击 probe.bat 探查一个真实任务页，把 out\probe_* 发回给我精调
echo  3) 之后双击 run.bat 开始答题
pause
