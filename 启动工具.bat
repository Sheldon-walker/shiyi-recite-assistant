@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   拾忆 · 艾宾浩斯背诵助手（WebView2 版）
echo ============================================
echo.

REM 第一步：检查 Python 是否在 PATH 中。
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有找到 Python。
    echo 请先安装 Python 3.10 或更高版本，并勾选 Add Python to PATH。
    echo.
    pause
    exit /b 1
)

REM 第二步：检查 WebView2 宿主依赖。
python -c "import webview, clr, openai" >nul 2>nul
if errorlevel 1 (
    echo 第一次运行，正在安装 WebView2 界面依赖...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [错误] 依赖安装失败，请检查网络后重试。
        echo 也可以手动执行：python -m pip install pywebview pythonnet openai
        echo.
        pause
        exit /b 1
    )
    echo 依赖安装完成。
    echo.
)

REM 第三步：用 pythonw 启动，避免一直显示黑色命令行窗口。
start "" pythonw "%~dp0webview_app.py"
exit /b 0
