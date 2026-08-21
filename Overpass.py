import time
import requests

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsField, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject,
)
from qgis.PyQt.QtCore import QVariant

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

OVERPASS_TIMEOUT = 60   # value baked into the [timeout:] clause of the query itself
REQUEST_TIMEOUT = 75    # HTTP client-side timeout, kept slightly above OVERPASS_TIMEOUT


def reproject_extent_to_4326(extent, source_crs):
    """
    Overpass always expects bounding boxes in lat/lon (EPSG:4326), regardless
    of what CRS the rest of the plugin works in (e.g. EPSG:27700).
    """
    target_crs = QgsCoordinateReferenceSystem("EPSG:4326")
    if source_crs.authid() == target_crs.authid():
        return extent

    transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
    return transform.transformBoundingBox(extent)


def build_overpass_query(bbox_4326, tag_key, tag_value):
    """
    Queries both 'node' and 'way' since OSM contributors tag the same
    real-world feature differently (a single point vs. a building outline).
    'out center' makes a way return one representative point instead of a
    full outline, so every result is usable as a point regardless of type.
    """
    bbox_str = (
        f"{bbox_4326.yMinimum()},{bbox_4326.xMinimum()},"
        f"{bbox_4326.yMaximum()},{bbox_4326.xMaximum()}"
    )

    query = f"""
    [out:json][timeout:{OVERPASS_TIMEOUT}];
    (
      node["{tag_key}"="{tag_value}"]({bbox_str});
      way["{tag_key}"="{tag_value}"]({bbox_str});
    );
    out center qt;
    """
    return query


def query_overpass(query):
    """
    Sends the query, trying each server in OVERPASS_URLS with one retry
    each before giving up. Public Overpass instances can be slow/unavailable
    at busy times, so this fallback meaningfully improves reliability over
    hitting a single URL once.

    Includes a custom User-Agent — the default 'python-requests/x.x' one
    gets rejected with a 406 by overpass-api.de, since it looks like
    anonymous bot traffic without one.
    """
    headers = {
        "User-Agent": "SuitabilityScorePlugin/0.1 (QGIS plugin)"
    }

    last_error = None
    for url in OVERPASS_URLS:
        for attempt in range(2):
            try:
                response = requests.post(url, data={"data": query}, headers=headers, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                last_error = e
                if attempt == 0:
                    time.sleep(2)

    raise RuntimeError(f"All Overpass servers failed. Last error: {last_error}")


def fetch_osm_elements(extent, source_crs, tag_key, tag_value):
    """
    Pure network fetch — builds the query, sends it, returns raw Overpass
    'elements' JSON. Deliberately creates NO QGIS vector layer objects, so
    this is safe to call from a background thread (e.g. inside a QgsTask's
    run() method). Layer creation happens separately, in elements_to_layer(),
    which must run on the main thread.
    """
    bbox_4326 = reproject_extent_to_4326(extent, source_crs)
    query = build_overpass_query(bbox_4326, tag_key, tag_value)
    data = query_overpass(query)
    return data.get("elements", [])


def elements_to_layer(elements, target_crs, layer_name):
    """
    Converts Overpass's raw JSON elements into a QGIS point memory layer,
    reprojected into target_crs so it's immediately usable for distance
    calculations. MUST be called on the main thread — creates QgsVectorLayer
    objects, which are not thread-safe.
    """
    layer = QgsVectorLayer(f"Point?crs={target_crs.authid()}", layer_name, "memory")
    provider = layer.dataProvider()
    provider.addAttributes([
        QgsField("id", QVariant.LongLong),
        QgsField("name", QVariant.String),
    ])
    layer.updateFields()

    source_crs = QgsCoordinateReferenceSystem("EPSG:4326")
    transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())

    features = []
    for element in elements:
        if element.get("type") == "node":
            lat, lon = element["lat"], element["lon"]
        elif "center" in element:
            lat, lon = element["center"]["lat"], element["center"]["lon"]
        else:
            continue

        point_4326 = QgsPointXY(lon, lat)
        point_transformed = transform.transform(point_4326)

        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromPointXY(point_transformed))
        feature.setAttributes([
            element.get("id", 0),
            element.get("tags", {}).get("name", ""),
        ])
        features.append(feature)

    provider.addFeatures(features)
    layer.updateExtents()
    return layer


def fetch_osm_points(extent, target_crs, tag_key, tag_value):
    """
    Convenience wrapper combining fetch + layer-building in one call.
    Only safe to call from the MAIN thread (since it calls elements_to_layer).
    Do NOT call this from inside a QgsTask's run() — use fetch_osm_elements()
    there instead, and build the layer afterward in finished().
    """
    elements = fetch_osm_elements(extent, target_crs, tag_key, tag_value)
    layer_name = f"osm_{tag_value}"
    return elements_to_layer(elements, target_crs, layer_name)
