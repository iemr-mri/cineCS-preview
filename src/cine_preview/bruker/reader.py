"""load_scan factory — assembles a BrukerScan from a ParaVision scan directory.

Translates RawDataObject.m.  For parameter parsing see params.py;
for binary k-space reading see raw.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy.typing as npt

from cine_preview.bruker.params import parse_bruker_params
from cine_preview.bruker.raw import read_raw_data
from cine_preview.bruker.scan import BrukerScan

# Re-export so callers that import from cine_preview.bruker.reader keep working.
__all__ = ["load_scan", "is_sg_scan", "scan_plane", "parse_bruker_params", "read_raw_data"]


def load_scan(
    scan_dir: Path,
    precision: str = "double",
    specified_nrs: list[int] | None = None,
    specified_jobs: list[int] | None = None,
    read_raw: bool = True,
) -> BrukerScan:
    """Load a Bruker ParaVision scan directory into a BrukerScan.

    Equivalent to RawDataObject(path) in the MATLAB pipeline.

    Args:
        scan_dir:      Path to the scan directory (contains acqp, method, fid / rawdata.job*).
        precision:     "double" (default) or "single".  Controls float output dtype.
        specified_nrs: Subset of NR loops to read (1-indexed, pre-PV360 only).
        specified_jobs: Subset of job indices to read (0-indexed, PV360+ only).
        read_raw:      If False, skip binary data read (params only).

    Returns:
        Frozen BrukerScan.
    """
    scan_dir = Path(scan_dir)
    acqp = parse_bruker_params(scan_dir / "acqp")

    method: dict[str, Any] = {}
    method_path = scan_dir / "method"
    if method_path.exists():
        method = parse_bruker_params(method_path)

    visu: dict[str, Any] = {}
    visu_path = scan_dir / "pdata" / "1" / "visu_pars"
    if visu_path.exists():
        visu = parse_bruker_params(visu_path)

    reco: dict[str, Any] = {}
    reco_path = scan_dir / "pdata" / "1" / "reco"
    if reco_path.exists():
        reco = parse_bruker_params(reco_path)

    data: list[npt.NDArray[Any]] = []
    if read_raw:
        data = read_raw_data(
            acqp,
            scan_dir,
            precision=precision,
            specified_nrs=specified_nrs,
            specified_jobs=specified_jobs,
        )

    return BrukerScan(
        acqp=acqp, method=method, visu_pars=visu, reco=reco, data=data, scan_dir=scan_dir
    )


def is_sg_scan(scan: BrukerScan) -> bool:
    """Return True if the scan uses self-gating (no ECG trigger).

    Self-gated sequences write a MidlineRate parameter to the method file;
    ECG-gated sequences do not. This is the canonical identifier.
    """
    return "MidlineRate" in scan.method


def scan_plane(scan: BrukerScan) -> str:
    """Return the imaging plane: 'SAX', 'LAX', or 'other'.

    Checks ACQ_scan_name (case-insensitive) for plane substrings.  Replaces
    scanNameSplitter.m.  Lives in bruker/ because plane classification is
    useful outside the SG pipeline.

    Recognised SAX names: anything containing 'SAX' or 'segFLASH' (the AGORA
    project's segmented-FLASH SAX sequence — multiple single-slice scan dirs
    that together form one short-axis stack).
    """
    name: str = str(scan.acqp.get("ACQ_scan_name", "")).upper()
    if "SAX" in name or "SEGFLASH" in name:
        return "SAX"
    if "LAX" in name:
        return "LAX"
    return "other"
