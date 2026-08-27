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
    bbox_4326 = reproject_extent_to_4326(extent, source_crs)
    query = build_overpass_query(bbox_4326, tag_key, tag_value)
    data = query_overpass(query)
    return data.get("elements", [])


def elements_to_layer(elements, target_crs, layer_name):
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
    elements = fetch_osm_elements(extent, target_crs, tag_key, tag_value)
    layer_name = f"osm_{tag_value}"
    return elements_to_layer(elements, target_crs, layer_name)
