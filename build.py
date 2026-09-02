"""
ProteoPRM - build script
========================
Builds ProteoPRM (folder distribution) and ProteoPRM Results Viewer
(single-file EXE), then assembles them into one distributable folder
and creates an optional ZIP archive for download.

Usage
-----
  python build.py                  # full build + assemble + zip
  python build.py --no-zip         # build + assemble, skip zip
  python build.py --viewer-only    # rebuild viewer EXE only
  python build.py --main-only      # rebuild main app only
  python build.py --check          # dependency check only
"""

import os
import sys
import subprocess
import shutil
import argparse
import zipfile
import time
from pathlib import Path
from datetime import datetime


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE        = Path(__file__).resolve().parent         

# Use a local temporary path for build to avoid 4-hour OneDrive sync bottleneck
LOCAL_TEMP  = Path(os.environ.get('TEMP', 'C:/Temp')) / 'PRM_Build_Work'
DIST        = LOCAL_TEMP / 'dist'
BUILD       = LOCAL_TEMP / 'build'
MAIN_SPEC   = HERE / 'ProteoPRM.spec'
VIEWER_SPEC = HERE / 'ProteoPRM_Results_Viewer.spec'

# Final assembled folder (what the user downloads / uploads to GitHub Releases)
# We will copy the final assembled suite back to the project folder for the user
SUITE_NAME  = 'ProteoPRM_Suite'
SUITE_DIR   = DIST / SUITE_NAME
LOCAL_SUITE = HERE / 'dist' / SUITE_NAME


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hr(char='-', width=64):
    print(char * width)


def _run(cmd, label):
    """Run *cmd* as a subprocess, stream its output, raise on non-zero exit."""
    print(f'\n  Running: {" ".join(str(c) for c in cmd)}\n')
    t0 = time.time()
    result = subprocess.run([str(c) for c in cmd], cwd=str(HERE))
    elapsed = time.time() - t0
    if result.returncode != 0:
        raise RuntimeError(f'{label} failed (exit code {result.returncode})')
    print(f'\n  [OK] {label} completed in {elapsed:.1f} s')


def _find_python():
    return sys.executable


def _pyinstaller():
    """Module invocation is more reliable than the `pyinstaller` shim."""
    return [_find_python(), '-m', 'PyInstaller']


def _major_version(version_text):
    """Best-effort parse of a major version integer."""
    try:
        return int(str(version_text).split('.')[0])
    except Exception:
        return 999


def _prune_broken_dist_info():
    """
    Remove stale *.dist-info folders missing METADATA.

    PyInstaller checks package versions via importlib.metadata; broken dist-info
    folders can make version() return None and crash hooks.
    """
    import sysconfig

    site_packages = Path(sysconfig.get_paths()['purelib'])
    removed = 0

    for dist_info in site_packages.glob('*.dist-info'):
        if not (dist_info / 'METADATA').is_file():
            shutil.rmtree(dist_info, ignore_errors=True)
            if not dist_info.exists():
                removed += 1

    if removed:
        print(f'  [FIX] Removed {removed} broken *.dist-info folders')


def _ensure_setuptools_pkg_resources_compat():
    """
    Ensure pkg_resources still provides APIs expected by PyInstaller runtime hooks.

    PyInstaller's pyi_rth_pkgres hook currently assumes legacy pkg_resources
    symbols (e.g. NullProvider) that are absent in setuptools>=81.
    """
    import warnings
    from importlib import metadata as importlib_metadata

    try:
        setuptools_version = importlib_metadata.version('setuptools')
    except Exception:
        setuptools_version = None

    needs_pin = setuptools_version is None or _major_version(setuptools_version) >= 81
    if needs_pin:
        print('  [FIX] Pinning setuptools to <81 for PyInstaller compatibility ...')
        _run(
            [_find_python(), '-m', 'pip', 'install', '--force-reinstall', 'setuptools<81'],
            'Pin setuptools<81'
        )

    with warnings.catch_warnings():
        warnings.filterwarnings(
            'ignore',
            category=UserWarning,
            message='pkg_resources is deprecated'
        )
        import pkg_resources

    required_symbols = (
        'NullProvider',
        'register_loader_type',
        'register_finder',
        'find_on_path',
    )
    missing = [name for name in required_symbols if not hasattr(pkg_resources, name)]
    if missing:
        raise RuntimeError(
            'pkg_resources compatibility check failed. Missing symbols: '
            + ', '.join(missing)
            + '. Reinstall setuptools<81 and rebuild.'
        )

    final_setuptools = importlib_metadata.version('setuptools')
    print(f'  [OK]  setuptools/pkg_resources compatibility ({final_setuptools})')


