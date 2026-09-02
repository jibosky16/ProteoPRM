"""
ProteoPRM - build script
========================
Builds ProteoPRM (folder distribution) and ProteoPRM Results Viewer
(single-file EXE), then assembles them into one distributable folder
and creates an optional ZIP archive for download.

Usage
-----
  python build.py --both           # CPU + GPU suites (recommended)
  python build.py --cpu            # CPU-only suite
  python build.py --gpu            # CUDA GPU suite (also runs on CPU machines)
  python build.py                  # full build with currently installed torch
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

# Must match setup_venv.py / requirements.txt. CUDA wheels include kernels for
# all NVIDIA architectures PyTorch supports; CPU wheels keep the suite small.
TORCH_PIN         = 'torch==2.10.0'
TORCH_CPU_INDEX   = 'https://download.pytorch.org/whl/cpu'
TORCH_CUDA_INDEX  = 'https://download.pytorch.org/whl/cu124'


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


def _suite_layout(variant=None):
    """Return (suite_name, temp_suite_dir, project_suite_dir) for a torch variant."""
    if variant in ('CPU', 'GPU'):
        name = f'ProteoPRM_Suite_{variant}'
    else:
        name = SUITE_NAME
    return name, DIST / name, HERE / 'dist' / name


def _torch_info_subprocess():
    """
    Query torch in a fresh interpreter so a prior import (or a pip
    reinstall mid-build) cannot leave this process with a stale module.
    """
    probe = (
        'import torch; '
        'print(torch.__version__); '
        'print(getattr(getattr(torch, "version", None), "cuda", None) or "")'
    )
    result = subprocess.run(
        [_find_python(), '-c', probe],
        capture_output=True, text=True, timeout=300, cwd=str(HERE),
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or 'unknown error').strip()
        raise RuntimeError(f'torch probe failed: {err}')
    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    version = lines[0] if lines else 'unknown'
    cuda = lines[1] if len(lines) > 1 else ''
    return version, cuda


def install_torch(variant):
    """Install the CPU or CUDA PyTorch wheel matching TORCH_PIN."""
    if variant == 'GPU':
        index = TORCH_CUDA_INDEX
        label = 'CUDA PyTorch'
    elif variant == 'CPU':
        index = TORCH_CPU_INDEX
        label = 'CPU PyTorch'
    else:
        raise ValueError(f'Unknown torch variant: {variant}')

    print(f'\n  Installing {label} ({TORCH_PIN}) from {index}')
    print('  This can take several minutes (CUDA wheel is ~2.5 GB).')
    _run(
        [_find_python(), '-m', 'pip', 'install', '--force-reinstall',
         TORCH_PIN, '--index-url', index],
        f'Install {label}',
    )
    version, cuda = _torch_info_subprocess()
    if variant == 'GPU' and not cuda:
        raise RuntimeError(
            f'Installed torch {version} is still CPU-only after CUDA install. '
            f'Check network access to {index}.'
        )
    if variant == 'CPU' and cuda:
        raise RuntimeError(
            f'Installed torch {version} still reports CUDA {cuda} after CPU install.'
        )
    print(f'  [OK]  torch {version}  (CUDA {cuda or "none"})')
    return version, cuda


def ensure_torch(variant):
    """Install CPU/CUDA torch only if the current wheel does not already match."""
    try:
        version, cuda = _torch_info_subprocess()
        have_cuda = bool(cuda)
        want_cuda = variant == 'GPU'
        if have_cuda == want_cuda:
            print(f'  [OK]  torch {version} already matches {variant} '
                  f'(CUDA {cuda or "none"}) — skipping reinstall.')
            return version, cuda
        print(f'  Current torch {version} (CUDA {cuda or "none"}) does not match '
              f'{variant}; switching wheels.')
    except Exception as exc:
        print(f'  [!] Could not probe torch ({exc}); installing {variant} wheel.')
    return install_torch(variant)


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


def report_torch_build():
    """
    Report whether the build environment's PyTorch is a CUDA or CPU build.

    The packaged EXE ships with whatever torch is installed HERE, so this
    single decision determines whether end users get GPU AlphaPeptDeep
    prediction out of the box:

      * CUDA torch in build env -> GPU suite that uses any supported NVIDIA
        GPU automatically and still runs fine on CPU-only machines.
      * CPU torch in build env  -> smaller CPU suite, predictions always on CPU.

    `python build.py --both` installs each wheel in turn and produces both suites.
    """
    try:
        version, cuda = _torch_info_subprocess()
        if cuda:
            print(f'  [OK]  PyTorch {version} — CUDA {cuda} build')
            print('        -> The packaged EXE will use NVIDIA GPUs automatically')
            print('           (and falls back to CPU on machines without one).')
        else:
            print(f'  [OK]  PyTorch {version} — CPU-ONLY build')
            print('        -> This wheel produces the CPU suite.')
            print('           Use `python build.py --gpu` or `--both` for CUDA.')
        return version, cuda
    except Exception as exc:
        print(f'  [X]   PyTorch not usable in the build environment: {exc}')
        return None, None


# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------
def check_dependencies():
    _hr()
    print('Checking build dependencies ...')
    _prune_broken_dist_info()
    _ensure_setuptools_pkg_resources_compat()
    _ensure_pyinstaller_metadata_health()
    report_torch_build()

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


def assemble(variant=None):
    """
    Merge both build outputs into a delivery folder.

    variant: 'CPU', 'GPU', or None (legacy ProteoPRM_Suite/).
    """
    suite_name, suite_dir, local_suite = _suite_layout(variant)
    _hr()
    print(f'Stage 3/3 - Assembling {suite_name}/ ...')

    main_dist   = DIST / 'ProteoPRM'
    viewer_exe  = DIST / 'ProteoPRM_Results_Viewer.exe'

    if not main_dist.is_dir():
        raise FileNotFoundError(
            f'Main app dist not found: {main_dist}\n'
            'Run build_main() first.'
        )

    if suite_dir.exists():
        shutil.rmtree(suite_dir)
        print(f'  Removed old {suite_dir.name}/')

    shutil.copytree(str(main_dist), str(suite_dir))
    print(f'  Copied ProteoPRM dist -> {suite_dir.name}/')

    if viewer_exe.is_file():
        dest = suite_dir / viewer_exe.name
        shutil.copy2(str(viewer_exe), str(dest))
        mb = dest.stat().st_size / 1024 / 1024
        print(f'  Copied ProteoPRM_Results_Viewer.exe  ({mb:.1f} MB)')
    else:
        print(f'  [!] Viewer EXE not found at {viewer_exe} - skipped.')

    total_mb = sum(
        f.stat().st_size for f in suite_dir.rglob('*') if f.is_file()
    ) / 1024 / 1024
    print(f'  Suite total size : {total_mb:.1f} MB')
    print(f'  Output path      : {suite_dir}')

    print(f'  Copying final suite to project folder (OneDrive) ...')
    local_suite.parent.mkdir(parents=True, exist_ok=True)
    rc = subprocess.run(
        ['robocopy', str(suite_dir), str(local_suite),
         '/MIR', '/MT:8', '/R:3', '/W:5',
         '/NFL', '/NDL', '/NJH', '/NJS', '/NC', '/NS', '/NP'],
        capture_output=True, text=True,
    )
    if rc.returncode >= 8:
        print(f'  [!] robocopy failed (exit {rc.returncode}). Falling back to shutil ...')
        if local_suite.exists():
            shutil.rmtree(local_suite, ignore_errors=True)
        shutil.copytree(str(suite_dir), str(local_suite), dirs_exist_ok=True)
    print(f'  Local Project Path    : {local_suite}')
    return suite_name, suite_dir, local_suite


def create_zip(variant=None):
    """Create a ZIP archive of the assembled suite for GitHub Releases."""
    suite_name, suite_dir, local_suite = _suite_layout(variant)
    _hr()
    print(f'Creating distribution ZIP for {suite_name} (ZIP_DEFLATED level 6) ...')
    date_str  = datetime.now().strftime('%Y%m%d')
    zip_name  = f'{suite_name}_{date_str}.zip'
    zip_path  = DIST / zip_name

    if zip_path.exists():
        zip_path.unlink()

    n = 0
    with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(suite_dir.rglob('*')):
            if f.is_file():
                arc = Path(suite_name) / f.relative_to(suite_dir)
                zf.write(str(f), str(arc))
                n += 1

    mb = zip_path.stat().st_size / 1024 / 1024
    print(f'  [OK] {zip_path.name}  ({mb:.1f} MB,  {n:,} files)')

    local_zip = HERE / 'dist' / zip_path.name
    local_zip.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(zip_path), str(local_zip))
    print(f'  Copied ZIP to   : {local_zip}')
    return zip_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_one_variant(variant, build_viewer_exe, assemble_suite, make_zip, main_only, viewer_only):
    """Build one torch variant. Viewer is optionally skipped if already built."""
    outputs = []
    if viewer_only:
        build_viewer()
        return outputs

    if variant:
        print(f'\n  === {variant} suite ===')
        ensure_torch(variant)

    if main_only:
        build_main()
        return outputs

    build_main()
    if build_viewer_exe:
        build_viewer()

    if assemble_suite:
        suite_name, suite_dir, local_suite = assemble(variant)
        zip_path = create_zip(variant) if make_zip else None
        outputs.append((suite_name, local_suite, zip_path))
    return outputs


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
    torch_group = parser.add_mutually_exclusive_group()
    torch_group.add_argument(
        '--cpu', action='store_true',
        help='Build the CPU-only suite (ProteoPRM_Suite_CPU)')
    torch_group.add_argument(
        '--gpu', action='store_true',
        help='Build the CUDA GPU suite (ProteoPRM_Suite_GPU); also runs on CPU machines')
    torch_group.add_argument(
        '--both', action='store_true',
        help='Build CPU and GPU suites (installs each torch wheel in turn)')
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

    if args.both:
        variants = ['CPU', 'GPU']
    elif args.cpu:
        variants = ['CPU']
    elif args.gpu:
        variants = ['GPU']
    else:
        variants = [None]

    t_start = time.time()
    full_build = not args.main_only and not args.viewer_only
    all_outputs = []

    try:
        if args.viewer_only:
            build_viewer()
        else:
            for i, variant in enumerate(variants):
                build_viewer_exe = (i == 0) and not args.main_only
                all_outputs.extend(_build_one_variant(
                    variant,
                    build_viewer_exe=build_viewer_exe,
                    assemble_suite=full_build and not args.no_assemble,
                    make_zip=full_build and not args.no_assemble and not args.no_zip,
                    main_only=args.main_only,
                    viewer_only=False,
                ))

        elapsed = time.time() - t_start
        _hr('=')
        print(f'  BUILD SUCCESSFUL  ({elapsed / 60:.1f} min)')
        for suite_name, local_suite, zip_path in all_outputs:
            print(f'  Distributable : {local_suite}')
            if zip_path:
                print(f'  ZIP Archive   : {HERE / "dist" / zip_path.name}')
                print(f'  ZIP (temp)    : {zip_path}')
        _hr('=')

    except Exception as exc:
        _hr('=')
        print(f'  BUILD FAILED: {exc}')
        _hr('=')
        sys.exit(1)


if __name__ == '__main__':
    main()

