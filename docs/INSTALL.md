# Profiler Machine Installation Guide

## Requirements

- **Python 3.12.x** (exactly 3.12, not 3.11 or 3.14+)
- Windows 7 or newer, **or** a modern Linux distribution (verified on Arch)
- 4GB RAM minimum, 8GB+ recommended
- Internet connection for package downloads
- An NVIDIA GPU is highly recommended, AMD GPUs are unfortunately currently not supported  
- **Linux only:** an audio CLI player on `PATH` for alert sounds — `ffmpeg` (provides `ffplay`) is recommended; `paplay`/`aplay` also work. Without one the app runs fine, alerts are just silent.

### Why Python 3.12?
- `onnxruntime` (inference engine) incompatible with Python 3.14+
- `lapx` requires 3.12.x wheels
- **Upgrading Python may break the installation**

## CUDA & cuDNN Installation (Optional, though highly recommended)

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
5. Verify installation (run this command in cmd/any terminal):
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
Again, in your terminal, type:
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

## Installing PROFM

### Windows Users

Navigate to the folder where you downloaded the project and find the following file:  
```
install.bat
```
Double-click or run in Command Prompt. The installation script handles everything else.

### Linux

Run the cross-platform installer:
```
python install.py
```
The installer needs a Python 3.12 interpreter. It looks for one in this order:
1. `python3.12` on your `PATH`
2. the interpreter you launched it with (if it happens to be 3.12)
3. a standalone 3.12 fetched via [`uv`](https://docs.astral.sh/uv/)

Arch and other rolling distros ship Python 3.13+, which breaks `onnxruntime`/`lapx`, so
install **either** a 3.12 package **or** `uv` before running the installer:

```bash
# Option A — uv (recommended; no system Python changes)
sudo pacman -S uv         # or: curl -LsSf https://astral.sh/uv/install.sh | sh
python install.py         # install.py calls `uv python install 3.12` for you

# Option B — a distro/AUR 3.12 package, then point the installer at it
python3.12 install.py
```

For alert audio, install an `ffplay`-capable player (skip if you don't care about sounds):
```bash
sudo pacman -S ffmpeg     # Debian/Ubuntu: sudo apt install ffmpeg
```

> macOS is untested. The installer's logic is the same there; contributions welcome.

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
Warnings usually safe to ignore (`pip` **will** warn about dependency conflicts, this is safe to ignore and the whole reason for the installation script).

### 8. Creates Directories
- `config/` — stores settings, feeds, session state
- `logs/` — application logs


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
If still failing, check if you have Visual C++ Redistributable installed.

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
In your preferred console, type:
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

### 2. Enroll yourself as root
Navigate to `profiler-machine\database\enroll`, and place any image with a clear view of your face inside this folder.

### 3. Launch Application
```
python main.py
```

On startup, the app will ask you to choose from available webcams that were detected on your computer.  
Select any webcam(s) you'd like to add, and these will be automatically saved to `config\feeds.json`.  
First launch loads face/body models (~2GB downloaded, ~30 sec warmup).  
Check `logs/profiler_machine.log` if startup fails.  
If all went well, try logging in by typing `profiler login 000-00-0000`.

### 4. Enroll further people
If there's anyone else that you'd like to enroll, you can place an image of them in the same folder as before (`profiler-machine\database\enroll`). Everyone who is enrolled from this folder will be designated as `IRRELEVANT` unless manually changed from inside the app. Anyone who hasn't been enrolled and appears in any feed for more than a few seconds will be automatically enrolled (though they can be randomly designated as `IRRELEVANT` (89% chance), `PERPETRATOR`/`VICTIM` (5% chance each) or `THREAT` (1% chance)).

### 5. Mobile Access (Tailscale)
If you wish to access the PROFM web interface outside of your local network, follow these steps:
1. Install Tailscale: https://tailscale.com/download
2. Add your computer and phone (or other devices you wish to access the interface from) to the Tailnet
3. Ensure all your devices are connected to the Tailnet
4. On your phone: Open your browser and navigate to to `https://<tailscale-computer-ip>:8000`

### 6. Enjoy!
You now hold the entire power PROFM has to hold. If you'd like to see a list of console commands and what they do, you can either run `help` in the app's console, or check [COMMANDS.md](COMMANDS.md).

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

Total: <1GB disk, 3-5GB RAM during operation.

---

## Notes

- Batch script is Windows-only (uses `.bat` syntax)
- Python script works on Windows/Mac/Linux (paths auto-adjust)
- Both scripts are idempotent (safe to rerun)
- Do NOT use `pip install -e .` — Profiler Machine is not a package

---

## Getting Help

1. Check `logs/profiler_machine.log` after errors
2. GitHub Issues: https://github.com/anthrxc/profiler-machine
3. Verify all dependencies:
   ```
   pip list
   ```
   Compare against `requirements.txt`
4. If all else fails, use your preferred AI model to help you out (and please open a GitHub issue where you share the chat where your issues were solved)
