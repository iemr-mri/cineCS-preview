"""Iterative compressed-sensing reconstruction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from cine_preview.reconstruction.kspace import fft2c, ifft2c


@dataclass(frozen=True)
class CSConfig:
    """Configuration for iterative CS reconstruction.

    Attributes:
        max_iterations:        Maximum number of CS iterations.
        percentile_threshold:  Percentile used to set the soft-threshold value on
                               the first iteration (0–100).  Default 50 matches both
                               MATLAB CINE originals (CS_percentThresh = 50).
                               TPM uses 75 (``PC_CS_tempFFT_..._190402.m``).
        convergence_threshold: Stop when |Δrms / Δrms_iter1| drops below this
                               fraction.  Default 0.01 (1 %) matches the CINE
                               originals; TPM uses 0.001 (10× tighter).
    """

    max_iterations: int = 50
    percentile_threshold: float = 50.0
    convergence_threshold: float = 0.01


def reconstruct_cs(
    kspace: npt.NDArray[Any],
    config: CSConfig = CSConfig(),
    *,
    frame_axis: int = 3,
    extra_pool_axes: tuple[int, ...] = (),
) -> npt.NDArray[Any]:
    """Iterative compressed-sensing reconstruction.

    Translates reconstructCS.m / CSreconstructor.m (CINE) and generalises to
    cover TPM's joint-sparsity-across-venc variant (PC_CS_tempFFT_..._190402.m).

    Algorithm, looped over each outer-axis index combination:
      1. IFFT to image space for all frames (and venc, if pooled).
      2. Temporal FFT along ``frame_axis`` → soft-threshold → IFFT.
      3. Restore originally acquired k-space lines (data consistency).
      4. Repeat until convergence or ``max_iterations``.

    The soft-threshold value is set once on iteration 1 from the magnitude
    percentile over the spatial axes + ``frame_axis`` + ``extra_pool_axes``.
    For TPM, passing ``extra_pool_axes=(venc_axis,)`` causes the threshold
    pool to span ``(x, y, frame, venc)`` jointly — exploiting the high
    correlation between the 4/9 venc encodings of the same anatomy.

    Args:
        kspace:           Complex array with the spatial axes at positions
                          0 and 1; zero at unsampled phase-encode lines.
                          CINE shape: [x, y, slices, frames, coils].
                          TPM shape:  [x, y, slices, frames, venc, coils]
                          (pass ``extra_pool_axes=(4,)``).
        config:           CS hyperparameters.
        frame_axis:       Axis to apply the temporal FFT/IFFT along.
        extra_pool_axes:  Additional axes (besides spatial and ``frame_axis``)
                          to include in the magnitude-percentile pool.
                          Empty for CINE; ``(venc_axis,)`` for TPM.

    Returns:
        Reconstructed k-space with the same shape as the input.
    """
    if frame_axis in (0, 1):
        raise ValueError("frame_axis cannot be a spatial axis (0 or 1).")
    if any(ax in (0, 1, frame_axis) for ax in extra_pool_axes):
        raise ValueError(
            "extra_pool_axes must not overlap with spatial axes or frame_axis."
        )
    if len(set(extra_pool_axes)) != len(extra_pool_axes):
        raise ValueError("extra_pool_axes must be unique.")

    pool_axes = {0, 1, frame_axis, *extra_pool_axes}
    outer_axes = tuple(ax for ax in range(kspace.ndim) if ax not in pool_axes)
    outer_shape = tuple(kspace.shape[ax] for ax in outer_axes)

    us_mask = kspace != 0
    no_data_mask = ~us_mask
    kspace_cs: npt.NDArray[Any] = np.zeros_like(kspace)

    for outer_idx in np.ndindex(*outer_shape) if outer_shape else [()]:
        sel: list[Any] = [slice(None)] * kspace.ndim
        for ax, value in zip(outer_axes, outer_idx):
            sel[ax] = value
        sel_tuple = tuple(sel)
        sub_frame_axis = frame_axis - sum(1 for ax in outer_axes if ax < frame_axis)

        kspace_sub = kspace[sel_tuple]
        mask_sub = us_mask[sel_tuple]
        no_data_sub = no_data_mask[sel_tuple]

        # Initialise image-space series via IFFT on the spatial axes.
        im_temp: npt.NDArray[Any] = ifft2c(kspace_sub)

        thresh_val = 0.0
        diff_rms = np.zeros(config.max_iterations)

        for iteration in range(config.max_iterations):
            kspace_temporal: npt.NDArray[Any] = np.fft.fft(im_temp, axis=sub_frame_axis)

            # First iteration: percentile across the whole sub-array
            # (spatial + frame + any extra-pool axes).
            if iteration == 0:
                thresh_val = float(
                    np.percentile(np.abs(kspace_temporal), config.percentile_threshold)
                )

            kspace_temporal = _soft_thresh(kspace_temporal, thresh_val)
            im_temp = np.fft.ifft(kspace_temporal, axis=sub_frame_axis)

            kspace_after = fft2c(im_temp) * mask_sub
            diff = kspace_sub - kspace_after
            selected = diff[mask_sub]
            diff_rms[iteration] = float(np.sqrt(np.mean(np.abs(selected) ** 2)))

            adjusted = kspace_sub + fft2c(im_temp) * no_data_sub
            im_temp = ifft2c(adjusted)

            if iteration > 0:
                diff_current = diff_rms[iteration] - diff_rms[iteration - 1]
                diff_first = diff_rms[1] - diff_rms[0]
                ratio = abs(diff_current / diff_first) if diff_first != 0 else 1.0
                if ratio < config.convergence_threshold:
                    break

        kspace_cs[sel_tuple] = fft2c(im_temp)

    return kspace_cs


def _soft_thresh(x: npt.NDArray[Any], threshold: float) -> npt.NDArray[Any]:
    """Complex soft thresholding.

    Reduces magnitude by threshold; preserves phase.  Values with magnitude
    ≤ threshold are zeroed.  Matches SoftThresh.m / softThresh in CSreconstructor.m.
    """
    magnitude = np.abs(x)
    # Avoid 0/0 by substituting 1.0 where the condition is False (scale will be 0 there anyway).
    safe_magnitude: npt.NDArray[Any] = np.where(magnitude > threshold, magnitude, 1.0)
    scale: npt.NDArray[Any] = np.where(
        magnitude > threshold, (magnitude - threshold) / safe_magnitude, 0.0
    )
    result: npt.NDArray[Any] = x * scale
    return result
