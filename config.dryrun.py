"""
Central configuration for bldg_extract_overture (V202601).

DRY_RUN = True  →  ห้าม insert/POST ไปยัง production จริง
                    แสดงผลเป็น [DRY RUN] log แทน
"""
import os
import configparser

# ── Safety guard ──────────────────────────────────────────────────────────────
# ตั้งค่า True เพื่อป้องกันการเขียนข้อมูลไปยัง production API / MongoDB จริง
DRY_RUN: bool = True

# ── Target layer / collection ─────────────────────────────────────────────────
DEFAULT_BRANCH: str = "5512011"
BLDG_COLLECTION_NAME: str = "b5512011_bldg"


def collection_for_branch(branch: str) -> str:
    """Collection name ตาม convention ของ pwagis: b{branch}_bldg"""
    branch = (branch or DEFAULT_BRANCH).strip()
    return f"b{branch}_bldg"

# ── Overture Maps ─────────────────────────────────────────────────────────────
# ดู release ที่มีจริง: aws s3 ls s3://overturemaps-us-west-2/release/ --no-sign-request
# (S3 bucket เก็บเฉพาะ release ล่าสุด ~2 ตัว — ถ้า query ไม่เจอไฟล์ให้อัปเดตค่านี้)
OVERTURE_RELEASE: str = "2026-05-20.0"
OVERTURE_S3_BASE: str = (
    "s3://overturemaps-us-west-2/release/"
    f"{OVERTURE_RELEASE}/theme=buildings/type=building/*"
)

# ── Local paths ───────────────────────────────────────────────────────────────
# _HERE = โฟลเดอร์ package (bldg_extract_overture) — ใช้เป็นฐานของ Data/logs
# เพื่อให้ทำงานได้ทั้ง dev layout และตอนติดตั้งใน QGIS profile plugins
_HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(_HERE)
DATA_DIR = os.path.join(_HERE, "Data")
LOG_DIR = os.path.join(_HERE, "logs")

# ── pwagis API (read from config_test.ini or config.ini) ──────────────────────
# หาในโฟลเดอร์ package ก่อน (ตอนติดตั้งใน QGIS) แล้วค่อย parent (dev layout)
# ถ้ามีหลายไฟล์ ไฟล์หลังสุดใน list ชนะ → config.ini ใน package ชนะทุกอย่าง
_config_files = [
    os.path.join(PLUGIN_DIR, "config_test.ini"),
    os.path.join(PLUGIN_DIR, "config.ini"),
    os.path.join(_HERE, "config_test.ini"),
    os.path.join(_HERE, "config.ini"),
]

_cfg = configparser.ConfigParser()
_cfg.read(_config_files, encoding="utf-8")

API_BASE_URL: str = _cfg.get("pwagis", "baseUrl", fallback="")
API_USERNAME: str = _cfg.get("pwagis", "username", fallback="")
API_PASSWORD: str = _cfg.get("pwagis", "password", fallback="")

# ── MongoDB ───────────────────────────────────────────────────────────────────
MONGO_URI: str = _cfg.get("mongodb", "uri", fallback="mongodb://localhost:27017")
MONGO_DB: str = _cfg.get("mongodb", "db", fallback="pwagis_test")

# ── Go insert API (bldg_insert_api) ────────────────────────────────────────────
# ปลายทางของปุ่ม "Upload to API" — test ใช้ :8080,
# production ผ่าน nginx location /bldg_insert_api/ (server จริง port 5014)
INSERT_API_BASE_URL: str = _cfg.get("insert_api", "base_url",
                                    fallback="http://localhost:8080")

# ── Topology check ────────────────────────────────────────────────────────────
PWAGIS_DIR: str = _cfg.get("paths", "pwagis_dir",
                            fallback=r"G:\My Drive\application_projects\pwagis")
TOPO_BBOX_PATH: str = os.path.join(
    PWAGIS_DIR, "topology_check", "data", "province_bbox.geojson"
)
