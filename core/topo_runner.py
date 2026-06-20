"""
topo_runner.py — Wrapper around pwagis topology_check/lib/topology.py.

Calls topo_bldg() (mode="1", GeoDataFrame input) to validate building polygons.
Topology columns added to the GeoDataFrame (ชื่อตาม topology.py จริง):
  topo_area, topo_multipolygon, topo_polygon_invalid,
  topo_polygon_duplicates, topo_pologon_outregion,
  topo_polygon_overlap, topo_polygon_selfintersect
"""

import os
import sys
import logging
import tempfile
from typing import Optional

import geopandas as gpd

from ..config import PWAGIS_DIR, TOPO_BBOX_PATH

logger = logging.getLogger(__name__)


def run_topo_bldg(
    gdf: gpd.GeoDataFrame,
    bbox_path: Optional[str] = None,
    logfile: Optional[str] = None,
    progress_cb=None,
) -> gpd.GeoDataFrame:
    """
    Run topology checks on building GeoDataFrame.

    Args:
        gdf:        Building GeoDataFrame (EPSG:4326 recommended)
        bbox_path:  Path to province/boundary GeoJSON for out-of-region check.
                    Falls back to TOPO_BBOX_PATH from config.
        logfile:    Path for topology log file (auto-created if None)
        progress_cb: callable(pct:int, msg:str) or None

    Returns:
        GeoDataFrame with topology result columns appended.
        Rows with any topology error have the corresponding column = 'true'.
    """
    _log(progress_cb, 0, "Starting topology check on buildings...")

    topo_bldg = _import_topo_bldg()
    _log(progress_cb, 10, "topology module loaded.")

    if bbox_path is None:
        bbox_path = TOPO_BBOX_PATH

    # mode="1" (string!) → read_data คืน input ตรง ๆ ดังนั้น input_bbox
    # ต้องโหลดเป็น GeoDataFrame เองก่อนส่งเข้าไป
    bbox_gdf = None
    if os.path.exists(bbox_path):
        bbox_gdf = gpd.read_file(bbox_path)
    else:
        logger.warning("bbox file not found: %s — out-of-region check will fail.", bbox_path)

    if logfile is None:
        logfile = os.path.join(tempfile.gettempdir(), "bldg_topo.log")

    _log(progress_cb, 20, f"Running topo_bldg (mode=\"1\", {len(gdf):,} features)...")
    try:
        result_gdf = topo_bldg(
            mode="1",
            input_pwa_layer=gdf.copy(),
            input_bbox=bbox_gdf,
            logfile=logfile,
        )
    except Exception as exc:
        logger.error("topo_bldg failed: %s", exc)
        raise RuntimeError(f"Topology check failed: {exc}") from exc

    _log(progress_cb, 90, "Topology check complete.")
    _summarise(result_gdf, progress_cb)
    return result_gdf


def summarise_topo_results(gdf: gpd.GeoDataFrame) -> dict:
    """
    Return a dict of topology error counts per rule.

    Keys: same as topo column names.
    Values: int count of features with error = 'true'.
    """
    topo_cols = [c for c in gdf.columns if c.startswith("topo_")]
    summary = {}
    for col in topo_cols:
        summary[col] = int((gdf[col].astype(str).str.lower() == "true").sum())
    return summary


def has_critical_errors(gdf: gpd.GeoDataFrame) -> bool:
    """Return True if any critical topology errors exist (invalid, self-intersect, overlap)."""
    critical = [
        "topo_polygon_invalid",
        "topo_polygon_selfintersect",
        "topo_polygon_overlap",
    ]
    for col in critical:
        if col in gdf.columns:
            if (gdf[col].astype(str).str.lower() == "true").any():
                return True
    return False


# ── Internal ───────────────────────────────────────────────────────────────────

def _load_module(name: str, path: str):
    """Load a module from file and register it in sys.modules."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _import_topo_bldg():
    """
    Import topo_bldg from pwagis topology_check by loading the lib files directly.

    topology.py ทำ `from pwagis.topology_check.lib.read_file import ...` ซึ่งถ้า
    import แบบปกติจะไปโหลด pwagis plugin ทั้งตัว (ต้องใช้ sip/QGIS GUI) — จึง
    pre-register stub package + โหลด read_file/result จากไฟล์ตรง ๆ แทน
    """
    import types

    topo_lib = os.path.join(PWAGIS_DIR, "topology_check", "lib")
    topology_path = os.path.join(topo_lib, "topology.py")
    if not os.path.exists(topology_path):
        raise ImportError(
            f"topology.py not found at {topology_path}.\n"
            f"Check that PWAGIS_DIR is correct in config_test.ini / config.ini."
        )

    try:
        for pkg in ("pwagis", "pwagis.topology_check", "pwagis.topology_check.lib"):
            if pkg not in sys.modules:
                sys.modules[pkg] = types.ModuleType(pkg)
        for sub in ("read_file", "result"):
            full = f"pwagis.topology_check.lib.{sub}"
            if full not in sys.modules:
                _load_module(full, os.path.join(topo_lib, f"{sub}.py"))
        mod = _load_module("_pwagis_topology", topology_path)
        return mod.topo_bldg
    except Exception as exc:
        raise ImportError(
            f"Cannot import topo_bldg from {PWAGIS_DIR}.\n"
            f"Check that PWAGIS_DIR is correct in config_test.ini.\n"
            f"Original error: {exc}"
        ) from exc


def _summarise(gdf: gpd.GeoDataFrame, progress_cb):
    summary = summarise_topo_results(gdf)
    lines = [f"  {k}: {v} error(s)" for k, v in summary.items() if v > 0]
    if lines:
        msg = "Topology issues found:\n" + "\n".join(lines)
        logger.warning(msg)
    else:
        msg = "All topology checks passed."
        logger.info(msg)
    _log(progress_cb, 100, msg)


def _log(cb, pct: int, msg: str):
    logger.info(msg)
    if cb:
        cb(pct, msg)
