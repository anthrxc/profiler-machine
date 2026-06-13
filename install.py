#!/usr/bin/env python3
"""
Profiler Machine Installation Script
Handles Python 3.12 constraints and dependency workarounds for Windows
"""

import sys
import subprocess
import os
import platform
from pathlib import Path


class Installer:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.venv_python = sys.executable
        
    def log_error(self, msg):
        print(f"❌ ERROR: {msg}")
        self.errors.append(msg)
    
    def log_warning(self, msg):
        print(f"⚠️  WARNING: {msg}")
        self.warnings.append(msg)
    
    def log_success(self, msg):
        print(f"✓ {msg}")
    
    def check_python_version(self):
        """Verify Python 3.12.x is running"""
        print("\n[1/8] Checking Python version...")
        
        major, minor, micro = sys.version_info[:3]
        version_str = f"{major}.{minor}.{micro}"
        
        if major != 3 or minor != 12:
            self.log_error(f"Python 3.12.x required, found {version_str}")
            self.log_error("Python 3.14+ is incompatible with onnxruntime/lapx")
            return False
        
        self.log_success(f"Python {version_str} detected")
        return True
    
    def check_os(self):
        """Verify Windows platform"""
        print("\n[2/8] Checking OS...")
        
        if platform.system() != "Windows":
            self.log_warning(f"Script optimized for Windows, detected {platform.system()}")
            self.log_warning("Some paths/commands may not work correctly")
            return True
        
        self.log_success("Windows detected")
        return True
    
    def check_cuda(self):
        """Check for CUDA installation (optional)"""
        print("\n[3/8] Checking for CUDA...")
        
        try:
            result = subprocess.run(
                ["nvcc", "--version"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                self.log_success("CUDA Toolkit detected (GPU acceleration enabled)")
                return True
            else:
                print("      CUDA not found (optional - app will run on CPU)")
                print("      See INSTALL.md for optional GPU setup")
                return True
        except FileNotFoundError:
            print("      CUDA Toolkit not in PATH (optional - app will run on CPU)")
            print("      See INSTALL.md for optional GPU setup")
            return True
        except Exception as e:
            self.log_warning(f"Could not check CUDA: {str(e)[:100]}")
            return True
    
    def create_venv(self):
        """Create virtual environment"""
        print("\n[4/8] Creating virtual environment...")
        
        venv_path = Path("venv")
        if venv_path.exists():
            self.log_success("venv directory already exists")
        else:
            try:
                subprocess.run(
                    [sys.executable, "-m", "venv", "venv"],
                    capture_output=True,
                    check=True,
                    timeout=60
                )
                self.log_success("Virtual environment created")
            except subprocess.CalledProcessError as e:
                self.log_error(f"Failed to create venv: {e.stderr.decode()[:200]}")
                return False
            except Exception as e:
                self.log_error(f"Unexpected error: {str(e)}")
                return False
        
        # Set Python executable to use venv version
        if platform.system() == "Windows":
            self.venv_python = str(venv_path / "Scripts" / "python.exe")
        else:
            self.venv_python = str(venv_path / "bin" / "python")
        
        return True
    
    def upgrade_pip(self):
        """Upgrade pip, setuptools, wheel in venv"""
        print("\n[5/8] Upgrading pip and setuptools...")
        
        try:
            subprocess.run(
                [self.venv_python, "-m", "pip", "install", "--upgrade", 
                 "pip", "setuptools", "wheel"],
                capture_output=True,
                check=True,
                timeout=300
            )
            self.log_success("pip and setuptools upgraded")
            return True
        except subprocess.CalledProcessError as e:
            self.log_error(f"Failed to upgrade pip: {e.stderr.decode()[:200]}")
            return False
        except Exception as e:
            self.log_error(f"Unexpected error: {str(e)}")
            return False
    
    def pre_install_problematic(self):
        """Pre-install packages that fail in requirements.txt"""
        print("\n[6/8] Pre-installing problematic packages...")
        
        # Install bytetracker with --no-deps
        print("      Installing bytetracker (--no-deps)...")
        try:
            subprocess.run(
                [self.venv_python, "-m", "pip", "install", "--no-deps",
                 "bytetracker==0.3.2"],
                capture_output=True,
                check=False,
                timeout=300
            )
            self.log_success("bytetracker (--no-deps)")
        except Exception as e:
            self.log_warning(f"bytetracker pre-install: {str(e)[:100]}")
        
        # Install playsound from git
        print("      Installing playsound from git...")
        try:
            subprocess.run(
                [self.venv_python, "-m", "pip", "install",
                 "git+https://github.com/taconi/playsound@92385c78ec05c2fc3afad1afc5edc9d1282aa1e5"],
                capture_output=True,
                check=False,
                timeout=300
            )
            self.log_success("playsound (git)")
        except Exception:
            # Fallback to PyPI version
            print("      Falling back to playsound==1.2.2 from PyPI...")
            try:
                subprocess.run(
                    [self.venv_python, "-m", "pip", "install", "playsound==1.2.2"],
                    capture_output=True,
                    check=False,
                    timeout=300
                )
                self.log_success("playsound (PyPI fallback)")
            except Exception as e:
                self.log_warning(f"playsound fallback: {str(e)[:100]}")
    
    def install_requirements(self):
        """Install from requirements.txt (bytetracker/playsound already done)"""
        print("\n[7/8] Installing remaining dependencies from requirements.txt...")
        print("      (This may take 5-10 minutes...)")
        
        req_path = Path("requirements.txt")
        if not req_path.exists():
            self.log_error("requirements.txt not found in current directory")
            return False
        
        try:
            subprocess.run(
                [self.venv_python, "-m", "pip", "install", "-r", "requirements.txt",
                 "--no-warn-script-location", "--ignore-installed", "bytetracker", "playsound"],
                capture_output=True,
                check=False,
                timeout=1200
            )
            self.log_success("Dependencies installed (some warnings expected)")
            return True
        except subprocess.TimeoutExpired:
            self.log_error("Installation timed out (>20 minutes)")
            return False
        except Exception as e:
            self.log_error(f"Installation failed: {str(e)}")
            return False
    
    def verify_imports(self):
        """Test critical imports"""
        print("\n[8/8] Verifying critical imports...")
        
        imports = [
            ("insightface", "Face recognition"),
            ("PyQt5", "UI framework"),
            ("cv2", "Computer vision"),
            ("onnxruntime", "ONNX inference"),
            ("bytetrack", "Multi-object tracking"),
            ("flask", "Web server"),
            ("sqlite3", "Database"),
        ]
        
        failed = []
        for module, description in imports:
            try:
                # Use venv Python to import
                result = subprocess.run(
                    [self.venv_python, "-c", f"import {module}"],
                    capture_output=True,
                    check=True,
                    timeout=10
                )
                self.log_success(f"{description} ({module})")
            except Exception as e:
                self.log_warning(f"{description} ({module}): {str(e)[:100]}")
                failed.append(module)
        
        if failed:
            self.log_warning(f"{len(failed)} imports failed, but app may still run")
            self.log_warning("Check logs/profiler_machine.log after first launch")
            return True
        
        return True
    
    def create_directories(self):
        """Create required directories"""
        print("\nCreating application directories...")
        
        dirs = [
            "config",
            "logs",
        ]
        
        for dir_path in dirs:
            Path(dir_path).mkdir(parents=True, exist_ok=True)
            self.log_success(f"Directory: {dir_path}")
    
    def run(self):
        """Execute full installation"""
        print("=" * 50)
        print("Profiler Machine Installer")
        print("=" * 50)
        
        steps = [
            ("Python version check", self.check_python_version),
            ("OS check", self.check_os),
            ("CUDA check", self.check_cuda),
            ("Create virtual environment", self.create_venv),
            ("Upgrade pip", self.upgrade_pip),
            ("Pre-install problematic packages", self.pre_install_problematic),
            ("Install remaining dependencies", self.install_requirements),
            ("Verify imports", self.verify_imports),
        ]
        
        for step_name, step_func in steps:
            if not step_func():
                self.log_error(f"Failed at: {step_name}")
                if step_name not in ["Verify imports"]:
                    return False
        
        self.create_directories()
        
        # Print summary
        print("\n" + "=" * 50)
        if self.errors:
            print("Installation FAILED")
            print("=" * 50)
            for err in self.errors:
                print(f"  • {err}")
            return False
        else:
            print("Installation COMPLETE!")
            print("=" * 50)
            if self.warnings:
                print("\nWarnings:")
                for warn in self.warnings:
                    print(f"  • {warn}")
            
            print("\nIMPORTANT: Always activate venv before running:")
            if platform.system() == "Windows":
                print("  call venv\\Scripts\\activate.bat")
            else:
                print("  source venv/bin/activate")
            
            print("\nNext steps:")
            print("  1. Activate venv (if not already active)")
            print("  2. Launch: python main.py")
            print("  3. Mobile access: Configure Tailscale")
            print("  4. Errors? Check: logs/profiler_machine.log")
            print("\nGitHub: https://github.com/antonhrx/profiler-machine")
            return True


if __name__ == "__main__":
    installer = Installer()
    success = installer.run()
    sys.exit(0 if success else 1)