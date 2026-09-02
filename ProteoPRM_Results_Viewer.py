"""
ProteoPRM - Results Viewer
==========================
Standalone viewer for ProteoPRM analysis results.
Can be launched independently to explore previously saved results (CSV folder),
or auto-launched by the main ProteoPRM app after a successful run.

Usage:
    python ProteoPRM_Results_Viewer.py                          # standalone
    python ProteoPRM_Results_Viewer.py results_folder           # auto-load results
    python ProteoPRM_Results_Viewer.py results_folder mzml_dir  # auto-load results + mzML folder
"""

import tkinter as tk
import tkinter.ttk as ttk
from tkinter import scrolledtext, filedialog, messagebox
import pandas as pd
import numpy as np
import os
import sys
import io
import re
import logging
import threading
import collections
import traceback

from scipy.signal import savgol_filter
from scipy.ndimage import gaussian_filter1d
from scipy import stats
from scipy.cluster import hierarchy

try:
    import sv_ttk
    _HAS_SV_TTK = True
except ImportError:
    _HAS_SV_TTK = False

try:
    from pyteomics import mzml
    from pyteomics.mzml import PreIndexedMzML
    _HAS_PYTEOMICS = True
except ImportError:
    _HAS_PYTEOMICS = False

try:
    from fisher_py import RawFile
    _HAS_FISHER = True
except Exception:
    _HAS_FISHER = False


def _eic_rows_matched_only(df):
    """
    Return only EIC rows that represent fragments matched to observed signal.

    ProteoPRM also writes rows with intensity 0 for *unmatched* predicted
    fragments (so the full predicted spectrum can be drawn elsewhere). Those
    rows must not be overlaid on MS2 or Spectral-QC mirror plots — otherwise
    each theoretical m/z is snapped to the nearest raw peak and appears as a
    false \"matched\" stem.
    """
    if df is None or getattr(df, 'empty', True):
        return df
    if 'intensity' not in df.columns:
        return df
    _v = pd.to_numeric(df['intensity'], errors='coerce').fillna(0.0)
    return df.loc[_v > 0].copy()


# ---------------------------------------------------------------------------
# Result CSV cache
# ---------------------------------------------------------------------------
_excel_sheet_cache = {}  # (folder, sheet_name) -> DataFrame
_ms2_spectrum_cache = {}  # (mzml_path, normalized_scan_key) -> spectrum dict
_MS2_CACHE_MAX = 200     # max cached spectra before eviction
_mzml_reader_cache = {}  # mzml_path -> PreIndexedMzML persistent reader
_mirror_plot_cache = collections.OrderedDict()  # (peptide, charge, file, scan) -> (rgba_bytes, w, h, info_str)
_MIRROR_CACHE_MAX = 300


def _output_path(output_folder, sheet_name):
    """Return the CSV file path for a given result sheet inside *output_folder*."""
    safe_name = sheet_name.replace(' ', '_')
    return os.path.join(output_folder, f"{safe_name}.csv")


def _get_sheet_disk_path(output_folder, sheet_name):
    """Resolve on-disk path for a results sheet (Parquet-first for EICs)."""
    safe_name = sheet_name.replace(' ', '_')
    if sheet_name == 'EICs':
        parquet_path = os.path.join(output_folder, f"{safe_name}.parquet")
        if os.path.isfile(parquet_path):
            return parquet_path
    return _output_path(output_folder, sheet_name)


def _get_cached_excel_sheet(filepath_or_folder, sheet_name):
    key = (filepath_or_folder, sheet_name)
    if key not in _excel_sheet_cache:
        actual_path = _get_sheet_disk_path(filepath_or_folder, sheet_name)
        logging.debug(f"Reading '{sheet_name}' from {os.path.basename(actual_path)}")
        if str(actual_path).lower().endswith('.parquet'):
            _excel_sheet_cache[key] = pd.read_parquet(actual_path)
        else:
            _excel_sheet_cache[key] = pd.read_csv(actual_path)
    return _excel_sheet_cache[key]


def _invalidate_cache(filepath=None):
    global _excel_sheet_cache
    if filepath is None:
        _excel_sheet_cache.clear()
        _mirror_plot_cache.clear()
    else:
        _excel_sheet_cache = {k: v for k, v in _excel_sheet_cache.items() if k[0] != filepath}
        _mirror_plot_cache.clear()


# ---------------------------------------------------------------------------
# Canvas-based rounded button (consistent look regardless of ttk theme)
# ---------------------------------------------------------------------------
def _resolve_parent_bg(parent):
    """Get the background colour of a parent widget."""
    for getter in (
        lambda: parent.cget('bg'),
        lambda: parent.cget('background'),
        lambda: str(parent.tk.call('ttk::style', 'lookup',
                                   parent.winfo_class(), '-background')),
        lambda: str(parent.tk.call('ttk::style', 'lookup',
                                   'TFrame', '-background')),
    ):
        try:
            val = getter()
            if val and str(val).strip():
                return str(val)
        except Exception:
            continue
    return '#f0f0f0'


