# cine-preview

A small standalone GUI for on-scanner QC of CINE SAX (`segFLASH_CS`)
acquisitions. The operator has no native way to judge the image quality of
compressed-sensing CINE SAX scans at the scanner — this tool reconstructs
selected scans on demand and lets them browse the resulting movies.

This is a lightweight app ported and adjusted from the ieMR-toolbox on `https://github.com/iemr-mri/ieMR-toolbox`.

## Objectives

1. Launch a Qt GUI that lets the operator pick a **subject folder** (a
   Bruker ParaVision session containing one subdirectory per scan).
2. Auto-detect all **CINE SAX** scans in that folder by matching the
   `segFLASH` keyword in `ACQ_scan_name`.
3. Show the detected scans in a checklist; the operator picks one or more.
4. Run **sort + CS recon + coil combine** on each selected scan (no DICOM
   write, no caching — preview only).
5. Open a **preview screen** where the operator can:
   - Step / scrub through frames (with play/pause for cine playback).
   - Step / scrub through slices.
   - Step / scrub through the selected scans.
6. Provide a **"pick another subject"** button that returns to step 1, so the
   operator can repeat the workflow without closing the app.
7. Ship as a single double-clickable `.exe` via PyInstaller.

## Layout

```
export/
├── NOTES.md              ← this file
├── pyproject.toml        ← package metadata + runtime deps
├── cine-preview.spec     ← PyInstaller recipe
├── build-exe.ps1         ← one-command build → dist\cine-preview.exe
└── src/cine_preview/
    ├── __init__.py
    ├── __main__.py       ← entry point: python -m cine_preview / frozen exe
    ├── gui.py            ← PySide6 GUI (subject → scan-select → preview)
    ├── pipeline.py       ← reconstruct_scan() + scan detection
    ├── bruker/           ← Bruker JCAMP-DX + fid/job0 readers (copied)
    │   ├── __init__.py
    │   ├── params.py
    │   ├── raw.py
    │   ├── reader.py
    │   └── scan.py
    └── reconstruction/   ← sort → CS recon → coil combine (copied)
        ├── __init__.py
        ├── kspace.py
        ├── compressed_sensing.py
        └── coil_combination.py
```

The `bruker/` and `reconstruction/` packages are direct copies from
`ieMR-toolbox`, with imports rewritten from `iemr_toolbox.*` → `cine_preview.*`.
They are entirely self-contained — no DICOM, no config, no pipeline runners.

## What was deliberately left out

- **DICOM writer / geometry** (`dicom/`) — preview-only, never written.
- **Sort module** (`pipeline/sort.py`) — operator picks the subject directly,
  no copy-into-CINE-folder step.
- **Pipeline runner / cancellation / cache** — one-shot per scan; if a
  reconstruction fails it is reported in the log and the next scan continues.
- **`segFLASH` SG (self-gated) handling** — SG reconstruction lives in
  another project; CS-CINE only here. (`is_sg_scan` is not consulted because
  the operator workflow tells us they want SAX cine; if they pick an SG scan
  by mistake, recon errors are surfaced and reported.)
- **TPM / strain / other analyses** — out of scope.

## Building

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[build]"
.\build-exe.ps1
```

The resulting `dist\cine-preview.exe` is a single self-contained file —
no Python install required on the scanner workstation. Double-click to run.

## Source attribution

`bruker/` and `reconstruction/` are ports of legacy MATLAB code in
`MATLAB-legacy/` of the parent `ieMR-toolbox` repo (originally
`RawDataObject.m`, `kspaceSort.m`, `reconstructCS.m`, `combineCoils.m`).
See the docstrings in each module for the legacy file each function maps to.
