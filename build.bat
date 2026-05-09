@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo   IQ-converter to SIGMF  --  Build Script  by Sudama
echo ============================================================
echo.

:: ── Python check ─────────────────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ and add it to PATH.
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo Python: %%v

:: ── Install dependencies ──────────────────────────────────────────────────
echo.
echo [1/4] Installing dependencies...
python -m pip install --upgrade pip --quiet
python -m pip install numpy Pillow pyinstaller --quiet
if errorlevel 1 (
    echo [ERROR] pip install failed.
    pause & exit /b 1
)
echo       OK

:: ── Generate icon ─────────────────────────────────────────────────────────
echo.
echo [2/4] Generating icon...
python create_icon.py
if errorlevel 1 (
    echo [WARNING] Icon generation failed, building without icon.
    set ICON_FLAG=
) else (
    if exist icon.ico (
        set ICON_FLAG=--icon=icon.ico
    ) else (
        set ICON_FLAG=
    )
)
echo       OK

:: ── Clean previous artefacts ──────────────────────────────────────────────
echo.
echo [3/4] Building with PyInstaller...
if exist build         rmdir /s /q build
if exist dist          rmdir /s /q dist
if exist "IQ-Converter-SIGMF.spec" del "IQ-Converter-SIGMF.spec"

python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "IQ-Converter-SIGMF" ^
    %ICON_FLAG% ^
    --add-data "icon.ico;." ^
    --hidden-import numpy ^
    --hidden-import numpy.core ^
    --hidden-import PIL ^
    --hidden-import tkinter ^
    --hidden-import tkinter.ttk ^
    --hidden-import tkinter.filedialog ^
    --hidden-import tkinter.messagebox ^
    --clean ^
    --noconfirm ^
    main.py

if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller build failed. Check output above.
    pause & exit /b 1
)
echo       OK

:: ── Summary ───────────────────────────────────────────────────────────────
echo.
echo [4/4] Build complete!
echo.
if exist "dist\IQ-Converter-SIGMF.exe" (
    for %%F in ("dist\IQ-Converter-SIGMF.exe") do (
        set /a SZ_MB=%%~zF / 1048576
        echo   Executable : dist\IQ-Converter-SIGMF.exe
        echo   Size       : !SZ_MB! MB
    )
) else (
    echo   dist\IQ-Converter-SIGMF.exe
)
echo.
echo ============================================================
echo   Run dist\IQ-Converter-SIGMF.exe to launch the application
echo ============================================================
echo.
pause
