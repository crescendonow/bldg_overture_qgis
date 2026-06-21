"""
insert_api_client.py — POST GeoJSON building features to the Go insert API
(bldg_insert_api).

แยกจาก api_client.py (ตัวนั้นคุยกับ pwagis REST API). ตัวนี้คุยกับ Go service ที่
ทำ topology check (PostGIS) + spatial join (admin.nostra_tambon_63) + generate id
+ insert ลง MongoDB vallaris_feature

dry-run / commit ถูกควบคุมที่ฝั่ง server (ค่า DRY_RUN ของ Go API); ฝั่งนี้แค่ส่งข้อมูล
แล้วรายงานผลที่ server ตอบกลับ
"""

import logging
from typing import Optional

import requests

from ..config import INSERT_API_BASE_URL, INSERT_API_KEY

logger = logging.getLogger(__name__)

# ส่งทีละชุดเพื่อกัน payload ใหญ่เกินไป
CHUNK_SIZE = 500

# ค่า remark (source) สำหรับติดตามที่มาของข้อมูล เผื่อต้อง delete ทีหลัง
SOURCE_EXTRACT = "bldg_extract_overture"  # ดึงจาก Overture แล้ว insert
SOURCE_UPLOAD = "bldg_insert_api"         # upload จากไฟล์ที่ user นำเข้าเอง


def post_features(
    feature_collection: dict,
    pwacode: str,
    base_url: str = INSERT_API_BASE_URL,
    dry_run_override: Optional[bool] = None,
    fix: bool = False,
    source: str = "",
    api_key: str = INSERT_API_KEY,
    timeout: int = 120,
    progress_cb=None,
) -> dict:
    """
    POST a GeoJSON FeatureCollection to {base_url}/buildings.

    Args:
        feature_collection: dict {"type":"FeatureCollection","features":[...]}
        pwacode:            branch code (e.g. "5521040")
        base_url:           Go API base URL
        dry_run_override:   None = ใช้ค่า server; True/False = บังคับผ่าน ?dryRun=
        fix:                ?fix=true → ให้ server เรียก ST_MakeValid
        source:             ?source=… → server ตั้ง properties.remark เป็นค่านี้
                            (SOURCE_EXTRACT / SOURCE_UPLOAD) เพื่อ trace ที่มา
        api_key:            ค่า X-API-Key header (ว่าง = ไม่แนบ; server อาจปฏิเสธ 401)
        progress_cb:        callable(pct:int, msg:str) or None

    Returns:
        {"inserted": int, "dry_run": bool|None, "success": int,
         "failed": int, "errors": list}
    """
    feats = feature_collection.get("features", []) or []
    total = len(feats)
    summary = {"inserted": 0, "dry_run": None, "success": 0, "failed": 0, "errors": []}

    if total == 0:
        _log(progress_cb, 100, "No features to upload.")
        return summary

    base = base_url.rstrip("/")
    url = f"{base}/buildings"
    headers = {"X-API-Key": api_key} if api_key else {}

    for start in range(0, total, CHUNK_SIZE):
        chunk = feats[start:start + CHUNK_SIZE]
        params = {"pwaCode": pwacode}
        if dry_run_override is not None:
            params["dryRun"] = "true" if dry_run_override else "false"
        if fix:
            params["fix"] = "true"
        if source:
            params["source"] = source
        payload = {"type": "FeatureCollection", "features": chunk}

        try:
            resp = requests.post(url, params=params, json=payload,
                                 headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            summary["failed"] += len(chunk)
            summary["errors"].append(str(exc))
            logger.error("upload chunk failed: %s", exc)
            continue

        if resp.status_code == 200:
            data = resp.json()
            summary["dry_run"] = data.get("dryRun")
            summary["inserted"] += int(data.get("inserted", 0))
            for r in data.get("results", []):
                if r.get("status") in ("inserted", "would-insert"):
                    summary["success"] += 1
                else:
                    summary["failed"] += 1
            summary["errors"].extend(data.get("errors", []) or [])
        else:
            summary["failed"] += len(chunk)
            summary["errors"].append(f"HTTP {resp.status_code}: {resp.text[:300]}")

        done = min(start + CHUNK_SIZE, total)
        _log(progress_cb, int(done / total * 100),
             f"Uploaded {done}/{total} features…")

    logger.info("upload complete: %s", summary)
    return summary


def _log(cb, pct: int, msg: str):
    logger.info(msg)
    if cb:
        cb(pct, msg)
