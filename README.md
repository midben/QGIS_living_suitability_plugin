# QGIS_living_suitability_plugin

takes weighted values from 4 attributes within a predetermined area to calculate where is the most optimal area to live in (within ENGLAND)

## Overview

This plugin uses UK LSOA data and Overpass API to find an optimal area to live in using a colour-coded dotted grid to display the "suitability score" of each dot.

the 4 parameters in question:
-Crime rate by LSOA
-Median House Price by LSOA
-Distance from a supermarket
-Distance from a school

This plugin could be useful for someone looking to move to a new area. But using the weighted algorithm also allows them to query individual attributes.

The user is presented with a window in which they can either search within a county or a box they can draw. The weights of the parameters must add up to 100 to search.

## Installation Requirements
 
### Software
 
- **QGIS 3.22 or later** (developed and tested on QGIS 3.44 LTR)
- **Git LFS** — the bundled LSOA dataset (`data/lsoa_lookup.gpkg`, ~500MB) is stored via Git LFS, so it must be installed *before* cloning, or the file will download as a small pointer file instead of the actual data:
```bash
  git lfs install
```
 
### Python dependencies
 
QGIS ships its own bundled Python interpreter — plugins run inside that environment, not your system Python. This plugin requires one package beyond what QGIS includes by default:
 
- **`requests`** — used for the Overpass API calls
Install it into QGIS's own Python environment (not your regular Python), using QGIS's OSGeo4W Shell (Windows) or QGIS's bundled `pip`:
 
```bash
# From the OSGeo4W Shell (Windows) or QGIS's Python environment on Mac/Linux
pip install requests
```
 
If `requests` isn't available, the plugin will fail with `ModuleNotFoundError: No module named 'requests'` the first time it tries to fetch OSM data.
 
### Getting the plugin
 
```bash
git clone https://github.com/midben/QGIS_living_suitability_plugin.git
```
 
Ensure Git LFS is installed *before* running this clone — otherwise re-run `git lfs pull` afterward inside the cloned folder to fetch the actual `.gpkg` file.
 
### Installing into QGIS
 
1. Copy (or symlink) the cloned folder into your QGIS profile's plugin directory:
   - **Windows**: `C:\Users\<you>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\`
   - **Mac**: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
   - **Linux**: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
2. Restart QGIS
3. `Plugins > Manage and Install Plugins > Installed` → enable **Suitability Score Calculator**
   (tick "Show also experimental plugins" in Settings if it doesn't appear, since this plugin is marked experimental)
### Network access
 
The plugin makes live requests to the Overpass API (`overpass-api.de`, with `overpass.kumi.systems` as a fallback) to fetch schools and supermarkets for the selected region. An internet connection is required at analysis time — the LSOA/crime/price data is bundled locally and does not require network access.

