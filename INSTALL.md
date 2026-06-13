# Profiler Machine Installation Guide

## Quick Start

### Windows Users
Choose ONE method:

**Option A: Batch Script (Easiest)**
```
install.bat
```
Double-click or run in Command Prompt. Script handles all workarounds.

**Option B: Python Script**
```
python install.py
```

### ⚠️ CUDA 12.x Highly Recommended (Optional)
GPU acceleration dramatically speeds up face detection (~100x faster).

Before running installer, optionally install NVIDIA CUDA Toolkit 12.x:
https://developer.nvidia.com/cuda-12-4-0-download-wizard

Then cuDNN 9.x: https://developer.nvidia.com/cudnn

**Without CUDA:** App runs on CPU, face detection ~10x slower but functional.

---

## Requirements

- **Python 3.12.x** (exactly 3.12, not 3.11 or 3.14+)
- Windows 7 or newer
- 4GB RAM minimum, 8GB+ recommended
- Internet connection for package downloads

### Why Python 3.12?
- `onnxruntime` (inference engine) incompatible with Python 3.14+
- `lapx` (Hungarian algorithm for tracking) requires 3.12.x wheels
- **Upgrading Python may break the installation**

---

## CUDA & cuDNN Installation (Optional - Highly Recommended)

Profiler Machine can run CPU-only, but GPU acceleration makes face detection ~100x faster.

**With GPU:** 1-2 sec per face, realtime feeds
**Without GPU:** 10+ sec per face, slow but functional

Requires NVIDIA CUDA 12.x + cuDNN 9.x.

### Step 1: Install CUDA Toolkit 12.x

1. Visit: https://developer.nvidia.com/cuda-12-4-0-download-wizard
2. Select:
   - **OS:** Windows
   - **Architecture:** x86_64
   - **Version:** Windows 10 or Windows 11
   - **Installer Type:** exe (local)
3. Download & run installer
4. Accept defaults or choose custom path
5. Verify installation:
   ```
   nvcc --version
   ```
   Should output: `Cuda compilation tools, release 12.x`

### Step 2: Install cuDNN 9.x

1. Create NVIDIA Developer Account (free): https://developer.nvidia.com/login
2. Visit: https://developer.nvidia.com/cudnn
3. Download: **cuDNN 9.x for CUDA 12.x** (choose Windows zip)
4. Extract zip file
5. Copy files to CUDA installation:
   - `bin/` files → `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.x\bin\`
   - `include/` files → `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.x\include\`
   - `lib/` files → `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.x\lib\x64\`

### Step 3: Verify Installation

```bash
python -c "import torch; print(torch.cuda.is_available())"
```
Should output: `True`

If `False`, CUDA/cuDNN not properly installed. Check:
- CUDA path in Windows Environment Variables
- cuDNN files copied to correct CUDA directory
- Visual C++ Redistributable installed (required by CUDA)

### CPU-Only Mode (Default Fallback)

If CUDA/cuDNN unavailable or installation fails, app runs on CPU automatically.

Performance impact:
- Face detection: ~10-15 sec per person (vs 1-2 sec on GPU)
- Body detection: ~2-3 sec per frame (vs 0.2 sec on GPU)
- Anti-spoofing: minimal impact

**No code changes needed.** Just run installer without CUDA/cuDNN.

To manually use CPU-only, edit `requirements.txt` BEFORE running installer:

Remove:
```
onnxruntime-gpu==1.24.4
torch==2.11.0
nvidia-*
```

Add:
```
onnxruntime==1.24.4
torch-cpu==2.11.0
```

Then run installer normally.

---

## What the Installer Does

### 1. Verifies Python 3.12
Exits if wrong version detected.

### 2. Checks OS
Confirms Windows (though script can work on Mac/Linux).

### 3. Creates Virtual Environment
Isolated Python environment in `venv/` directory.
Prevents conflicts with system packages.

### 4. Upgrades pip & setuptools
Ensures package manager handles all dependencies.

### 5. Pre-installs Problematic Packages
**bytetracker (--no-deps):** Installed separately before requirements.txt to avoid dependency conflicts.
**playsound:** Attempts git fork first; falls back to PyPI v1.2.2 if git unavailable.

### 6. Installs requirements.txt
All other packages with pinned versions.
Takes 5–10 minutes depending on internet speed.
Uses `--ignore-installed bytetracker playsound` to preserve pre-installed versions.

### 7. Verifies Imports
Tests critical modules (InsightFace, PyQt5, OpenCV, onnxruntime).
Warnings usually safe to ignore.

### 8. Creates Directories
- `config/` — settings, feeds, session state
- `logs/` — application logs
- `assets/audio/voice/` — TTS cache

---

## Problematic Packages (Handled by Installer)

### bytetracker
**Issue:** Has conflicting nested dependencies that override core packages.
**Solution:** Installer pre-installs with `--no-deps`, then runs full requirements.txt (which respects already-installed version).

### playsound
**Issue:** Custom git fork has no wheels on Python 3.12; requires build tools or Git.
**Solution:** Installer attempts git fork first, falls back to PyPI v1.2.2 if unavailable.
Git fork: `https://github.com/taconi/playsound@92385c78ec05c2fc3afad1afc5edc9d1282aa1e5`
PyPI fallback: `playsound==1.2.2`

