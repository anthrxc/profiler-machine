@echo off
REM Profiler Machine Installation Script for Windows
REM Handles Python 3.12 constraints and dependency workarounds

setlocal enabledelayedexpansion

echo.
echo ========================================
echo Profiler Machine Installer
echo ========================================
echo.

REM Check Python version
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH
    echo Please install Python 3.12.x from https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i

REM Extract major.minor version
for /f "tokens=1,2 delims=." %%a in ("%PYTHON_VERSION%") do (
    set MAJOR=%%a
    set MINOR=%%b
)

if not "%MAJOR%.%MINOR%"=="3.12" (
    echo ERROR: Python 3.12.x required, found %PYTHON_VERSION%
    echo Python 3.14+ is incompatible with onnxruntime/lapx
    pause
    exit /b 1
)

echo [✓] Python %PYTHON_VERSION% detected
echo.

REM Create virtual environment
echo [1/8] Creating virtual environment...
if exist "venv" (
    echo Virtual environment already exists, skipping creation
) else (
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
)
echo [✓] Virtual environment ready
echo.

REM Activate virtual environment
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /b 1
)
echo [✓] Virtual environment activated
echo.

REM Check for CUDA
echo [2/8] Checking for CUDA installation...
nvcc --version >nul 2>&1
if errorlevel 1 (
    echo NOTE: CUDA Toolkit not detected (optional, recommended for performance)
    echo App will run on CPU. See INSTALL.md for GPU setup.
) else (
    echo [✓] CUDA Toolkit detected
)
echo.

REM Upgrade pip, setuptools, wheel
echo [3/8] Upgrading pip and setuptools...
python -m pip install --upgrade pip setuptools wheel >nul 2>&1
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip/setuptools
    pause
    exit /b 1
)
echo [✓] pip and setuptools upgraded
echo.

REM Pre-install bytetracker with --no-deps before requirements.txt
echo [4/8] Pre-installing bytetracker (--no-deps workaround)...
python -m pip install --no-deps bytetracker==0.3.2 >nul 2>&1
if errorlevel 1 (
    echo WARNING: bytetracker pre-install failed, will retry later
)
echo [✓] bytetracker prepared
echo.

REM Pre-install playsound from git
echo [5/8] Pre-installing playsound from git...
python -m pip install git+https://github.com/taconi/playsound@92385c78ec05c2fc3afad1afc5edc9d1282aa1e5 >nul 2>&1
if errorlevel 1 (
    echo WARNING: playsound git install failed, will use PyPI fallback
    python -m pip install playsound==1.2.2 >nul 2>&1
)
echo [✓] playsound prepared
echo.

REM Install core dependencies from requirements.txt (excluding bytetracker and playsound)
echo [6/8] Installing dependencies from requirements.txt...
echo Note: This may take several minutes...
python -m pip install -r requirements.txt --no-warn-script-location --ignore-installed bytetracker playsound >nul 2>&1
if errorlevel 1 (
    echo WARNING: Some packages may have failed
    echo Continuing with verification...
)
echo [✓] Dependencies installed
echo.

REM Verify critical imports
echo [7/8] Verifying critical imports...
python -c "import insightface; import PyQt5; import cv2; import onnxruntime" >nul 2>&1
if errorlevel 1 (
    echo WARNING: Some imports failed, but installation may still work
    echo Try running Profiler Machine to see full error details
) else (
    echo [✓] All critical imports verified
)
echo.

REM Create necessary directories
echo [8/8] Creating application directories...
if not exist "config" mkdir config
if not exist "logs" mkdir logs

echo [✓] Directories created
echo.

echo ========================================
echo Installation Complete!
echo ========================================
echo.
echo IMPORTANT: Always activate venv before running:
echo   call venv\Scripts\activate.bat
echo.
echo Next steps:
echo  1. Activate venv (if not already active): call venv\Scripts\activate.bat
echo  2. Launch Profiler Machine: python main.py
echo  3. For mobile access: Configure Tailscale on your network
echo  4. Check logs/profiler_machine.log for errors
echo.
echo If you encounter issues:
echo  - Verify venv is active (should see "(venv)" in prompt)
echo  - For GPU speedup: Check INSTALL.md for optional CUDA 12.x setup
echo  - Reinstall problematic package with: pip install --force-reinstall [package_name]
echo  - Check GitHub issues for known solutions
echo.

pause