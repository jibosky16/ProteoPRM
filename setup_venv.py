"""
Portable venv setup script
==========================
Creates or updates the virtual environment for the current user/machine.

IMPORTANT: ProteoPRM is tested and recommended on Python 3.11+

Usage:
    python setup_venv.py              # Setup Python 3.11 venv (RECOMMENDED)
    python setup_venv.py --venv311    # Explicit Python 3.11 setup
    python setup_venv.py --venv312    # Alternative: Python 3.12 setup
    python setup_venv.py --clean      # Delete and recreate the 3.11 env
"""

import os
import sys
import subprocess
import shutil
import argparse
from pathlib import Path


def get_project_root():
    """Repository root (directory that contains this script)."""
    return Path(__file__).resolve().parent


def setup_venv(venv_name='venv311', python_version='3.11', clean=False):
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

    args = parser.parse_args()

    if args.clean:
        setup_venv('venv311', '3.11', clean=True)
    elif args.venv312:
        print("\n[!] WARNING: Python 3.12 is supported but not recommended.")
        print("    ProteoPRM is tested on Python 3.11.")
        setup_venv('venv312', '3.12', clean=False)
    else:
        setup_venv('venv311', '3.11', clean=False)


if __name__ == '__main__':
    main()
