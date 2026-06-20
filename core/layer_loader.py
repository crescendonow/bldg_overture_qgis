from qgis.core import QgsVectorLayer, QgsProject
from qgis.utils import iface


def load_gpkg_layer(gpkg_path: str, layer_name: str = 'buildings') -> QgsVectorLayer:
    """
    Load a GeoPackage layer into the current QGIS project.
    Must be called from the main thread (e.g. QgsTask.finished()).
    """
    uri   = f'{gpkg_path}|layername={layer_name}'
    layer = QgsVectorLayer(uri, layer_name, 'ogr')
    if layer.isValid():
        QgsProject.instance().addMapLayer(layer)
        iface.setActiveLayer(layer)
        iface.zoomToActiveLayer()
    return layer
