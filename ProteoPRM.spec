# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# ProteoPRM – PyInstaller spec  (one-folder build)
# =============================================================================
# Build with:
#   cd Executable
#   pyinstaller ProteoPRM.spec
# Or run build.py which drives both specs and does post-build compression.
# =============================================================================

import os
import sys
from pathlib import Path

SPEC_DIR = Path(SPECPATH)          # always set by PyInstaller to the dir of this .spec file


# ---------------------------------------------------------------------------
# Helper: collect all files from a folder tree, preserving structure.
# ---------------------------------------------------------------------------
def _collect_tree(src_dir, dest_prefix):
    """Walk *src_dir* and return a list of (src_abs, dest_rel) tuples."""
    result = []
    src = Path(src_dir)
    if not src.is_dir():
        return result
    for p in src.rglob('*'):
        if p.is_file():
            rel = p.relative_to(src.parent)   # keep the top-level folder name
            result.append((str(p), str(Path(dest_prefix) / rel.relative_to(Path(dest_prefix).name
                                                                             if Path(dest_prefix).name == src.name
                                                                             else rel.parts[0]))))
    return result


# ---------------------------------------------------------------------------
# Data files to bundle
# ---------------------------------------------------------------------------
datas = [
    # Core reference files
    (str(SPEC_DIR / 'unimod.csv'),   '.'),
    (str(SPEC_DIR / 'unimod.xml'),   '.'),
    (str(SPEC_DIR / 'icon.ico'),     '.'),
    (str(SPEC_DIR / 'GradBoost.rtmodel'), '.'),

    # MS2PIP XGBoost model files (4 × ~30 MB)
    (str(SPEC_DIR / 'ms2pip_models'), 'ms2pip_models'),

    # AlphaPeptDeep pretrained models (generic / phospho / digly sub-folders)
    (str(SPEC_DIR / 'AlphaPeptDeep pretrained_models_v3'),
     'AlphaPeptDeep pretrained_models_v3'),

    # Trained RT models (GradBoost .rtmodel, AlphaPeptDeep .rtmodel)
    (str(SPEC_DIR / 'Trained RT Models'), 'Trained RT Models'),
]

# DeepLC package data (Keras model weights, AA composition, baseline)
import importlib.util as _ilu
_deeplc_spec = _ilu.find_spec('deeplc')
if _deeplc_spec and _deeplc_spec.submodule_search_locations:
    _dlc_pkg = Path(_deeplc_spec.submodule_search_locations[0])
    if (_dlc_pkg / 'mods').is_dir():
        datas.append((str(_dlc_pkg / 'mods'), 'deeplc/mods'))
    if (_dlc_pkg / 'aa_comp_rel.csv').is_file():
        datas.append((str(_dlc_pkg / 'aa_comp_rel.csv'), 'deeplc'))
    if (_dlc_pkg / 'baseline_performance').is_dir():
        datas.append((str(_dlc_pkg / 'baseline_performance'), 'deeplc/baseline_performance'))

# fisher_py package data (ThermoFisher .NET assemblies under fisher_py/dll/net4)
_fisher_spec = _ilu.find_spec('fisher_py')
if _fisher_spec and _fisher_spec.submodule_search_locations:
    _fisher_pkg = Path(_fisher_spec.submodule_search_locations[0])
    if (_fisher_pkg / 'dll').is_dir():
        datas.append((str(_fisher_pkg / 'dll'), 'fisher_py/dll'))

# pythonnet and clr_loader (required for fisher_py to initialize .NET environment properly)
_pythonnet_spec = _ilu.find_spec('pythonnet')
if _pythonnet_spec and _pythonnet_spec.submodule_search_locations:
    _pynet_pkg = Path(_pythonnet_spec.submodule_search_locations[0])
    if (_pynet_pkg / 'runtime').is_dir():
        datas.append((str(_pynet_pkg / 'runtime'), 'pythonnet/runtime'))

_clr_loader_spec = _ilu.find_spec('clr_loader')
if _clr_loader_spec and _clr_loader_spec.submodule_search_locations:
    _clr_loader_pkg = Path(_clr_loader_spec.submodule_search_locations[0])
    if (_clr_loader_pkg / 'ffi').is_dir():
        datas.append((str(_clr_loader_pkg / 'ffi'), 'clr_loader/ffi'))

