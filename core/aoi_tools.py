from qgis.gui import QgsMapToolExtent, QgsMapTool, QgsRubberBand
from qgis.core import (
    QgsWkbTypes, QgsRectangle, QgsCoordinateReferenceSystem,
    QgsProject, QgsGeometry, QgsPointXY,
)
from qgis.PyQt.QtCore import pyqtSignal, Qt
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


def points_to_bbox(points) -> dict:
    """
    Pure helper: list of (x, y) vertices → {xmin, ymin, xmax, ymax}.
    Kept QGIS-free so it can be unit-tested. Returns None for < 1 point.
    """
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return {"xmin": min(xs), "ymin": min(ys), "xmax": max(xs), "ymax": max(ys)}


class FreePolygonAOITool(QgsMapTool):
    """
    Map tool that lets the user draw a polygon by clicking vertices.
    Left-click adds a vertex; right-click (or double-click) finishes.
    Only the polygon's bounding box is used downstream, so it emits the same
    aoi_selected(dict) signal (xmin/ymin/xmax/ymax in WGS84) as RectangleAOITool.
    """
    aoi_selected = pyqtSignal(dict)

    def __init__(self, canvas, rubber_band=None):
        super().__init__(canvas)
        self._canvas = canvas
        self._rubber_band = rubber_band
        self._points = []  # list[QgsPointXY] in map (project) CRS

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            pt = self.toMapCoordinates(event.pos())
            self._points.append(pt)
            self._redraw()
        elif event.button() == Qt.RightButton:
            self._finish()

    def canvasDoubleClickEvent(self, event):
        # Double-click also finishes the polygon.
        self._finish()

    def _redraw(self):
        if not self._rubber_band:
            return
        self._rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        if len(self._points) >= 2:
            geom = QgsGeometry.fromPolygonXY([self._points])
            self._rubber_band.addGeometry(geom, None)
            self._rubber_band.show()

    def _finish(self):
        if len(self._points) < 3:
            return  # not a valid polygon yet
        geom = QgsGeometry.fromPolygonXY([self._points])
        rect = geom.boundingBox()
        src_crs = QgsProject.instance().crs()
        bbox = rect_to_wgs84(rect, src_crs)
        if self._rubber_band:
            self._update_rubber_band(rect)
        self._points = []
        self.aoi_selected.emit(bbox)

    def _update_rubber_band(self, rect: QgsRectangle):
        self._rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        self._rubber_band.addGeometry(QgsGeometry.fromRect(rect), None)
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
