@echo off
REM Profiler Machine Installation Script for Windows
REM Handles Python 3.12 constraints and dependency workarounds

setlocal enabledelayedexpansion

echo.
echo ========================================
echo Profiler Machine Installer
echo ========================================
echo.

REM Check Python 3.12 is available via py launcher
py -3.12 --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.12 not found
    echo Please install Python 3.12.x from https://www.python.org/downloads/
    echo Make sure to check "Add to PATH" during installation
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('py -3.12 --version 2^>^&1') do set PYTHON_VERSION=%%i
echo [OK] Python %PYTHON_VERSION% detected
echo.

REM Create virtual environment using py -3.12 explicitly
echo [1/9] Creating virtual environment...
if exist "venv" (
    echo Virtual environment already exists, skipping creation
) else (
    py -3.12 -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
)
echo [OK] Virtual environment ready
echo.

REM Activate virtual environment
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /b 1
)
echo [OK] Virtual environment activated
echo.

REM Verify venv is using 3.12
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set VENV_VERSION=%%i
echo [OK] venv Python: %VENV_VERSION%
echo.

REM Check for CUDA
echo [2/9] Checking for CUDA installation...
nvcc --version >nul 2>&1
if errorlevel 1 (
    echo NOTE: CUDA Toolkit not detected. App will run on CPU.
    echo See INSTALL.md for optional GPU setup.
) else (
    echo [OK] CUDA Toolkit detected - GPU acceleration enabled
)
echo.

REM Upgrade pip and wheel. Pin setuptools below 81 because setuptools 81
REM removed importable pkg_resources, which breaks legacy source builds (lap).
echo [3/9] Upgrading pip and wheel, pinning setuptools...
python -m pip install --upgrade pip wheel --quiet
python -m pip install "setuptools<81" --quiet
if errorlevel 1 (
    echo ERROR: Failed to set up pip/setuptools/wheel
    pause
    exit /b 1
)
echo [OK] pip, setuptools (<81), and wheel ready
echo.

REM Pre-install lapx (provides the lap module, bypasses lap build conflicts)
echo [4/9] Pre-installing lapx (lap conflict workaround)...
python -m pip install lapx==0.9.4 --quiet
if errorlevel 1 (
    echo WARNING: lapx pre-install had issues, will retry in main install
)
echo [OK] lapx prepared
echo.

REM Pre-install bytetracker with --no-deps (dependency workaround)
echo [5/9] Pre-installing bytetracker (--no-deps workaround)...
python -m pip install --no-deps bytetracker==0.3.2 --quiet
if errorlevel 1 (
    echo WARNING: bytetracker pre-install failed, will attempt in main install
)
echo [OK] bytetracker prepared
echo.

REM Pre-install playsound from PyPI
echo [6/9] Pre-installing playsound...
python -m pip install playsound==1.2.2 --quiet
if errorlevel 1 (
    echo WARNING: playsound pre-install failed, will retry in main install
)
echo [OK] playsound prepared
echo.

REM Install ALL dependencies from requirements.txt
echo [7/9] Installing all dependencies from requirements.txt...
echo This may take several minutes (installing torch, onnxruntime, etc)...
python -m pip install -r requirements.txt --prefer-binary --quiet
if errorlevel 1 (
    echo WARNING: Some packages may have failed to install
    echo Check output above for details
    echo Installation will continue with verification...
)
echo [OK] Dependencies installed
echo.

REM Verify critical imports
echo [8/9] Verifying critical imports...
python -c "import insightface; import PyQt5; import cv2; import onnxruntime; import torch; import lap; import bytetracker" >nul 2>&1
if errorlevel 1 (
    echo WARNING: Some critical imports failed
    echo Run this to see the full error:
    echo   python -c "import insightface; import PyQt5; import cv2; import onnxruntime; import torch; import lap; import bytetracker"
    pause
    exit /b 1
) else (
    echo [OK] All critical imports verified
)
echo.

REM Create necessary directories
echo [9/9] Creating application directories...
if not exist "config" mkdir config
if not exist "logs" mkdir logs

echo [OK] Directories created
echo.

echo ========================================
echo Installation Complete!
echo ========================================
echo.
echo Installed packages:
python -m pip list
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
echo  - Reinstall package: pip install --force-reinstall --no-cache-dir [package]
echo  - Check GitHub issues for known solutions
echo.

pause