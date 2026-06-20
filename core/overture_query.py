"""
overture_query.py — Download building footprints from Overture Maps.

Two methods:
  A) overturemaps Python package  (primary)
  B) DuckDB + S3 parquet           (fallback)
"""

import os
import subprocess
import tempfile
import geopandas as gpd
from typing import Optional


def download_buildings(
    bbox: dict,
    output_path: Optional[str] = None,
    method: str = "auto",
    progress_cb=None,
) -> gpd.GeoDataFrame:
    """
    Download Overture Maps buildings for a given bbox.

    Args:
        bbox: dict with keys xmin, ymin, xmax, ymax  (WGS84)
        output_path: optional path to save intermediate GeoParquet
        method: "overturemaps" | "duckdb" | "auto"
        progress_cb: callable(pct:int, msg:str) or None

    Returns:
        GeoDataFrame with building polygons, CRS=EPSG:4326
    """
    if method == "auto":
        method = _detect_method()

    _log(progress_cb, 0, f"Downloading buildings via [{method}] "
         f"bbox={bbox['xmin']:.4f},{bbox['ymin']:.4f},"
         f"{bbox['xmax']:.4f},{bbox['ymax']:.4f}")

    if method == "overturemaps":
        gdf = _download_via_overturemaps(bbox, output_path, progress_cb)
    elif method == "duckdb":
        gdf = _download_via_duckdb(bbox, output_path, progress_cb)
    else:
        raise ValueError(f"Unknown method: {method!r}. Use 'overturemaps' or 'duckdb'.")

    if gdf is None or gdf.empty:
        _log(progress_cb, 100, "No buildings found in the given bbox.")
        return gpd.GeoDataFrame(columns=["id", "geometry"])

    # Ensure WGS84
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")

    _log(progress_cb, 100, f"Downloaded {len(gdf):,} buildings.")
    return gdf


def _detect_method() -> str:
    try:
        import overturemaps  # noqa: F401
        return "overturemaps"
    except ImportError:
        pass
    try:
        import duckdb  # noqa: F401
        return "duckdb"
    except ImportError:
        pass
    raise ImportError(
        "Neither 'overturemaps' nor 'duckdb' is installed.\n"
        "Install one: pip install overturemaps   or   pip install duckdb"
    )


# ── Method A: overturemaps package ────────────────────────────────────────────

def _download_via_overturemaps(bbox, output_path, progress_cb) -> gpd.GeoDataFrame:
    """Use overturemaps.core.geodataframe() to fetch buildings."""
    try:
        from overturemaps import core as om_core
    except ImportError:
        raise ImportError("Install overturemaps: pip install overturemaps")

    _log(progress_cb, 10, "Querying Overture Maps (overturemaps package)...")
    west  = bbox["xmin"]
    south = bbox["ymin"]
    east  = bbox["xmax"]
    north = bbox["ymax"]

    gdf = om_core.geodataframe("building", bbox=(west, south, east, north))
    _log(progress_cb, 70, f"Fetched {len(gdf):,} raw records.")

    if output_path:
        gdf.to_parquet(output_path)
        _log(progress_cb, 80, f"Saved raw parquet → {output_path}")

    return gdf


# ── Method B: DuckDB + S3 ─────────────────────────────────────────────────────

# คอลัมน์ attribute ที่อยากได้ — เลือกเฉพาะที่มีจริงใน release นั้น ๆ
_DESIRED_COLUMNS = [
    "id", "height", "num_floors", "class", "subtype",
    "level", "names", "sources", "confidence",
]


def _download_via_duckdb(bbox, output_path, progress_cb) -> gpd.GeoDataFrame:
    """Use DuckDB spatial + httpfs to query Overture S3 parquet directly."""
    try:
        import duckdb
    except ImportError:
        raise ImportError("Install duckdb: pip install duckdb")

    _log(progress_cb, 10, "Connecting to DuckDB...")
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("INSTALL httpfs;  LOAD httpfs;")

    from ..config import OVERTURE_RELEASE
    s3_path = (
        f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"
        "/theme=buildings/type=building/*"
    )

    # ตรวจ schema จริงของ release ก่อน — คอลัมน์และชนิด geometry ต่างกันได้
    # (duckdb ≥1.4 อ่าน GeoParquet เป็น GEOMETRY native; รุ่นเก่าเห็นเป็น WKB BLOB)
    _log(progress_cb, 15, "Reading parquet schema...")
    schema = con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{s3_path}', hive_partitioning = 1)"
    ).fetchall()
    available = {row[0]: row[1] for row in schema}

    cols = [c for c in _DESIRED_COLUMNS if c in available]
    if available.get("geometry", "").upper() == "GEOMETRY":
        geom_expr = "ST_AsWKB(geometry) AS geometry"
    else:
        geom_expr = "geometry"

    _log(progress_cb, 20, "Querying S3 parquet (DuckDB)...")
    sql = f"""
        SELECT
            {', '.join(cols)},
            {geom_expr}
        FROM read_parquet('{s3_path}', hive_partitioning = 1)
        WHERE bbox.xmax >= {bbox['xmin']}
          AND bbox.xmin <= {bbox['xmax']}
          AND bbox.ymax >= {bbox['ymin']}
          AND bbox.ymin <= {bbox['ymax']}
    """
    df = con.execute(sql).df()
    _log(progress_cb, 70, f"DuckDB returned {len(df):,} rows.")
    con.close()

    if df.empty:
        return gpd.GeoDataFrame()

    import shapely
    df["geometry"] = df["geometry"].apply(lambda b: shapely.from_wkb(bytes(b)))
    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")

    if output_path:
        gdf.to_parquet(output_path)
        _log(progress_cb, 80, f"Saved raw parquet → {output_path}")

    return gdf


def _log(cb, pct: int, msg: str):
    if cb:
        cb(pct, msg)
