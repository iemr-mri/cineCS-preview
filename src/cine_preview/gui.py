"""PySide6 GUI: pick subject → pick scans → reconstruct → browse.

Three stacked screens in one window:
  1. SubjectScreen   — file dialog + selected-path display.
  2. ScanSelectScreen — list of detected CINE SAX scans (multi-select).
  3. PreviewScreen   — slice / scan / frame navigation + play/pause.
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QStackedWidget,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from cine_preview.pipeline import is_cine_sax_scan, reconstruct_scan, scan_label


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class ReconstructedScan:
    """Result of reconstructing one scan — magnitude images plus a display label."""

    label: str
    images: npt.NDArray[np.float64]  # [x, y, slices, frames]


# ---------------------------------------------------------------------------
# Worker — runs reconstruction off the UI thread
# ---------------------------------------------------------------------------


class ReconstructionWorker(QThread):
    """Reconstructs a list of scans on a background thread.

    Emits ``progress(index, total, label)`` before each scan, ``scan_done``
    once a scan has been reconstructed, and ``finished_all`` (or
    ``failed``) at the end.
    """

    progress = Signal(int, int, str)
    scan_done = Signal(object)  # ReconstructedScan
    failed = Signal(str, str)   # scan label, error message
    finished_all = Signal()

    def __init__(self, scan_dirs: list[Path]) -> None:
        super().__init__()
        self._scan_dirs = scan_dirs

    def run(self) -> None:  # noqa: D401 — QThread override
        total = len(self._scan_dirs)
        for i, scan_dir in enumerate(self._scan_dirs):
            label = scan_label(scan_dir)
            self.progress.emit(i + 1, total, label)
            try:
                images = reconstruct_scan(scan_dir)
            except (ValueError, KeyError, IndexError, FileNotFoundError, OSError) as exc:
                self.failed.emit(label, f"{type(exc).__name__}: {exc}")
                continue
            self.scan_done.emit(ReconstructedScan(label=label, images=images))
        self.finished_all.emit()


# ---------------------------------------------------------------------------
# Screen 1 — Select subject folder
# ---------------------------------------------------------------------------


class SubjectScreen(QWidget):
    subject_chosen = Signal(Path)

    def __init__(self) -> None:
        super().__init__()
        self._subject_dir: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(16)

        title = QLabel("CINE SAX preview")
        title.setStyleSheet("font-size: 20pt; font-weight: bold;")
        layout.addWidget(title)

        layout.addWidget(QLabel(
            "Pick a subject folder containing Bruker scan directories.\n"
            "All CINE SAX (segFLASH_CS) scans inside will be detected."
        ))

        self._path_label = QLabel("(no folder selected)")
        self._path_label.setStyleSheet("color: gray; padding: 8px; border: 1px solid lightgray;")
        self._path_label.setWordWrap(True)
        layout.addWidget(self._path_label)

        button_row = QHBoxLayout()
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse)
        button_row.addWidget(browse_btn)

        self._next_btn = QPushButton("Find CINE SAX scans →")
        self._next_btn.setEnabled(False)
        self._next_btn.clicked.connect(self._emit_chosen)
        button_row.addWidget(self._next_btn)
        button_row.addStretch()
        layout.addLayout(button_row)

        layout.addStretch()

    def reset(self) -> None:
        self._subject_dir = None
        self._path_label.setText("(no folder selected)")
        self._path_label.setStyleSheet("color: gray; padding: 8px; border: 1px solid lightgray;")
        self._next_btn.setEnabled(False)

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Select subject folder")
        if not chosen:
            return
        self._subject_dir = Path(chosen)
        self._path_label.setText(str(self._subject_dir))
        self._path_label.setStyleSheet("padding: 8px; border: 1px solid #888;")
        self._next_btn.setEnabled(True)

    def _emit_chosen(self) -> None:
        if self._subject_dir is not None:
            self.subject_chosen.emit(self._subject_dir)


# ---------------------------------------------------------------------------
# Screen 2 — Select scans + reconstruct
# ---------------------------------------------------------------------------


class ScanSelectScreen(QWidget):
    back_requested = Signal()
    reconstruct_requested = Signal(list)  # list[Path]

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        self._title = QLabel("CINE SAX scans")
        self._title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        layout.addWidget(self._title)

        layout.addWidget(QLabel("Select one or more scans to reconstruct."))

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self._list, stretch=1)

        button_row = QHBoxLayout()
        back_btn = QPushButton("← Back")
        back_btn.clicked.connect(self.back_requested)
        button_row.addWidget(back_btn)
        button_row.addStretch()

        self._reconstruct_btn = QPushButton("Reconstruct selected →")
        self._reconstruct_btn.clicked.connect(self._emit_reconstruct)
        button_row.addWidget(self._reconstruct_btn)
        layout.addLayout(button_row)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setVisible(False)
        layout.addWidget(self._log)

    def populate(self, subject_dir: Path) -> None:
        self._title.setText(f"CINE SAX scans — {subject_dir.name}")
        self._list.clear()
        self._log.clear()
        self._log.setVisible(False)
        self._progress.setVisible(False)
        self._set_busy(False)

        scan_dirs = sorted(
            (d for d in subject_dir.iterdir() if d.is_dir()),
            key=lambda d: (len(d.name), d.name),
        )
        cine_dirs = [d for d in scan_dirs if is_cine_sax_scan(d)]
        if not cine_dirs:
            item = QListWidgetItem("(no segFLASH_CS scans found)")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            self._reconstruct_btn.setEnabled(False)
            return

        for scan_dir in cine_dirs:
            item = QListWidgetItem(scan_label(scan_dir))
            item.setData(Qt.ItemDataRole.UserRole, str(scan_dir))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._list.addItem(item)
        self._reconstruct_btn.setEnabled(True)

    def _emit_reconstruct(self) -> None:
        selected: list[Path] = []
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(Path(item.data(Qt.ItemDataRole.UserRole)))
        if not selected:
            QMessageBox.information(self, "No scans selected", "Tick at least one scan.")
            return

        self._set_busy(True)
        self._progress.setVisible(True)
        self._progress.setRange(0, len(selected))
        self._progress.setValue(0)
        self._log.setVisible(True)
        self._log.clear()

        self.reconstruct_requested.emit(selected)

    # ---- worker callbacks ----------------------------------------------------

    def show_progress(self, index: int, total: int, label: str) -> None:
        self._progress.setRange(0, total)
        self._progress.setValue(index - 1)
        self._log.append(f"[{index}/{total}] reconstructing {label}…")

    def show_failure(self, label: str, message: str) -> None:
        self._log.append(f"   FAILED ({label}): {message}")

    def reset_after_finish(self) -> None:
        self._progress.setValue(self._progress.maximum())
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._reconstruct_btn.setEnabled(not busy)


# ---------------------------------------------------------------------------
# Screen 3 — Browse reconstructed scans
# ---------------------------------------------------------------------------


class PreviewScreen(QWidget):
    return_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._scans: list[ReconstructedScan] = []
        self._scan_index = 0
        self._slice_index = 0
        self._frame_index = 0

        self._timer = QTimer(self)
        self._timer.setInterval(60)  # ~16 fps; tweakable below
        self._timer.timeout.connect(self._advance_frame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._header = QLabel("")
        self._header.setStyleSheet("font-size: 12pt; font-weight: bold;")
        layout.addWidget(self._header)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumSize(400, 400)
        self._image_label.setStyleSheet("background-color: black;")
        layout.addWidget(self._image_label, stretch=1)

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)

        # Slice slider
        slice_row = QHBoxLayout()
        slice_row.addWidget(QLabel("Slice"))
        self._slice_prev = QPushButton("◀")
        self._slice_prev.clicked.connect(lambda: self._step_slice(-1))
        slice_row.addWidget(self._slice_prev)
        self._slice_slider = QSlider(Qt.Orientation.Horizontal)
        self._slice_slider.valueChanged.connect(self._on_slice_changed)
        slice_row.addWidget(self._slice_slider, stretch=1)
        self._slice_next = QPushButton("▶")
        self._slice_next.clicked.connect(lambda: self._step_slice(1))
        slice_row.addWidget(self._slice_next)
        layout.addLayout(slice_row)

        # Scan slider
        scan_row = QHBoxLayout()
        scan_row.addWidget(QLabel("Scan"))
        self._scan_prev = QPushButton("◀")
        self._scan_prev.clicked.connect(lambda: self._step_scan(-1))
        scan_row.addWidget(self._scan_prev)
        self._scan_slider = QSlider(Qt.Orientation.Horizontal)
        self._scan_slider.valueChanged.connect(self._on_scan_changed)
        scan_row.addWidget(self._scan_slider, stretch=1)
        self._scan_next = QPushButton("▶")
        self._scan_next.clicked.connect(lambda: self._step_scan(1))
        scan_row.addWidget(self._scan_next)
        layout.addLayout(scan_row)

        # Frame slider + play/pause
        frame_row = QHBoxLayout()
        frame_row.addWidget(QLabel("Frame"))
        self._frame_prev = QPushButton("◀")
        self._frame_prev.clicked.connect(lambda: self._step_frame(-1))
        frame_row.addWidget(self._frame_prev)
        self._frame_slider = QSlider(Qt.Orientation.Horizontal)
        self._frame_slider.valueChanged.connect(self._on_frame_changed)
        frame_row.addWidget(self._frame_slider, stretch=1)
        self._frame_next = QPushButton("▶")
        self._frame_next.clicked.connect(lambda: self._step_frame(1))
        frame_row.addWidget(self._frame_next)

        self._play_btn = QPushButton()
        self._play_btn.setCheckable(True)
        self._play_btn.toggled.connect(self._toggle_play)
        self._update_play_icon()
        frame_row.addWidget(self._play_btn)
        layout.addLayout(frame_row)

        # Bottom row — return
        bottom = QHBoxLayout()
        bottom.addStretch()
        return_btn = QPushButton("⟲ Pick another subject")
        return_btn.clicked.connect(self._on_return)
        bottom.addWidget(return_btn)
        layout.addLayout(bottom)

    # ---- public API ----------------------------------------------------------

    def load_scans(self, scans: list[ReconstructedScan]) -> None:
        self._scans = scans
        self._scan_index = 0
        self._slice_index = 0
        self._frame_index = 0

        n_scans = len(scans)
        self._scan_slider.blockSignals(True)
        self._scan_slider.setRange(0, max(0, n_scans - 1))
        self._scan_slider.setValue(0)
        self._scan_slider.setEnabled(n_scans > 1)
        self._scan_slider.blockSignals(False)

        self._refresh_for_current_scan()

    # ---- slot helpers --------------------------------------------------------

    def _refresh_for_current_scan(self) -> None:
        if not self._scans:
            return
        scan = self._scans[self._scan_index]
        _, _, n_slices, n_frames = scan.images.shape

        self._slice_index = min(self._slice_index, n_slices - 1)
        self._frame_index = min(self._frame_index, n_frames - 1)

        self._slice_slider.blockSignals(True)
        self._slice_slider.setRange(0, max(0, n_slices - 1))
        self._slice_slider.setValue(self._slice_index)
        self._slice_slider.setEnabled(n_slices > 1)
        self._slice_slider.blockSignals(False)

        self._frame_slider.blockSignals(True)
        self._frame_slider.setRange(0, max(0, n_frames - 1))
        self._frame_slider.setValue(self._frame_index)
        self._frame_slider.setEnabled(n_frames > 1)
        self._frame_slider.blockSignals(False)

        self._update_view()

    def _on_scan_changed(self, value: int) -> None:
        self._scan_index = value
        self._refresh_for_current_scan()

    def _on_slice_changed(self, value: int) -> None:
        self._slice_index = value
        self._update_view()

    def _on_frame_changed(self, value: int) -> None:
        self._frame_index = value
        self._update_view()

    def _step_scan(self, delta: int) -> None:
        if not self._scans:
            return
        new_index = (self._scan_index + delta) % len(self._scans)
        self._scan_slider.setValue(new_index)

    def _step_slice(self, delta: int) -> None:
        if not self._scans:
            return
        n_slices = self._scans[self._scan_index].images.shape[2]
        if n_slices == 0:
            return
        self._slice_slider.setValue((self._slice_index + delta) % n_slices)

    def _step_frame(self, delta: int) -> None:
        if not self._scans:
            return
        n_frames = self._scans[self._scan_index].images.shape[3]
        if n_frames == 0:
            return
        self._frame_slider.setValue((self._frame_index + delta) % n_frames)

    def _advance_frame(self) -> None:
        self._step_frame(1)

    def _toggle_play(self, checked: bool) -> None:
        if checked:
            self._timer.start()
        else:
            self._timer.stop()
        self._update_play_icon()

    def _update_play_icon(self) -> None:
        style = self.style()
        if self._play_btn.isChecked():
            self._play_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            self._play_btn.setText(" Pause")
        else:
            self._play_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            self._play_btn.setText(" Play")

    def _on_return(self) -> None:
        if self._play_btn.isChecked():
            self._play_btn.setChecked(False)
        self.return_requested.emit()

    # ---- rendering -----------------------------------------------------------

    def _update_view(self) -> None:
        if not self._scans:
            return
        scan = self._scans[self._scan_index]
        nx, ny, n_slices, n_frames = scan.images.shape
        frame = scan.images[:, :, self._slice_index, self._frame_index]

        pixmap = _array_to_pixmap(frame)
        size = self._image_label.size()
        scaled = pixmap.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)

        self._header.setText(scan.label)
        self._status.setText(
            f"slice {self._slice_index + 1}/{n_slices}   "
            f"frame {self._frame_index + 1}/{n_frames}   "
            f"({nx}×{ny})"
        )

    def resizeEvent(self, event) -> None:  # noqa: D401, N802 — Qt override
        super().resizeEvent(event)
        self._update_view()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _array_to_pixmap(frame: npt.NDArray[np.float64]) -> QPixmap:
    """Convert a 2D float frame to an 8-bit grayscale QPixmap.

    Each frame is normalised independently — fine for QC where absolute
    intensity is not the question.
    """
    arr = np.asarray(frame, dtype=np.float64)
    lo = float(arr.min())
    hi = float(arr.max())
    if hi > lo:
        norm = (arr - lo) / (hi - lo)
    else:
        norm = np.zeros_like(arr)
    buf = np.ascontiguousarray((norm * 255.0).clip(0, 255).astype(np.uint8))
    height, width = buf.shape
    qimage = QImage(buf.data, width, height, width, QImage.Format.Format_Grayscale8)
    # Detach from the underlying numpy buffer so it survives `buf` going out of scope.
    return QPixmap.fromImage(qimage.copy())


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CINE SAX preview")
        self.resize(900, 800)

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._subject_screen = SubjectScreen()
        self._scan_screen = ScanSelectScreen()
        self._preview_screen = PreviewScreen()

        self._stack.addWidget(self._subject_screen)
        self._stack.addWidget(self._scan_screen)
        self._stack.addWidget(self._preview_screen)

        self._subject_screen.subject_chosen.connect(self._on_subject_chosen)
        self._scan_screen.back_requested.connect(self._show_subject_screen)
        self._scan_screen.reconstruct_requested.connect(self._start_reconstruction)
        self._preview_screen.return_requested.connect(self._show_subject_screen)

        self._worker: ReconstructionWorker | None = None
        self._pending_scans: list[ReconstructedScan] = []

    def _show_subject_screen(self) -> None:
        self._subject_screen.reset()
        self._stack.setCurrentWidget(self._subject_screen)

    def _on_subject_chosen(self, subject_dir: Path) -> None:
        self._scan_screen.populate(subject_dir)
        self._stack.setCurrentWidget(self._scan_screen)

    def _start_reconstruction(self, scan_dirs: list[Path]) -> None:
        self._pending_scans = []
        worker = ReconstructionWorker(scan_dirs)
        worker.progress.connect(self._scan_screen.show_progress)
        worker.scan_done.connect(self._on_scan_done)
        worker.failed.connect(self._scan_screen.show_failure)
        worker.finished_all.connect(self._on_reconstruction_finished)
        self._worker = worker
        worker.start()

    def _on_scan_done(self, scan: ReconstructedScan) -> None:
        self._pending_scans.append(scan)

    def _on_reconstruction_finished(self) -> None:
        self._scan_screen.reset_after_finish()
        if not self._pending_scans:
            QMessageBox.warning(self, "Nothing to show", "No scans reconstructed.")
            return
        self._preview_screen.load_scans(self._pending_scans)
        self._stack.setCurrentWidget(self._preview_screen)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    def _excepthook(exc_type, exc_value, exc_tb):
        message = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        QMessageBox.critical(None, "Unhandled error", message)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
