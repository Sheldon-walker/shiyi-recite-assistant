@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   拾忆 · 艾宾浩斯背诵助手 - EXE 打包
echo ============================================
echo.

REM 第一步：确认 Python 可用。
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有找到 Python。
    echo 请先安装 Python 3.10 或更高版本，并勾选 Add Python to PATH。
    echo.
    if not defined SHIYI_BUILD_NO_PAUSE pause
    exit /b 1
)

REM conda 会把 Tcl/Tk 的 DLL 放在 Library\bin 下。
REM 把这个目录加入 PATH，PyInstaller 才能自动收集 tcl86t.dll / tk86t.dll，
REM 否则打包出来的 exe 会因为缺少 Tk 运行库而无法启动。
for /f "usebackq delims=" %%I in (`python -c "import sys; print(sys.base_prefix)"`) do set "PYTHON_BASE=%%I"
if exist "%PYTHON_BASE%\Library\bin" set "PATH=%PYTHON_BASE%\Library\bin;%PATH%"
if exist "%PYTHON_BASE%\DLLs" set "PATH=%PYTHON_BASE%\DLLs;%PATH%"

REM 第二步：检查 PyInstaller，没有就自动安装。
python -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo [1/3] 未检测到 PyInstaller，正在自动安装...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo.
        echo [错误] PyInstaller 安装失败，请检查网络后重试。
        echo 也可以手动执行：python -m pip install pyinstaller
        echo.
        if not defined SHIYI_BUILD_NO_PAUSE pause
        exit /b 1
    )
) else (
    echo [1/3] PyInstaller 已安装。
)
echo.

REM 第三步：清理上次的中间文件，但保留 dist 中已有的用户数据。
echo [2/3] 清理构建缓存...
if exist "build" rmdir /s /q "build"
if not exist "build" mkdir "build"
if not exist "dist" mkdir "dist"
echo.

REM 第四步：调用 PyInstaller。
REM --onefile   : 打包成一个 exe
REM --windowed  : GUI 程序，不显示黑色控制台窗口
REM --collect-all webview : 把 WebView2 互操作 DLL 等资源一起打包
REM --collect-all pythonnet / clr_loader : .NET 互操作运行时
REM --add-data  : 把窗口图标和 web 前端复制进 exe 的临时资源目录
REM --exclude-module : 本项目不需要科学计算库，
REM                    排除后可以避免把 NumPy/MKL 等大体积依赖一起打包。
REM --runtime-tmpdir "." : 单文件 exe 解压到“当前工作目录”（桌面快捷方式
REM                    会把工作目录设为 dist），绕开权限异常的系统临时目录，
REM                    普通用户也能运行，不需要管理员权限。
echo [3/3] 开始打包，首次打包可能需要 1~3 分钟，请耐心等待...
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "拾忆背诵助手" ^
    --icon "%cd%\assets\app_icon.ico" ^
    --add-data "%cd%\assets;assets" ^
    --add-data "%cd%\web;web" ^
    --collect-all webview ^
    --collect-all pythonnet ^
    --collect-all clr_loader ^
    --collect-all openai ^
    --hidden-import clr ^
    --exclude-module numpy ^
    --exclude-module scipy ^
    --exclude-module pandas ^
    --exclude-module matplotlib ^
    --exclude-module IPython ^
    --runtime-tmpdir "." ^
    --distpath "%cd%\dist" ^
    --workpath "%cd%\build" ^
    --specpath "%cd%\build" ^
    "%cd%\webview_app.py"

if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请查看上方 PyInstaller 的错误信息。
    if not defined SHIYI_BUILD_NO_PAUSE pause
    exit /b 1
)

REM 第一次打包时，把当前数据带到 dist，避免打开 exe 后看不到已有背诵。
REM 如果 dist 里已经有 review_data.json，则不覆盖，保护 exe 版本自己的数据。
if not exist "dist\review_data.json" (
    if exist "review_data.json" (
        copy /Y "review_data.json" "dist\review_data.json" >nul
    )
)

REM 构建缓存不再需要；保留 dist 输出和其中的用户数据。
if exist "build" rmdir /s /q "build"

REM 创建（或修复）桌面快捷方式。
REM 关键点：
REM 1. WorkingDirectory 指向 dist，exe 会把运行文件解压到这里；
REM 2. IconLocation 直接读取 exe 内嵌图标，不再依赖单独的 ico 路径，
REM    这样桌面图标不会因为 ico 被移动或路径包含中文而显示空白。
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell; $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) '拾忆背诵助手.lnk'; $s = $ws.CreateShortcut($lnk); $s.TargetPath = '%cd%\dist\拾忆背诵助手.exe'; $s.WorkingDirectory = '%cd%\dist'; $s.IconLocation = '%cd%\dist\拾忆背诵助手.exe,0'; $s.Description = '拾忆 · 艾宾浩斯背诵助手'; $s.Save(); Write-Host ('已创建/修复桌面快捷方式：' + $lnk)"
if errorlevel 1 (
    echo [提示] 桌面快捷方式创建失败，可以直接运行 dist 里的 exe。
)
REM 通知资源管理器刷新图标缓存。
ie4uinit.exe -show >nul 2>nul

echo.
echo ============================================
echo   打包成功！
echo   可执行文件：%cd%\dist\拾忆背诵助手.exe
echo   数据文件：  %cd%\dist\review_data.json
echo   桌面快捷方式：拾忆背诵助手.lnk
echo ============================================
echo.
echo 可以直接双击 dist 里的 exe 使用。
if not defined SHIYI_BUILD_NO_PAUSE pause
exit /b 0