def _ensure_pyinstaller_metadata_health():
    """
    Validate metadata needed by PyInstaller hook version checks.
    """
    from importlib import metadata as importlib_metadata

    # Dist names checked by PyInstaller hooks via check_requirement(...)
    critical = ['setuptools', 'matplotlib', 'scipy', 'scikit-learn']
    bad = []
    for dist_name in critical:
        try:
            version = importlib_metadata.version(dist_name)
            if not isinstance(version, str) or not version.strip():
                bad.append(dist_name)
        except Exception:
            bad.append(dist_name)

    if bad:
        raise RuntimeError(
            'Broken package metadata detected for: '
            + ', '.join(sorted(set(bad)))
            + '. Reinstall these packages before building.'
        )


# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------
def check_dependencies():
    _hr()
    print('Checking build dependencies ...')
    _prune_broken_dist_info()
    _ensure_setuptools_pkg_resources_compat()
    _ensure_pyinstaller_metadata_health()

    required = {
        'PyInstaller': 'PyInstaller',
        'numpy':       'numpy',
        'scipy':       'scipy',
        'pandas':      'pandas',
        'pyteomics':   'pyteomics',
        'matplotlib':  'matplotlib',
        'sklearn':     'sklearn',
        'PIL':         'PIL',
        'sv_ttk':      'sv_ttk',
        'tqdm':        'tqdm',
        'pyarrow':     'pyarrow',
        'fisher_py':   'fisher_py',
        'mokapot':     'mokapot',
        'ms2pip':      'ms2pip',
        'peptdeep':    'peptdeep',
        'psm_utils':   'psm_utils',
        'sqlalchemy':  'sqlalchemy',
        'deeplc':      'deeplc',
        'tensorflow':  'tensorflow',
        'numba':       'numba',
        'llvmlite':    'llvmlite',
        'xgboost':     'xgboost',
        'openpyxl':    'openpyxl',
        'xlrd':        'xlrd',
        'xlsxwriter':  'xlsxwriter',
    }
    missing = []
    for label, mod in required.items():
        try:
            # Use find_spec for heavy packages (TF, DeepLC) to avoid slow full import
            if mod in ('tensorflow', 'deeplc'):
                import importlib.util
                if importlib.util.find_spec(mod) is None:
                    raise ImportError(mod)
            else:
                __import__(mod)
            print(f'  [OK]  {label}')
        except ImportError:
            print(f'  [X]   {label}  <-- MISSING')
            missing.append(label)

    if missing:
        print(f'\n  Missing: {", ".join(missing)}')
        print('  Install with:  pip install ' + ' '.join(missing))
        return False

    if not shutil.which('upx'):
        print('\n  [!] UPX not found on PATH - binaries will not be compressed.')
        print('      Download from https://upx.github.io and add to PATH for smaller output.')
    else:
        print(f'  [OK]  UPX  ({shutil.which("upx")})')

    print('\n  All required packages present.')
    return True


# ---------------------------------------------------------------------------
# Build stages
# ---------------------------------------------------------------------------
def build_main():
    """Build ProteoPRM as a one-folder distribution."""
    _hr()
    print('Stage 1/3 - Building ProteoPRM (one-folder) ...')
    if not MAIN_SPEC.exists():
        raise FileNotFoundError(f'Spec not found: {MAIN_SPEC}')
    _run(
        _pyinstaller() + [
            '--clean', '--noconfirm',
            f'--distpath={DIST}',
            f'--workpath={BUILD / "ProteoPRM"}',
            str(MAIN_SPEC),
        ],
        'PyInstaller - ProteoPRM',
    )


def build_viewer():
    """Build ProteoPRM Results Viewer as a single self-contained EXE."""
    _hr()
    print('Stage 2/3 - Building ProteoPRM Results Viewer (one-file EXE) ...')
    if not VIEWER_SPEC.exists():
        raise FileNotFoundError(f'Spec not found: {VIEWER_SPEC}')
    _run(
        _pyinstaller() + [
            '--clean', '--noconfirm',
            f'--distpath={DIST}',
            f'--workpath={BUILD / "ProteoPRM_Results_Viewer"}',
            str(VIEWER_SPEC),
        ],
        'PyInstaller - ProteoPRM_Results_Viewer',
    )


