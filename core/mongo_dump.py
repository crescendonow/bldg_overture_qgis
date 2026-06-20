"""
mongo_dump.py — Dump validated building features to MongoDB.

Collection : bldg_overture_{branch}
Database   : pwagis_test  (from config)

DRY_RUN = True  →  ห้าม insert ไปยัง production จริง
                    แสดงเฉพาะ [DRY RUN] log แทน
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import geopandas as gpd

from ..config import DRY_RUN, MONGO_URI, MONGO_DB, BLDG_COLLECTION_NAME

logger = logging.getLogger(__name__)


def dump_buildings(
    gdf: gpd.GeoDataFrame,
    branch: str,
    topo_results: Optional[dict] = None,
    progress_cb=None,
) -> dict:
    """
    Dump building GeoDataFrame to MongoDB.

    Args:
        gdf:          GeoDataFrame of buildings (EPSG:4326)
        branch:       branch code, e.g. "5512011"
        topo_results: dict {overture_id: bool} — True = topology passed
        progress_cb:  callable(pct:int, msg:str) or None

    Returns:
        {"inserted": int, "collection": str, "dry_run": bool}
    """
    collection_name = f"bldg_overture_{branch}"
    total = len(gdf)
    result = {"inserted": 0, "collection": collection_name, "dry_run": DRY_RUN}

    if total == 0:
        _log(progress_cb, 100, "Nothing to insert (empty GeoDataFrame).")
        return result

    if DRY_RUN:
        _log(progress_cb, 0,
             f"[DRY RUN] Would insert {total:,} documents into "
             f"{MONGO_DB}.{collection_name} — skipped (DRY_RUN=True).")
        logger.warning("[DRY RUN] MongoDB insert skipped. Set DRY_RUN=False to enable.")
        result["inserted"] = total
        return result

    # ── Real execution path (DRY_RUN=False) ───────────────────────────────────
    try:
        from pymongo import MongoClient, GEOSPHERE, ASCENDING
        from pymongo.errors import BulkWriteError
    except ImportError:
        raise ImportError("Install pymongo: pip install pymongo")

    _log(progress_cb, 5, f"Connecting to MongoDB: {MONGO_URI}")
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db     = client[MONGO_DB]
    col    = db[collection_name]

    # Ensure indexes
    _ensure_indexes(col, GEOSPHERE, ASCENDING)

    extract_ts = datetime.now(tz=timezone.utc).isoformat()
    docs = []
    for _, row in gdf.iterrows():
        ot_id = str(row.get("id", ""))
        doc = {
            "type":      "Feature",
            "geometry":  json.loads(row.geometry.to_json()),
            "properties": _row_props(row),
            "meta": {
                "branch":       branch,
                "collection":   BLDG_COLLECTION_NAME,
                "extract_date": extract_ts,
                "source":       "overture_maps",
                "topo_valid":   topo_results.get(ot_id, True) if topo_results else None,
            },
        }
        docs.append(doc)

    _log(progress_cb, 30, f"Inserting {total:,} documents...")
    try:
        ins = col.insert_many(docs, ordered=False)
        result["inserted"] = len(ins.inserted_ids)
    except BulkWriteError as bwe:
        inserted = bwe.details.get("nInserted", 0)
        result["inserted"] = inserted
        logger.warning("BulkWriteError — inserted %d, errors: %s",
                       inserted, bwe.details.get("writeErrors", [])[:5])

    client.close()
    _log(progress_cb, 100,
         f"MongoDB dump done: {result['inserted']:,} documents in "
         f"{MONGO_DB}.{collection_name}")
    return result


def ensure_indexes(branch: str):
    """Create recommended indexes on bldg_overture_{branch} (dry-run safe)."""
    collection_name = f"bldg_overture_{branch}"
    if DRY_RUN:
        logger.info("[DRY RUN] ensure_indexes('%s') skipped.", collection_name)
        return
    try:
        from pymongo import MongoClient, GEOSPHERE, ASCENDING
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        col = client[MONGO_DB][collection_name]
        _ensure_indexes(col, GEOSPHERE, ASCENDING)
        client.close()
        logger.info("Indexes ensured on %s.%s", MONGO_DB, collection_name)
    except Exception as exc:
        logger.error("ensure_indexes failed: %s", exc)
        raise


# ── Internal ───────────────────────────────────────────────────────────────────

def _ensure_indexes(col, GEOSPHERE, ASCENDING):
    existing = {idx["name"] for idx in col.list_indexes()}
    if "geometry_2dsphere" not in existing:
        col.create_index([("geometry", GEOSPHERE)], name="geometry_2dsphere")
    if "extract_date_-1" not in existing:
        col.create_index([("meta.extract_date", -1)], name="extract_date_-1")
    if "overture_id_1" not in existing:
        col.create_index(
            [("properties.id", ASCENDING)],
            name="overture_id_1",
            unique=True,
            sparse=True,
        )


def _row_props(row) -> dict:
    props = {}
    for k, v in row.items():
        if k == "geometry":
            continue
        if hasattr(v, "item"):    # numpy scalar
            v = v.item()
        elif v is None or (v != v):  # NaN
            v = None
        props[k] = v
    return props


def _log(cb, pct: int, msg: str):
    logger.info(msg)
    if cb:
        cb(pct, msg)
