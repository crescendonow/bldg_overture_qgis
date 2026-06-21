from qgis.PyQt.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
)
from qgis.PyQt.QtCore import pyqtSignal, QTimer, QElapsedTimer


class ProgressDialog(QDialog):
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_cancelled = False
        self._busy = False
        self._base_status = "Initializing..."
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._build_ui()
        self.btnCancel.clicked.connect(self._on_cancel)
        self._elapsed.start()
        self._timer.start()

    def _build_ui(self):
        self.setWindowTitle("Extracting Buildings (Overture Maps)...")
        self.resize(420, 150)
        layout = QVBoxLayout(self)

        self.lblStatus = QLabel("Initializing...")
        self.lblStatus.setWordWrap(True)
        layout.addWidget(self.lblStatus)

        self.progressBar = QProgressBar()
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)
        layout.addWidget(self.progressBar)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btnCancel = QPushButton("Cancel")
        btn_row.addWidget(self.btnCancel)
        layout.addLayout(btn_row)

    def _on_cancel(self):
        self._is_cancelled = True
        self._timer.stop()
        self.lblStatus.setText("Cancelling...")
        self.btnCancel.setEnabled(False)
        self.cancelled.emit()

    def is_cancelled(self) -> bool:
        return self._is_cancelled

    def set_progress(self, pct: int):
        # A real percentage takes the bar out of busy/indeterminate mode.
        if self._busy:
            self.set_busy(False)
        self.progressBar.setValue(pct)

    def set_status(self, text: str):
        self._base_status = text
        self._render_status()

    def set_busy(self, on: bool):
        """
        Toggle the indeterminate 'marquee' animation for long blocking phases
        (e.g. the DuckDB→S3 query) so the dialog clearly looks alive even when
        no percentage is available.
        """
        if on == self._busy:
            return
        self._busy = on
        if on:
            self.progressBar.setRange(0, 0)  # indeterminate animation
        else:
            self.progressBar.setRange(0, 100)

    def _tick(self):
        self._render_status()

    def _render_status(self):
        if self._is_cancelled:
            return
        secs = int(self._elapsed.elapsed() / 1000)
        self.lblStatus.setText(f"{self._base_status}  (elapsed {secs}s)")

    def closeEvent(self, event):  # noqa: N802 (Qt signature)
        self._timer.stop()
        super().closeEvent(event)
