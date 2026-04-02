# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# ProteoPRM Results Viewer – PyInstaller spec  (one-folder build)
# =============================================================================
# Build with:
#   cd Executable
#   pyinstaller ProteoPRM_Results_Viewer.spec
# Or run build.py which drives both specs.
#
# The viewer is a lightweight companion app.  It does NOT bundle MS2PIP /
# AlphaPeptDeep models – those live only in the main ProteoPRM folder.
# The two EXEs are expected to reside in the same distribution directory.
# =============================================================================

from pathlib import Path
from PyInstaller.utils.hooks import collect_all

SPEC_DIR = Path(SPECPATH)


datas = [
    (str(SPEC_DIR / 'unimod.csv'), '.'),
    (str(SPEC_DIR / 'icon.ico'),   '.'),
]

hidden = [
    # ── Tkinter ─────────────────────────────────────────────────────────────
    'tkinter', 'tkinter.ttk', 'tkinter.scrolledtext', 'tkinter.filedialog',
    'tkinter.messagebox', 'tkinter.font',
    'sv_ttk',

    # ── Scientific core ─────────────────────────────────────────────────────
    'numpy', 'scipy', 'scipy.signal', 'scipy.integrate', 'scipy.ndimage',
    'scipy.stats', 'scipy.cluster', 'scipy.cluster.hierarchy',
    'scipy.special._cdflib',
    'pandas', 'openpyxl', 'pyarrow', 'pyarrow.parquet',

    # ── Visualisation ────────────────────────────────────────────────────────
    'matplotlib', 'matplotlib.pyplot', 'matplotlib.figure',
    'matplotlib.backends.backend_tkagg',
    'matplotlib.backends._backend_tk',
    'seaborn', 'PIL', 'PIL.Image', 'PIL.ImageTk',

    # ── MS data parsing ──────────────────────────────────────────────────────
    'pyteomics', 'pyteomics.mzml', 'pyteomics.proforma',
    'pyteomics.mass', 'pyteomics.auxiliary',
    'fisher_py', 'clr', 'clr_loader', 'pythonnet',

    # ── scikit-learn (for any ML model loading in viewer) ────────────────────
    'sklearn', 'sklearn.utils._typedefs', 'sklearn.utils._cython_blas',

    # ── Misc ─────────────────────────────────────────────────────────────────
    'requests', 'psutil', 'pkg_resources',
    'importlib.util', 'importlib.metadata',
    'json', 'pickle', 'csv', 'io', 'traceback', 'gc',
    'concurrent.futures', 'threading',
]

my_binaries = []
for pkg in ['fisher_py']:
    d, b, h = collect_all(pkg)
    datas.extend(d)
    my_binaries.extend(b)
    hidden.extend(h)


a = Analysis(
    [str(SPEC_DIR / 'ProteoPRM_Results_Viewer.py')],
    pathex=[str(SPEC_DIR)],
    binaries=my_binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'IPython', 'jupyter', 'notebook', 'nbformat', 'nbconvert',
        'pytest', '_pytest',
        'matplotlib.backends.backend_pdf',
        'matplotlib.backends.backend_svg',
        'matplotlib.backends.backend_ps',
        'PySide2', 'PyQt5', 'wx',
        'sqlalchemy', 'psycopg2',
        'statsmodels',
        # Prediction engines not needed in viewer
        'ms2pip', 'peptdeep', 'mokapot',
        'numba', 'llvmlite',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher if 'block_cipher' in dir() else None)

# --onefile: everything packed into a single ProteoPRM_Results_Viewer.exe
# that can be dropped directly alongside ProteoPRM.exe.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ProteoPRM_Results_Viewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        '_C.pyd',
        'ThermoFisher.CommonCore.BackgroundSubtraction.dll',
        'ThermoFisher.CommonCore.Data.dll',
        'ThermoFisher.CommonCore.MassPrecisionEstimator.dll',
        'ThermoFisher.CommonCore.RawFileReader.dll',
        'OpenMcdf.dll', 'OpenMcdf.Extensions.dll',
        'Python.Runtime.dll', 'clr.pyd'
    ],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(SPEC_DIR / 'icon.ico'),
)
