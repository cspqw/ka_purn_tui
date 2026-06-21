@echo off
chcp 65001 >nul
echo.
echo ╔══════════════════════════════════════════════╗
echo ║     K.A-purn-tui - 一键安装脚本            ║
echo ╚══════════════════════════════════════════════╝
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo        下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python 已安装

:: 创建虚拟环境（如不存在）
if not exist ".venv" (
    echo.
    echo [1/4] 创建虚拟环境 .venv ...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
) else (
    echo [OK] 虚拟环境已存在
)

:: 激活虚拟环境
echo.
echo [2/4] 激活虚拟环境 ...
call .venv\Scripts\activate.bat

:: 升级 pip
echo.
echo [3/4] 升级 pip ...
python -m pip install --upgrade pip --quiet

:: 安装依赖
echo.
echo [4/4] 安装项目依赖 ...
pip install -e ".[dev]" --quiet
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

echo.
echo ╔══════════════════════════════════════════════╗
echo ║        安装完成！                          ║
echo ╚══════════════════════════════════════════════╝
echo.
echo 使用方法:
echo   1. 设置 API Key:   set DEEPSEEK_API_KEY=sk-your-key-here
echo      或在项目根目录创建 config.jsonc 写入 api_key
echo   2. 启动程序:        .venv\Scripts\activate ^&^& ka-purn-tui
echo   3. 小说模式:        启动后输入 /mode novel
echo.
echo 详细文档见 README.md 和 docs\ARCHITECTURE.md
echo.
echo ═══════════════════════════════════════════════
pause
