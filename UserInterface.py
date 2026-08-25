from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox,
    QPushButton, QMessageBox, QProgressBar, QComboBox
)
from qgis.gui import QgsMapToolExtent
from qgis.core import QgsProject, QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform

from .BundledData import load_bundled_lsoa_layer, load_bundled_counties_layer
from .SuitabilityTask import SuitabilityTask


class SuitabilityDialog(QDialog):
    """
    The plugin's UI. Its only jobs are:
      1. Let the user draw a region on the map
      2. Let the user set weights that must sum to 100
      3. Launch the analysis as a background task when Run is clicked

    LSOA data is loaded automatically from the plugin's bundled GeoPackage
    (see BundledData.py) — the user never has to name or select it.

    Does NOT fetch OSM data or do any scoring math itself — that lives in
    SuitabilityCore.py / Overpass.py / SuitabilityTask.py. This file is UI only.
    """

    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.extent = None  # populated once the user draws a region
        self.task = None    # keeps a reference to the running QgsTask

        self.setWindowTitle("Suitability Score Calculator")
        self.layout = QVBoxLayout()

        self._build_region_section()
        self._build_weights_section()
        self._build_spacing_section()
        self._build_run_section()

        self.setLayout(self.layout)

    # ---------- UI construction ----------

    def _build_region_section(self):
        self.extent_label = QLabel("No region selected yet")

        self.select_region_btn = QPushButton("Draw region on map")
        self.select_region_btn.clicked.connect(self.start_extent_selection)
        self.layout.addWidget(self.select_region_btn)

        row = QHBoxLayout()
        row.addWidget(QLabel("Or select a county:"))
        self.county_combo = QComboBox()
        self.county_combo.addItem("— Select —")
        self.county_combo.addItems(self._load_county_names())
        self.county_combo.currentTextChanged.connect(self.on_county_selected)
        row.addWidget(self.county_combo)
        self.layout.addLayout(row)

        self.layout.addWidget(self.extent_label)

    def _build_weights_section(self):
        self.weight_boxes = {}
        for key, label in [
            ("school", "School proximity weight"),
            ("supermarket", "Supermarket proximity weight"),
            ("crime", "Safety (inverse crime) weight"),
            ("price", "Affordability weight"),
        ]:
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            spin = QSpinBox()
            spin.setRange(0, 100)
            spin.valueChanged.connect(self.update_weight_total)
            row.addWidget(spin)
            self.layout.addLayout(row)
            self.weight_boxes[key] = spin

        self.total_label = QLabel("Total: 0 / 100")
        self.layout.addWidget(self.total_label)

    def _build_spacing_section(self):
        row = QHBoxLayout()
        row.addWidget(QLabel("Grid spacing (metres):"))
        self.spacing_box = QSpinBox()
        self.spacing_box.setRange(25, 1000)
        self.spacing_box.setValue(100)
        row.addWidget(self.spacing_box)
        self.layout.addLayout(row)

    def _build_run_section(self):
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.layout.addWidget(self.progress_bar)

        self.run_btn = QPushButton("Run analysis")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self.run_analysis)
        self.layout.addWidget(self.run_btn)

    # ---------- Region drawing ----------

    def start_extent_selection(self):
        self.extent_tool = QgsMapToolExtent(self.canvas)
        self.extent_tool.extentChanged.connect(self.on_extent_selected)
        self.canvas.setMapTool(self.extent_tool)

    def on_extent_selected(self, rect):
        """
        Fires once the user finishes dragging a rectangle. The canvas is
        typically in EPSG:3857 (Web Mercator, the default with an OSM
        basemap), but the grid, Overpass query, and LSOA join all need the
        extent in the LSOA layer's CRS (EPSG:27700, British National Grid).
        Reproject here, once, so self.extent is always in the working CRS
        no matter what CRS the canvas happens to be displaying in.
        """
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:27700")

        if canvas_crs.authid() != target_crs.authid():
            transform = QgsCoordinateTransform(canvas_crs, target_crs, QgsProject.instance())
            rect = transform.transformBoundingBox(rect)

        self.extent = rect
        self.extent_label.setText(
            f"Region: ({rect.xMinimum():.0f}, {rect.yMinimum():.0f}) "
            f"to ({rect.xMaximum():.0f}, {rect.yMaximum():.0f})"
        )
        self.update_weight_total()

    # ---------- County handling ----------

    def _load_county_names(self):
        layer = load_bundled_counties_layer()
        return sorted(f["CTYUA25NM"] for f in layer.getFeatures())


    def on_county_selected(self, county_name):
        if county_name == "— Select —":
            return
        layer = load_bundled_counties_layer()
        for feature in layer.getFeatures():
            if feature["CTYUA25NM"] == county_name:
                self.extent = feature.geometry().boundingBox()
                self.region_geometry = feature.geometry()
                self.extent_label.setText(f"Region: {county_name}")
                self.update_weight_total()
                return

    # ---------- Weight validation ----------

    def update_weight_total(self):
        total = sum(box.value() for box in self.weight_boxes.values())
        self.total_label.setText(f"Total: {total} / 100")
        self.run_btn.setEnabled(total == 100 and self.extent is not None)

    # ---------- Running the analysis ----------

    def run_analysis(self):
        """
        Loads the bundled LSOA layer, collects the weights, and launches the
        analysis as a background QgsTask so QGIS's UI thread stays responsive
        during the Overpass fetch.
        """
        try:
            lsoa_layer = load_bundled_lsoa_layer()
        except (FileNotFoundError, ValueError) as e:
            QMessageBox.critical(self, "Bundled data missing", str(e))
            return

        weights = {k: v.value() for k, v in self.weight_boxes.items()}

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.run_btn.setEnabled(False)

        self.task = SuitabilityTask(
            description="Calculating suitability scores",
            extent=self.extent,
            spacing=self.spacing_box.value(),
            lsoa_layer=lsoa_layer,
            weights=weights,
            region_geometry=self.region_geometry,
            on_success=self._on_analysis_success,
            on_error=self._on_analysis_error,
        )
        self.task.progressChanged.connect(lambda: self.progress_bar.setValue(int(self.task.progress())))

        QgsApplication.taskManager().addTask(self.task)

    def _on_analysis_success(self, result_layer):
        """Runs on the main thread once the background task finishes successfully."""
        self.progress_bar.setVisible(False)
        self.run_btn.setEnabled(True)
        QgsProject.instance().addMapLayer(result_layer)
        QMessageBox.information(self, "Done", "Suitability layer added to the map.")

    def _on_analysis_error(self, error_message):
        """Runs on the main thread if the background task failed."""
        self.progress_bar.setVisible(False)
        self.run_btn.setEnabled(True)
        QMessageBox.critical(self, "Analysis failed", error_message)
