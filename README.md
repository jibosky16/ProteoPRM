# ProteoPRM
ProteoPRM is an automated Python GUI for targeted PRM proteomics analysis. It eliminates manual transition curation and incorporates machine learning rescoring and probabilistic deconvolution of chimeric spectra, delivering high-throughput, reproducible PRM quantification that matches industry standards like Skyline

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
| **Spectral prediction** | **MS2PIP** (HCD/CID models) and **AlphaPeptDeep** (instrument- & NCE-aware deep-learning models) for predicted fragment intensities |
| **PSM scoring** | Mokapot Percolator-style SVM rescoring with automatic fallback to target-decoy FDR when discrimination is insufficient |
| **Quantification** | EIC area integration of fragments |
| **Protein rollup** | Summation of peptide intensities |
| **Results Viewer** | Standalone interactive viewer with mirror plots, EIC traces, hierarchical clustering, and re-integration without reprocessing |
| **Utilities** | PRM Inclusion List Generator (from Proteome Discoverer exports), RT predictor, spectral QC viewer, peptide fragmentation calculator |
| **Output** | CSV exports |

---

## System Requirements

| No strict system requirements |

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
git clone https://github.com/<your-username>/ProteoPRM.git
cd ProteoPRM

# 2. Create and activate a virtual environment (Python 3.11 recommended)
python -m venv venv311
venv311\Scripts\activate

# 3. Install dependencies
pip install -r [requirements.txt](http://_vscodecontentref_/0)

# 4. Launch the application
python [ProteoPRM.py](http://_vscodecontentref_/1)
