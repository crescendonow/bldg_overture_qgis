from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRectangle,
)

WGS84 = QgsCoordinateReferenceSystem('EPSG:4326')


def rect_to_wgs84(rect: QgsRectangle, src_crs: QgsCoordinateReferenceSystem) -> dict:
    if src_crs == WGS84:
        r = rect
    else:
        xform = QgsCoordinateTransform(src_crs, WGS84, QgsProject.instance())
        r = xform.transformBoundingBox(rect)
    return {
        'xmin': r.xMinimum(),
        'ymin': r.yMinimum(),
        'xmax': r.xMaximum(),
        'ymax': r.yMaximum(),
    }


def bbox_area_km2(bbox: dict) -> float:
    import math
    lat_mid = (bbox['ymin'] + bbox['ymax']) / 2.0
    lat_km  = 111.0
    lon_km  = 111.0 * math.cos(math.radians(lat_mid))
    width   = (bbox['xmax'] - bbox['xmin']) * lon_km
    height  = (bbox['ymax'] - bbox['ymin']) * lat_km
    return abs(width * height)