# alphabase package data (required by peptdeep/alphabase runtime)
_alphabase_spec = _ilu.find_spec('alphabase')
if _alphabase_spec and _alphabase_spec.submodule_search_locations:
    _alphabase_pkg = Path(_alphabase_spec.submodule_search_locations[0])
    _ab_const = _alphabase_pkg / 'constants' / 'const_files'
    if _ab_const.is_dir():
        datas.append((str(_ab_const), 'alphabase/constants/const_files'))

# xgboost package data (requires xgboost.dll in xgboost/lib)
_xgboost_spec = _ilu.find_spec('xgboost')
if _xgboost_spec and _xgboost_spec.submodule_search_locations:
    _xgboost_pkg = Path(_xgboost_spec.submodule_search_locations[0])
    _xgb_lib = _xgboost_pkg / 'lib'
    if _xgb_lib.is_dir():
        datas.append((str(_xgb_lib), 'xgboost/lib'))
    _xgb_version = _xgboost_pkg / 'VERSION'
    if _xgb_version.is_file():
        datas.append((str(_xgb_version), 'xgboost'))

# calibrated_apd_models: ship only the manifest.json seed so the folder
# exists next to the EXE and the code doesn't error on first launch.
_cal_manifest = SPEC_DIR / 'calibrated_apd_models' / 'manifest.json'
if _cal_manifest.is_file():
    datas.append((str(_cal_manifest), 'calibrated_apd_models'))


# ---------------------------------------------------------------------------
# Hidden imports
# ---------------------------------------------------------------------------
hidden = [
    # ── Tkinter ─────────────────────────────────────────────────────────────
    'tkinter', 'tkinter.ttk', 'tkinter.scrolledtext', 'tkinter.filedialog',
    'tkinter.messagebox', 'tkinter.font',
    'sv_ttk',

    # ── Scientific core ─────────────────────────────────────────────────────
    'numpy', 'scipy', 'scipy.signal', 'scipy.integrate', 'scipy.ndimage',
    'scipy.stats', 'scipy.cluster', 'scipy.cluster.hierarchy',
    'scipy.sparse', 'scipy.special',
    'pandas', 'openpyxl', 'pyarrow', 'pyarrow.parquet',

    # ── Visualisation ───────────────────────────────────────────────────────
    'matplotlib', 'matplotlib.pyplot', 'matplotlib.figure',
    'matplotlib.backends.backend_tkagg',
    'matplotlib.backends._backend_tk',
    'seaborn', 'PIL', 'PIL.Image', 'PIL.ImageTk',

    # ── MS data parsing ──────────────────────────────────────────────────────
    'pyteomics', 'pyteomics.mzml', 'pyteomics.proforma',
    'pyteomics.mass', 'pyteomics.auxiliary',
    'fisher_py',

    # ── MS2PIP ──────────────────────────────────────────────────────────────
    'ms2pip', 'ms2pip.core', 'ms2pip.constants', 'ms2pip._utils',
    'ms2pip._utils.xgb_models', 'ms2pip.result',
    'ms2pip.spectrum', 'ms2pip.spectrum_input', 'ms2pip.spectrum_output',
    'psm_utils', 'psm_utils.io', 'psm_utils.psm', 'psm_utils.psm_list',

    # ── AlphaPeptDeep / peptdeep ─────────────────────────────────────────────
    'peptdeep', 'peptdeep.model', 'peptdeep.model.ms2', 'peptdeep.model.rt',
    'peptdeep.model.charge', 'peptdeep.model.ccs',
    'peptdeep.pretrained_models', 'peptdeep.utils',
    'torch', 'torch.nn', 'torch.optim',
    'alphabase', 'alphabase.peptide', 'alphabase.constants',
    'alphabase.io', 'alphabase.spectral_library',

    # ── Mokapot ──────────────────────────────────────────────────────────────
    'mokapot', 'mokapot.brew', 'mokapot.parsers', 'mokapot.model',
    'mokapot.confidence',

    # ── scikit-learn ─────────────────────────────────────────────────────────
    'sklearn', 'sklearn.ensemble', 'sklearn.svm', 'sklearn.preprocessing',
    'sklearn.pipeline', 'sklearn.model_selection',
    'sklearn.utils._typedefs', 'sklearn.utils._cython_blas',
    'sklearn.neighbors._quad_tree',
    'sklearn.tree._utils',

    # ── DeepLC / TensorFlow / Keras ──────────────────────────────────────────
    'deeplc', 'deeplc.deeplc', 'deeplc.feat_extractor',
    'deeplcretrainer',
    'tensorflow', 'tensorflow.python', 'tensorflow.lite.python.lite',
    'keras', 'keras.src',
    'h5py', 'google.protobuf', 'absl',
    'ml_dtypes', 'opt_einsum', 'optree', 'flatbuffers', 'astunparse',
    'gast', 'termcolor', 'wrapt', 'grpc',

    # ── numba / llvmlite / pythonnet ─────────────────────────────────────────
    'numba', 'numba.core', 'llvmlite', 'llvmlite.binding',
    'clr', 'clr_loader', 'pythonnet',

    # ── Misc ─────────────────────────────────────────────────────────────────
    'tqdm', 'requests', 'psutil', 'pkg_resources',
    'xgboost',
    'xml.etree.ElementTree', 'lxml', 'lxml.etree',
    'importlib.util', 'importlib.metadata',
    'concurrent.futures', 'multiprocessing', 'threading',
    'json', 'pickle', 'csv', 'io', 'traceback', 'gc',
]

