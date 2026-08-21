def classFactory(iface):
    """QGIS calls this function on plugin load. Must return the plugin class instance."""
    from .main import SuitabilityPlugin
    return SuitabilityPlugin(iface)