def assemble():
    """
    Merge both build outputs into a single ProteoPRM_Suite/ delivery folder.

    Final layout of ProteoPRM_Suite/:
      ProteoPRM.exe                       main launcher
      ProteoPRM_Results_Viewer.exe        viewer (one-file, placed here)
      _internal/                          Python runtime + shared DLLs
      ms2pip_models/                      MS2PIP XGBoost model files
      AlphaPeptDeep pretrained_models_v3/ APD pretrained model weights
      Trained RT Models/                  .rtmodel files for RT prediction
      calibrated_apd_models/              user-writable; manifest seed only
      unimod.csv / unimod.xml
      GradBoost.rtmodel
      icon.ico
    """
    _hr()
    print('Stage 3/3 - Assembling ProteoPRM_Suite/ ...')

    main_dist   = DIST / 'ProteoPRM'
    viewer_exe  = DIST / 'ProteoPRM_Results_Viewer.exe'

    if not main_dist.is_dir():
        raise FileNotFoundError(
            f'Main app dist not found: {main_dist}\n'
            'Run build_main() first.'
        )

    if SUITE_DIR.exists():
        shutil.rmtree(SUITE_DIR)
        print(f'  Removed old {SUITE_DIR.name}/')

    shutil.copytree(str(main_dist), str(SUITE_DIR))
    print(f'  Copied ProteoPRM dist -> {SUITE_DIR.name}/')

    if viewer_exe.is_file():
        dest = SUITE_DIR / viewer_exe.name
        shutil.copy2(str(viewer_exe), str(dest))
        mb = dest.stat().st_size / 1024 / 1024
        print(f'  Copied ProteoPRM_Results_Viewer.exe  ({mb:.1f} MB)')
    else:
        print(f'  [!] Viewer EXE not found at {viewer_exe} - skipped.')

    total_mb = sum(
        f.stat().st_size for f in SUITE_DIR.rglob('*') if f.is_file()
    ) / 1024 / 1024
    print(f'  Suite total size : {total_mb:.1f} MB')
    print(f'  Output path      : {SUITE_DIR}')

    print(f'  Copying final suite to project folder (OneDrive) ...')
    LOCAL_SUITE.parent.mkdir(parents=True, exist_ok=True)
    # Use robocopy /MIR for OneDrive-resilient mirroring (handles file locks)
    rc = subprocess.run(
        ['robocopy', str(SUITE_DIR), str(LOCAL_SUITE),
         '/MIR', '/MT:8', '/R:3', '/W:5',
         '/NFL', '/NDL', '/NJH', '/NJS', '/NC', '/NS', '/NP'],
        capture_output=True, text=True,
    )
    # robocopy exit codes 0-7 are success; >=8 is failure
    if rc.returncode >= 8:
        print(f'  [!] robocopy failed (exit {rc.returncode}). Falling back to shutil ...')
        if LOCAL_SUITE.exists():
            shutil.rmtree(LOCAL_SUITE, ignore_errors=True)
        shutil.copytree(str(SUITE_DIR), str(LOCAL_SUITE), dirs_exist_ok=True)
    print(f'  Local Project Path    : {LOCAL_SUITE}')


def create_zip():
    """Create a ZIP archive of ProteoPRM_Suite/ for upload to GitHub Releases."""
    _hr()
    print('Creating distribution ZIP (ZIP_DEFLATED level 6) ...')
    date_str  = datetime.now().strftime('%Y%m%d')
    zip_path  = DIST / f'ProteoPRM_Suite_{date_str}.zip'

    if zip_path.exists():
        zip_path.unlink()

    n = 0
    with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(SUITE_DIR.rglob('*')):
            if f.is_file():
                arc = Path(SUITE_NAME) / f.relative_to(SUITE_DIR)
                zf.write(str(f), str(arc))
                n += 1

    mb = zip_path.stat().st_size / 1024 / 1024
    print(f'  [OK] {zip_path.name}  ({mb:.1f} MB,  {n:,} files)')
    
    local_zip = HERE / 'dist' / zip_path.name
    shutil.copy2(str(zip_path), str(local_zip))
    print(f'  Copied ZIP to   : {local_zip}')
    return zip_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description='Build the ProteoPRM executable suite',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--no-zip',      action='store_true', help='Skip ZIP creation')
    parser.add_argument('--main-only',   action='store_true', help='Build main app only')
    parser.add_argument('--viewer-only', action='store_true', help='Build viewer only')
    parser.add_argument('--no-assemble', action='store_true', help='Skip assembly step')
    parser.add_argument('--check',       action='store_true', help='Dependency check only')
    args = parser.parse_args()

    _hr('=')
    print('  ProteoPRM Build System')
    print(f'  {datetime.now().strftime("%Y-%m-%d  %H:%M:%S")}')
    print(f'  Python  : {sys.executable}')
    print(f'  Spec dir: {HERE}')
    _hr('=')

    if not check_dependencies():
        sys.exit(1)

    if args.check:
        return

    t_start = time.time()
    full_build = not args.main_only and not args.viewer_only

    try:
        if args.viewer_only:
            build_viewer()
        elif args.main_only:
            build_main()
        else:
            build_main()
            build_viewer()

        if full_build and not args.no_assemble:
            assemble()
            zip_path = None
            if not args.no_zip:
                zip_path = create_zip()

        elapsed = time.time() - t_start
        _hr('=')
        print(f'  BUILD SUCCESSFUL  ({elapsed / 60:.1f} min)')
        if full_build and not args.no_assemble:
            print(f'  Distributable : {LOCAL_SUITE}')
            if not args.no_zip:
                print(f'  ZIP Archive   : {HERE / "dist" / zip_path.name}')

            if not args.no_zip and zip_path:
                print(f'  ZIP archive   : {zip_path}')
        _hr('=')

    except Exception as exc:
        _hr('=')
        print(f'  BUILD FAILED: {exc}')
        _hr('=')
        sys.exit(1)


if __name__ == '__main__':
    main()