# NOTE ON GPU SUPPORT IN THE PACKAGED EXE:
# The EXE ships whatever PyTorch build is installed in the BUILD venv
# (PyInstaller's torch hook collects its DLLs automatically, including the
# CUDA runtime when present). Build with a CUDA torch to produce ONE suite
# that uses NVIDIA GPUs automatically and still runs on CPU-only machines:
#   pip install torch==2.10.0 --force-reinstall --index-url https://download.pytorch.org/whl/cu124
# build.py prints which torch build it is packaging at the start of a build.

from PyInstaller.utils.hooks import collect_all
my_binaries = []

for pkg in ['fisher_py', 'peptdeep', 'ms2pip', 'deeplc']:
    # Some third-party packages expose test-only submodules that import
    # optional dependencies (for example: hypothesis). Ignore those failures
    # so packaging can continue with runtime-relevant modules.
    d, b, h = collect_all(pkg, on_error='ignore')
    datas.extend(d)
    my_binaries.extend(b)
    hidden.extend(h)

# NOTE:
# Do not use collect_all('xgboost'): xgboost.testing imports pytest/hypothesis
# and can fail in PyInstaller's isolated child process. We already include
# xgboost runtime assets via hiddenimports + xgboost/lib data collection above.


a = Analysis(
    [str(SPEC_DIR / 'ProteoPRM.py')],
    pathex=[str(SPEC_DIR)],
    binaries=my_binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Jupyter / IPython bloat
        'IPython', 'jupyter', 'notebook', 'nbformat', 'nbconvert',
        # Test frameworks
        'pytest', '_pytest',
        # Unused backends
        'matplotlib.backends.backend_pdf',
        'matplotlib.backends.backend_svg',
        'matplotlib.backends.backend_ps',
        # Large unused packages
        'PySide2', 'PyQt5', 'wx',
        'psycopg2',
        'statsmodels',
    ],
    noarchive=False,
    optimize=1,           # removes assert statements; safe for production
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher if 'block_cipher' in dir() else None)

exe = EXE(
    pyz,
    a.scripts,
    [],                   # no extra binaries merged into EXE for onedir
    exclude_binaries=True,
    name='ProteoPRM',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,             # UPX compress individual binaries where possible
    upx_exclude=[
        # Don't UPX-compress PyTorch binaries – they self-verify at load time
        'torch_cpu.dll', 'torch_cuda.dll', '_C.pyd',
        'xgboost.dll',
        # Exclude .NET assemblies (UPX corrupts them)
        'ThermoFisher.CommonCore.BackgroundSubtraction.dll',
        'ThermoFisher.CommonCore.Data.dll',
        'ThermoFisher.CommonCore.MassPrecisionEstimator.dll',
        'ThermoFisher.CommonCore.RawFileReader.dll',
        'OpenMcdf.dll', 'OpenMcdf.Extensions.dll',
        'Python.Runtime.dll', 'clr.pyd',
    ],
    console=False,        # windowed GUI – no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(SPEC_DIR / 'icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[
        'torch_cpu.dll', 'torch_cuda.dll', '_C.pyd', 'xgboost.dll',
        'ThermoFisher.CommonCore.BackgroundSubtraction.dll',
        'ThermoFisher.CommonCore.Data.dll',
        'ThermoFisher.CommonCore.MassPrecisionEstimator.dll',
        'ThermoFisher.CommonCore.RawFileReader.dll',
        'OpenMcdf.dll', 'OpenMcdf.Extensions.dll',
        'Python.Runtime.dll', 'clr.pyd'
    ],
    name='ProteoPRM',     # output folder name inside dist/
)
