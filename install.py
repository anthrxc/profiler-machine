#!/usr/bin/env python3
"""
Profiler Machine Installation Script
Handles Python 3.12 constraints and dependency workarounds.

Mirrors install.bat. Creates a venv with Python 3.12, then runs every pip
command through the venv's own interpreter (a running Python process cannot
"activate" a venv in-place the way a shell can, so we call the venv python
explicitly via subprocess).
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / "venv"
CONSTRAINTS = ROOT / "constraints.txt"


def venv_python() -> Path:
    """Path to the python executable inside the venv (OS-dependent layout)."""
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def ok(msg):
    print(f"[OK] {msg}")


def note(msg):
    print(msg)


def fail(msg):
    print(f"ERROR: {msg}")


def run(cmd, check=True, quiet=True, env=None):
    """Run a command. Returns the CompletedProcess, or None on failure when
    check=True so callers can emit a WARNING instead of aborting."""
    kwargs = {"cwd": str(ROOT), "env": env}
    if quiet:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    result = subprocess.run(cmd, **kwargs)
    if check and result.returncode != 0:
        return None
    return result


def pip(args, py=None, quiet=True, env=None):
    """Invoke pip via the given python (defaults to the venv python)."""
    python = str(py) if py else str(venv_python())
    return run([python, "-m", "pip", *args], check=True, quiet=quiet, env=env)


def find_python_312():
    """Return (command_list, version_str) that launches Python 3.12, or (None, None).

    On Windows prefer the 'py -3.12' launcher; otherwise fall back to the
    interpreter running this script if it happens to be 3.12.
    """
    if os.name == "nt":
        probe = subprocess.run(
            ["py", "-3.12", "--version"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        if probe.returncode == 0:
            return ["py", "-3.12"], probe.stdout.strip().split()[-1]

    # Fallback: this interpreter, only if it is 3.12.x
    major, minor, micro = sys.version_info[:3]
    if (major, minor) == (3, 12):
        return [sys.executable], f"{major}.{minor}.{micro}"
    return None, None


def _cleanup():
    """Remove the temporary constraints file if present."""
    try:
        if CONSTRAINTS.exists():
            CONSTRAINTS.unlink()
    except OSError:
        pass


def main():
    print()
    print("========================================")
    print("Profiler Machine Installer")
    print("========================================")
    print()

    # Python 3.12 check
    py312, py_version = find_python_312()
    if py312 is None:
        fail("Python 3.12 not found")
        print("Please install Python 3.12.x from https://www.python.org/downloads/")
        print('Make sure to check "Add to PATH" during installation')
        sys.exit(1)
    ok(f"Python {py_version} detected")
    print()

    # [1/9] Create virtual environment
    print("[1/9] Creating virtual environment...")
    if VENV_DIR.exists():
        print("Virtual environment already exists, skipping creation")
    else:
        if run([*py312, "-m", "venv", str(VENV_DIR)], check=True, quiet=True) is None:
            fail("Failed to create virtual environment")
            sys.exit(1)
    if not venv_python().exists():
        fail("venv python not found after creation")
        sys.exit(1)
    ok("Virtual environment ready")
    print()

    vpy = venv_python()

    # Report the venv interpreter version (parity with the .bat)
    ver = subprocess.run([str(vpy), "--version"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    ok(f"venv Python: {ver.stdout.strip().split()[-1]}")
    print()

    # [2/9] CUDA check
    print("[2/9] Checking for CUDA installation...")
    cuda_ok = False
    if shutil.which("nvcc") is not None:
        nvcc = subprocess.run(["nvcc", "--version"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cuda_ok = nvcc.returncode == 0
    if cuda_ok:
        ok("CUDA Toolkit detected - GPU acceleration enabled")
    else:
        note("NOTE: CUDA Toolkit not detected. App will run on CPU.")
        note("See INSTALL.md for optional GPU setup.")
    print()

    # [3/9] Build constraints (setuptools fix)
    # setuptools 81 removed importable pkg_resources, which breaks legacy
    # source builds (e.g. lap, pulled in transitively by ultralytics/bytetracker).
    # Exporting this constraint via PIP_CONSTRAINT applies the cap to pip's
    # isolated BUILD envs too, not just this venv.
    print("[3/9] Configuring build constraints (setuptools fix)...")
    CONSTRAINTS.write_text("setuptools<81\n", encoding="utf-8")
    env = os.environ.copy()
    env["PIP_CONSTRAINT"] = str(CONSTRAINTS)

    pip(["install", "--upgrade", "pip", "wheel"], py=vpy, env=env)
    if pip(["install", "--upgrade", "setuptools"], py=vpy, env=env) is None:
        fail("Failed to set up pip/setuptools/wheel")
        sys.exit(1)

    shown = subprocess.run(
        [str(vpy), "-m", "pip", "show", "setuptools"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    setuptools_version = "unknown"
    for line in shown.stdout.splitlines():
        if line.startswith("Version:"):
            setuptools_version = line.split(":", 1)[1].strip()
            break
    ok(f"pip and wheel ready, setuptools pinned to {setuptools_version}")
    print()

    # [4/9] Pre-install lapx (prebuilt wheels, provides the lap import, no compiler)
    print("[4/9] Pre-installing lapx (lap conflict workaround)...")
    if pip(["install", "lapx==0.9.4"], py=vpy, env=env) is None:
        print("WARNING: lapx pre-install had issues, will retry in main install")
    ok("lapx prepared")
    print()

    # [5/9] Pre-install bytetracker + ultralytics (--no-deps)
    # Both declare a dependency on the 'lap' distribution, which only ships as
    # a source build (needs numpy + a compiler) and keeps failing. lapx above
    # already provides the 'lap' import at runtime, so installing these
    # --no-deps stops pip from ever pulling/building real lap. requirements.txt
    # is a full freeze, so every other dependency is still pinned.
    print("[5/9] Pre-installing bytetracker and ultralytics (--no-deps workaround)...")
    if pip(["install", "--no-deps", "bytetracker==0.3.2"], py=vpy, env=env) is None:
        print("WARNING: bytetracker pre-install failed, will attempt in main install")
    if pip(["install", "--no-deps", "ultralytics==8.3.50"], py=vpy, env=env) is None:
        print("WARNING: ultralytics pre-install failed, will attempt in main install")
    ok("bytetracker and ultralytics prepared")
    print()

    # [6/9] Pre-install playsound
    print("[6/9] Pre-installing playsound...")
    if pip(["install", "playsound==1.2.2"], py=vpy, env=env) is None:
        print("WARNING: playsound pre-install failed, will retry in main install")
    ok("playsound prepared")
    print()

    # [7/9] Install all dependencies
    # PIP_CONSTRAINT (set above) is still in effect and propagates to any
    # isolated build env, so pkg_resources is available there.
    print("[7/9] Installing all dependencies from requirements.txt...")
    print("This may take several minutes (installing torch, onnxruntime, etc)...")
    result = pip(
        ["install", "-r", "requirements.txt", "--prefer-binary"],
        py=vpy, quiet=False, env=env,
    )
    if result is None:
        print("WARNING: Some packages may have failed to install")
        print("Check output above for details")
        print("Installation will continue with verification...")
    ok("Dependencies installed")
    print()

    # [8/9] Verify critical imports
    print("[8/9] Verifying critical imports...")
    import_check = (
        "import insightface; import PyQt5; import cv2; import onnxruntime; "
        "import torch; import lap; import bytetracker; import ultralytics"
    )
    verify = subprocess.run(
        [str(vpy), "-c", import_check],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if verify.returncode != 0:
        print("WARNING: Some critical imports failed")
        print("Run this to see the full error:")
        print(f'  "{vpy}" -c "{import_check}"')
        _cleanup()
        sys.exit(1)
    ok("All critical imports verified")
    print()

    # [9/9] Create application directories
    print("[9/9] Creating application directories...")
    (ROOT / "config").mkdir(exist_ok=True)
    (ROOT / "logs").mkdir(exist_ok=True)
    ok("Directories created")
    print()

    _cleanup()
    ok("Erased temporary files")
    print()

    # Done
    activate = (r"venv\Scripts\activate.bat" if os.name == "nt"
                else "source venv/bin/activate")
    print("========================================")
    print("Installation Complete!")
    print("========================================")
    print()
    print("IMPORTANT: Ignore pip errors about dependency conflicts,")
    print("  this is expected and the sole purpose of this installation script.")
    print()
    print("IMPORTANT: Always activate venv before running:")
    print(f"  {activate}")
    print()
    print("Next steps:")
    print(f"  1. Activate venv (if not already active): {activate}")
    print("  2. Launch Profiler Machine: python main.py")
    print("  3. For mobile access: Configure Tailscale on your network")
    print("  4. Check logs/profiler_machine.log for errors")
    print()
    print("If you encounter issues:")
    print('  - Verify venv is active (should see "(venv)" in prompt)')
    print("  - For GPU speedup: Check INSTALL.md for optional CUDA 12.x setup")
    print("  - Reinstall package: pip install --force-reinstall --no-cache-dir [package]")
    print("  - Check GitHub issues for known solutions")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInstallation cancelled.")
        _cleanup()
        sys.exit(1)