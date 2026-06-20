"""
bldg_extract_overture.py — Main QGIS plugin class.
"""

import os
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsApplication

from .utils.dependency_check import check_dependencies, prompt_install


class BldgExtractOverturePlugin:
    def __init__(self, iface):
        self.iface   = iface
        self.plugin_dir = os.path.dirname(__file__)
        self._action = None
        self._dialog = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QgsApplication.getThemeIcon('/mActionAddOgrLayer.svg')
        self._action = QAction(icon, 'Extract Buildings (Overture)', self.iface.mainWindow())
        self._action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self._action)
        self.iface.addPluginToVectorMenu('&Building Extractor', self._action)

    def unload(self):
        self.iface.removePluginVectorMenu('&Building Extractor', self._action)
        self.iface.removeToolBarIcon(self._action)
        del self._action

    def run(self):
        missing = check_dependencies()
        if missing:
            prompt_install(missing, self.iface.mainWindow())
            return

        if self._dialog is None:
            from .bldg_extract_dialog import BldgExtractDialog
            self._dialog = BldgExtractDialog(self.iface, self.iface.mainWindow())

        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
