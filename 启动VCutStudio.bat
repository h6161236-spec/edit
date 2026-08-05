@echo off
rem ============================================================
rem  VCut Studio - development launcher
rem  Double-click to start the app from source.
rem  Priority: .venv > venv > system python; falls back to the
rem  packaged dist build when source dependencies are missing.
rem ============================================================
setlocal
cd /d "%~dp0"

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"

"%PY%" -c "import vcut_studio" >nul 2>&1
if errorlevel 1 (
    echo [VCut Studio] Dependencies not found. Installing editable package...
    "%PY%" -m pip install -e ".[asr]"
    if errorlevel 1 (
        echo [VCut Studio] Source install failed.
        if exist "dist\VCutStudio\VCutStudio.exe" (
            echo [VCut Studio] Falling back to packaged build: dist\VCutStudio\VCutStudio.exe
            start "" "dist\VCutStudio\VCutStudio.exe"
            exit /b 0
        )
        echo [VCut Studio] Install failed. Run manually: pip install -e ".[asr]"
        pause
        exit /b 1
    )
)

echo [VCut Studio] Starting development build via %PY% ...
"%PY%" -m vcut_studio
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo [VCut Studio] App exited abnormally with code %EXIT_CODE%
    pause
)
endlocal
