"""
Portable venv setup script
==========================
Creates or updates the virtual environment for the current user/machine.
This ensures the venv works correctly after cloning to a different computer.

IMPORTANT: ProteoPRM is tested and recommended on Python 3.11+

Usage:
  python setup_venv.py              # Setup Python 3.11 venv (RECOMMENDED)
  python setup_venv.py --venv311    # Explicit Python 3.11 setup
  python setup_venv.py --venv312    # Alternative: Python 3.12 setup
  python setup_venv.py --clean      # Delete and recreate all envs
"""

import os
import sys
import subprocess
import shutil
import argparse
from pathlib import Path


def _check_python_available(target_version='3.11'):
    """Check if target Python version is available on system."""
    try:
        result = subprocess.run(
            ['py', f'-{target_version}', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
    except Exception:
        pass
    return False, None


def get_project_root():
    """Get the project root directory (parent of Executable/)."""
    executable_dir = Path(__file__).parent
    return executable_dir.parent


def setup_venv(venv_name='venv311', python_version='3.11', clean=False):
    """
    Create or update a virtual environment.
    
    Args:
        venv_name: Name of venv folder (e.g., 'venv311', '.venv311')
        python_version: Python version to use (e.g., '3.11', '3.12')
        clean: If True, delete and recreate the venv
    """
    project_root = get_project_root()
    venv_path = project_root / venv_name
    
    print(f"\n{'='*70}")
    print(f"Setting up Python {python_version} virtual environment")
    print(f"{'='*70}")
    print(f"Project root:  {project_root}")
    print(f"Venv path:     {venv_path}")
    print(f"Current user:  {os.getenv('USERNAME', 'unknown')}")
    print(f"Python exe:    {sys.executable}\n")
    
    # Clean existing venv if requested
    if clean and venv_path.exists():
        print(f"[*] Deleting existing venv at {venv_path}...")
        shutil.rmtree(venv_path)
    
    # Create venv
    if not venv_path.exists():
        print(f"[*] Creating new virtual environment...")
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
    
    # Upgrade pip
    print(f"\n[*] Upgrading pip...")
    pip_exe = venv_path / 'Scripts' / 'pip.exe'
    try:
        subprocess.run(
            [str(pip_exe), 'install', '--upgrade', 'pip'],
            check=True,
            capture_output=True
        )
        print(f"[OK] pip upgraded")
    except subprocess.CalledProcessError as e:
        print(f"[WARNING] Failed to upgrade pip: {e}")
    
    # Install requirements if they exist
    requirements_file = Path(__file__).parent / 'requirements.txt'
    if requirements_file.exists():
        print(f"\n[*] Installing requirements from {requirements_file.name}...")
        try:
            subprocess.run(
                [str(pip_exe), 'install', '-r', str(requirements_file)],
                check=True
            )
            print(f"[OK] Requirements installed")
        except subprocess.CalledProcessError as e:
            print(f"[WARNING] Some packages may not have installed: {e}")
    else:
        print(f"[!] No requirements.txt found")
    
    print(f"\n{'='*70}")
    print(f"[SUCCESS] Virtual environment ready!")
    print(f"{'='*70}")
    print(f"\nTo activate on Windows PowerShell:")
    print(f"  .\\{venv_name}\\Scripts\\Activate.ps1")
    print(f"\nTo activate on Windows CMD:")
    print(f"  {venv_name}\\Scripts\\activate.bat\n")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Setup virtual environment for ProteoPRM (Python 3.11+ RECOMMENDED)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python setup_venv.py              # Setup Python 3.11 (RECOMMENDED)
  python setup_venv.py --venv311    # Explicit Python 3.11 setup
  python setup_venv.py --venv312    # Alternative: Python 3.12 setup
  python setup_venv.py --clean      # Delete and recreate all envs

IMPORTANT:
  ProteoPRM is tested and optimized for Python 3.11.
  While 3.12+ may work, 3.11 is the recommended version.
        """
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
        help='Delete and recreate all virtual environments'
    )
    
    args = parser.parse_args()
    
    if args.clean:
        project_root = get_project_root()
        print(f"\n[*] Deleting all virtual environments...")
        for venv_name in ['venv311', 'venv312', '.venv311', '.venv312']:
            venv_path = project_root / venv_name
            if venv_path.exists():
                print(f"    Removing {venv_name}...")
                shutil.rmtree(venv_path)
        
        # Recreate venv311 (recommended)
        print(f"\n[*] Recreating Python 3.11 environment (recommended)...")
        setup_venv('venv311', '3.11', clean=False)
    
    elif args.venv312:
        print(f"\n[!] WARNING: Python 3.12 is supported but not recommended.")
        print(f"    ProteoPRM is tested on Python 3.11.")
        setup_venv('venv312', '3.12', clean=False)
    else:
        # Default: setup venv311 (RECOMMENDED)
        setup_venv('venv311', '3.11', clean=False)
            if venv_path.exists():
                print(f"Deleting {venv_path}...")
                shutil.rmtree(venv_path)
        
        # Recreate both
        setup_venv('venv311', '3.11', clean=False)
        setup_venv('venv312', '3.12', clean=False)
    
    elif args.venv312:
        setup_venv('venv312', '3.12', clean=False)
    else:
        # Default: setup venv311
        setup_venv('venv311', '3.11', clean=False)


if __name__ == '__main__':
    main()
