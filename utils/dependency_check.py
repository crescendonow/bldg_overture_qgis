import os
import sys
import subprocess
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt

# Packages ที่ต้องมีเสมอ (ติดตั้งได้บน Python 3.9 ของ QGIS 3.34)
REQUIRED_PACKAGES = [
    ('geopandas', 'geopandas'),
    ('fiona',     'fiona'),
    ('pymongo',   'pymongo'),
    ('requests',  'requests'),
    ('shapely',   'shapely'),
]

# Download backends — ต้องมีอย่างน้อยหนึ่งตัว
# หมายเหตุ: overturemaps ต้องการ Python >= 3.10 จึงติดตั้งบน QGIS 3.34 (Py 3.9) ไม่ได้
# ใน QGIS ให้ใช้ duckdb เป็นหลัก
DOWNLOAD_BACKENDS = [
    ('overturemaps', 'overturemaps'),
    ('duckdb',       'duckdb'),
]


def check_dependencies() -> list:
    """Return a list of pip package names that must be installed."""
    missing = []
    for import_name, install_name in REQUIRED_PACKAGES:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(install_name)

    # ต้องมี download backend อย่างน้อยหนึ่งตัว — ถ้าไม่มีเลย แนะนำ duckdb
    # (overturemaps ใช้ไม่ได้กับ Python 3.9 ของ QGIS 3.34)
    has_backend = False
    for import_name, _ in DOWNLOAD_BACKENDS:
        try:
            __import__(import_name)
            has_backend = True
            break
        except ImportError:
            pass
    if not has_backend:
        missing.append('duckdb')

    return missing


def _get_python_exe() -> str:
    """
    Locate the real python.exe for pip.

    ใน QGIS บน Windows, sys.executable ชี้ไปที่ qgis-bin.exe ไม่ใช่ python.exe
    ต้องใช้ python.exe จาก sys.exec_prefix (เช่น ...\\apps\\Python39\\python.exe)
    """
    candidate = os.path.join(sys.exec_prefix, 'python.exe')
    if os.path.exists(candidate):
        return candidate
    candidate = os.path.join(sys.exec_prefix, 'bin', 'python')
    if os.path.exists(candidate):
        return candidate
    return sys.executable


def install_packages(packages: list, parent=None) -> tuple:
    python_exe = _get_python_exe()
    progress = QProgressDialog(
        'Installing dependencies...', 'Cancel', 0, len(packages), parent
    )
    progress.setWindowModality(Qt.WindowModal)
    progress.setMinimumDuration(0)

    for i, pkg in enumerate(packages):
        progress.setValue(i)
        progress.setLabelText(f'Installing {pkg}...')
        if progress.wasCanceled():
            return False, 'Installation cancelled by user.'
        result = subprocess.run(
            [python_exe, '-m', 'pip', 'install', pkg,
             '--quiet', '--no-warn-script-location'],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            progress.close()
            return False, f'Failed to install {pkg}:\n{result.stderr}'

    progress.setValue(len(packages))
    progress.close()
    return True, ''


def prompt_install(missing: list, parent=None) -> bool:
    names = '\n  - '.join(missing)
    reply = QMessageBox.question(
        parent,
        'Missing Dependencies',
        f'The following packages are required but not installed:\n\n'
        f'  - {names}\n\nInstall them now? QGIS may need to restart.',
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if reply != QMessageBox.Yes:
        return False

    ok, err = install_packages(missing, parent)
    if not ok:
        QMessageBox.critical(parent, 'Installation Failed', err)
        return False

    QMessageBox.information(
        parent,
        'Installation Complete',
        'Dependencies installed.\nPlease restart QGIS and try again.',
    )
    return False