class RoundedCanvasButton:
    """A canvas-based button with rounded corners — immune to ttk theme overrides."""
    def __init__(self, parent, text='', bg='#2e7d32', fg='white',
                 hover_bg=None, font=('Segoe UI', 11, 'bold'),
                 corner_radius=8, height=38, command=None, cursor='hand2',
                 disabled_bg='#b0b0b0', disabled_fg='#f2f2f2'):
        self.bg = bg
        self.fg = fg
        self.hover_bg = hover_bg or bg
        self.disabled_bg = disabled_bg
        self.disabled_fg = disabled_fg
        self.corner_radius = corner_radius
        self._command = command
        self._text = text
        self._font = font
        self._pressed = False
        self._enabled = True
        self.canvas = tk.Canvas(parent, height=height,
                                highlightthickness=0, bd=0, cursor=cursor)
        self.canvas.configure(bg=_resolve_parent_bg(parent))
        self._text_id = self.canvas.create_text(0, 0, text=text, font=font,
                                                 fill=fg, anchor='center')
        self.canvas.bind('<Configure>', self._on_resize)
        self.canvas.bind('<Enter>', self._on_enter)
        self.canvas.bind('<Leave>', self._on_leave)
        self.canvas.bind('<ButtonPress-1>', self._on_press)
        self.canvas.bind('<ButtonRelease-1>', self._on_release)

    def _draw_rounded_rect(self, x1, y1, x2, y2, r, fill, tag):
        self.canvas.delete(tag)
        if x2 - x1 < 1:
            return
        r = min(r, (x2 - x1) // 2, (y2 - y1) // 2)
        if r < 1:
            self.canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline='', tags=tag)
            return
        self.canvas.create_arc(x1, y1, x1 + 2*r, y1 + 2*r, start=90, extent=90,
                               fill=fill, outline='', tags=tag)
        self.canvas.create_arc(x2 - 2*r, y1, x2, y1 + 2*r, start=0, extent=90,
                               fill=fill, outline='', tags=tag)
        self.canvas.create_arc(x1, y2 - 2*r, x1 + 2*r, y2, start=180, extent=90,
                               fill=fill, outline='', tags=tag)
        self.canvas.create_arc(x2 - 2*r, y2 - 2*r, x2, y2, start=270, extent=90,
                               fill=fill, outline='', tags=tag)
        self.canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline='', tags=tag)
        self.canvas.create_rectangle(x1, y1 + r, x1 + r, y2 - r, fill=fill, outline='', tags=tag)
        self.canvas.create_rectangle(x2 - r, y1 + r, x2, y2 - r, fill=fill, outline='', tags=tag)
        self.canvas.tag_raise(self._text_id)

    def _redraw(self, color=None):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1:
            return
        fill = (self.disabled_bg if not self._enabled else (color or self.bg))
        self._draw_rounded_rect(0, 0, w, h, self.corner_radius, fill, 'btn_bg')
        self.canvas.itemconfigure(self._text_id, fill=(self.fg if self._enabled else self.disabled_fg))
        self.canvas.coords(self._text_id, w // 2, h // 2)

    def _on_resize(self, event=None):
        self._redraw()

    def _on_enter(self, event=None):
        if self._enabled:
            self._redraw(self.hover_bg)

    def _on_leave(self, event=None):
        self._pressed = False
        self._redraw(self.bg if self._enabled else self.disabled_bg)

    def _on_press(self, event=None):
        if self._enabled:
            self._pressed = True
            self._redraw(self.hover_bg)

    def _on_release(self, event=None):
        if self._enabled and self._pressed and self._command:
            self._pressed = False
            self._redraw(self.hover_bg)
            self._command()

    def grid(self, **kw):
        self.canvas.grid(**kw)

    def pack(self, **kw):
        self.canvas.pack(**kw)

    def pack_forget(self):
        self.canvas.pack_forget()

    def grid_remove(self):
        self.canvas.grid_remove()

    def configure(self, **kw):
        if 'command' in kw:
            self._command = kw.pop('command')
        if 'text' in kw:
            self._text = kw.pop('text')
            self.canvas.itemconfigure(self._text_id, text=self._text)


def _scan_key(scan_value):
    """Return a normalized scan key (digits only) for robust matching."""
    text = str(scan_value).strip()
    match = re.search(r'(\d+)(?:\.0+)?$', text)
    if match:
        return match.group(1)
    match = re.search(r'scan=(\d+)', text, re.IGNORECASE)
    if match:
        return match.group(1)
    try:
        as_num = pd.to_numeric([text], errors='coerce')[0]
        if pd.notna(as_num):
            return str(int(round(float(as_num))))
    except Exception:
        pass
    return text


def _find_scan_rows(peptide_eic, requested_scan):
    """Find rows for requested scan; fallback to numerically nearest scan in peptide_eic."""
    if "scan_number" not in peptide_eic.columns or peptide_eic.empty:
        return pd.DataFrame(), None

    req_key = _scan_key(requested_scan)
    scan_keys = peptide_eic["scan_number"].apply(_scan_key)

    # Exact key match first
    exact = peptide_eic[scan_keys == req_key]
    if not exact.empty:
        return exact, req_key

    # Numeric nearest-scan fallback
    scan_num = pd.to_numeric(peptide_eic["scan_number"], errors='coerce')
    try:
        req_num = float(req_key)
    except Exception:
        req_num = np.nan

    if pd.notna(req_num) and scan_num.notna().any():
        diffs = (scan_num - req_num).abs()
        nearest_idx = diffs.idxmin()
        nearest_scan_val = peptide_eic.loc[nearest_idx, "scan_number"]
        nearest_key = _scan_key(nearest_scan_val)
        nearest = peptide_eic[scan_keys == nearest_key]
        if not nearest.empty:
            return nearest, nearest_key

    return pd.DataFrame(), req_key


_fisher_reader_cache = {}

def _get_mzml_reader(mzml_path):
    """Return a persistent PreIndexedMzML reader for *mzml_path* (cached).

    The reader's index is parsed only once; subsequent calls reuse the
    same object, making random-access spectrum lookups near-instant.
    """
    if mzml_path in _mzml_reader_cache:
        return _mzml_reader_cache[mzml_path]
    if _HAS_PYTEOMICS and os.path.splitext(mzml_path)[1].lower() == '.mzml':
        try:
            reader = PreIndexedMzML(mzml_path)
            # Pre-compute a lightning-fast hash map of cleaned scan keys to exact string IDs (Takes ~10ms once per file)
            reader._fast_id_map = {}
            if hasattr(reader, 'index') and 'spectrum' in reader.index:
                for spec_id in reader.index['spectrum'].keys():
                    reader._fast_id_map[_scan_key(str(spec_id))] = spec_id
            _mzml_reader_cache[mzml_path] = reader
            return reader
        except Exception:
            pass
    return None


def _get_spectrum_for_scan(mzml_path, requested_scan):
    """Fast spectrum lookup with persistent reader cache and graceful fallback."""
    req_key = _scan_key(requested_scan)
    cache_key = (mzml_path, req_key)
    if cache_key in _ms2_spectrum_cache:
        return _ms2_spectrum_cache[cache_key]

    spectrum = None
    ext_lower = os.path.splitext(mzml_path)[1].lower()

    # Fast random access via persistent PreIndexedMzML reader
    reader = _get_mzml_reader(mzml_path)
    if reader is not None:
        # Instant direct O(1) hash map lookup from the pre-computed dictionary (~0.01ms vs iterating 50k keys)
        try:
            target_id = getattr(reader, '_fast_id_map', {}).get(req_key)
            if target_id is not None:
                spectrum = reader.get_by_id(target_id)
        except Exception:
            pass

    # Direct .raw single-scan access via fisher_py (O(1), no iteration)
    if spectrum is None and ext_lower == '.raw' and _HAS_FISHER:
        try:
            scan_num = int(req_key)
            if mzml_path not in _fisher_reader_cache:
                _fisher_reader_cache[mzml_path] = RawFile(mzml_path)
            raw_file = _fisher_reader_cache[mzml_path]
            masses, intensities, _charges, _filt = raw_file.get_scan_from_scan_number(scan_num)
            mz_arr = np.asarray(masses, dtype=np.float64)
            int_arr = np.asarray(intensities, dtype=np.float64)
            if mz_arr.size > 0:
                spectrum = {'m/z array': mz_arr, 'intensity array': int_arr}
        except Exception:
            pass

    # Fallback sequential search (works for mzML and .raw reader)
    if spectrum is None:
        try:
            with read_spectra(mzml_path) as reader:
                for spec in reader:
                    spec_id = str(spec.get("id", ""))
                    spec_key = _scan_key(spec_id)
                    if spec_key == req_key:
                        spectrum = spec
                        break
        except Exception:
            pass

    if spectrum is not None:
        # Evict oldest entry if cache is full
        if len(_ms2_spectrum_cache) >= _MS2_CACHE_MAX:
            try:
                _ms2_spectrum_cache.pop(next(iter(_ms2_spectrum_cache)))
            except StopIteration:
                pass
        _ms2_spectrum_cache[cache_key] = spectrum
    return spectrum


# ---------------------------------------------------------------------------
# Spectrum reading (mzML / .raw via pyteomics / fisher_py)
# ---------------------------------------------------------------------------
def _parse_scan_filter(filter_string):
    """Parse a Thermo scan filter string to extract MS level and precursor m/z."""
    info = {'ms_level': 1, 'precursor_mz': None, 'scan_window': None}
    ms_match = re.search(r'\bms(\d*)\b', filter_string, re.IGNORECASE)
    if ms_match:
        level = ms_match.group(1)
        info['ms_level'] = int(level) if level else 1
    prec_match = re.search(r'(\d+\.?\d*)\s*@', filter_string)
    if prec_match:
        info['precursor_mz'] = float(prec_match.group(1))
    window_match = re.search(r'\[(\d+\.?\d*)\s*-\s*(\d+\.?\d*)\]', filter_string)
    if window_match:
        info['scan_window'] = (float(window_match.group(1)), float(window_match.group(2)))
    return info


def _read_raw_with_fisher(raw_path):
    """Yield pyteomics-compatible spectrum dicts from a Thermo .raw file."""
    raw_file = RawFile(raw_path)
    for scan_number in range(raw_file.first_scan, raw_file.last_scan + 1):
        try:
            masses, intensities, charges, _filt = raw_file.get_scan_from_scan_number(scan_number)
            rt = raw_file.get_retention_time_from_scan_number(scan_number)
            filter_str = raw_file.get_scan_event_str_from_scan_number(scan_number)
            filter_info = _parse_scan_filter(filter_str)
            mz_array = np.asarray(masses, dtype=np.float64)
            int_array = np.asarray(intensities, dtype=np.float64)
            if mz_array.size == 0:
                continue
            spectrum = {
                'id': f'controllerType=0 controllerNumber=1 scan={scan_number}',
                'ms level': filter_info['ms_level'],
                'm/z array': mz_array,
                'intensity array': int_array,
                'scanList': {'scan': [{'scan start time': rt}]},
            }
            if filter_info.get('scan_window'):
                sw_lo, sw_hi = filter_info['scan_window']
                spectrum['scanList']['scan'][0]['scanWindowList'] = {
                    'scanWindow': [{'cvParam': [
                        {'name': 'scan window lower limit', 'value': str(sw_lo)},
                        {'name': 'scan window upper limit', 'value': str(sw_hi)},
                    ]}]
                }
            if filter_info['ms_level'] >= 2 and filter_info['precursor_mz'] is not None:
                chg_array = np.asarray(charges, dtype=np.float64)
                nonzero = chg_array[chg_array > 0]
                charge_state = 0
                if nonzero.size > 0:
                    unique, counts = np.unique(nonzero.astype(int), return_counts=True)
                    charge_state = int(unique[np.argmax(counts)])
                selected_ion = {'selected ion m/z': filter_info['precursor_mz']}
                if charge_state > 0:
                    selected_ion['charge state'] = charge_state
                spectrum['precursorList'] = {
                    'precursor': [{'selectedIonList': {'selectedIon': [selected_ion]}}]
                }
            yield spectrum
        except Exception:
            continue


def read_spectra(file_path):
    """Read spectra from mzML or .raw file. Returns a context manager."""
    from contextlib import contextmanager
    ext = os.path.splitext(file_path)[1].lower()

    # Thermo .raw via fisher_py
    if ext == '.raw' and _HAS_FISHER:
        @contextmanager
        def _fisher_ctx():
            yield _read_raw_with_fisher(file_path)
        return _fisher_ctx()

    # mzML via pyteomics
    if _HAS_PYTEOMICS:
        return mzml.read(file_path)

    @contextmanager
    def _empty():
        yield []
    return _empty()


# ============================================================================
# Results Viewer Application
# ============================================================================
class ResultsViewer:
    """Standalone results viewer window."""

    def __init__(self, root, results_file=None, mzml_folder=None):
        self.root = root
        self.root.title("ProteoPRM - Results Viewer")
        self.root.geometry("1300x850")
        self.root.resizable(True, True)

        if _HAS_SV_TTK:
            sv_ttk.set_theme("light")
            try:
                _style = ttk.Style(root)
                _style.layout("TButton", _style.layout("Accent.TButton"))
                _style.configure("TButton", **_style.configure("Accent.TButton"))
                _style.map("TButton", **_style.map("Accent.TButton"))
            except Exception:
                pass

        # Custom button styles
        _s = ttk.Style(root)
        try:
            _s.configure("Green.TButton", background="#2e7d32", foreground="white",
                          font=("Segoe UI", 9, "bold"))
            _s.map("Green.TButton",
                   background=[("active", "#1b5e20"), ("pressed", "#1b5e20")],
                   foreground=[("active", "white")])
            _s.configure("Orange.TButton", background="#e65100", foreground="white",
                          font=("Segoe UI", 9))
            _s.map("Orange.TButton",
                   background=[("active", "#bf360c"), ("pressed", "#bf360c")],
                   foreground=[("active", "white")])
        except Exception:
            pass

        self.results_file = None
        self.mzml_folder = None
        self._eic_displayed = False
        self._last_rt_width_val = ""
        self._qc_tab_populated = False  # Track if Spectral QC tab has been loaded

        self._build_ui()

        # Auto-load if paths provided
        if results_file and os.path.isdir(results_file):
            self.results_entry.configure(state="normal")
            self.results_entry.delete(0, tk.END)
            self.results_entry.insert(0, results_file)
            self.results_entry.configure(state="readonly")
            if mzml_folder and os.path.isdir(mzml_folder):
                self.mzml_entry.configure(state="normal")
                self.mzml_entry.delete(0, tk.END)
                self.mzml_entry.insert(0, mzml_folder)
                self.mzml_entry.configure(state="readonly")
                self.mzml_folder = mzml_folder
            # Avoid modal dialogs while startup splash is visible.
            self._load_results(results_file, show_dialog=False)

    # --------------------------------------------------------------------- #
    # UI Construction
    # --------------------------------------------------------------------- #
    def _build_ui(self):
        # ---- Top bar: file selection ----
        top_frame = ttk.Frame(self.root)
        top_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(top_frame, text="Results:").pack(side="left", padx=(0, 5))
        self.results_entry = ttk.Entry(top_frame, width=50, state="readonly")
        self.results_entry.pack(side="left", padx=5, fill="x", expand=True)
        ttk.Button(top_frame, text="Browse Folder", command=self._browse_results_folder).pack(side="left", padx=2)

        ttk.Label(top_frame, text="mzML Folder:").pack(side="left", padx=(15, 5))
        self.mzml_entry = ttk.Entry(top_frame, width=35, state="readonly")
        self.mzml_entry.pack(side="left", padx=5, fill="x", expand=True)
        ttk.Button(top_frame, text="Browse", command=self._browse_mzml).pack(side="left", padx=5)

        _load_rcb = RoundedCanvasButton(
            top_frame, text="Load",
            bg='#2e7d32', fg='white', hover_bg='#1b5e20',
            font=('Segoe UI', 10, 'bold'), corner_radius=8, height=34,
            command=self._load_from_ui,
        )
        _load_rcb.pack(side="left", padx=10)

        # ---- Main notebook ----
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=5)

        # EIC Visualization tab
        self.eic_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.eic_frame, text="EIC Visualization")
        self._build_eic_tab()

        # Visualization & Analysis tab
        self.viz_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.viz_frame, text="Visualization & Analysis")
        self._build_viz_tab()

        # Spectral Prediction QC tab
        self.spectral_qc_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.spectral_qc_frame, text="Spectral Prediction QC")
        self._build_spectral_qc_tab()

    def _build_eic_tab(self):
        # Main horizontal layout: left sidebar | center plot | right sidebar
        self.eic_frame.columnconfigure(1, weight=1)
        self.eic_frame.rowconfigure(0, weight=1)

        # === LEFT SIDEBAR ===
        left_sidebar = ttk.LabelFrame(self.eic_frame, text=" Controls ", padding=(10, 5))
        left_sidebar.grid(row=0, column=0, sticky="ns", padx=(5, 2), pady=5)

        ttk.Label(left_sidebar, text="Peptide:").pack(anchor="w", pady=(5, 2))
        self.eic_peptide_var = tk.StringVar()
        self.eic_peptide_combo = ttk.Combobox(left_sidebar, textvariable=self.eic_peptide_var,
                                              width=28, state="readonly")
        self.eic_peptide_combo.pack(fill="x", pady=(0, 8))

        ttk.Label(left_sidebar, text="File:").pack(anchor="w", pady=(5, 2))
        self.eic_file_var = tk.StringVar()
        self.eic_file_combo = ttk.Combobox(left_sidebar, textvariable=self.eic_file_var,
                                           width=28, state="readonly")
        self.eic_file_combo.pack(fill="x", pady=(0, 8))

        ttk.Separator(left_sidebar, orient="horizontal").pack(fill="x", pady=8)

        ttk.Label(left_sidebar, text="Smoothing:").pack(anchor="w", pady=(5, 2))
        self.smooth_var = tk.StringVar(value="None")
        ttk.Combobox(left_sidebar, textvariable=self.smooth_var,
                     values=["None", "Gaussian", "Savitzky-Golay"],
                     state="readonly", width=16).pack(fill="x", pady=(0, 5))

        ttk.Label(left_sidebar, text="Window:").pack(anchor="w", pady=(5, 2))
        self.smooth_window_var = tk.IntVar(value=5)
        ttk.Spinbox(left_sidebar, from_=3, to=101, increment=2,
                    textvariable=self.smooth_window_var, width=8).pack(anchor="w", pady=(0, 8))

        ttk.Separator(left_sidebar, orient="horizontal").pack(fill="x", pady=8)

        ttk.Button(left_sidebar, text="Display EIC",
                   style="Orange.TButton",
                   command=self._plot_eic).pack(fill="x", pady=3)
        ttk.Button(left_sidebar, text="Display MS2 Spectra",
                   style="Orange.TButton",
                   command=self._plot_ms2).pack(fill="x", pady=3)

        # === CENTER PLOT AREA ===
        self.eic_canvas_frame = ttk.Frame(self.eic_frame)
        self.eic_canvas_frame.grid(row=0, column=1, sticky="nsew", padx=2, pady=5)

        # === RIGHT SIDEBAR ===
        right_sidebar = ttk.LabelFrame(self.eic_frame, text=" RT & Integration ", padding=(10, 5))
        right_sidebar.grid(row=0, column=2, sticky="ns", padx=(2, 5), pady=5)

        ttk.Label(right_sidebar, text="RT Lines:").pack(anchor="w", pady=(5, 2))
        self.show_original_rt_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right_sidebar, text="Original RT",
                        variable=self.show_original_rt_var,
                        command=self._on_rt_toggle).pack(anchor="w", padx=10, pady=1)
        self.show_corrected_rt_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right_sidebar, text="Corrected RT",
                        variable=self.show_corrected_rt_var,
                        command=self._on_rt_toggle).pack(anchor="w", padx=10, pady=1)

        ttk.Separator(right_sidebar, orient="horizontal").pack(fill="x", pady=8)

        ttk.Label(right_sidebar, text="RT Width (min):").pack(anchor="w", pady=(5, 2))
        self.reintegrate_rt_width_var = tk.StringVar(value="")
        self.reintegrate_rt_width_entry = ttk.Entry(right_sidebar,
                                                     textvariable=self.reintegrate_rt_width_var, width=8)
        self.reintegrate_rt_width_entry.pack(anchor="w", pady=(0, 5))
        self.reintegrate_rt_width_entry.bind("<Return>", lambda e: self._on_rt_width_changed())
        self.reintegrate_rt_width_entry.bind("<FocusOut>", lambda e: self._on_rt_width_changed())

        ttk.Label(right_sidebar, text="Use RT:").pack(anchor="w", pady=(5, 2))
        self.reintegrate_rt_source_var = tk.StringVar(value="Original")
        ttk.Combobox(right_sidebar, textvariable=self.reintegrate_rt_source_var,
                     values=["Original", "Corrected"], state="readonly", width=10).pack(anchor="w", pady=(0, 8))

        ttk.Separator(right_sidebar, orient="horizontal").pack(fill="x", pady=8)

        ttk.Button(right_sidebar, text="Re-Integrate All",
                   style="Green.TButton",
                   command=self._reintegrate_all).pack(fill="x", pady=3)

    def _build_viz_tab(self):
        self.viz_notebook = ttk.Notebook(self.viz_frame)
        self.viz_notebook.pack(fill="both", expand=True, padx=5, pady=5)

        # QC tab
        self.qc_frame = ttk.Frame(self.viz_notebook)
        self.viz_notebook.add(self.qc_frame, text="Quality Control")
        qc_ctrl = ttk.Frame(self.qc_frame)
        qc_ctrl.pack(fill="x", padx=5, pady=5)
        ttk.Label(qc_ctrl, text="QC Metric:").pack(side="left", padx=5)
        self.qc_metric_var = tk.StringVar(value="Mass Accuracy")
        ttk.Combobox(qc_ctrl, textvariable=self.qc_metric_var,
                     values=["Mass Accuracy", "Retention Time Deviation",
                             "PSM Score", "RT Drift", "Mass Drift"],
                     width=22, state="readonly").pack(side="left", padx=5)
        ttk.Button(qc_ctrl, text="Generate QC Plot",
                   command=self._generate_qc_plot).pack(side="left", padx=5)
        self.qc_canvas_frame = ttk.Frame(self.qc_frame)
        self.qc_canvas_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # Multivariate tab
        self.mv_frame = ttk.Frame(self.viz_notebook)
        self.viz_notebook.add(self.mv_frame, text="Multivariate Analysis")
        mv_ctrl = ttk.Frame(self.mv_frame)
        mv_ctrl.pack(fill="x", padx=5, pady=5)
        ttk.Label(mv_ctrl, text="Analysis Type:").pack(side="left", padx=5)
        self.mv_type_var = tk.StringVar(value="PCA")
        ttk.Combobox(mv_ctrl, textvariable=self.mv_type_var,
                     values=["PCA", "Hierarchical Clustering", "Heatmap"],
                     width=22, state="readonly").pack(side="left", padx=5)
        ttk.Label(mv_ctrl, text="Normalize:").pack(side="left", padx=5)
        self.mv_normalize_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(mv_ctrl, variable=self.mv_normalize_var).pack(side="left")
        ttk.Button(mv_ctrl, text="Analyze",
                   command=self._run_multivariate).pack(side="left", padx=5)
        self.mv_canvas_frame = ttk.Frame(self.mv_frame)
        self.mv_canvas_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # ML tab
        self.ml_frame = ttk.Frame(self.viz_notebook)
        self.viz_notebook.add(self.ml_frame, text="Machine Learning")
        ml_ctrl = ttk.Frame(self.ml_frame)
        ml_ctrl.pack(fill="x", padx=5, pady=5)
        ttk.Label(ml_ctrl, text="Model Type:").pack(side="left", padx=5)
        self.ml_model_var = tk.StringVar(value="Random Forest")
        ttk.Combobox(ml_ctrl, textvariable=self.ml_model_var,
                     values=["Random Forest", "K-Means Clustering"],
                     width=22, state="readonly").pack(side="left", padx=5)
        ttk.Label(ml_ctrl, text="Test Size (%):").pack(side="left", padx=5)
        self.ml_test_size_var = tk.IntVar(value=30)
        ttk.Spinbox(ml_ctrl, from_=10, to=50, textvariable=self.ml_test_size_var,
                    width=5).pack(side="left", padx=5)
        ttk.Button(ml_ctrl, text="Train Model",
                   command=self._train_ml_model).pack(side="left", padx=5)
        self.ml_results_frame = ttk.Frame(self.ml_frame)
        self.ml_results_frame.pack(fill="both", expand=True, padx=5, pady=5)

    def _build_spectral_qc_tab(self):
        """Build the Spectral Prediction QC tab with PSM table, SA histogram, and mirror plot."""
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

        self._qc_data = {'df': None, 'eic_df': None, 'sa_col': 'spectral_angle', 'filepath': None}

        self.spectral_qc_frame.columnconfigure(0, weight=1)
        self.spectral_qc_frame.rowconfigure(1, weight=1)

        # Status bar
        self._qc_status_var = tk.StringVar(
            value="Load a results file to view Spectral Prediction QC.")
        ttk.Label(self.spectral_qc_frame, textvariable=self._qc_status_var,
                  foreground='gray').grid(row=0, column=0, sticky='w', padx=8, pady=(4, 0))

        # Sub-notebook for QC sub-tabs (2 tabs: PSM SA + Histogram)
        self._qc_nb = ttk.Notebook(self.spectral_qc_frame)
        self._qc_nb.grid(row=1, column=0, sticky='nsew', padx=4, pady=4)

        # ── Tab 1: PSM table (top) + Mirror plot (bottom) ──
        tab_table = ttk.Frame(self._qc_nb)
        self._qc_nb.add(tab_table, text="PSM Spectral Angles")
        tab_table.columnconfigure(0, weight=1)
        tab_table.rowconfigure(0, weight=1)

        pw = ttk.PanedWindow(tab_table, orient='vertical')
        pw.pack(fill='both', expand=True)

        # -- Upper pane: treeview --
        tree_outer = ttk.Frame(pw)
        pw.add(tree_outer, weight=1)
        tree_outer.columnconfigure(0, weight=1)
        tree_outer.rowconfigure(0, weight=1)

        tree_cols = ('peptide', 'modification', 'charge', 'file', 'scan', 'spectral_angle',
                     'matched_fragments', 'mass_accuracy')
        self._qc_tree = ttk.Treeview(tree_outer, columns=tree_cols,
                                     show='headings', selectmode='browse')
        _col_labels = {
            'peptide': 'Peptide', 'modification': 'Modification', 'charge': 'Charge', 'file': 'File',
            'scan': 'Scan', 'spectral_angle': 'SA Score',
            'matched_fragments': 'Matched Ions', 'mass_accuracy': 'Mass Acc (ppm)',
        }
        for c in tree_cols:
            self._qc_tree.heading(
                c, text=_col_labels.get(c, c),
                command=lambda _col=c: self._sort_qc_tree(_col, False))
            w = 90 if c not in ('peptide', 'modification', 'file') else 200
            self._qc_tree.column(c, width=w, minwidth=60)
        tree_scroll = ttk.Scrollbar(tree_outer, orient='vertical',
                                    command=self._qc_tree.yview)
        self._qc_tree.configure(yscrollcommand=tree_scroll.set)
        self._qc_tree.grid(row=0, column=0, sticky='nsew')
        tree_scroll.grid(row=0, column=1, sticky='ns')
        self._mirror_debounce_id = None
        self._qc_tree.bind('<<TreeviewSelect>>', self._on_qc_tree_select_debounced)

        # -- Lower pane: mirror plot --
        mirror_outer = ttk.Frame(pw)
        pw.add(mirror_outer, weight=2)

        self._qc_mirror_info_var = tk.StringVar(
            value="Select a PSM above to view its mirror plot.")
        ttk.Label(mirror_outer, textvariable=self._qc_mirror_info_var,
                  font=('Segoe UI', 9)).pack(anchor='w', padx=8, pady=2)

        self._qc_fig_mirror = Figure(figsize=(8, 4), dpi=100)
        self._qc_ax_mirror = self._qc_fig_mirror.add_subplot(111)
        self._qc_canvas_mirror = FigureCanvasTkAgg(self._qc_fig_mirror,
                                                    master=mirror_outer)
        self._qc_canvas_mirror.get_tk_widget().pack(fill='both', expand=True)
        _mirror_tb = ttk.Frame(mirror_outer)
        _mirror_tb.pack(fill='x')
        NavigationToolbar2Tk(self._qc_canvas_mirror, _mirror_tb).update()

        # ── Tab 2: SA histogram ──
        tab_hist = ttk.Frame(self._qc_nb)
        self._qc_nb.add(tab_hist, text="SA Distribution")
        
        # Bind tab selection to lazy-load Spectral QC when user clicks that tab
        self._qc_nb.bind('<<NotebookTabChanged>>', self._on_qc_tab_selected)
        self.notebook.bind('<<NotebookTabChanged>>', self._on_main_tab_changed, add="+")
        self._qc_fig_hist = Figure(figsize=(7, 4), dpi=100)
        self._qc_ax_hist = self._qc_fig_hist.add_subplot(111)
        self._qc_canvas_hist = FigureCanvasTkAgg(self._qc_fig_hist, master=tab_hist)
        self._qc_canvas_hist.get_tk_widget().pack(fill='both', expand=True)
        _hist_tb = ttk.Frame(tab_hist)
        _hist_tb.pack(fill='x')
        NavigationToolbar2Tk(self._qc_canvas_hist, _hist_tb).update()

        # ── Export button (orange, rounded canvas) ──
        export_frame = ttk.Frame(self.spectral_qc_frame)
        export_frame.grid(row=2, column=0, sticky='ew', padx=4, pady=(0, 4))
        _export_rcb = RoundedCanvasButton(
            export_frame, text="Export SA Scores to CSV",
            bg='#ef6c00', fg='white', hover_bg='#f57c00',
            font=('Segoe UI', 10, 'bold'), corner_radius=8, height=34,
            command=self._export_sa_csv,
        )
        _export_rcb.pack(side='left', padx=6, pady=4)

    # --------------------------------------------------------------------- #
    # File browsing / loading
    # --------------------------------------------------------------------- #
    def _browse_results_folder(self):
        path = filedialog.askdirectory(title="Select Results Folder")
        if path:
            self.results_entry.configure(state="normal")
            self.results_entry.delete(0, tk.END)
            self.results_entry.insert(0, path)
            self.results_entry.configure(state="readonly")

    def _browse_mzml(self):
        path = filedialog.askdirectory(title="Select mzML / Raw Folder")
        if path:
            self.mzml_entry.configure(state="normal")
            self.mzml_entry.delete(0, tk.END)
            self.mzml_entry.insert(0, path)
            self.mzml_entry.configure(state="readonly")
            self.mzml_folder = path

    def _load_from_ui(self):
        path = self.results_entry.get()
        if not path or not os.path.isdir(path):
            messagebox.showerror("Error", "Please select a valid results folder.")
            return
        mzml_path = self.mzml_entry.get()
        if mzml_path and os.path.isdir(mzml_path):
            self.mzml_folder = mzml_path
        self._load_results(path)

    def _load_results(self, path, show_dialog=True):
        """Load results folder and populate dropdowns."""
        _invalidate_cache(self.results_file)  # clear old cache
        self.results_file = path
        try:
            psm_df = _get_cached_excel_sheet(path, "PSM")
            combos = []
            for _, row in psm_df.iterrows():
                pep = row["peptide"]
                if str(pep).startswith("DECOY_"):
                    continue
                mod = row.get("modification", "")
                if mod and pd.notna(mod) and str(mod).strip():
                    combo = f"{pep} ({mod})"
                else:
                    combo = str(pep)
                if combo not in combos:
                    combos.append(combo)
            combos = sorted(combos)
            files = sorted(psm_df["file"].unique())

            self.eic_peptide_combo["values"] = combos
            self.eic_file_combo["values"] = files
            if combos:
                self.eic_peptide_var.set(combos[0])
            if files:
                self.eic_file_var.set(files[0])

            self.root.title(f"ProteoPRM - Results Viewer  [{os.path.basename(path)}]")
            # Defer Spectral QC tab population (will load lazily when user clicks that tab)
            self._qc_tab_populated = False
            self._qc_data['filepath'] = path  # Store path for lazy loading
            loaded_msg = f"Loaded: {len(combos)} peptides, {len(files)} files."
            self._qc_status_var.set(loaded_msg)
            if show_dialog:
                messagebox.showinfo("Loaded", f"Results loaded successfully.\n"
                                    f"{len(combos)} peptides, {len(files)} files.")
        except Exception as e:
            self._qc_status_var.set(f"Load error: {e}")
            if show_dialog:
                messagebox.showerror("Error", f"Failed to load results: {e}")
            else:
                logging.exception("Auto-load failed during startup")

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #
    def _clear_canvas(self, frame):
        for w in frame.winfo_children():
            w.destroy()

    def _check_loaded(self):
        if not self.results_file or not os.path.isdir(self.results_file):
            messagebox.showwarning("No Data", "Please load a results folder first.")
            return False
        return True

    def _embed_figure(self, fig, canvas_frame):
        """Embed a matplotlib Figure in a tkinter frame with navigation toolbar."""
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        canvas = FigureCanvasTkAgg(fig, master=canvas_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        tb_frame = ttk.Frame(canvas_frame)
        tb_frame.pack(fill=tk.X)
        NavigationToolbar2Tk(canvas, tb_frame).update()

    # --------------------------------------------------------------------- #
    # Spectral Prediction QC
    # --------------------------------------------------------------------- #
    def _on_main_tab_changed(self, event=None):
        if self.notebook.select():
            if self.notebook.tab(self.notebook.select(), "text") == "Spectral Prediction QC":
                self._on_qc_tab_selected()

    def _on_qc_tab_selected(self, event=None):
        """Lazy-load Spectral QC data when user clicks on that tab for the first time."""
        if self._qc_tab_populated or not self._qc_data.get('filepath'):
            return
        self._qc_tab_populated = True
        filepath = self._qc_data['filepath']
        # Schedule population on next mainloop iteration to avoid blocking UI
        self.root.after(100, lambda: self._populate_spectral_qc(filepath))

    def _populate_spectral_qc(self, filepath):
        """Load spectral-angle data from the results file/folder and populate the QC tab."""
        try:
            df = _get_cached_excel_sheet(filepath, 'PSM')

            # Identify SA column
            sa_col = None
            for candidate in ['spectral_angle', 'Spectral Angle', 'SA',
                              'spectral_contrast_angle', 'sa_score']:
                if candidate in df.columns:
                    sa_col = candidate
                    break
            if sa_col is None:
                self._qc_status_var.set(
                    "No spectral-angle column found. Run analysis with "
                    "spectral prediction enabled.")
                return

            self._qc_data['df'] = df
            self._qc_data['sa_col'] = sa_col

            # Pre-load EICs sheet for mirror plot
            eic_df = pd.DataFrame()
            try:
                eic_df = _get_cached_excel_sheet(filepath, 'EICs')
                if not eic_df.empty:
                    # Cache the grouped EIC dataframe to eliminate O(N) searches (which take ~50-200ms per row click)
                    self._qc_data['eic_groupby'] = dict(tuple(eic_df.groupby(['peptide', 'file'])))
            except Exception:
                pass
            self._qc_data['eic_df'] = eic_df

            # Clear and populate tree
            for item in self._qc_tree.get_children():
                self._qc_tree.delete(item)

            pep_col = next((c for c in df.columns
                            if c.lower() in ('peptide', 'sequence')), None)
            mod_col = next((c for c in df.columns
                            if c.lower() in ('modification', 'modifications', 'mods')), None)
            chg_col = next((c for c in df.columns
                            if c.lower() in ('charge', 'precursor_charge')), None)
            file_col = next((c for c in df.columns
                             if c.lower() in ('file', 'raw_file', 'filename')), None)
            scan_col = next((c for c in df.columns
                             if c.lower() in ('scan', 'scan_number', 'scannumber')), None)
            mf_col = next((c for c in df.columns
                           if c.lower() in ('matched_fragments', 'fragment_count')), None)
            ma_col = next((c for c in df.columns
                           if c.lower() in ('mass_accuracy',)), None)

            n_with_sa = 0
            for _, row in df.iterrows():
                pep_val = str(row.get(pep_col, '')) if pep_col else ''
                if pep_val.startswith('DECOY_'):
                    continue
                sa_val = row.get(sa_col, 0)
                if pd.isna(sa_val) or sa_val == 0:
                    continue
                n_with_sa += 1
                self._qc_tree.insert('', 'end', values=(
                    pep_val,
                    '' if (not mod_col or pd.isna(row.get(mod_col))) else str(row.get(mod_col, '')).strip(),
                    str(row.get(chg_col, '')) if chg_col else '',
                    os.path.basename(str(row.get(file_col, ''))) if file_col else '',
                    str(row.get(scan_col, '')) if scan_col else '',
                    f"{float(sa_val):.4f}",
                    str(row.get(mf_col, '')) if mf_col else '',
                    f"{float(row.get(ma_col, 0)):.2f}" if ma_col else '',
                ))

            # Draw SA histogram
            sa_vals = df[sa_col].dropna()
            sa_vals = sa_vals[sa_vals > 0]
            self._qc_ax_hist.clear()
            if len(sa_vals) > 0:
                self._qc_ax_hist.hist(sa_vals, bins=50, color='#1976d2',
                                      edgecolor='white', alpha=0.85)
                median_sa = float(sa_vals.median())
                self._qc_ax_hist.axvline(median_sa, color='#d32f2f', linestyle='--',
                                         linewidth=1.5,
                                         label=f'Median SA = {median_sa:.3f}')
                self._qc_ax_hist.set_xlabel('Spectral Angle (SA)')
                self._qc_ax_hist.set_ylabel('Count')
                self._qc_ax_hist.set_title(
                    f'SA Distribution  (n={len(sa_vals):,},  median={median_sa:.3f})')
                self._qc_ax_hist.legend(loc='upper left')
            else:
                self._qc_ax_hist.text(0.5, 0.5, 'No SA scores > 0', ha='center',
                                      va='center',
                                      transform=self._qc_ax_hist.transAxes,
                                      fontsize=14, color='gray')
            self._qc_fig_hist.tight_layout()
            self._qc_canvas_hist.draw()

            self._qc_status_var.set(
                f"Loaded {len(df):,} PSMs — {n_with_sa:,} with SA > 0.  "
                f"Select a row to view in the Mirror Plot tab.")

        except Exception as exc:
            self._qc_status_var.set(f"Spectral QC: {exc}")
            logging.error(f"Spectral QC load error: {exc}")

    def _sort_qc_tree(self, col, reverse):
        """Sort the QC treeview by the given column."""
        items = [(self._qc_tree.set(k, col), k)
                 for k in self._qc_tree.get_children('')]
        # Try numeric sort first, fall back to string sort
        try:
            items.sort(key=lambda t: float(t[0]) if t[0] else 0, reverse=reverse)
        except (ValueError, TypeError):
            items.sort(key=lambda t: t[0], reverse=reverse)
        for index, (_, k) in enumerate(items):
            self._qc_tree.move(k, '', index)
        # Toggle sort direction on next click
        self._qc_tree.heading(
            col, command=lambda _col=col: self._sort_qc_tree(_col, not reverse))

    def _on_qc_tree_select_debounced(self, event=None):
        """Update mirror plot immediately when a row is selected."""
        if self._mirror_debounce_id is not None:
            try:
                self.root.after_cancel(self._mirror_debounce_id)
            except Exception:
                pass
        
        # Flash a loading message immediately before the process-heavy plot runs
        self._qc_mirror_info_var.set("Loading mirror plot... Please wait.")
        self.root.update_idletasks()

        # Increase delay slightly to allow the UI to repaint the label text
        self._mirror_debounce_id = self.root.after(20, self._on_qc_tree_select)

    def _on_qc_tree_select(self, event=None):
        """Draw mirror plot for the selected PSM row.

        - Observed (upper):  all raw scan peaks when mzML folder is set;
          matched ions in colour, unmatched peaks in light grey.
        - Predicted (lower):  all MS2PIP / AlphaPeptDeep predicted intensities
          from EIC data (both matched and unmatched predicted ions).
        """
        sel = self._qc_tree.selection()
        if not sel:
            return
        vals = self._qc_tree.item(sel[0], 'values')
        peptide = vals[0]
        # modification = vals[1]  (not used in mirror plot rendering)
        charge_str = vals[2]
        file_name = vals[3]
        scan_str = vals[4]
        sa_score = vals[5]

        if not self.results_file or not os.path.isdir(self.results_file):
            return

        ax = self._qc_ax_mirror
        ax.clear()

        from matplotlib.lines import Line2D

        _ion_colors = {
            'b': '#1976d2', 'y': '#d32f2f', 'a': '#7b1fa2',
            'c': '#388e3c', 'z': '#f57c00', 'x': '#5d4037',
        }
        _default_color = '#757575'
        _unmatched_color = '#bdbdbd'

        # ── 1. Load matched ions + predicted intensities from EICs ───
        matched_ions = []   # (mz, intensity, ion_label, base_type)
        pred_ions = []      # (mz, predicted_intensity, ion_label, base_type)

        eic_df = self._qc_data.get('eic_df')
        eic_grp = self._qc_data.get('eic_groupby')

        if eic_df is not None and not eic_df.empty:
            try:
                # Fast path using pre-grouped dataframe (~1ms)
                if eic_grp is not None:
                    pep_eic = eic_grp.get((peptide, file_name))
                    if pep_eic is None:
                        pep_eic = pd.DataFrame()
                else:
                    # Slow path (~50-200ms)
                    pep_eic = eic_df[
                        (eic_df['peptide'] == peptide) &
                        (eic_df['file'] == file_name)
                    ]

                if not pep_eic.empty and 'scan_number' in pep_eic.columns:
                    try:
                        scan_rows, _ = _find_scan_rows(pep_eic, scan_str)
                    except Exception:
                        req_key = _scan_key(scan_str)
                        scan_keys = pep_eic['scan_number'].apply(_scan_key)
                        scan_rows = pep_eic[scan_keys == req_key]

                    if not scan_rows.empty:
                        # Filter out neutral-loss rows safely
                        if 'neutral_loss' in scan_rows.columns:
                            nl_col = scan_rows['neutral_loss']
                            main = scan_rows[nl_col.isnull() | (nl_col.astype(str).str.strip() == '') | (nl_col.astype(str) == 'nan')]
                        else:
                            main = scan_rows

                        for _, row in main.iterrows():
                            it = str(row.get('ion_type', '')) if pd.notna(row.get('ion_type')) else ''
                            mz_col = 'fragment_theoretical_mz' if 'fragment_theoretical_mz' in main.columns else 'theoretical_mz'
                            mz = float(row.get(mz_col, 0))
                            inten = float(row.get('intensity', 0))
                            base_type = ''.join(c for c in it if c.isalpha()).lower()

                            if inten > 0:
                                matched_ions.append((mz, inten, it, base_type))

                            pred_int = row.get('predicted_intensity', np.nan)
                            try:
                                pred_int = float(pred_int)
                            except Exception:
                                pred_int = np.nan
                            if pd.notna(pred_int) and pred_int > 0:
                                pred_ions.append((mz, pred_int, it, base_type))
            except Exception as exc:
                logging.debug(f"Mirror plot EIC load error: {exc}")

        # Fallback: parse fragment_mzs from PSM sheet
        if not matched_ions:
            try:
                df = self._qc_data.get('df')
                if df is not None:
                    sa_col = self._qc_data['sa_col']
                    pep_col = next((c for c in df.columns
                                    if c.lower() in ('peptide', 'sequence')), None)
                    frag_mz_col = next((c for c in df.columns
                                        if c.lower() in ('fragment_mzs',)), None)
                    if pep_col and frag_mz_col:
                        for _, row in df.iterrows():
                            if (str(row.get(pep_col, '')) == peptide and
                                    f"{float(row.get(sa_col, 0)):.4f}" == sa_score):
                                frag_str = str(row.get(frag_mz_col, ''))
                                for entry in frag_str.split(','):
                                    entry = entry.strip()
                                    if ':' in entry:
                                        parts = entry.split(':')
                                        try:
                                            matched_ions.append(
                                                (float(parts[0]), 1.0, '', ''))
                                        except ValueError:
                                            pass
                                break
            except Exception:
                pass

        # ── 2. Load ALL raw scan peaks from mzML / .raw ─────────────
        all_scan_peaks = None
        mzml_folder = getattr(self, 'mzml_folder', None)
        if mzml_folder and os.path.isdir(mzml_folder):
            file_name_base = os.path.splitext(file_name)[0].lower()
            
            # Cache directory mapping to avoid os.listdir overhead on network drives (50-500ms)
            if getattr(self, '_mzml_folder_cache_path', None) != mzml_folder:
                self._mzml_folder_cache_path = mzml_folder
                self._mzml_file_mapping = {}
                try:
                    for fn in os.listdir(mzml_folder):
                        self._mzml_file_mapping[os.path.splitext(fn)[0].lower()] = os.path.join(mzml_folder, fn)
                except Exception:
                    pass

            data_file_path = self._mzml_file_mapping.get(file_name_base)
            if data_file_path is None:
                candidate = os.path.join(mzml_folder, file_name)
                if os.path.isfile(candidate):
                    data_file_path = candidate

            if data_file_path and os.path.isfile(data_file_path):
                spectrum = _get_spectrum_for_scan(data_file_path, scan_str)
                if spectrum is not None:
                    _mz_arr = spectrum.get('m/z array', np.array([]))
                    _int_arr = spectrum.get('intensity array', np.array([]))
                    if _mz_arr.size > 0 and _int_arr.size > 0:
                        all_scan_peaks = (_mz_arr.astype(np.float64),
                                          _int_arr.astype(np.float64))

        # ── 3. Draw Observed spectrum (upward) ───────────────────────
        actual_matched = 0
        has_raw = all_scan_peaks is not None
        tol_da = 0.02
        _LABEL_THRESH = 3.0

        if has_raw:
            mz_all, int_all = all_scan_peaks
            max_all = float(np.max(int_all)) if int_all.size > 0 else 1.0
            if max_all <= 0:
                max_all = 1.0
            int_norm = int_all / max_all * 100.0

            matched_raw_idx = {}
            for mmz, _, lbl, bt in matched_ions:
                diffs = np.abs(mz_all - mmz)
                best_idx = int(np.argmin(diffs))
                if diffs[best_idx] < tol_da:
                    matched_raw_idx[best_idx] = (lbl, bt)

            # Draw unmatched raw peaks in light grey
            unmatched_mask = np.ones(len(mz_all), dtype=bool)
            for idx in matched_raw_idx:
                unmatched_mask[idx] = False
            
            # Sub-sample/Filter unmatched noise peaks to guarantee instant rendering (~3ms vs 300ms)
            # Only draw unmatched peaks > 0.5% relative intensity to prevent matplotlib freezing on dense MS2 spectra
            visible_mask = unmatched_mask & (int_norm > 0.5)
            if np.any(visible_mask):
                ax.vlines(mz_all[visible_mask], 0, int_norm[visible_mask],
                          colors=_unmatched_color, linewidth=0.7, alpha=0.45)

            _batched_obs = {}
            for idx, (lbl, bt) in matched_raw_idx.items():
                _batched_obs.setdefault(bt, ([], [], []))
                _batched_obs[bt][0].append(mz_all[idx])
                _batched_obs[bt][1].append(int_norm[idx])
                _batched_obs[bt][2].append(lbl)
            for bt, (mzs, ints, lbls) in _batched_obs.items():
                color = _ion_colors.get(bt, _default_color)
                ax.vlines(mzs, 0, ints, colors=color, linewidth=1.4)
                for _m, _i, _l in zip(mzs, ints, lbls):
                    if _l and _i >= _LABEL_THRESH:
                        ax.text(_m, _i + 2, _l, fontsize=7,
                                ha='center', va='bottom', rotation=90, color=color)
            actual_matched = len(matched_raw_idx)
        else:
            if matched_ions:
                max_obs = max(i[1] for i in matched_ions)
                if max_obs <= 0:
                    max_obs = 1.0
                _batched_obs2 = {}
                for mz, inten, lbl, bt in matched_ions:
                    norm_int = inten / max_obs * 100.0
                    _batched_obs2.setdefault(bt, ([], [], []))
                    _batched_obs2[bt][0].append(mz)
                    _batched_obs2[bt][1].append(norm_int)
                    _batched_obs2[bt][2].append(lbl)
                for bt, (mzs, ints, lbls) in _batched_obs2.items():
                    color = _ion_colors.get(bt, _default_color)
                    ax.vlines(mzs, 0, ints, colors=color, linewidth=1.4)
                    for _m, _i, _l in zip(mzs, ints, lbls):
                        if _l and _i >= _LABEL_THRESH:
                            ax.text(_m, _i + 2, _l, fontsize=7, ha='center',
                                    va='bottom', rotation=90, color=color)
            actual_matched = len(matched_ions)

        # ── 4. Draw Predicted spectrum (downward) — all predicted ions ─
        pred_norm = []
        if pred_ions:
            max_pred = max(i[1] for i in pred_ions)
            if max_pred <= 0:
                max_pred = 1.0
            pred_norm = [(mz, inten / max_pred * 100.0, lbl, bt)
                         for mz, inten, lbl, bt in pred_ions]

        _batched_pred = {}
        for pmz, inten, plabel, pbt in pred_norm:
            _batched_pred.setdefault(pbt, ([], [], []))
            _batched_pred[pbt][0].append(pmz)
            _batched_pred[pbt][1].append(-inten)
            _batched_pred[pbt][2].append(plabel)
        for pbt, (mzs, neg_ints, lbls) in _batched_pred.items():
            color = _ion_colors.get(pbt, _default_color)
            ax.vlines(mzs, 0, neg_ints, colors=color, linewidth=1.2, alpha=0.9)
            for _m, _ni, _l in zip(mzs, neg_ints, lbls):
                if _l and abs(_ni) >= _LABEL_THRESH:
                    ax.text(_m, _ni - 2, _l, fontsize=7, ha='center',
                            va='top', rotation=90, color=color, alpha=0.9)

        # ── 5. Axes formatting ───────────────────────────────────────
        ax.axhline(0, color='black', linewidth=0.8)
        ax.set_xlabel('m/z')

        info_str = f"{peptide}  z={charge_str}   SA={sa_score}   matched={actual_matched}"
        self._qc_mirror_info_var.set(info_str)
        ax.set_title(f'Mirror Plot \u2014 {peptide} {charge_str}+   SA = {sa_score}')

        current_ylim = ax.get_ylim()
        max_abs = max(abs(current_ylim[0]), abs(current_ylim[1]), 100)
        ax.set_ylim(-max_abs * 1.15, max_abs * 1.15)
        ax.set_ylabel('Relative Intensity (%)')
        yticks = ax.get_yticks()
        ax.set_yticks(yticks)
        ax.set_yticklabels([f'{abs(v):.0f}' for v in yticks])

        ax.text(0.01, 0.95, 'Observed \u2191', transform=ax.transAxes,
                fontsize=9, va='top', ha='left', fontstyle='italic', color='#555')
        if pred_norm:
            ax.text(0.01, 0.05, 'Predicted \u2193', transform=ax.transAxes,
                    fontsize=9, va='bottom', ha='left', fontstyle='italic', color='#555')
        else:
            ax.text(0.01, 0.05, 'Predicted \u2193  (no predictions available)',
                    transform=ax.transAxes, fontsize=8, va='bottom', ha='left',
                    fontstyle='italic', color='#888')

        seen_types = set()
        legend_handles = []
        for items_list in [matched_ions, pred_norm]:
            for item in items_list:
                bt = item[3]
                if bt and bt not in seen_types:
                    seen_types.add(bt)
                    legend_handles.append(
                        Line2D([0], [0], color=_ion_colors.get(bt, _default_color),
                               linewidth=2, label=f'{bt}-ions'))
        if has_raw:
            legend_handles.append(
                Line2D([0], [0], color=_unmatched_color, linewidth=1.5,
                       alpha=0.5, label='unmatched'))
        if legend_handles:
            ax.legend(handles=legend_handles, loc='upper right', fontsize=8)

        self._qc_fig_mirror.subplots_adjust(left=0.08, right=0.97, top=0.92, bottom=0.10)
        self._qc_canvas_mirror.draw_idle()

    def _export_sa_csv(self):
        """Export spectral-angle scores to CSV."""
        df = self._qc_data.get('df')
        if df is None:
            messagebox.showwarning("No Data", "Load results first.")
            return
        fp = filedialog.asksaveasfilename(
            title="Export SA Scores",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All", "*.*")],
        )
        if not fp:
            return
        sa_col = self._qc_data['sa_col']
        cols = [c for c in df.columns if c.lower() in
                ('peptide', 'sequence', 'charge', 'precursor_charge',
                 'file', 'raw_file', 'scan', 'scan_number',
                 'matched_fragments', 'mass_accuracy', sa_col.lower())]
        if not cols:
            cols = list(df.columns)
        df[cols].to_csv(fp, index=False)
        self._qc_status_var.set(f"Exported to {os.path.basename(fp)}")

    # --------------------------------------------------------------------- #
    # EIC Reactivity Callbacks
    # --------------------------------------------------------------------- #
    def _on_rt_toggle(self):
        """Re-plot EIC when RT line toggles change."""
        if self._eic_displayed:
            self._plot_eic()

    def _on_rt_width_changed(self):
        """Re-plot EIC when RT width changes."""
        new_val = self.reintegrate_rt_width_var.get().strip()
        if new_val != self._last_rt_width_val:
            self._last_rt_width_val = new_val
            if self._eic_displayed:
                self._plot_eic()

    # --------------------------------------------------------------------- #
    # EIC Plotting
    # --------------------------------------------------------------------- #
    def _plot_eic(self):
        if not self._check_loaded():
            return
        peptide = self.eic_peptide_var.get()
        mzml_file = self.eic_file_var.get()
        if not peptide or not mzml_file:
            messagebox.showwarning("Input Error", "Please select a peptide and a file.")
            return

        self._clear_canvas(self.eic_canvas_frame)
        self._eic_displayed = False

        peptide_seq = peptide
        modification_from_input = ""
        if " (" in peptide and peptide.endswith(")"):
            peptide_seq = peptide.split(" (")[0]
            modification_from_input = peptide.split(" (")[1][:-1]

        try:
            import matplotlib.pyplot as plt
            from matplotlib.figure import Figure

            eic_df = _get_cached_excel_sheet(self.results_file, "EICs")
            peptide_eic = eic_df[(eic_df["peptide"] == peptide_seq) & (eic_df["file"] == mzml_file)]
            if modification_from_input and "modification" in eic_df.columns:
                peptide_eic = peptide_eic[peptide_eic["modification"] == modification_from_input]

            if peptide_eic.empty:
                messagebox.showinfo("No EIC Data",
                                    f"No EIC data found for {peptide_seq} in {mzml_file}.\n"
                                    "Re-run analysis with 'Generate EICs' checked.")
                return

            psm_df = _get_cached_excel_sheet(self.results_file, "PSM")
            peptide_data = psm_df[(psm_df["peptide"] == peptide_seq) & (psm_df["file"] == mzml_file)]
            if modification_from_input and "modification" in psm_df.columns:
                peptide_data = peptide_data[peptide_data["modification"] == modification_from_input]

            # Robust known_rt extraction (skip NaN values)
            known_rt = None
            if not peptide_data.empty and "known_rt" in peptide_data.columns:
                _krt = peptide_data["known_rt"].dropna()
                if not _krt.empty:
                    known_rt = float(_krt.values[0])

            # Corrected RT (from drift correction, if available)
            known_rt_corrected = None
            if not peptide_data.empty and "known_rt_corrected" in peptide_data.columns:
                _krtc = peptide_data["known_rt_corrected"].dropna()
                if not _krtc.empty:
                    known_rt_corrected = float(_krtc.values[0])

            # Determine RT window from PSM data
            if not peptide_data.empty and "start_rt" in peptide_data.columns:
                _srt = peptide_data["start_rt"].dropna()
                _ert = peptide_data["stop_rt"].dropna()
                if not _srt.empty and not _ert.empty:
                    start_rt = float(_srt.values[0])
                    stop_rt = float(_ert.values[0])
                else:
                    start_rt = peptide_eic["rt"].min()
                    stop_rt = peptide_eic["rt"].max()
            else:
                # Fallback: use range from EIC data with 1-min padding
                start_rt = peptide_eic["rt"].min()
                stop_rt = peptide_eic["rt"].max()

            # Override RT window if user specified a custom RT width
            rt_width_str = self.reintegrate_rt_width_var.get().strip()
            if rt_width_str:
                try:
                    rt_width = float(rt_width_str)
                    if rt_width > 0:
                        rt_src = self.reintegrate_rt_source_var.get()
                        if rt_src == "Corrected" and known_rt_corrected is not None:
                            center_rt = known_rt_corrected
                        elif known_rt is not None:
                            center_rt = known_rt
                        else:
                            center_rt = (start_rt + stop_rt) / 2.0
                        start_rt = center_rt - rt_width / 2.0
                        stop_rt = center_rt + rt_width / 2.0
                except ValueError:
                    pass

            fig = Figure(figsize=(10, 6), dpi=100)
            ax = fig.add_subplot(111)

            peptide_eic_filtered = peptide_eic.dropna(subset=["ion_type", "fragment_charge"])
            main_ions = peptide_eic_filtered[
                peptide_eic_filtered["neutral_loss"].isnull() | (peptide_eic_filtered["neutral_loss"] == "")]

            if main_ions.empty:
                messagebox.showinfo("No Matched Fragments", "No matched fragment ions in the data.")
                return

            group_cols = ["ion_type", "fragment_charge"]
            groups = main_ions.groupby(group_cols)
            colors = plt.cm.tab10(np.linspace(0, 1, max(len(groups), 1)))

            # Rank fragments by intensity within RT window
            global_max = 0
            frag_info = []
            for (ion_type, frag_charge), group in groups:
                df_rt = group.groupby("rt").agg({"intensity": "max"}).reset_index()
                df_rt_win = df_rt[(df_rt["rt"] >= start_rt) & (df_rt["rt"] <= stop_rt)]
                if len(df_rt_win) >= 5:
                    mx = df_rt_win["intensity"].max()
                    if mx > global_max:
                        global_max = mx
                    theo_mz = group["fragment_theoretical_mz"].iloc[0] if "fragment_theoretical_mz" in group.columns else 0.0
                    frag_info.append((ion_type, frag_charge, mx, theo_mz))

            frag_info.sort(key=lambda x: x[2], reverse=True)
            top_keys = {(it, fc): mz for it, fc, _, mz in frag_info[:20]}

            groups = main_ions.groupby(group_cols)
            max_intensity = 0
            smooth_method = self.smooth_var.get()
            smooth_window = self.smooth_window_var.get()

            for idx, ((ion_type, frag_charge), group) in enumerate(groups):
                if (ion_type, frag_charge) not in top_keys:
                    continue
                df_rt = group.groupby("rt").agg({"intensity": "max"}).reset_index()
                df_rt = df_rt[(df_rt["rt"] >= start_rt) & (df_rt["rt"] <= stop_rt)]
                if len(df_rt) < 5:
                    continue
                rts = df_rt["rt"].values
                intensities = df_rt["intensity"].values / global_max if global_max > 0 else df_rt["intensity"].values

                if smooth_method != "None" and len(intensities) >= smooth_window:
                    if smooth_method == "Gaussian":
                        intensities = gaussian_filter1d(intensities, sigma=max(1, smooth_window / 6))
                    else:
                        w = max(3, smooth_window if smooth_window % 2 else smooth_window + 1)
                        intensities = savgol_filter(intensities, w, polyorder=min(2, w - 1))

                if len(rts) > 1000:
                    step = len(rts) // 1000
                    rts, intensities = rts[::step], intensities[::step]

                if rts.size == 0:
                    continue
                max_intensity = max(max_intensity, intensities.max())

                theo_mz = top_keys[(ion_type, frag_charge)]
                label = f"{ion_type} ({frag_charge}+) m/z {theo_mz:.4f}"
                ax.plot(rts, intensities, label=label, color=colors[idx % len(colors)], alpha=0.7)
                ax.fill_between(rts, 0, intensities, color=colors[idx % len(colors)], alpha=0.15)

            ax.axvspan(start_rt, stop_rt, alpha=0.2, color="gray")
            # Show RT reference lines based on checkbox states
            if self.show_original_rt_var.get() and known_rt is not None:
                ax.axvline(x=known_rt, color="r", linestyle="--", linewidth=1, label="Original RT")
            if self.show_corrected_rt_var.get() and known_rt_corrected is not None:
                ax.axvline(x=known_rt_corrected, color="green", linestyle="--", linewidth=1.2, label="Corrected RT")

            ax.set_xlabel("Retention Time (min)")
            ax.set_ylabel("Normalized Intensity")
            ax.set_title(f"{peptide} in {mzml_file}")
            handles, labels = ax.get_legend_handles_labels()
            if handles:
                ax.legend(handles, labels, loc="upper right", fontsize="small", ncol=1, framealpha=0.9)
            ax.set_ylim(bottom=0, top=max_intensity * 1.1 if max_intensity > 0 else 1)
            ax.set_xlim(start_rt - 5, stop_rt + 5)

            self._embed_figure(fig, self.eic_canvas_frame)
            self._eic_displayed = True

        except Exception as e:
            logging.error(f"Error plotting EIC: {e}")
            traceback.print_exc()
            messagebox.showerror("Error", f"Failed to plot EIC: {e}")

    # --------------------------------------------------------------------- #
    # MS2 Spectrum
    # --------------------------------------------------------------------- #
    def _plot_ms2(self):
        if not self._check_loaded():
            return
        peptide = self.eic_peptide_var.get()
        mzml_file = self.eic_file_var.get()
        if not peptide or not mzml_file:
            messagebox.showwarning("Input Error", "Please select a peptide and a file.")
            return
        if not self.mzml_folder or not os.path.isdir(self.mzml_folder):
            messagebox.showwarning("mzML Folder Required",
                                   "Please select the mzML / raw files folder to display MS2 spectra.")
            return

        self._clear_canvas(self.eic_canvas_frame)

        peptide_seq = peptide
        modification_from_input = ""
        if " (" in peptide and peptide.endswith(")"):
            peptide_seq = peptide.split(" (")[0]
            modification_from_input = peptide.split(" (")[1][:-1]

        try:
            import matplotlib.pyplot as plt
            from matplotlib.figure import Figure

            eic_df = _get_cached_excel_sheet(self.results_file, "EICs")
            psm_df = _get_cached_excel_sheet(self.results_file, "PSM")

            peptide_eic = eic_df[(eic_df["peptide"] == peptide_seq) & (eic_df["file"] == mzml_file)]
            if modification_from_input:
                peptide_eic = peptide_eic[peptide_eic["modification"] == modification_from_input]

            if peptide_eic.empty:
                messagebox.showinfo("No Data", f"No EIC data found for {peptide_seq} in {mzml_file}.")
                return

            psm_peptide = psm_df[(psm_df["peptide"] == peptide_seq) & (psm_df["file"] == mzml_file)]
            if modification_from_input:
                psm_peptide = psm_peptide[psm_peptide["modification"] == modification_from_input]

            if not psm_peptide.empty:
                best_psm = psm_peptide.loc[psm_peptide["psm_score"].idxmax()]
                scan_number = best_psm["scan_number"]
                precursor_mz_val = best_psm.get("m_z", float("nan"))
                precursor_charge_val = best_psm.get("charge", "")
            else:
                scan_number = peptide_eic["scan_number"].iloc[0] if "scan_number" in peptide_eic.columns else None
                precursor_mz_val = peptide_eic["m_z"].iloc[0] if "m_z" in peptide_eic.columns else float("nan")
                precursor_charge_val = ""
                if "charge" in peptide_eic.columns:
                    precursor_charge_val = peptide_eic["charge"].iloc[0]
                elif "precursor_charge" in peptide_eic.columns:
                    precursor_charge_val = peptide_eic["precursor_charge"].iloc[0]

            if scan_number is None:
                messagebox.showwarning("No Data", "No scan number found for this peptide.")
                return

            # Match scan rows robustly (exact normalized key, then nearest numeric scan)
            scan_eic, matched_scan_key = _find_scan_rows(peptide_eic, scan_number)
            scan_eic = _eic_rows_matched_only(scan_eic)

            # Read spectrum from mzML
            mzml_path = os.path.join(self.mzml_folder, mzml_file)
            if not os.path.isfile(mzml_path):
                messagebox.showwarning("File Not Found", f"Cannot find {mzml_path}.\nPlease select the correct mzML folder.")
                return

            spectrum = _get_spectrum_for_scan(mzml_path, scan_number)

            if spectrum is None:
                messagebox.showwarning("No Data",
                    f"Spectrum for scan {scan_number} not found.\n"
                    f"Make sure the correct data folder is selected.")
                return

            fig = Figure(figsize=(10, 6), dpi=100)
            ax = fig.add_subplot(111)

            mz_array = spectrum.get("m/z array", np.array([]))
            intensity_array = spectrum.get("intensity array", np.array([]))
            if intensity_array.size > 0 and np.max(intensity_array) > 0:
                norm_int = intensity_array / np.max(intensity_array) * 100
            else:
                norm_int = intensity_array

            # Full spectrum in grey
            ml, sl, bl = ax.stem(mz_array, norm_int, linefmt="grey", markerfmt=" ", basefmt=" ")
            plt.setp(sl, alpha=0.5)

            ion_colors = {"b": "blue", "y": "red", "a": "purple", "c": "green",
                          "z": "orange", "x": "brown", "unknown": "darkgrey"}

            # Overlay matched ions
            ion_groups = {}
            for _, row in scan_eic.iterrows():
                it = str(row["ion_type"]).strip() if pd.notna(row.get("ion_type")) else "unknown"
                # Use fragment_charge if available, fall back to charge
                ch_col = "fragment_charge" if "fragment_charge" in scan_eic.columns else "charge"
                ch = int(row[ch_col]) if pd.notna(row.get(ch_col)) else 1
                nl = row.get("neutral_loss") if pd.notna(row.get("neutral_loss", None)) else None
                # Use fragment_theoretical_mz if available, fall back to theoretical_mz
                mz_col = "fragment_theoretical_mz" if "fragment_theoretical_mz" in scan_eic.columns else "theoretical_mz"
                theo_mz = float(row[mz_col]) if pd.notna(row.get(mz_col, None)) else 0.0
                base_it = "".join(c for c in it if c.isalpha())
                gk = (base_it, ch, nl)
                ion_groups.setdefault(gk, []).append((theo_mz, row))

            legend_handles = {}
            for (it, ch, nl), ions in ion_groups.items():
                color = ion_colors.get(it.lower(), "darkgrey")
                ls = "--" if nl else "-"
                alpha = 0.7 if nl else 1.0
                lk = (it, nl)
                if lk not in legend_handles:
                    lbl = f"{it}" + (f"-{nl}" if nl else "")
                    legend_handles[lk] = ax.plot([], [], color=color, label=lbl, linestyle=ls, linewidth=2)[0]

                mzs = [i[0] for i in ions]
                ints = []
                for mz in mzs:
                    idx = np.abs(mz_array - mz).argmin()
                    ints.append(norm_int[idx] if idx < len(norm_int) else 0)

                ml2, sl2, bl2 = ax.stem(mzs, ints, markerfmt="o", linefmt="-", basefmt=" ")
                ml2.set_color(color); ml2.set_alpha(alpha); ml2.set_markersize(6)
                if isinstance(sl2, list):
                    for s in sl2:
                        s.set_color(color); s.set_alpha(alpha)
                else:
                    sl2.set_color(color); sl2.set_alpha(alpha)

                for mz, intensity, (_, row) in zip(mzs, ints, ions):
                    if intensity > 5:
                        ion_num = "".join(c for c in str(row["ion_type"]) if c.isascii() and c.isdigit()) if pd.notna(row["ion_type"]) else ""
                        sup = {1: "\u207a", 2: "\u00b2\u207a", 3: "\u00b3\u207a"}.get(ch, f"^{ch}+")
                        lbl = f"{it}{ion_num}{sup}"
                        if nl:
                            lbl += f"-{nl}"
                        ax.text(mz, intensity + 2, lbl, fontsize=8, ha="center",
                                rotation=90 if nl else 0, color=color)

            # Get RT value safely from scan_eic or from the raw spectrum
            if not scan_eic.empty and "rt" in scan_eic.columns:
                rt_val = float(scan_eic['rt'].iloc[0])
            else:
                rt_val = 0.0
                if spectrum and 'scanList' in spectrum:
                    scans = spectrum['scanList'].get('scan', [])
                    if scans:
                        rt_val = float(scans[0].get('scan start time', 0.0))

            scan_info = (f"Scan: {scan_number}\n"
                         f"RT: {rt_val:.2f} min\n"
                         f"Precursor m/z: {precursor_mz_val:.4f}\n"
                         f"Charge: {precursor_charge_val}+\n"
                         f"Matched fragments: {len(scan_eic)}")
            ax.text(0.02, 0.98, scan_info, transform=ax.transAxes, va="top",
                    bbox=dict(boxstyle="round", facecolor="white", alpha=0.8), fontsize=9)

            if len(scan_eic) == 0:
                logging.warning(
                    f"No matched fragment rows for peptide={peptide_seq}, file={mzml_file}, "
                    f"requested_scan={scan_number}, matched_scan_key={matched_scan_key}"
                )

            if legend_handles:
                sorted_h = sorted(legend_handles.items(), key=lambda x: (x[0][1] is not None, x[0][0]))
                ax.legend(handles=[h[1] for h in sorted_h], loc="upper right", fontsize="small")

            ax.set_xlabel("m/z")
            ax.set_ylabel("Relative Intensity (%)")
            ax.set_title(f"{peptide}")
            ax.set_ylim(bottom=0)

            self._embed_figure(fig, self.eic_canvas_frame)

        except Exception as e:
            logging.error(f"Error plotting MS2: {e}")
            traceback.print_exc()
            messagebox.showerror("Error", f"Failed to plot MS2 spectrum: {e}")

    # --------------------------------------------------------------------- #
    # Re-Integration
    # --------------------------------------------------------------------- #
    def _reintegrate_all(self):
        """Re-integrate EIC areas for ALL peptides and files, then export as quant results."""
        if not self._check_loaded():
            return

        # Validate RT width
        rt_width_str = self.reintegrate_rt_width_var.get().strip()
        if not rt_width_str:
            messagebox.showwarning("Input Error",
                "Please enter an RT Width (minutes) for re-integration.")
            return
        try:
            rt_width = float(rt_width_str)
            if rt_width <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "RT Width must be a positive number.")
            return

        rt_source = self.reintegrate_rt_source_var.get()

        # Ask for output file
        default_name = os.path.basename(self.results_file) + "_reintegrated.csv"
        output_file = filedialog.asksaveasfilename(
            title="Save Re-Integration Results",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile=default_name
        )
        if not output_file:
            return

        try:
            eic_df = _get_cached_excel_sheet(self.results_file, "EICs")
            psm_df = _get_cached_excel_sheet(self.results_file, "PSM")

            # Get all unique peptide + file combinations (exclude decoys)
            target_psm = psm_df[~psm_df["peptide"].str.startswith("DECOY_")]
            combo_cols = ["peptide", "file"]
            if "modification" in target_psm.columns:
                combo_cols = ["peptide", "modification", "file"]
            combos = target_psm.groupby(combo_cols).first().reset_index()[combo_cols]

            if combos.empty:
                messagebox.showwarning("No Data", "No peptide/file combinations found.")
                return

            _trapz_fn = getattr(np, 'trapezoid', getattr(np, 'trapz', None))
            results = []
            skipped = 0
            processed = 0

            # Show progress
            total = len(combos)
            self.root.config(cursor="watch")
            self.root.update()

            for row_idx, row in combos.iterrows():
                pep = row["peptide"]
                f = row["file"]
                mod = row.get("modification", "") if "modification" in row.index else ""

                # Get PSM data for this combo
                pep_psm = target_psm[(target_psm["peptide"] == pep) & (target_psm["file"] == f)]
                if mod and pd.notna(mod) and str(mod).strip() and "modification" in pep_psm.columns:
                    pep_psm = pep_psm[pep_psm["modification"] == mod]

                if pep_psm.empty:
                    skipped += 1
                    continue

                # Determine center RT
                center_rt = None
                if rt_source == "Corrected" and "known_rt_corrected" in pep_psm.columns:
                    center_vals = pep_psm["known_rt_corrected"].dropna()
                    if not center_vals.empty:
                        center_rt = float(center_vals.values[0])

                if center_rt is None and "known_rt" in pep_psm.columns:
                    center_vals = pep_psm["known_rt"].dropna()
                    if not center_vals.empty:
                        center_rt = float(center_vals.values[0])

                if center_rt is None:
                    skipped += 1
                    continue

                new_start = center_rt - rt_width / 2.0
                new_stop = center_rt + rt_width / 2.0

                # Get EIC data
                pep_eic = eic_df[(eic_df["peptide"] == pep) & (eic_df["file"] == f)]
                if mod and pd.notna(mod) and str(mod).strip() and "modification" in eic_df.columns:
                    pep_eic = pep_eic[pep_eic["modification"] == mod]

                if pep_eic.empty:
                    skipped += 1
                    continue

                # Filter to new RT window
                eic_in_window = pep_eic[
                    (pep_eic["rt"] >= new_start) & (pep_eic["rt"] <= new_stop)
                ]
                if eic_in_window.empty:
                    skipped += 1
                    continue

                # Integrate: trapezoidal rule for each fragment.
                # Harmonized with the main pipeline (calculate_fragment_eic_areas):
                # - neutral-loss traces are included as separate fragments
                #   (grouped by ion_type + neutral_loss + charge), and
                # - each fragment needs at least 3 EIC points to integrate.
                eic_filtered = eic_in_window.dropna(subset=["ion_type", "fragment_charge"]).copy()
                eic_filtered["_nl_key"] = eic_filtered["neutral_loss"].fillna("").astype(str)
                _frag_groups = ["ion_type", "_nl_key", "fragment_charge"]

                total_area = 0.0
                for _frag_key, grp in eic_filtered.groupby(_frag_groups):
                    df_rt = grp.groupby("rt").agg({"intensity": "max"}).reset_index().sort_values("rt")
                    if len(df_rt) < 3:
                        continue
                    area = float(_trapz_fn(df_rt["intensity"].values, df_rt["rt"].values))
                    total_area += area

                # Sum of max intensities per fragment within the window
                total_intensity = 0.0
                if not eic_filtered.empty:
                    total_intensity = float(
                        eic_filtered.groupby(_frag_groups)["intensity"].max().sum()
                    )

                mz_val = float(pep_psm["m_z"].values[0]) if "m_z" in pep_psm.columns else 0.0
                charge_val = pep_psm["charge"].values[0] if "charge" in pep_psm.columns else 0

                result_row = {
                    "peptide": pep,
                    "m_z": mz_val,
                    "charge": charge_val,
                    "file": f,
                    "eic_area": total_area,
                    "total_intensity": total_intensity,
                    "center_rt": center_rt,
                    "rt_window_start": new_start,
                    "rt_window_stop": new_stop,
                }
                if mod and pd.notna(mod) and str(mod).strip():
                    result_row["modification"] = mod
                results.append(result_row)
                processed += 1

            self.root.config(cursor="")

            if not results:
                messagebox.showwarning("No Results",
                    "Re-integration produced no results.\n"
                    "Check that EIC data is available in the results file.")
                return

            results_long = pd.DataFrame(results)

            # Pivot to wide format (like Peptide Quantification sheet)
            pivot_index = ["peptide", "m_z", "charge"]
            if "modification" in results_long.columns:
                pivot_index.insert(1, "modification")

            area_pivot = results_long.pivot_table(
                index=pivot_index,
                columns="file",
                values="eic_area",
                aggfunc="sum",
                fill_value=0
            )
            area_pivot.columns = [f"{col}_eic_area" for col in area_pivot.columns]

            intensity_pivot = results_long.pivot_table(
                index=pivot_index,
                columns="file",
                values="total_intensity",
                aggfunc="sum",
                fill_value=0
            )
            intensity_pivot.columns = [f"{col}_intensity" for col in intensity_pivot.columns]

            quant_data = area_pivot.join(intensity_pivot, how="outer").reset_index()

            # ------------------------------------------------------------- #
            # Build Protein Quantification and Combined sheets using the
            # protein → peptide mapping from the original results file.
            # ------------------------------------------------------------- #
            protein_quant_df = pd.DataFrame()
            combined_df = pd.DataFrame()
            try:
                orig_combined = _get_cached_excel_sheet(self.results_file, "Combined")

                # Extract protein → peptide mapping from the original Combined sheet.
                # Protein rows have a non-empty Accession; peptide rows have
                # the peptide sequence in "Protein Name" and empty Accession.
                acc_col = "Accession" if "Accession" in orig_combined.columns else None
                name_col = "Protein Name" if "Protein Name" in orig_combined.columns else None

                if acc_col and name_col:
                    protein_map = {}  # accession -> {"name": ..., "peptides": [pep1, ...]}
                    current_acc = None
                    for _, crow in orig_combined.iterrows():
                        acc_val = crow.get(acc_col)
                        pname = crow.get(name_col)
                        if pd.notna(acc_val) and str(acc_val).strip():
                            current_acc = str(acc_val).strip()
                            protein_map[current_acc] = {
                                "name": str(pname).strip() if pd.notna(pname) else "",
                                "peptides": [],
                            }
                        elif current_acc and pd.notna(pname) and str(pname).strip():
                            protein_map[current_acc]["peptides"].append(str(pname).strip())

                    # Identify file columns present in quant_data
                    area_cols = [c for c in quant_data.columns if c.endswith("_eic_area")]
                    int_cols = [c for c in quant_data.columns if c.endswith("_intensity")]

                    # Build Protein Quantification rows
                    protein_rows = []
                    combined_rows = []
                    for acc, pinfo in protein_map.items():
                        # collect quant rows whose peptide is mapped to this protein
                        pep_rows = quant_data[quant_data["peptide"].isin(pinfo["peptides"])]
                        prot_row = {"Accession": acc, "Protein Name": pinfo["name"],
                                    "Peptides Used": len(pep_rows)}
                        for c in area_cols:
                            prot_row[c] = pep_rows[c].sum() if c in pep_rows.columns else 0
                        for c in int_cols:
                            prot_row[c] = pep_rows[c].sum() if c in pep_rows.columns else 0
                        protein_rows.append(prot_row)

                        # Combined sheet: protein header row  →  peptide detail rows
                        combined_rows.append(prot_row.copy())
                        for _, pr in pep_rows.iterrows():
                            pep_detail = {"Accession": "", "Protein Name": pr["peptide"],
                                          "Peptides Used": ""}
                            for c in area_cols:
                                pep_detail[c] = pr.get(c, 0)
                            for c in int_cols:
                                pep_detail[c] = pr.get(c, 0)
                            combined_rows.append(pep_detail)
                        combined_rows.append({})  # separator row

                    if protein_rows:
                        protein_quant_df = pd.DataFrame(protein_rows)
                    if combined_rows:
                        combined_df = pd.DataFrame(combined_rows)
            except Exception as pq_err:
                logging.warning(f"Could not build Protein/Combined sheets: {pq_err}")

            # Save to CSV — main re-integration file + optional separate CSVs
            quant_data.to_csv(output_file, index=False)
            _out_dir = os.path.dirname(output_file)
            _out_stem = os.path.splitext(os.path.basename(output_file))[0]
            if not protein_quant_df.empty:
                protein_quant_df.to_csv(
                    os.path.join(_out_dir, f"{_out_stem}_Protein_Quantification.csv"), index=False)
            if not combined_df.empty:
                combined_df.to_csv(
                    os.path.join(_out_dir, f"{_out_stem}_Combined.csv"), index=False)
            results_long.to_csv(
                os.path.join(_out_dir, f"{_out_stem}_Details.csv"), index=False)

            messagebox.showinfo("Re-Integration Complete",
                f"Re-integrated {processed} peptide/file combinations.\n"
                f"Skipped: {skipped}\n"
                f"RT Width: {rt_width:.2f} min, RT Source: {rt_source}\n\n"
                f"Results saved to:\n{os.path.basename(output_file)}")

        except Exception as e:
            self.root.config(cursor="")
            logging.error(f"Error during re-integration: {e}")
            traceback.print_exc()
            messagebox.showerror("Error", f"Re-integration failed: {e}")

    # --------------------------------------------------------------------- #
    # QC Plots
    # --------------------------------------------------------------------- #
    def _generate_qc_plot(self):
        if not self._check_loaded():
            return
        self._clear_canvas(self.qc_canvas_frame)
        metric = self.qc_metric_var.get()

        try:
            import seaborn as sns
            from matplotlib.figure import Figure

            results_df = _get_cached_excel_sheet(self.results_file, "PSM")
            target_df = results_df[~results_df["peptide"].str.startswith("DECOY_")]
            if target_df.empty:
                messagebox.showwarning("No Data", "No target PSMs found.")
                return

            fig = Figure(figsize=(12, 8), dpi=100)

            if metric == "Mass Accuracy":
                mass_acc, fnames = [], []
                for _, row in target_df.iterrows():
                    fmz = row["fragment_mzs"]
                    if pd.notna(fmz):
                        for part in str(fmz).split(", "):
                            if ":" in part:
                                _, acc = part.split(":")
                                mass_acc.append(float(acc))
                                fnames.append(row["file"])
                if not mass_acc:
                    messagebox.showinfo("No Data", "No mass accuracy data available.")
                    return
                mass_df = pd.DataFrame({"File": fnames, "Mass Accuracy (ppm)": mass_acc})
                gs = fig.add_gridspec(2, 2, width_ratios=[3, 1], height_ratios=[1, 3])
                ax_h = fig.add_subplot(gs[0, 0])
                ax_h.hist(mass_acc, bins=50, color="skyblue", edgecolor="black")
                ax_h.set_title("Mass Accuracy Distribution"); ax_h.set_xlabel("ppm"); ax_h.set_ylabel("Count")
                ax_b = fig.add_subplot(gs[1, 0])
                sns.boxplot(x="File", y="Mass Accuracy (ppm)", data=mass_df, ax=ax_b)
                ax_b.set_xticklabels(ax_b.get_xticklabels(), rotation=45, ha="right")
                ax_d = fig.add_subplot(gs[1, 1])
                sns.kdeplot(y=mass_acc, ax=ax_d, fill=True); ax_d.set_ylabel("ppm")
                ax_s = fig.add_subplot(gs[0, 1]); ax_s.axis("off")
                ax_s.text(0.5, 0.5, f"Mean: {np.mean(mass_acc):.4f}\nMedian: {np.median(mass_acc):.4f}\n"
                          f"Std: {np.std(mass_acc):.4f}\nN: {len(mass_acc)}", ha="center", va="center", fontsize=10)

            elif metric == "Retention Time Deviation":
                rt_data = target_df[pd.notna(target_df["known_rt"])].copy()
                if rt_data.empty:
                    messagebox.showwarning("No Data", "No known RT data available."); return
                rt_data["rt_dev"] = rt_data["rt"] - rt_data["known_rt"]
                gs = fig.add_gridspec(2, 2, width_ratios=[3, 1], height_ratios=[1, 3])
                ax_h = fig.add_subplot(gs[0, 0])
                ax_h.hist(rt_data["rt_dev"], bins=30, color="lightgreen", edgecolor="black")
                ax_h.set_title("RT Deviation"); ax_h.set_xlabel("min")
                ax_sc = fig.add_subplot(gs[1, 0])
                ax_sc.scatter(rt_data["known_rt"], rt_data["rt"], alpha=0.6)
                mn = min(rt_data["known_rt"].min(), rt_data["rt"].min())
                mx = max(rt_data["known_rt"].max(), rt_data["rt"].max())
                ax_sc.plot([mn, mx], [mn, mx], "r--"); ax_sc.set_xlabel("Expected RT"); ax_sc.set_ylabel("Observed RT")
                ax_d = fig.add_subplot(gs[1, 1])
                sns.kdeplot(y=rt_data["rt_dev"], ax=ax_d, fill=True)
                ax_s = fig.add_subplot(gs[0, 1]); ax_s.axis("off")
                ax_s.text(0.5, 0.5, f"Mean: {rt_data['rt_dev'].mean():.3f} min\n"
                          f"MAE: {rt_data['rt_dev'].abs().mean():.3f} min\nN: {len(rt_data)}", ha="center", va="center")

            elif metric == "PSM Score":
                gs = fig.add_gridspec(2, 2, width_ratios=[3, 1], height_ratios=[1, 3])
                ax_h = fig.add_subplot(gs[0, 0])
                ax_h.hist(target_df["psm_score"], bins=30, alpha=0.7, label="Target", color="skyblue")
                decoy_df = results_df[results_df["peptide"].str.startswith("DECOY_")]
                if not decoy_df.empty:
                    ax_h.hist(decoy_df["psm_score"], bins=30, alpha=0.7, label="Decoy", color="salmon")
                ax_h.legend(); ax_h.set_title("PSM Score"); ax_h.set_xlabel("Score")
                ax_b = fig.add_subplot(gs[1, 0])
                sns.boxplot(x="file", y="psm_score", data=target_df, ax=ax_b)
                ax_b.set_xticklabels(ax_b.get_xticklabels(), rotation=45, ha="right")
                ax_d = fig.add_subplot(gs[1, 1])
                sns.kdeplot(y=target_df["psm_score"], ax=ax_d, fill=True, color="skyblue", label="Target")
                if not decoy_df.empty:
                    sns.kdeplot(y=decoy_df["psm_score"], ax=ax_d, fill=True, color="salmon", alpha=0.5, label="Decoy")
                ax_d.legend()
                ax_s = fig.add_subplot(gs[0, 1]); ax_s.axis("off")
                txt = f"Target: {len(target_df)}\nMean: {target_df['psm_score'].mean():.4f}"
                if not decoy_df.empty:
                    ks, pv = stats.ks_2samp(target_df["psm_score"], decoy_df["psm_score"])
                    txt += f"\nDecoy: {len(decoy_df)}\nKS: {ks:.4f} (p={pv:.2e})"
                ax_s.text(0.5, 0.5, txt, ha="center", va="center", fontsize=9)

            elif metric == "RT Drift":
                # --- RT Drift visualization --------------------------------
                # Requires 'rt_drift_correction' and 'run_order' columns
                if "rt_drift_correction" not in results_df.columns or "run_order" not in results_df.columns:
                    messagebox.showinfo("No Data",
                        "RT drift correction was not applied for this analysis.\n"
                        "Enable it in Filters → RT Drift Correction and re-run.")
                    return
                drift_df = target_df.copy()
                drift_df["rt_drift_correction"] = pd.to_numeric(
                    drift_df["rt_drift_correction"], errors="coerce")
                drift_df["run_order"] = pd.to_numeric(
                    drift_df["run_order"], errors="coerce")
                # Drop rows with no correction (all-zero = correction not applied)
                drift_nonzero = drift_df[drift_df["rt_drift_correction"] != 0.0]
                if drift_nonzero.empty:
                    messagebox.showinfo("No Data",
                        "RT drift correction values are all zero — no drift was modeled.")
                    return

                # Per-file mean offset
                file_offsets = (
                    drift_nonzero.groupby(["file", "run_order"])
                    ["rt_drift_correction"].first()  # uniform per file
                    .reset_index()
                    .sort_values("run_order")
                )

                gs = fig.add_gridspec(2, 2, width_ratios=[3, 1], height_ratios=[1, 1])

                # Top-left: offset vs run order (scatter + line)
                ax1 = fig.add_subplot(gs[0, 0])
                ax1.bar(file_offsets["run_order"], file_offsets["rt_drift_correction"],
                        color="steelblue", alpha=0.8, edgecolor="black", linewidth=0.5)
                ax1.axhline(0, color="gray", linestyle="--", linewidth=0.8)
                ax1.set_xlabel("Run Order")
                ax1.set_ylabel("RT Offset (min)")
                ax1.set_title("Per-File RT Drift Offset vs. Run Order")

                # Top-right: statistics
                offsets = file_offsets["rt_drift_correction"].values
                ax_s = fig.add_subplot(gs[0, 1]); ax_s.axis("off")
                slope_txt = ""
                if len(offsets) >= 3:
                    try:
                        _sl, _ic = np.polyfit(file_offsets["run_order"].values,
                                              offsets, 1)
                        slope_txt = f"\nTrend: {_sl:+.4f} min/run"
                        # overlay trend line
                        x_fit = file_offsets["run_order"].values
                        ax1.plot(x_fit, _sl * x_fit + _ic, "r-", linewidth=1.5,
                                 label=f"Trend ({_sl:+.4f} min/run)")
                        ax1.legend(fontsize=8)
                    except Exception:
                        pass
                ax_s.text(0.5, 0.5,
                          f"Files: {len(offsets)}\n"
                          f"Mean offset: {np.mean(offsets):+.3f} min\n"
                          f"Median: {np.median(offsets):+.3f} min\n"
                          f"Std: {np.std(offsets):.3f} min\n"
                          f"Range: {np.ptp(offsets):.3f} min"
                          f"{slope_txt}",
                          ha="center", va="center", fontsize=10)

                # Bottom-left: before vs after RT accuracy distribution
                ax2 = fig.add_subplot(gs[1, 0])
                if "known_rt" in drift_df.columns and "known_rt_corrected" in drift_df.columns:
                    rt_obs = pd.to_numeric(drift_df["rt"], errors="coerce")
                    known_orig = pd.to_numeric(drift_df["known_rt"], errors="coerce")
                    known_corr = pd.to_numeric(drift_df["known_rt_corrected"], errors="coerce")
                    err_before = (rt_obs - known_orig).dropna().abs()
                    err_after = (rt_obs - known_corr).dropna().abs()
                    bins = np.linspace(0, max(err_before.quantile(0.99),
                                              err_after.quantile(0.99)), 40)
                    ax2.hist(err_before, bins=bins, alpha=0.6, color="salmon",
                             edgecolor="black", linewidth=0.3, label="Before correction")
                    ax2.hist(err_after, bins=bins, alpha=0.6, color="mediumseagreen",
                             edgecolor="black", linewidth=0.3, label="After correction")
                    ax2.set_xlabel("|RT error| (min)")
                    ax2.set_ylabel("Count")
                    ax2.set_title("RT Accuracy: Before vs After Drift Correction")
                    ax2.legend(fontsize=8)
                else:
                    ax2.text(0.5, 0.5, "known_rt / known_rt_corrected\ncolumns not available",
                             ha="center", va="center")
                    ax2.set_title("RT Accuracy Comparison")

                # Bottom-right: per-file boxplot of corrected RT accuracy
                ax3 = fig.add_subplot(gs[1, 1])
                rt_acc_data = pd.to_numeric(drift_nonzero["rt_accuracy"], errors="coerce").dropna()
                if not rt_acc_data.empty:
                    ax3.hist(rt_acc_data, bins=30, color="steelblue", alpha=0.7,
                             edgecolor="black", linewidth=0.3)
                    ax3.set_xlabel("RT Accuracy (min)")
                    ax3.set_ylabel("Count")
                    ax3.set_title("Post-Correction RT Accuracy")
                else:
                    ax3.text(0.5, 0.5, "No data", ha="center", va="center")

            elif metric == "Mass Drift":
                # --- Mass Drift visualization --------------------------------
                # Requires 'mass_drift_correction_ppm' and 'run_order' columns
                if "mass_drift_correction_ppm" not in results_df.columns:
                    messagebox.showinfo("No Data",
                        "Mass accuracy drift correction was not applied for this analysis.\n"
                        "Enable it in Filters → Mass Accuracy Drift Correction and re-run.")
                    return
                # Ensure run_order exists
                if "run_order" not in results_df.columns:
                    messagebox.showinfo("No Data",
                        "Run order information is missing.\n"
                        "Mass drift correction requires ≥3 data files.")
                    return

                drift_df = target_df.copy()
                drift_df["mass_drift_correction_ppm"] = pd.to_numeric(
                    drift_df["mass_drift_correction_ppm"], errors="coerce")
                drift_df["run_order"] = pd.to_numeric(
                    drift_df["run_order"], errors="coerce")

                drift_nonzero = drift_df[drift_df["mass_drift_correction_ppm"] != 0.0]
                if drift_nonzero.empty:
                    messagebox.showinfo("No Data",
                        "Mass drift correction values are all zero — no drift was modeled.")
                    return

                # Per-file ppm offset
                file_offsets = (
                    drift_nonzero.groupby(["file", "run_order"])
                    ["mass_drift_correction_ppm"].first()  # uniform per file
                    .reset_index()
                    .sort_values("run_order")
                )

                gs = fig.add_gridspec(2, 2, width_ratios=[3, 1], height_ratios=[1, 1])

                # Top-left: ppm offset vs run order (bar chart)
                ax1 = fig.add_subplot(gs[0, 0])
                ax1.bar(file_offsets["run_order"],
                        file_offsets["mass_drift_correction_ppm"],
                        color="darkorange", alpha=0.8, edgecolor="black",
                        linewidth=0.5)
                ax1.axhline(0, color="gray", linestyle="--", linewidth=0.8)
                ax1.set_xlabel("Run Order")
                ax1.set_ylabel("Mass Offset (ppm)")
                ax1.set_title("Per-File Mass Accuracy Drift vs. Run Order")

                # Top-right: statistics
                offsets = file_offsets["mass_drift_correction_ppm"].values
                ax_s = fig.add_subplot(gs[0, 1])
                ax_s.axis("off")
                slope_txt = ""
                if len(offsets) >= 3:
                    try:
                        _sl, _ic = np.polyfit(
                            file_offsets["run_order"].values, offsets, 1)
                        slope_txt = f"\nTrend: {_sl:+.4f} ppm/run"
                        x_fit = file_offsets["run_order"].values
                        ax1.plot(x_fit, _sl * x_fit + _ic, "r-",
                                 linewidth=1.5,
                                 label=f"Trend ({_sl:+.4f} ppm/run)")
                        ax1.legend(fontsize=8)
                    except Exception:
                        pass
                ax_s.text(0.5, 0.5,
                          f"Files: {len(offsets)}\n"
                          f"Mean offset: {np.mean(offsets):+.3f} ppm\n"
                          f"Median: {np.median(offsets):+.3f} ppm\n"
                          f"Std: {np.std(offsets):.3f} ppm\n"
                          f"Range: {np.ptp(offsets):.3f} ppm"
                          f"{slope_txt}",
                          ha="center", va="center", fontsize=10)

                # Bottom-left: before vs after mass accuracy distribution
                ax2 = fig.add_subplot(gs[1, 0])
                if "mass_accuracy_corrected" in drift_df.columns:
                    # Before: mass_accuracy + abs(correction) approximation
                    # The actual "before" is the corrected value + offset
                    # mass_accuracy is already the corrected value after the
                    # pipeline ran.  We reconstruct the original by adding
                    # back the per-file offset to the signed value.
                    ma_after = pd.to_numeric(
                        drift_df["mass_accuracy"], errors="coerce").dropna()
                    # For "before" we use mass_accuracy_signed + offset
                    signed = pd.to_numeric(
                        drift_df.get("mass_accuracy_signed",
                                     pd.Series(dtype=float)),
                        errors="coerce")
                    corr = drift_df["mass_drift_correction_ppm"]
                    if signed.notna().any() and corr.notna().any():
                        original_signed = signed + corr
                        ma_before = original_signed.abs().dropna()
                    else:
                        ma_before = ma_after  # fallback

                    bins = np.linspace(
                        0,
                        max(ma_before.quantile(0.99) if len(ma_before) > 0 else 1,
                            ma_after.quantile(0.99) if len(ma_after) > 0 else 1),
                        40)
                    ax2.hist(ma_before, bins=bins, alpha=0.6,
                             color="salmon", edgecolor="black",
                             linewidth=0.3, label="Before correction")
                    ax2.hist(ma_after, bins=bins, alpha=0.6,
                             color="mediumseagreen", edgecolor="black",
                             linewidth=0.3, label="After correction")
                    ax2.set_xlabel("Mass Accuracy (ppm)")
                    ax2.set_ylabel("Count")
                    ax2.set_title(
                        "Mass Accuracy: Before vs After Drift Correction")
                    ax2.legend(fontsize=8)
                else:
                    # Fallback: just show current mass accuracy
                    ma = pd.to_numeric(
                        drift_nonzero["mass_accuracy"],
                        errors="coerce").dropna()
                    if not ma.empty:
                        ax2.hist(ma, bins=30, color="darkorange",
                                 alpha=0.7, edgecolor="black",
                                 linewidth=0.3)
                    ax2.set_xlabel("Mass Accuracy (ppm)")
                    ax2.set_ylabel("Count")
                    ax2.set_title("Post-Correction Mass Accuracy")

                # Bottom-right: post-correction mass accuracy histogram
                ax3 = fig.add_subplot(gs[1, 1])
                ma_post = pd.to_numeric(
                    drift_nonzero["mass_accuracy"],
                    errors="coerce").dropna()
                if not ma_post.empty:
                    ax3.hist(ma_post, bins=30, color="darkorange",
                             alpha=0.7, edgecolor="black", linewidth=0.3)
                    ax3.set_xlabel("Mass Accuracy (ppm)")
                    ax3.set_ylabel("Count")
                    ax3.set_title("Post-Correction Mass Accuracy")
                else:
                    ax3.text(0.5, 0.5, "No data",
                             ha="center", va="center")

            fig.tight_layout()
            self._embed_figure(fig, self.qc_canvas_frame)

        except Exception as e:
            logging.error(f"QC plot error: {e}"); traceback.print_exc()
            messagebox.showerror("Error", f"Failed to generate QC plot: {e}")

    # --------------------------------------------------------------------- #
    # Multivariate Analysis
    # --------------------------------------------------------------------- #
    def _run_multivariate(self):
        if not self._check_loaded():
            return
        self._clear_canvas(self.mv_canvas_frame)

        try:
            from sklearn.preprocessing import StandardScaler
            from sklearn.decomposition import PCA
            import seaborn as sns
            import matplotlib.pyplot as plt
            from matplotlib.figure import Figure

            pep_df = _get_cached_excel_sheet(self.results_file, "Peptide Quantification")
            if pep_df.empty:
                messagebox.showwarning("No Data", "No peptide quantification data."); return

            int_cols = [c for c in pep_df.columns if "_intensity" in c]
            area_cols = [c for c in pep_df.columns if "_eic_area" in c]
            data_cols = int_cols or area_cols
            dtype = "Intensity" if int_cols else "EIC Area"
            if not data_cols:
                messagebox.showwarning("No Data", "No quantification columns found."); return

            samples = [c.split("_")[0] for c in data_cols]
            X = np.nan_to_num(pep_df[data_cols].values)
            pnames = pep_df["peptide"].values
            normalize = self.mv_normalize_var.get()
            if normalize:
                X = StandardScaler().fit_transform(np.log1p(X))

            fig = Figure(figsize=(10, 8), dpi=100)
            atype = self.mv_type_var.get()

            if atype == "PCA":
                pca = PCA(n_components=min(3, *X.shape))
                res = pca.fit_transform(X)
                ax = fig.add_subplot(111)
                ax.scatter(res[:, 0], res[:, 1], s=50, alpha=0.7)
                for i, p in enumerate(pnames):
                    ax.annotate(p, (res[i, 0], res[i, 1]), fontsize=8, alpha=0.7)
                ev = pca.explained_variance_ratio_
                ax.set_xlabel(f"PC1 ({ev[0]:.1%})"); ax.set_ylabel(f"PC2 ({ev[1]:.1%})")
                ax.set_title(f"PCA of {dtype}" + (" (Norm)" if normalize else "")); ax.grid(True, alpha=0.3)
            elif atype == "Hierarchical Clustering":
                Z = hierarchy.linkage(X, method="ward")
                ax = fig.add_subplot(111)
                hierarchy.dendrogram(Z, labels=pnames, leaf_font_size=8, ax=ax,
                                     color_threshold=0.7 * max(Z[:, 2]))
                ax.set_title(f"Clustering by {dtype}"); plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
            elif atype == "Heatmap":
                hm = pd.DataFrame(X, index=pnames, columns=samples)
                ax = fig.add_subplot(111)
                sns.heatmap(hm, cmap="viridis", ax=ax, xticklabels=True, yticklabels=True)
                ax.set_title(f"Heatmap of {dtype}"); plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

            fig.tight_layout()
            self._embed_figure(fig, self.mv_canvas_frame)

        except Exception as e:
            logging.error(f"Multivariate error: {e}"); traceback.print_exc()
            messagebox.showerror("Error", f"Failed: {e}")

    # --------------------------------------------------------------------- #
    # Machine Learning
    # --------------------------------------------------------------------- #
    def _train_ml_model(self):
        if not self._check_loaded():
            return
        for w in self.ml_results_frame.winfo_children():
            w.destroy()

        try:
            from sklearn.preprocessing import StandardScaler
            from sklearn.decomposition import PCA
            from sklearn.cluster import KMeans
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.model_selection import train_test_split, cross_val_score
            from sklearn.metrics import accuracy_score, classification_report, silhouette_score
            from matplotlib.figure import Figure

            pep_df = _get_cached_excel_sheet(self.results_file, "Peptide Quantification")
            if pep_df.empty:
                messagebox.showwarning("No Data", "No peptide quantification data."); return

            int_cols = [c for c in pep_df.columns if "_intensity" in c]
            area_cols = [c for c in pep_df.columns if "_eic_area" in c]
            data_cols = int_cols or area_cols
            dtype = "Intensity" if int_cols else "EIC Area"
            if not data_cols:
                messagebox.showwarning("No Data", "No quantification columns."); return

            samples = [c.split("_")[0] for c in data_cols]
            X = np.nan_to_num(pep_df[data_cols].values)
            pnames = pep_df["peptide"].values
            if X.shape[0] < 10:
                messagebox.showwarning("Insufficient Data", f"Need >= 10 peptides. Got {X.shape[0]}."); return

            tw = scrolledtext.ScrolledText(self.ml_results_frame, wrap=tk.WORD, height=15)
            tw.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            tw.tag_configure("title", font=("Arial", 12, "bold"))
            tw.tag_configure("sub", font=("Arial", 10, "bold"))

            model_type = self.ml_model_var.get()
            test_size = self.ml_test_size_var.get() / 100

            tw.insert(tk.END, f"ML Analysis: {model_type}\n\n", "title")
            tw.insert(tk.END, f"Data: {dtype}, {X.shape[0]} peptides, {X.shape[1]} samples\n\n")

            if model_type == "Random Forest":
                def extract_group(fn):
                    for i, c in enumerate(fn):
                        if c == "_" or c.isdigit():
                            return fn[:i]
                    return fn
                groups = [extract_group(n) for n in samples]
                ugroups = list(set(groups))
                if len(ugroups) < 2:
                    tw.insert(tk.END, "Need >= 2 sample groups for RF.\n"); return
                y = np.array([ugroups.index(g) for g in groups])
                Xt = X.T
                try:
                    Xtr, Xte, ytr, yte = train_test_split(Xt, y, test_size=test_size, random_state=42, stratify=y)
                except ValueError:
                    Xtr, Xte, ytr, yte = train_test_split(Xt, y, test_size=test_size, random_state=42)
                clf = RandomForestClassifier(n_estimators=100, random_state=42)
                clf.fit(Xtr, ytr)
                ypred = clf.predict(Xte)
                tw.insert(tk.END, f"Accuracy: {accuracy_score(yte, ypred):.2%}\n\n", "sub")
                fi = clf.feature_importances_
                tw.insert(tk.END, "Top 10 Important Peptides:\n", "sub")
                for rank, idx in enumerate(np.argsort(fi)[::-1][:10]):
                    tw.insert(tk.END, f"  {rank+1}. {pnames[idx]}: {fi[idx]:.4f}\n")
                cv = cross_val_score(clf, Xt, y, cv=min(5, len(ugroups)))
                tw.insert(tk.END, f"\nCV Accuracy: {cv.mean():.2%}\n")

            elif model_type == "K-Means Clustering":
                Xs = StandardScaler().fit_transform(X)
                max_k = min(10, X.shape[0] - 1)
                sil = [silhouette_score(Xs, KMeans(k, random_state=42, n_init=10).fit_predict(Xs))
                       for k in range(2, max_k + 1)]
                opt_k = 2 + sil.index(max(sil))
                labels = KMeans(opt_k, random_state=42, n_init=10).fit_predict(Xs)
                tw.insert(tk.END, f"Optimal k={opt_k}, Silhouette={max(sil):.4f}\n\n", "sub")
                for cid in range(opt_k):
                    members = [pnames[i] for i, l in enumerate(labels) if l == cid]
                    tw.insert(tk.END, f"Cluster {cid+1}: {len(members)} peptides\n")
                    tw.insert(tk.END, f"  {', '.join(members[:8])}")
                    if len(members) > 8:
                        tw.insert(tk.END, f" ... +{len(members)-8} more")
                    tw.insert(tk.END, "\n")

                # PCA scatter
                fig = Figure(figsize=(8, 5), dpi=100)
                ax = fig.add_subplot(111)
                pca = PCA(n_components=2)
                Xp = pca.fit_transform(Xs)
                for cid in range(opt_k):
                    pts = Xp[labels == cid]
                    ax.scatter(pts[:, 0], pts[:, 1], label=f"Cluster {cid+1}", alpha=0.7)
                ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]:.1%})")
                ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]:.1%})")
                ax.set_title("K-Means Clusters (PCA)"); ax.legend()
                fig.tight_layout()

                cf = ttk.Frame(self.ml_results_frame)
                cf.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
                self._embed_figure(fig, cf)

        except Exception as e:
            logging.error(f"ML error: {e}"); traceback.print_exc()
            messagebox.showerror("Error", f"Failed: {e}")