---

## Virtual Environment Activation

**IMPORTANT:** After installation, always activate venv before running app.

### Windows
```
call venv\Scripts\activate.bat
```
Prompt changes to `(venv) C:\path>`

### Mac/Linux
```
source venv/bin/activate
```
Prompt changes to `(venv) user@machine:$`

Verify activation: `python --version` should show 3.12.x

---

## Troubleshooting

### "Python 3.12.x required"
**Fix:** Download Python 3.12 from https://www.python.org/downloads/
When installing, check "Add Python to PATH"

### Installation hangs
**Fix:** Open Task Manager, force-quit `python.exe`
Rerun installer. Some packages are large (torch, onnxruntime).

### "onnxruntime import error"
**Fix:** Windows only. Try:
```
pip install --force-reinstall onnxruntime==1.24.4
```
If still failing, check you have Visual C++ Redistributable installed.

### "bytetracker import error"
**Fix:** This is expected if your system lacks lap/lapx wheels.
App will still run, tracking will be slower.
Manual install: `pip install --no-deps bytetracker==0.3.2`

### "playsound import error"
**Fix:** Installer falls back to PyPI v1.2.2 if git install fails.
If still failing: `pip install playsound==1.2.2`
Audio alerts may not work, but app runs normally.

### "ModuleNotFoundError: No module named 'insightface'"
**Fix:** Verify install completed:
```
pip list | grep insightface
```
If missing, manually install:
```
pip install insightface==0.7.3
```

---

## After Installation

### 1. Activate Virtual Environment
```
call venv\Scripts\activate.bat  (Windows)
source venv/bin/activate        (Mac/Linux)
```
Verify: `(venv)` should appear in your command prompt.

### 2. Launch Application
```
python main.py
```

First launch loads face/body models (~2GB downloaded, ~30 sec warmup).
Check `logs/profiler_machine.log` if startup fails.

### 3. Mobile Access (Tailscale)
1. Install Tailscale: https://tailscale.com/download
2. Sign in and connect to network
3. On phone: Open browser to `https://<your-machine-ip>:8000`

---

## Advanced: Manual Install

If installers fail, install step-by-step:

```bash
# 1. Verify Python
python --version
# Should show: Python 3.12.x

# 2. Upgrade tools
python -m pip install --upgrade pip setuptools wheel

# 3. Install all deps
pip install -r requirements.txt

# 4. CRITICAL: Reinstall bytetracker without deps
pip install --force-reinstall --no-deps bytetracker==0.3.2

# 5. Test import
python -c "import insightface; import PyQt5; print('OK')"

# 6. Launch
python main.py
```

---

## System Requirements for ML Models

**Face Recognition (InsightFace):** ~500MB disk, 2GB RAM
**Body Detection (YOLOv8n):** ~50MB disk, 1GB RAM
**Anti-Spoofing (MiniFASNetV2):** ~3MB disk, 512MB RAM
**Whisper (Voice):** ~1.5GB disk, 2GB RAM

Total: ~2-3GB disk, 5-6GB RAM during operation.

---

## Notes

- Batch script is Windows-only (uses `.bat` syntax)
- Python script works on Windows/Mac/Linux (paths auto-adjust)
- Both scripts are idempotent (safe to rerun)
- Do NOT use `pip install -e .` — Profiler Machine is not a package

---

## Getting Help

1. Check `logs/profiler_machine.log` after errors
2. GitHub Issues: https://github.com/antonhrx/profiler-machine
3. Verify all dependencies:
   ```
   pip list
   ```
   Compare against `requirements.txt`