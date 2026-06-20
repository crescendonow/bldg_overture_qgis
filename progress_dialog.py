from qgis.PyQt.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
)
from qgis.PyQt.QtCore import pyqtSignal


class ProgressDialog(QDialog):
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_cancelled = False
        self._build_ui()
        self.btnCancel.clicked.connect(self._on_cancel)

    def _build_ui(self):
        self.setWindowTitle("Extracting Buildings (Overture Maps)...")
        self.resize(420, 150)
        layout = QVBoxLayout(self)

        self.lblStatus = QLabel("Initializing...")
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
        self.lblStatus.setText("Cancelling...")
        self.btnCancel.setEnabled(False)
        self.cancelled.emit()

    def is_cancelled(self) -> bool:
        return self._is_cancelled

    def set_progress(self, pct: int):
        self.progressBar.setValue(pct)

    def set_status(self, text: str):
        self.lblStatus.setText(text)