# ============================================================================
# Entry point
# ============================================================================
def main():
    results_file = sys.argv[1] if len(sys.argv) > 1 else None
    mzml_folder = sys.argv[2] if len(sys.argv) > 2 else None
    root = tk.Tk()

    def _resolve_app_icon_path():
        base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, 'icon.ico')

    def _load_splash_icon_image(icon_path, size=88):
        if not icon_path or not os.path.exists(icon_path):
            return None

        try:
            from PIL import Image, ImageTk
            img = Image.open(icon_path).convert('RGBA').resize((size, size), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            pass

        try:
            return tk.PhotoImage(file=icon_path)
        except Exception:
            return None

    def _show_startup_splash(root_window, icon_path):
        splash = tk.Toplevel(root_window)
        splash.overrideredirect(True)
        splash.attributes('-topmost', True)
        splash.configure(bg='#e5e7eb')

        width, height = 480, 300
        screen_w = splash.winfo_screenwidth()
        screen_h = splash.winfo_screenheight()
        x = int((screen_w - width) / 2)
        y = int((screen_h - height) / 2)
        splash.geometry(f"{width}x{height}+{x}+{y}")

        card = tk.Frame(splash, bg='white', bd=1, relief='solid')
        card.place(relx=0.5, rely=0.5, anchor='center', width=468, height=288)

        icon_img = _load_splash_icon_image(icon_path, size=88)
        if icon_img is not None:
            splash._icon_img = icon_img
            tk.Label(card, image=icon_img, bg='white').pack(pady=(22, 8))
        else:
            tk.Label(card, text='ProteoPRM', bg='white', fg='#2e7d32',
                     font=('Segoe UI', 16, 'bold')).pack(pady=(28, 8))

        tk.Label(
            card,
            text='ProteoPRM Results Viewer',
            bg='white',
            fg='#111827',
            font=('Segoe UI', 21, 'bold')
        ).pack()

        tk.Label(
            card,
            text='Inspect, visualize, and re-integrate PRM results',
            bg='white',
            fg='#374151',
            font=('Segoe UI', 10)
        ).pack(pady=(4, 2))

        tk.Label(
            card,
            text='Loading interface...',
            bg='white',
            fg='#6b7280',
            font=('Segoe UI', 10)
        ).pack(pady=(10, 10))

        progress = ttk.Progressbar(card, mode='indeterminate', length=320)
        progress.pack()
        progress.start(12)

        splash.update_idletasks()
        splash.update()
        return splash, progress

    app_icon_path = _resolve_app_icon_path()
    startup_splash = None
    startup_splash_progress = None

    try:
        root.withdraw()
        startup_splash, startup_splash_progress = _show_startup_splash(root, app_icon_path)
    except Exception:
        startup_splash = None
        startup_splash_progress = None

    try:
        import ctypes
        # Ensure Windows correctly groups the taskbar icon instead of using the default python icon
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("proteoprm.results_viewer.app.1.0")
    except Exception:
        pass

    # Set the window/taskbar icon if running from bundled executable or source repo
    try:
        if os.path.exists(app_icon_path):
            root.iconbitmap(app_icon_path)
            try:
                # Register as Tk default so future Toplevel windows inherit it.
                root.iconbitmap(default=app_icon_path)
            except TypeError:
                pass
    except Exception:
        pass

    ResultsViewer(root, results_file=results_file, mzml_folder=mzml_folder)

    try:
        if startup_splash_progress is not None:
            startup_splash_progress.stop()
        if startup_splash is not None and startup_splash.winfo_exists():
            startup_splash.destroy()
    except Exception:
        pass

    root.deiconify()
    root.lift()
    try:
        root.focus_force()
    except Exception:
        pass

    root.mainloop()


if __name__ == "__main__":
    main()
