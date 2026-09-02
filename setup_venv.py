"""
Portable venv setup script
==========================
Creates or updates the virtual environment for the current user/machine.

IMPORTANT: ProteoPRM is tested and recommended on Python 3.11+

GPU support (out of the box):
    After installing requirements, this script checks for an NVIDIA GPU
    (via nvidia-smi). If one is found, it automatically replaces the default
    PyTorch wheel with the matching CUDA build so AlphaPeptDeep predictions
    run on the GPU with no manual steps. Machines without an NVIDIA GPU
    keep the default wheel and run on CPU. Use --cpu-only to skip this.

Usage:
    python setup_venv.py              # Setup Python 3.11 venv (RECOMMENDED)
    python setup_venv.py --venv311    # Explicit Python 3.11 setup
    python setup_venv.py --venv312    # Alternative: Python 3.12 setup
    python setup_venv.py --clean      # Delete and recreate the 3.11 env
    python setup_venv.py --cpu-only   # Skip CUDA PyTorch auto-install
"""

import os
import re
import sys
import subprocess
import shutil
import argparse
from pathlib import Path

# Torch pin must match requirements.txt. The CUDA wheels bundle the CUDA
# runtime + kernels for every NVIDIA architecture PyTorch supports (with PTX
# forward-compatibility for newer cards), so one wheel covers all common
# NVIDIA GPUs — only a reasonably recent driver is required on the machine.
TORCH_PIN = 'torch==2.10.0'
TORCH_CUDA12_INDEX = 'https://download.pytorch.org/whl/cu124'
TORCH_CUDA11_INDEX = 'https://download.pytorch.org/whl/cu118'


def get_project_root():
    """Repository root (directory that contains this script)."""
    return Path(__file__).resolve().parent


def detect_nvidia_gpu():
    """Return (gpu_name, driver_cuda_major) or (None, None) if no NVIDIA GPU."""
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None, None
        gpu_name = result.stdout.strip().split('\n')[0].strip()

        cuda_major = None
        result2 = subprocess.run(['nvidia-smi'], capture_output=True, text=True, timeout=10)
        if result2.returncode == 0:
            m = re.search(r'CUDA Version:\s*(\d+)\.(\d+)', result2.stdout)
            if m:
                cuda_major = int(m.group(1))
        return gpu_name, cuda_major
    except Exception:
        return None, None


def install_cuda_torch(pip_exe, python_exe):
    """Install the CUDA build of PyTorch when an NVIDIA GPU is present.

    Called after requirements.txt so it simply replaces the default torch
    wheel with the CUDA one for the same pinned version. No-op without an
    NVIDIA GPU. Returns True if a CUDA torch install was performed.
    """
    gpu_name, cuda_major = detect_nvidia_gpu()
    if not gpu_name:
        print("\n[*] No NVIDIA GPU detected (nvidia-smi absent) — keeping default PyTorch (CPU).")
        return False

    print(f"\n[*] NVIDIA GPU detected: {gpu_name} "
          f"(driver CUDA {cuda_major if cuda_major else 'unknown'})")

    # Check whether the installed torch is already CUDA-capable.
    try:
        check = subprocess.run(
            [str(python_exe), '-c',
             'import torch; print(torch.version.cuda or "cpu")'],
            capture_output=True, text=True, timeout=120
        )
        if check.returncode == 0 and check.stdout.strip() not in ('', 'cpu', 'None'):
            print(f"[OK] Installed PyTorch is already a CUDA build "
                  f"(CUDA {check.stdout.strip()}) — nothing to do.")
            return False
    except Exception:
        pass

    if cuda_major is not None and cuda_major < 11:
        print("[!] Driver CUDA version is older than 11 — too old for current "
              "PyTorch CUDA wheels. Update the NVIDIA driver, then re-run this script.")
        return False

    index_url = TORCH_CUDA11_INDEX if (cuda_major == 11) else TORCH_CUDA12_INDEX
    print(f"[*] Installing CUDA PyTorch ({TORCH_PIN}) from {index_url}")
    print("    (~2.5 GB download — this enables GPU AlphaPeptDeep predictions)")
    try:
        subprocess.run(
            [str(pip_exe), 'install', '--force-reinstall', TORCH_PIN,
             '--index-url', index_url],
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"[WARNING] CUDA PyTorch install failed ({e}). "
              f"The app will run on CPU; re-run this script to retry.")
        return False

    # Verify CUDA actually works in the venv.
    try:
        verify = subprocess.run(
            [str(python_exe), '-c',
             'import torch; '
             'ok = torch.cuda.is_available(); '
             'print(torch.cuda.get_device_name(0) if ok else "unavailable")'],
            capture_output=True, text=True, timeout=180
        )
        out = verify.stdout.strip()
        if verify.returncode == 0 and out and out != 'unavailable':
            print(f"[OK] PyTorch CUDA verified on: {out}")
        else:
            print("[WARNING] CUDA torch installed but CUDA is not usable yet "
                  "(driver too old?). The app will fall back to CPU automatically.")
    except Exception as e:
        print(f"[WARNING] Could not verify CUDA torch: {e}")
    return True


