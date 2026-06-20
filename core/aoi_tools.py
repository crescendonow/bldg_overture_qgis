from qgis.gui import QgsMapToolExtent, QgsRubberBand
from qgis.core import (
    QgsWkbTypes, QgsRectangle, QgsCoordinateReferenceSystem,
    QgsProject, QgsGeometry,
)
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QColor

from ..utils.crs_helper import rect_to_wgs84


class RectangleAOITool(QgsMapToolExtent):
    """
    Map tool that lets the user draw a rectangle on the canvas.
    Emits aoi_selected(dict) with keys xmin/ymin/xmax/ymax in WGS84.
    """
    aoi_selected = pyqtSignal(dict)

    def __init__(self, canvas, rubber_band=None):
        super().__init__(canvas)
        self._canvas = canvas
        self._rubber_band = rubber_band
        self.extentChanged.connect(self._on_extent_changed)

    def _on_extent_changed(self, rect: QgsRectangle):
        if rect.isEmpty():
            return
        src_crs = QgsProject.instance().crs()
        bbox = rect_to_wgs84(rect, src_crs)
        if self._rubber_band:
            self._update_rubber_band(rect)
        self.aoi_selected.emit(bbox)

    def _update_rubber_band(self, rect: QgsRectangle):
        self._rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        geom = QgsGeometry.fromRect(rect)
        self._rubber_band.addGeometry(geom, None)
        self._rubber_band.show()


def make_rubber_band(canvas) -> QgsRubberBand:
    rb = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
    rb.setColor(QColor(255, 0, 0, 100))
    rb.setFillColor(QColor(255, 0, 0, 30))
    rb.setWidth(2)
    return rb


def get_layer_extent_bbox(layer) -> dict:
    rect = layer.extent()
    return rect_to_wgs84(rect, layer.crs())


def get_selected_features_bbox(layer) -> dict:
    rect = layer.boundingBoxOfSelected()
    if rect.isEmpty():
        return None
    return rect_to_wgs84(rect, layer.crs())
