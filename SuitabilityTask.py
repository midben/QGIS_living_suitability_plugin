from qgis.core import QgsTask, QgsMessageLog, Qgis

from .Overpass import fetch_osm_elements, elements_to_layer
from .SuitabilityCore import (
    generate_grid, nearest_distances, join_lsoa_attributes,
    apply_weights_and_style,
)


class SuitabilityTask(QgsTask):
    def __init__(self, description, extent, spacing, lsoa_layer, weights, region_geometry, on_success, on_error):
        super().__init__(description, QgsTask.CanCancel)
        self.extent = extent
        self.spacing = spacing
        self.lsoa_layer = lsoa_layer
        self.weights = weights
        self.region_geometry = region_geometry
        self.on_success = on_success  # callback(result_layer), run on main thread
        self.on_error = on_error      # callback(error_message), run on main thread

        self.school_elements = None
        self.supermarket_elements = None
        self.error_message = None

    def run(self):
        """Background thread: pure network I/O only, no QGIS objects."""
        try:
            self.setProgress(15)
            self.school_elements = fetch_osm_elements(self.extent, self.lsoa_layer.crs(), "amenity", "school")
            self.setProgress(50)
            self.supermarket_elements = fetch_osm_elements(self.extent, self.lsoa_layer.crs(), "shop", "supermarket")
            self.setProgress(70)
            return True
        except Exception as e:
            self.error_message = str(e)
            QgsMessageLog.logMessage(f"Overpass fetch failed: {e}", "SuitabilityPlugin", Qgis.Critical)
            return False

    def finished(self, result):
        """Main thread: safe to build/read QGIS vector layers here."""
        if not result:
            self.on_error(self.error_message or "Network request failed — check the QGIS log panel.")
            return

        try:
            crs = self.lsoa_layer.crs()

            grid_layer = generate_grid(self.extent, self.spacing, crs, self.region_geometry)

            school_layer = elements_to_layer(self.school_elements, crs, "osm_school")
            supermarket_layer = elements_to_layer(self.supermarket_elements, crs, "osm_supermarket")

            school_dist = nearest_distances(grid_layer, school_layer)
            supermarket_dist = nearest_distances(grid_layer, supermarket_layer)
            lsoa_attrs = join_lsoa_attributes(
                grid_layer, self.lsoa_layer, fields=["crime_count", "avg_price"], extent=self.extent
            )

            result_layer = apply_weights_and_style(
                grid_layer, school_dist, supermarket_dist, lsoa_attrs, self.weights
            )

            self.on_success(result_layer)
        except Exception as e:
            QgsMessageLog.logMessage(f"Scoring step failed: {e}", "SuitabilityPlugin", Qgis.Critical)
            self.on_error(str(e))
