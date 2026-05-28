"""Reconstruct one CINE scan from raw Bruker data into magnitude images.

Stripped-down version of the ieMR-toolbox CINE pipeline — no DICOM write,
no geometry corrections, no caching. Returns a real magnitude image stack
[x, y, slices, frames] suitable for on-scanner visual QC.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import numpy.typing as npt

from cine_preview.bruker.params import read_param_string
from cine_preview.bruker.reader import load_scan
from cine_preview.reconstruction.coil_combination import combine_coils
from cine_preview.reconstruction.compressed_sensing import reconstruct_cs
from cine_preview.reconstruction.kspace import sort_kspace, zero_fill_kspace


# Cine SAX sequence keyword. The on-scanner CS sequence is named
# ``segFLASH_CS_*``; we filter scans by substring match on ACQ_scan_name.
CINE_SAX_KEYWORD = "segFLASH"


def is_cine_sax_scan(scan_dir: Path) -> bool:
    """Return True if the scan's ACQ_scan_name marks it as a CINE SAX acquisition.

    Reads only the ACQ_scan_name field from acqp (cheap — no method file,
    no raw binary) so this can be called for every scan in a subject folder
    without slowing the listing.
    """
    acqp_path = scan_dir / "acqp"
    if not acqp_path.exists():
        return False
    try:
        name = read_param_string(acqp_path, "ACQ_scan_name") or ""
    except OSError:
        return False
    return CINE_SAX_KEYWORD.lower() in name.lower()


def scan_label(scan_dir: Path) -> str:
    """Return a short ``"<number>: <ACQ_scan_name>"`` label for a scan dir."""
    acqp_path = scan_dir / "acqp"
    try:
        name = read_param_string(acqp_path, "ACQ_scan_name") or "?"
    except OSError:
        name = "?"
    return f"{scan_dir.name}: {name}"


def reconstruct_scan(scan_dir: Path) -> npt.NDArray[np.float64]:
    """Run sort + CS recon + coil combine on one scan directory.

    Returns:
        Real magnitude image stack with shape ``[x, y, slices, frames]``.
    """
    scan = load_scan(scan_dir)

    kspace = sort_kspace(scan)
    # CINE has a single flow-encoding direction; squeeze it.
    kspace = kspace[:, :, :, :, 0, :]

    if "CSPhaseEncList" in scan.method:
        kspace = reconstruct_cs(kspace)

    kspace = zero_fill_kspace(kspace)
    images: npt.NDArray[np.float64] = combine_coils(kspace).astype(np.float64)
    return images
