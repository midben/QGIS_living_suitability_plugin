from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsSpatialIndex, QgsField, QgsFeatureRequest,
    QgsGraduatedSymbolRenderer, QgsClassificationQuantile,
    QgsStyle
)
from qgis.PyQt.QtCore import QVariant


def generate_grid(extent, spacing, crs, region_geometry=None):
    """
    Create a point grid across the given extent.

    If region_geometry is provided, only points that fall within
    the region boundary are added.
    """
    layer = QgsVectorLayer(
        f"Point?crs={crs.authid()}",
        "grid",
        "memory"
    )
    provider = layer.dataProvider()

    features = []

    x = extent.xMinimum()

    while x < extent.xMaximum():
        y = extent.yMinimum()

        while y < extent.yMaximum():

            point = QgsPointXY(x, y)
            point_geometry = QgsGeometry.fromPointXY(point)

            # Only add points inside the selected region
            if region_geometry is None or region_geometry.contains(point_geometry):
                feature = QgsFeature()
                feature.setGeometry(point_geometry)
                features.append(feature)

            y += spacing

        x += spacing

    provider.addFeatures(features)
    layer.updateExtents()

    return layer


def nearest_distances(grid_layer, hub_layer):
    """For each point in grid_layer, return distance (map units) to nearest feature in hub_layer."""
    if hub_layer.featureCount() == 0:
        return [None] * grid_layer.featureCount()

    index = QgsSpatialIndex(hub_layer.getFeatures())
    hub_geoms = {f.id(): f.geometry() for f in hub_layer.getFeatures()}

    distances = []
    for feature in grid_layer.getFeatures():
        point = feature.geometry().asPoint()
        nearest_ids = index.nearestNeighbor(point, 1)
        if nearest_ids:
            nearest_geom = hub_geoms[nearest_ids[0]]
            distances.append(feature.geometry().distance(nearest_geom))
        else:
            distances.append(None)
    return distances


def join_lsoa_attributes(grid_layer, lsoa_layer, fields, extent=None):
    """
    For each grid point, find the LSOA polygon it falls inside and pull out
    given field values.

    extent: optional QgsRectangle to pre-filter lsoa_layer down to only the
    features intersecting the study area before building the spatial index.
    Without this, the entire bundled LSOA layer (tens of thousands of
    polygons nationwide) gets indexed on every single run regardless of how
    small the selected region is — slow enough to look like a freeze.
    """
    if extent is not None:
        request = QgsFeatureRequest().setFilterRect(extent)
        candidate_features = list(lsoa_layer.getFeatures(request))
    else:
        candidate_features = list(lsoa_layer.getFeatures())

    index = QgsSpatialIndex()
    for feature in candidate_features:
        index.insertFeature(feature)
    lsoa_features = {f.id(): f for f in candidate_features}

    results = {f: [] for f in fields}
    for feature in grid_layer.getFeatures():
        point_geom = feature.geometry()
        candidate_ids = index.intersects(point_geom.boundingBox())
        match = None
        for cid in candidate_ids:
            candidate = lsoa_features[cid]
            if candidate.geometry().contains(point_geom):
                match = candidate
                break
        for field in fields:
            if match is None:
                value = None
            else:
                value = match[field]
                # PyQGIS can hand back a QVariant NULL object instead of
                # Python None for missing values — normalize() only checks
                # for None, so this conversion matters.
                if isinstance(value, QVariant) and value.isNull():
                    value = None
            results[field].append(value)
    return results


def normalize(values, invert=False):
    """Min-max scale a list of numbers to 0-1. If invert=True, smaller raw values score higher."""
    clean = [v for v in values if v is not None]
    if not clean:
        return [0.5 for _ in values]
    vmin, vmax = min(clean), max(clean)
    if vmin == vmax:
        return [0.5 for _ in values]

    def scale(v):
        if v is None:
            return 0.5
        norm = (v - vmin) / (vmax - vmin)
        return 1 - norm if invert else norm

    return [scale(v) for v in values]


def apply_weights_and_style(grid_layer, school_dist, supermarket_dist, lsoa_attrs, weights):
    """
    Normalizes raw distance/attribute lists already computed against a grid
    layer, writes the weighted score onto the layer, and applies graduated
    styling. Kept separate from the fetch/distance steps so it can be called
    from SuitabilityTask.finished() on the main thread, after the network
    part of the work has already completed in the background.
    """
    school_score = normalize(school_dist, invert=True)
    supermarket_score = normalize(supermarket_dist, invert=True)
    crime_score = normalize(lsoa_attrs["crime_count"], invert=True)
    price_score = normalize(lsoa_attrs["avg_price"], invert=True)

    w = {k: v / 100 for k, v in weights.items()}

    provider = grid_layer.dataProvider()
    provider.addAttributes([
        QgsField("school_dist", QVariant.Double),
        QgsField("supermarket_dist", QVariant.Double),
        QgsField("crime_count", QVariant.Double),
        QgsField("avg_price", QVariant.Double),
        QgsField("suitability_score", QVariant.Double),
    ])
    grid_layer.updateFields()

    grid_layer.startEditing()
    for i, feat in enumerate(grid_layer.getFeatures()):
        score = (
            w["school"] * school_score[i]
            + w["supermarket"] * supermarket_score[i]
            + w["crime"] * crime_score[i]
            + w["price"] * price_score[i]
        )
        grid_layer.changeAttributeValue(feat.id(), grid_layer.fields().indexOf("school_dist"), school_dist[i])
        grid_layer.changeAttributeValue(feat.id(), grid_layer.fields().indexOf("supermarket_dist"), supermarket_dist[i])
        grid_layer.changeAttributeValue(feat.id(), grid_layer.fields().indexOf("crime_count"), lsoa_attrs["crime_count"][i])
        grid_layer.changeAttributeValue(feat.id(), grid_layer.fields().indexOf("avg_price"), lsoa_attrs["avg_price"][i])
        grid_layer.changeAttributeValue(feat.id(), grid_layer.fields().indexOf("suitability_score"), score)
    grid_layer.commitChanges()

    renderer = QgsGraduatedSymbolRenderer()
    renderer.setClassAttribute("suitability_score")
    renderer.setClassificationMethod(QgsClassificationQuantile())
    renderer.updateClasses(grid_layer, 10)  # create the class ranges first

    # Grab a built-in ramp from QGIS's style library by name
    ramp = QgsStyle.defaultStyle().colorRamp("Reds")
    renderer.updateColorRamp(ramp)

    grid_layer.setRenderer(renderer)
    grid_layer.setOpacity(0.65)
    grid_layer.triggerRepaint()

    return grid_layer
