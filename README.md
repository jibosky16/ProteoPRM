# ProteoPRM

ProteoPRM is an automated Python GUI for targeted PRM proteomics analysis. It eliminates manual transition curation and incorporates machine learning rescoring and probabilistic deconvolution of chimeric spectra, delivering high-throughput, reproducible PRM quantification that matches industry standards like Skyline.

> Current version: **1.0.0**

---

## Table of Contents

1. [Key Features](#key-features)
2. [System Requirements](#system-requirements)
3. [Installation](#installation)
   - [Standalone Executable](#standalone-executable)
   - [From Source](#from-source)
4. [Input Files](#input-files)
5. [Quick Start](#quick-start)
6. [Detailed Workflow](#detailed-workflow)
   - [1 · File Loading](#1--file-loading)
   - [2 · Analysis Settings](#2--analysis-settings)
   - [3 · Running Analysis](#3--running-analysis)
   - [4 · Results Viewer](#4--results-viewer)
7. [Built-in Tools](#built-in-tools)
   - [PRM Inclusion List Generator](#prm-inclusion-list-generator)
   - [RT Predictor](#rt-predictor)
   - [Spectral Prediction QC Viewer](#spectral-prediction-qc-viewer)
   - [Peptide Fragmentation Viewer](#peptide-fragmentation-viewer)
8. [Output Files](#output-files)
9. [Configuration & Settings](#configuration--settings)
10. [Dependencies](#dependencies)
11. [Building the Executable](#building-the-executable)
12. [License](#license)
13. [Citation](#citation)

---

## Key Features

| Category | Capability |
|---|---|
| **Raw data** | Thermo `.raw`, Sciex `.wiff`, Bruker `.d`, and `.mzML` — vendor files auto-converted via *ProteoWizard msconvert* |
| **Fragment matching** | b/y/a/x/c/z ions ± tolerance (Da or ppm); neutral-loss ions (phospho, deamidation, etc.); configurable m/z window |
| **Spectral prediction** | **MS2PIP** (HCD/CID XGBoost models) and **AlphaPeptDeep** (instrument- & NCE-aware deep-learning models) for predicted fragment intensities |
| **Chimeric deconvolution** | Probabilistic shared-ion deconvolution guided by predicted spectral libraries — correctly apportions intensity when isolation windows overlap |
| **PSM scoring** | Mokapot Percolator-style SVM rescoring with automatic fallback to target-decoy FDR when discrimination is insufficient |
| **Quantification** | Fragment-level EIC area integration with optional intensity-based quantification |
| **Protein rollup** | Summation of peptide-level quantities to protein level with FASTA-aware mapping |
| **Drift correction** | RT and mass-accuracy drift correction using reference peptides (direct offset or trend model) |
| **Results Viewer** | Standalone interactive viewer with mirror plots, EIC traces, hierarchical clustering, and re-integration without reprocessing |
| **Utilities** | PRM Inclusion List Generator, DeepLC/sklearn RT predictor, spectral QC viewer, peptide fragmentation calculator |
| **Output** | Folder-based CSV exports (PSM, peptide quantification, protein quantification, combined, QC metrics, EICs) |

---

## System Requirements

- **OS:** Windows 10/11 (native or WSL2). macOS/Linux supported when running from source.
- **Python:** 3.11 recommended (required for the full dependency stack).
- **RAM:** 8 GB minimum, 16 GB+ recommended for large datasets.
- **Disk:** ~2 GB for dependencies; additional space for raw files and results.
- **GPU (optional):** NVIDIA GPU with CUDA for accelerated AlphaPeptDeep predictions. CPU fallback is automatic.
- **ProteoWizard:** Required for automatic vendor raw file conversion. Install from [proteowizard.sourceforge.net](https://proteowizard.sourceforge.net) and ensure `msconvert` is on your system `PATH`.

---

## Installation

### Standalone Executable

1. Download the latest `ProteoPRM_v1.0.0.zip` from the [Releases](../../releases) page.
2. Extract to any folder.
3. Double-click **ProteoPRM.exe** to launch.

> **ProteoWizard** is required for automatic vendor raw file conversion. Install
> from [proteowizard.sourceforge.net](https://proteowizard.sourceforge.net) and
> ensure `msconvert` is discoverable on your system `PATH` (ProteoPRM will also
> scan common install locations automatically).

### From Source

```bash
# 1. Clone the repository
git clone https://github.com/jibosky16/ProteoPRM.git
cd ProteoPRM

# 2. Create and activate a virtual environment (Python 3.11 recommended)
py -3.11 -m venv venv311
.\venv311\Scripts\Activate.ps1       # Windows PowerShell
# source venv311/bin/activate        # macOS / Linux

# 3. Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Launch the application
python ProteoPRM.py
```

---

## Input Files

ProteoPRM requires two inputs:

| Input | Description |
|---|---|
| **PRM Input File** | Excel workbook (`.xlsx`) containing the target peptide list. Required columns: `Sequence`, `Modifications`, `m/z`, `z` (charge), `Start [min]`, `Stop [min]`, `Top Apex RT [min]`. The RT window columns define when to look for each peptide. |
| **Data Folder** | A folder containing mass spectrometry data files. Supported formats: Thermo `.raw`, Sciex `.wiff`, Bruker `.d`, or pre-converted `.mzML` files. Vendor files are automatically converted to mzML via ProteoWizard. |

Optional inputs:

| Input | Description |
|---|---|
| **FASTA file** | Protein sequence database for protein-level rollup, sequence coverage, and combined reporting. |
| **Output folder** | Destination for result files. If not specified, a subfolder is created next to the data folder. |

---

## Quick Start

1. Launch ProteoPRM.
2. Click **Browse** next to "PRM Input File" and select your target peptide Excel file.
3. Click **Browse** next to "Raw Files/mzML Folder" and select the folder containing your `.raw` or `.mzML` files.
4. Click **Browse** next to "Output Folder Location" and choose a folder where the results will be stored.
5. (Optional) Load a FASTA file for protein-level rollup.
6. Adjust tolerance settings if needed (defaults: 10 ppm precursor, 20 ppm fragment).
7. Click **Run** to start the analysis.
8. When complete, the **ProteoPRM Results Viewer** launches automatically.

---

## Detailed Workflow

### 1 · File Loading

- **PRM Input File:** Browse and select the Excel workbook containing your target peptide list with sequences, modifications, m/z values, charge states, and retention time windows.
- **Data Folder:** Select the folder with mass spectrometry files. ProteoPRM auto-detects vendor formats and converts them to mzML using ProteoWizard.
- **FASTA File (optional):** Provide a protein database for protein-level quantification.
- **Output Folder:** Choose where to save results. Defaults to a subfolder adjacent to your data.

### 2 · Analysis Settings

**Mass Tolerance**

| Parameter | Default | Options |
|---|---|---|
| Precursor tolerance | 10 | ppm or Da |
| Fragment tolerance | 20 | ppm or Da |
| Fragment m/z range | 50 – 5000 | Lower and upper bounds |

**Fragmentation Type**

Supported types: `HCD`, `CID`, `ETD`, `EThcD`, `UVPD`, `HCD+ETD`, `CID+ETD`, `HCD+UVPD`.

**FDR Threshold**

Default: 1%. Applied via Mokapot q-values (or target-decoy competition as fallback).

**Quantification Method**

- **Area** — EIC area integration (recommended)
- **Intensity** — summed fragment intensities
- **Both** — reports both metrics

**Fragment Usage**

| Mode | Description |
|---|---|
| **All** | Use all matched fragments for quantification |
| **Unique (Quant)** | Use unique (non-shared) fragments for quantification only |
| **Unique (ID and Quant)** | Use unique fragments for both identification scoring and quantification |
| **Probabilistic (Deconv)** | Shared fragments are split probabilistically between co-eluting peptides using predicted spectral libraries from MS2PIP or AlphaPeptDeep |

**Spectral Prediction Engine** (for probabilistic mode)

- **MS2PIP** — XGBoost-based models (HCDch2, CIDch2). Fast, no GPU required.
- **AlphaPeptDeep** — Deep-learning models with instrument-specific and NCE-aware predictions. Supports calibration via MGF/PSM files exported from Proteome Discoverer. Optional GPU acceleration.

**Neutral Losses**

Configurable neutral losses: H₂O, NH₃, H₃PO₄, CH₃SOH, and extended series for multiply-modified peptides.

**Drift Correction**

- **RT drift:** Correct retention time shifts across runs using reference peptides.
- **Mass drift:** Correct mass accuracy drift using reference peptides. Models: direct offset or trend model.

### 3 · Running Analysis

Click **Run** to start. The analysis proceeds through these stages:

1. **Peptide loading** — reads the target list and generates decoy peptides
2. **Fragment index pre-computation** — builds theoretical fragment ions for all targets
3. **Spectral prediction** (if probabilistic mode) — pre-computes predicted intensities for all peptides via MS2PIP or AlphaPeptDeep
4. **File processing** — concurrent extraction of MS2 spectra, fragment matching, and EIC computation for each raw file
5. **Post-processing** — feature calculation, spurious PSM filtering, Mokapot rescoring, FDR control
6. **Quantification** — peptide-level and protein-level aggregation
7. **Export** — CSV files written to the output folder

Progress is displayed in the log panel. Processing uses multi-threaded file handling with automatic batch sizing based on available RAM.

### 4 · Results Viewer

After a successful run, the **ProteoPRM Results Viewer** launches automatically. It is a standalone application that loads the results folder and provides:

- **Mirror plots** — observed vs predicted (MS2PIP/AlphaPeptDeep) fragment spectra
- **EIC traces** — extracted ion chromatograms for individual fragments
- **Hierarchical clustering** — heatmaps and dendrograms for replicate comparison
- **Re-integration** — adjust integration parameters and recalculate quantities from cached EIC data without reprocessing raw files
- **CSV export** — export filtered results directly from the viewer

---

## Built-in Tools

Access built-in tools via the **Tools** menu.

### PRM Inclusion List Generator

Converts a **Proteome Discoverer PeptideGroups export** into a filtered PRM inclusion list ready for instrument methods.

**Filters:**

- Confidence level (High / Medium / Low / Any)
- Charge states (2+, 3+, 4+, 5+)
- m/z range
- Peptide length (min / max)
- Missed cleavages
- PSM count and XCorr thresholds
- q-value threshold
- Unique peptides only
- Exclude modifications, Met/Cys/Trp-containing peptides, N-terminal Gln
- Exclude acid-labile motifs (DP, DG) and deamidation-prone motifs (NG, QG)

**Protein Accession Filtering:**

- Enter comma-separated protein accessions
- Or upload a FASTA file to filter by all proteins in the database
- Only peptides from matched proteins in the input data are returned

**Output:**

- Configurable RT window (± minutes around apex RT)
- Max peptides per protein and total peptide limit
- Export as instrument-ready CSV or full table with all metadata

### RT Predictor

Predicts retention times for target peptides using machine learning models trained on your own data.

**Two prediction engines:**

- **sklearn** — HistGradientBoosting or GradientBoosting on ~150 hand-crafted amino acid composition and physicochemical features. Fast, no additional dependencies.
- **DeepLC** — Deep-learning transfer learning from pre-trained models with user-data calibration. Requires the `deeplc` package.
- **AlphaPeptDeep** — Deep-learning transfer learning from pre-trained models with user-data calibration. Requires the `PeptDeep` package.

**Workflow:**

1. Load a training dataset (Proteome Discoverer PeptideGroups export with RT information)
2. Load peptides to predict (CSV/Excel with Sequence column)
3. Train and predict — the model learns from your LC setup and predicts RTs for new peptides
4. Export predictions directly to the PRM Inclusion List Generator format

### Spectral Prediction QC Viewer

Compare predicted (MS2PIP or AlphaPeptDeep) vs experimental fragment spectra from a completed analysis.

- **PSM Spectral Angles tab** — table of per-PSM spectral angle scores with interactive mirror plots (observed vs predicted)
- **SA Distribution tab** — histogram of spectral angle distributions across the dataset
- **Export** — save spectral angle scores to CSV

> Requires running the analysis with **Probabilistic (Deconv)** fragment usage mode to generate spectral angle scores.

### Peptide Fragmentation Viewer

Interactive theoretical fragment ion calculator for method development and troubleshooting.

- **Single peptide mode** — enter a peptide sequence and modifications to view all theoretical fragment ions
- **Bulk mode** — load an Excel/CSV file to process multiple peptides
- **Fragmentation types** — HCD, CID, ETD, EThcD, UVPD
- **Ion charges** — 1+, 2+, 3+
- **Neutral losses** — H₂O, NH₃, and extended neutral loss series
- **Predicted spectrum** — when MS2PIP is available, view and export the predicted MS2 spectrum (CSV and PNG)

---

## Output Files

All results are saved as CSV files in the specified output folder:

| File | Description |
|---|---|
| `PSM.csv` | All peptide-spectrum matches passing FDR threshold. Includes peptide sequence, modifications, charge, m/z, RT, mass accuracy, matched fragments, PSM score, Mokapot q-value/PEP, spectral angle, and per-file quantification values. |
| `Peptide_Quantification.csv` | Peptide-level quantification aggregated across scans. One row per peptide per file with area and/or intensity values. |
| `Protein_Quantification.csv` | Protein-level quantification. Peptide quantities summed to protein level using FASTA-derived mappings. |
| `Combined.csv` | Hierarchical protein → peptide layout combining protein and peptide quantification in a single wide-format table. |
| `QC_Metrics.csv` | Per-file quality control metrics: median mass error, RT shifts, identification rates, and other diagnostics. (Optional — toggle in Preferences.) |
| `EICs.csv` | Fragment-level extracted ion chromatogram data points for all matched ions across all scans. (Optional — toggle in Preferences.) |

---

## Configuration & Settings

### Save / Load Configuration

Use **File → Save Configuration** and **File → Load Configuration** to persist all analysis parameters as a JSON file. This includes:

- File paths (input, data folder, output, FASTA)
- All tolerance and threshold settings
- Fragmentation type and quantification method
- Fragment usage mode and prediction engine settings
- Neutral loss selections
- Drift correction parameters
- Preferences (output toggles, UI options)

### Preferences

Access via **Settings → Preferences**:

| Setting | Description |
|---|---|
| Include PSM sheet | Include `PSM.csv` in the output |
| Include EIC sheet | Include `EICs.csv` in the output |
| Include QC Metrics | Include `QC_Metrics.csv` in the output |
| Auto-scroll logs | Automatically scroll the log panel during analysis |
| Confirm overwrite | Prompt before overwriting existing results |
| Remember directories | Remember the last-used file paths between sessions |

### Chemical Modifications

Access via **Settings → Modifications Manager** to add, edit, or remove custom post-translational modifications used in fragment ion calculations.

---

## Dependencies

Core dependencies (see `requirements.txt` for pinned versions):

| Package | Purpose |
|---|---|
| `numpy`, `scipy`, `pandas` | Scientific computing and data handling |
| `scikit-learn` | Machine learning (RT prediction, feature engineering) |
| `pyteomics` | Mass spectrometry data parsing (mzML) |
| `mokapot` | Percolator-style SVM rescoring |
| `ms2pip` | XGBoost fragment intensity prediction |
| `peptdeep` | AlphaPeptDeep deep-learning spectral prediction |
| `psm-utils` | PSM data structures for ms2pip batch API |
| `deeplc` | Deep-learning retention time prediction (optional) |
| `matplotlib`, `seaborn` | Plotting and visualization |
| `openpyxl` | Excel file I/O |
| `sv-ttk` | Modern themed Tkinter widgets |
| `xgboost` | Gradient boosting (used by ms2pip) |
| `torch` | PyTorch backend (used by peptdeep/alphabase) |
| `tensorflow` | TensorFlow backend (used by DeepLC) |
| `tqdm` | Progress bars |
| `psutil` | System resource monitoring |
| `lxml` | XML parsing (Unimod modifications) |
| `pyinstaller` | Executable building |

---

## Building the Executable

ProteoPRM is packaged as a standalone executable using PyInstaller.

```bash
# Activate the virtual environment
.\venv311\Scripts\Activate.ps1

# Run the build script
python build.py
```

Build options:

| Flag | Description |
|---|---|
| `python build.py` | Build the full ProteoPRM Suite (main app + results viewer) |
| `python build.py --main-only` | Build only the main ProteoPRM application |
| `python build.py --viewer-only` | Build only the Results Viewer |
| `python build.py --no-zip` | Skip creating the distribution ZIP |
| `python build.py --check` | Verify the build environment without building |

The build output is placed in `dist/ProteoPRM_Suite/`. The PyInstaller `.spec` files bundle:

- Unimod modification database
- MS2PIP XGBoost model files
- AlphaPeptDeep pretrained models
- Trained RT prediction models
- Application icon and resources

---

## License

ProteoPRM is provided for academic and research use. See the repository for license details.

---

## Citation

If you use ProteoPRM in your research, please cite:

> Fowowe M, Onigbinde S, Daramola O, Adeniyi M and Mechref Y. ProteoPRM: An Automated GUI Tool for the Analysis and Quantification of Parallel Reaction Monitoring Proteomics Data.
> GitHub: [https://github.com/jibosky16/ProteoPRM](https://github.com/jibosky16/ProteoPRM)

---

## Acknowledgments

ProteoPRM integrates several open-source tools and libraries:

- **[Mokapot](https://github.com/wfondrie/mokapot)** — Percolator-style confidence estimation
- **[MS2PIP](https://github.com/compomics/ms2pip)** — XGBoost fragment intensity prediction
- **[AlphaPeptDeep / peptdeep](https://github.com/MannLabs/alphapeptdeep)** — Deep-learning spectral prediction
- **[DeepLC](https://github.com/compomics/DeepLC)** — Deep-learning retention time prediction
- **[ProteoWizard](https://proteowizard.sourceforge.net)** — Vendor raw file conversion
- **[Pyteomics](https://github.com/levitsky/pyteomics)** — Mass spectrometry data parsing
