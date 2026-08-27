import os
from qgis.core import QgsVectorLayer


def load_bundled_lsoa_layer():
    plugin_dir = os.path.dirname(__file__)
    gpkg_path = os.path.join(plugin_dir, "data", "lsoa_lookup.gpkg")

    if not os.path.exists(gpkg_path):
        raise FileNotFoundError(
            f"Bundled LSOA data not found at {gpkg_path}. "
            "Make sure data/lsoa_lookup.gpkg is included in the plugin folder."
        )

    layer = QgsVectorLayer(gpkg_path, "lsoa_lookup", "ogr")
    if not layer.isValid():
        raise ValueError(f"Bundled LSOA layer at {gpkg_path} failed to load — check the file isn't corrupted.")

    return layer

def load_bundled_counties_layer():
    plugin_dir = os.path.dirname(__file__)
    gpkg_path = os.path.join(plugin_dir, "data", "counties.gpkg")

    if not os.path.exists(gpkg_path):
        raise FileNotFoundError(
            f"Bundled counties data not found at {gpkg_path}. "
            "Make sure data/counties.gpkg is included in the plugin folder."
        )

    layer = QgsVectorLayer(gpkg_path, "counties", "ogr")
    if not layer.isValid():
        raise ValueError(f"Bundled counties layer at {gpkg_path} failed to load — check the file isn't corrupted.")

    return layer
