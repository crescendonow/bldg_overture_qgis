"""
api_client.py — POST building features to the pwagis REST API.

Target collection : b5512011_bldg
Endpoint          : POST /api/2.0/resources/features/pwa/collections/{id}/items
                        ?validate=attribute

DRY_RUN = True   → ห้าม POST ไปยัง production จริง
                    แสดงเฉพาะ [DRY RUN] log แทน
"""

import json
import logging
import time
from typing import Optional, Tuple

import requests
import geopandas as gpd

from ..config import (
    DRY_RUN,
    API_BASE_URL,
    API_USERNAME,
    API_PASSWORD,
    BLDG_COLLECTION_NAME,
)

logger = logging.getLogger(__name__)

# ── Token cache (module-level, เพื่อ reuse ใน session เดียวกัน) ────────────────
_token_cache: dict = {"access": "", "refresh": ""}


# ── Public API ─────────────────────────────────────────────────────────────────

def post_buildings(
    gdf: gpd.GeoDataFrame,
    progress_cb=None,
    collection_name: str = BLDG_COLLECTION_NAME,
) -> dict:
    """
    POST each building feature to the pwagis API.

    Args:
        gdf:             GeoDataFrame of buildings (CRS must be EPSG:4326)
        progress_cb:     callable(pct:int, msg:str) or None
        collection_name: override collection (default: b5512011_bldg)

    Returns:
        {"success": int, "failed": int, "errors": list, "dry_run": bool}
    """
    results = {"success": 0, "failed": 0, "errors": [], "dry_run": DRY_RUN}
    total = len(gdf)

    if total == 0:
        _log(progress_cb, 100, "Nothing to POST (empty GeoDataFrame).")
        return results

    if DRY_RUN:
        _log(progress_cb, 0,
             f"[DRY RUN] Would POST {total:,} buildings to collection "
             f"'{collection_name}' — skipped (DRY_RUN=True).")
        logger.warning("[DRY RUN] API POST skipped. Set DRY_RUN=False to enable.")
        results["success"] = total
        return results

    # ── Real execution path (DRY_RUN=False) ───────────────────────────────────
    if not API_BASE_URL:
        raise RuntimeError(
            "pwagis API base URL ว่าง (ไม่ได้ตั้ง [pwagis] baseUrl ใน config_test.ini). "
            "เส้นทาง 'POST to pwagis API' นี้เป็น legacy/test — สำหรับ insert "
            "production ให้ใช้ปุ่ม 'Upload to API' (Go insert API) แทน."
        )
    token = _ensure_token()
    collection_id = _get_collection_id(token, collection_name)
    if not collection_id:
        raise RuntimeError(f"Collection '{collection_name}' not found on server.")

    url = (f"{API_BASE_URL}/api/2.0/resources/features/pwa"
           f"/collections/{collection_id}/items?validate=attribute")
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json"}

    for i, (_, row) in enumerate(gdf.iterrows()):
        feature = _row_to_feature(row, collection_name)
        try:
            resp = requests.post(url, json=feature, headers=headers, timeout=30)
            if resp.status_code in (200, 201):
                results["success"] += 1
            else:
                results["failed"] += 1
                results["errors"].append({
                    "index": i,
                    "status": resp.status_code,
                    "body": resp.text[:300],
                })
        except requests.RequestException as exc:
            results["failed"] += 1
            results["errors"].append({"index": i, "error": str(exc)})

        if progress_cb and (i % 50 == 0 or i == total - 1):
            pct = int((i + 1) / total * 100)
            _log(progress_cb, pct,
                 f"POST {i + 1}/{total}  success={results['success']}  "
                 f"failed={results['failed']}")

    logger.info("POST complete: %s", results)
    return results


def get_collection_id(collection_name: str = BLDG_COLLECTION_NAME) -> Optional[str]:
    """Return the server collection id for a given collection name (dry-run safe)."""
    if DRY_RUN:
        logger.info("[DRY RUN] get_collection_id('%s') skipped.", collection_name)
        return None
    token = _ensure_token()
    return _get_collection_id(token, collection_name)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _ensure_token() -> str:
    """Return a valid bearer token, refreshing if expired."""
    if not _token_cache["access"]:
        _login()
    elif _is_token_expired(_token_cache["access"]):
        _refresh_token()
    return _token_cache["access"]


def _login():
    url = f"{API_BASE_URL}/api/2.0/login"
    payload = {"username": API_USERNAME, "password": API_PASSWORD}
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    _token_cache["access"]  = data.get("accessToken", "")
    _token_cache["refresh"] = data.get("refreshToken", "")
    logger.info("Logged in. Token obtained.")


def _refresh_token():
    url = f"{API_BASE_URL}/api/2.0/token"
    payload = {"grant_type": "refresh_token",
               "refresh_token": _token_cache["refresh"]}
    resp = requests.post(url, json=payload, timeout=15)
    if resp.status_code == 200:
        _token_cache["access"] = resp.json().get("accessToken", "")
    else:
        # Re-login if refresh fails
        _login()


def _is_token_expired(token: str) -> bool:
    url = (f"{API_BASE_URL}/api/2.0/resources/references/pipe-types")
    try:
        resp = requests.get(url,
                            headers={"Authorization": f"Bearer {token}"},
                            timeout=10)
        return resp.status_code == 401
    except requests.RequestException:
        return True


def _get_collection_id(token: str, collection_name: str) -> Optional[str]:
    url = (f"{API_BASE_URL}/api/2.0/resources/features/pwa/collections"
           f"?title={collection_name}")
    resp = requests.get(url,
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=15)
    if resp.status_code != 200:
        logger.error("Cannot get collection id: HTTP %s", resp.status_code)
        return None
    data = resp.json()
    collections = data.get("collections", data if isinstance(data, list) else [])
    for col in collections:
        if col.get("title", "").lower() == collection_name.lower():
            return col.get("id") or col.get("collectionId")
    return None


def _row_to_feature(row, collection_name: str) -> dict:
    """Convert a GeoDataFrame row to a GeoJSON Feature payload."""
    from shapely.geometry import mapping

    props = {k: v for k, v in row.items() if k != "geometry"}
    # Serialise any non-JSON-native values
    for k, v in props.items():
        if hasattr(v, "item"):        # numpy scalar
            props[k] = v.item()
        elif v is None or v != v:     # NaN check
            props[k] = None

    props["collection_name"] = collection_name

    # mapping() คืน tuple ซ้อน — json round-trip แปลงเป็น list ให้ serialize ได้
    return {
        "type": "Feature",
        "geometry": json.loads(json.dumps(mapping(row.geometry))),
        "properties": props,
    }


def _log(cb, pct: int, msg: str):
    logger.info(msg)
    if cb:
        cb(pct, msg)
