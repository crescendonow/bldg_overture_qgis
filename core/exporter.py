"""
exporter.py — Export building GeoDataFrame to multiple GIS formats.

Output formats:
  .gpkg    — GeoPackage (primary, loads into QGIS)
  .geojson — GeoJSON    (sent to pwagis API)
  .shp     — Shapefile  (for ArcGIS / external exchange)
  .tab     — MapInfo TAB (legacy PWA systems)
"""

import os
import logging
from datetime import datetime
from typing import Optional
import geopandas as gpd

logger = logging.getLogger(__name__)

# Column name map for Shapefile (field names ≤10 chars)
_SHP_RENAME = {
    "overture_id":  "ot_id",
    "num_floors":   "n_floors",
    "confidence":   "confid",
}

# Columns to keep in export (drop heavy/nested fields)
_KEEP_COLS = [
    "geometry", "id", "height", "num_floors", "class",
    "confidence", "names", "sources",
]


def export_buildings(
    gdf: gpd.GeoDataFrame,
    branch: str,
    output_dir: str,
    progress_cb=None,
) -> dict:
    """
    Export buildings to .gpkg / .geojson / .shp / .tab.

    Args:
        gdf:        GeoDataFrame (CRS will be forced to EPSG:4326)
        branch:     branch code, e.g. "5512011"
        output_dir: folder to write files into
        progress_cb: callable(pct:int, msg:str) or None

    Returns:
        dict with keys "gpkg", "geojson", "shp", "tab" → absolute paths
    """
    os.makedirs(output_dir, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(output_dir, f"B{branch}_BLDG_{ts}")

    gdf = prepare_for_export(gdf)
    _log(progress_cb, 0, f"Exporting {len(gdf):,} buildings → {output_dir}")

    results = {}

    # 1) GeoPackage
    gpkg = f"{base}.gpkg"
    gdf.to_file(gpkg, layer="buildings", driver="GPKG")
    results["gpkg"] = gpkg
    _log(progress_cb, 25, f"[1/4] .gpkg → {os.path.basename(gpkg)}")

    # 2) GeoJSON
    geojson = f"{base}.geojson"
    gdf.to_file(geojson, driver="GeoJSON")
    results["geojson"] = geojson
    _log(progress_cb, 50, f"[2/4] .geojson → {os.path.basename(geojson)}")

    # 3) Shapefile (field names truncated to ≤10 chars)
    shp = f"{base}.shp"
    _export_shp(gdf, shp)
    results["shp"] = shp
    _log(progress_cb, 75, f"[3/4] .shp → {os.path.basename(shp)}")

    # 4) MapInfo TAB
    tab = f"{base}.tab"
    _export_tab(gdf, tab)
    results["tab"] = tab
    _log(progress_cb, 100, f"[4/4] .tab → {os.path.basename(tab)}")

    logger.info("Export complete: %s", results)
    return results


def prepare_for_export(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Normalise CRS to WGS84 and keep/flatten only exportable columns.

    Also used by the Insert-API upload step (Step 6): the raw Overture gdf has
    nested columns (`names`, `sources`) whose cells are numpy ndarrays/dicts and
    are NOT JSON-serialisable. Selecting `_KEEP_COLS` and stringifying those two
    columns yields the same scalar-only shape the exported file holds, so
    `gdf.to_json()` succeeds — matching what the upload-from-file path sends.
    """
    gdf = gdf.copy()

    # Ensure WGS84
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")

    # Keep only known columns that exist
    keep = [c for c in _KEEP_COLS if c in gdf.columns]
    if "geometry" not in keep:
        keep.append("geometry")
    gdf = gdf[keep]

    # Flatten nested dict/list columns to string (gpkg/shp cannot store them)
    for col in ["names", "sources"]:
        if col in gdf.columns:
            gdf[col] = gdf[col].apply(
                lambda v: str(v) if v is not None else ""
            )

    return gdf


def _export_shp(gdf: gpd.GeoDataFrame, path: str):
    """Shapefile: rename long column names and write."""
    shp_gdf = gdf.rename(columns=_SHP_RENAME)
    # encoding="utf-8" → เขียน .cpg กำกับ ไม่งั้น DBF จะ default เป็น ISO-8859-1
    # แล้วตัวอักษรไทยใน names เพี้ยน
    shp_gdf.to_file(path, driver="ESRI Shapefile", encoding="utf-8")


def _export_tab(gdf: gpd.GeoDataFrame, path: str):
    """MapInfo TAB: requires fiona with 'MapInfo File' driver."""
    try:
        gdf.to_file(path, driver="MapInfo File")
    except Exception as exc:
        logger.warning("MapInfo TAB export failed (%s). Writing MIF/MID instead.", exc)
        mif_path = path.replace(".tab", ".mif")
        try:
            gdf.to_file(mif_path, driver="MapInfo File")
        except Exception as exc2:
            logger.error("MIF export also failed: %s", exc2)
            raise RuntimeError(f"TAB/MIF export failed: {exc2}") from exc2


def _log(cb, pct: int, msg: str):
    logger.info(msg)
    if cb:
        cb(pct, msg)