def setup_venv(venv_name='venv311', python_version='3.11', clean=False, cpu_only=False):
    """Create or update a virtual environment in the project root."""
    project_root = get_project_root()
    venv_path = project_root / venv_name

    print(f"\n{'='*70}")
    print(f"Setting up Python {python_version} virtual environment")
    print(f"{'='*70}")
    print(f"Project root:  {project_root}")
    print(f"Venv path:     {venv_path}")
    print(f"Current user:  {os.getenv('USERNAME', os.getenv('USER', 'unknown'))}")
    print(f"Python exe:    {sys.executable}\n")

    if clean and venv_path.exists():
        print(f"[*] Deleting existing venv at {venv_path}...")
        shutil.rmtree(venv_path)

    if not venv_path.exists():
        print("[*] Creating new virtual environment...")
        try:
            subprocess.run(
                [sys.executable, '-m', 'venv', str(venv_path)],
                check=True
            )
            print(f"[OK] Virtual environment created at {venv_path}")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to create venv: {e}")
            return False
    else:
        print(f"[*] Virtual environment already exists at {venv_path}")

    if sys.platform == 'win32':
        pip_exe = venv_path / 'Scripts' / 'pip.exe'
        python_exe = venv_path / 'Scripts' / 'python.exe'
    else:
        pip_exe = venv_path / 'bin' / 'pip'
        python_exe = venv_path / 'bin' / 'python'

    print("\n[*] Upgrading pip...")
    try:
        subprocess.run(
            [str(python_exe), '-m', 'pip', 'install', '--upgrade', 'pip'],
            check=True,
        )
        print("[OK] pip upgraded")
    except subprocess.CalledProcessError as e:
        print(f"[WARNING] Failed to upgrade pip: {e}")

    requirements_file = project_root / 'requirements.txt'
    if requirements_file.exists():
        print(f"\n[*] Installing requirements from {requirements_file.name}...")
        try:
            subprocess.run(
                [str(pip_exe), 'install', '-r', str(requirements_file)],
                check=True
            )
            print("[OK] Requirements installed")
        except subprocess.CalledProcessError as e:
            print(f"[WARNING] Some packages may not have installed: {e}")
    else:
        print("[!] No requirements.txt found")

    # GPU support out of the box: swap in CUDA PyTorch when an NVIDIA GPU
    # is present (no-op otherwise; --cpu-only skips entirely).
    if cpu_only:
        print("\n[*] --cpu-only: skipping CUDA PyTorch auto-install.")
    else:
        install_cuda_torch(pip_exe, python_exe)

    print(f"\n{'='*70}")
    print("[SUCCESS] Virtual environment ready!")
    print(f"{'='*70}")
    if sys.platform == 'win32':
        print(f"\nTo activate on Windows PowerShell:")
        print(f"  .\\{venv_name}\\Scripts\\Activate.ps1")
        print(f"\nTo activate on Windows CMD:")
        print(f"  {venv_name}\\Scripts\\activate.bat\n")
    else:
        print(f"\nTo activate:")
        print(f"  source {venv_name}/bin/activate\n")

    return True


def main():
    parser = argparse.ArgumentParser(
        description='Setup virtual environment for ProteoPRM (Python 3.11+ RECOMMENDED)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--venv311',
        action='store_true',
        help='Setup Python 3.11 venv (RECOMMENDED - venv311)'
    )
    group.add_argument(
        '--venv312',
        action='store_true',
        help='Setup Python 3.12 venv (alternative - venv312)'
    )
    group.add_argument(
        '--clean',
        action='store_true',
        help='Delete and recreate the Python 3.11 virtual environment'
    )
    parser.add_argument(
        '--cpu-only',
        action='store_true',
        help='Skip automatic CUDA PyTorch install even if an NVIDIA GPU is detected'
    )

    args = parser.parse_args()

    if args.clean:
        setup_venv('venv311', '3.11', clean=True, cpu_only=args.cpu_only)
    elif args.venv312:
        print("\n[!] WARNING: Python 3.12 is supported but not recommended.")
        print("    ProteoPRM is tested on Python 3.11.")
        setup_venv('venv312', '3.12', clean=False, cpu_only=args.cpu_only)
    else:
        setup_venv('venv311', '3.11', clean=False, cpu_only=args.cpu_only)


if __name__ == '__main__':
    main()
