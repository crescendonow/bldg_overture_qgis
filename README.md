# Building Footprint Extractor (Overture Maps)

**เวอร์ชัน** 0.1.0 | **QGIS** ≥ 3.28 | **ผู้พัฒนา** PWA GIS Team

ดึง building footprints จาก [Overture Maps Foundation](https://overturemaps.org/) (AWS S3 parquet) → ส่งออกหลายรูปแบบ → ตรวจสอบ topology → อัปโหลดเข้า pwagis API pipeline

---

## Pipeline (6 ขั้นตอน)

เมื่อปุ่ม **Extract** ถูกกด ปลั๊กอินจะทำงานตามลำดับผ่าน background thread:

| ขั้น | ขั้นตอน | รายละเอียด | โมดูล |
|------|---------|------------|--------|
| 1 | **Download** | ดึง building polygons จาก Overture Maps (S3 parquet) ผ่าน bbox ที่กำหนด | `core/overture_query.py` |
| 2 | **Export** | ส่งออกเป็น 4 รูปแบบ: `.gpkg` / `.geojson` / `.shp` / `.tab` | `core/exporter.py` |
| 3 | **Topology Check** | ตรวจสอบ 7 กฎ topology (เปิดโดยค่าเริ่มต้น) | `core/topo_runner.py` |
| 4 | POST to pwagis API | ส่งเข้า pwagis REST API **(legacy/test, ปิดโดยค่าเริ่มต้น)** | `core/api_client.py` |
| 5 | Dump to MongoDB | เขียนลง MongoDB โดยตรง **(legacy/test, ปิดโดยค่าเริ่มต้น)** | `core/mongo_dump.py` |
| 6 | Upload to Insert API | ส่งเข้า Go insert API **(production path, เคารพ DRY_RUN)** | `core/insert_api_client.py` |

**หลัง extract เสร็จ** — โหลดไฟล์ `.gpkg` เข้า QGIS อัตโนมัติ (ถ้าเปิด option ไว้)

### กฎ Topology ที่ตรวจสอบ (7 กฎ)

| คอลัมน์ | ความหมาย |
|---------|----------|
| `topo_area` | พื้นที่อาคารผิดปกติ (เล็ก/ใหญ่เกินเกณฑ์) |
| `topo_multipolygon` | Geometry เป็น MultiPolygon (ไม่ควรเป็น) |
| `topo_polygon_invalid` | Geometry ไม่ถูกต้อง (invalid polygon) |
| `topo_polygon_duplicates` | Polygon ซ้ำกัน |
| `topo_pologon_outregion` | อยู่นอกขอบเขตจังหวัด/พื้นที่ที่กำหนด |
| `topo_polygon_overlap` | Polygon ทับซ้อนกัน |
| `topo_polygon_selfintersect` | Polygon ตัดตัวเอง |

> **หมายเหตุ:** Topology check ต้องใช้ external module `topo_bldg()` จาก `pwagis` plugin — กำหนด path ผ่าน `PWAGIS_DIR` ในไฟล์ `.ini`

---

## โครงสร้างโปรเจกต์

```
bldg_extract_overture/
├── __init__.py                  # Plugin entry point → classFactory()
├── bldg_extract_overture.py     # Main plugin class, toolbar/menu registration
├── bldg_extract_dialog.py       # UI dialog + _ExtractionTask / _UploadTask (QThread)
├── progress_dialog.py           # Modal progress dialog (ยกเลิกได้)
├── config.py                    # LIVE config (DRY_RUN=False, production URLs)
├── config.dryrun.py             # Safe config template (DRY_RUN=True, localhost)
├── metadata.txt                 # Plugin metadata
│
├── core/
│   ├── overture_query.py        # Download จาก Overture Maps (overturemaps / DuckDB)
│   ├── exporter.py              # Export .gpkg/.geojson/.shp/.tab + prepare_for_export()
│   ├── topo_runner.py           # Topology check wrapper (dynamic import pwagis)
│   ├── api_client.py            # POST to pwagis REST API (legacy/test)
│   ├── mongo_dump.py            # Direct MongoDB insert (legacy/test)
│   ├── insert_api_client.py     # POST to Go insert API (production)
│   ├── layer_loader.py          # Auto-load .gpkg เข้า QGIS
│   └── aoi_tools.py             # Rectangle drawing tool + bbox helpers
│
├── utils/
│   ├── dependency_check.py      # ตรวจสอบ/ติดตั้ง packages ที่ขาด
│   └── crs_helper.py            # CRS transformation utilities
│
├── ui/                          # UI resources
├── Data/                        # Default output folder
└── logs/                        # Log files
```

---

## AOI (Area of Interest)

กำหนดพื้นที่ดึงข้อมูลได้ 4 วิธี:

1. **Draw rectangle on map** — วาดสี่เหลี่ยมบนแผนที่โดยตรง
2. **Use active layer extent** — ใช้ขอบเขตของ layer ที่เลือกใน QGIS
3. **Use selected features extent** — ใช้ขอบเขตของ features ที่เลือก (selected)
4. **Enter bbox manually** — กรอก `xmin,ymin,xmax,ymax` เอง (WGS84 decimal degrees)

---

## Configuration

### ไฟล์ Config

| ไฟล์ | สถานะ | รายละเอียด |
|------|-------|-----------|
| `config.dryrun.py` | **Safe (แนะนำสำหรับทดสอบ)** | `DRY_RUN=True`, API ชี้ไป `localhost` |
| `config.py` | **LIVE (production)** | `DRY_RUN=False`, API ชี้ production จริง |

### วิธีเริ่มใช้งานแบบปลอดภัย

```bash
# คัดลอก safe template เป็น config จริง
copy config.dryrun.py config.py
```

### Overture Maps Release

ค่า Overture release ที่ใช้ดึงข้อมูล: **`2026-05-20.0`**

อัปเดตได้ที่ตัวแปร `OVERTURE_RELEASE` ใน `config.py` / `config.dryrun.py`
(ดู release ที่มี: `aws s3 ls s3://overturemaps-us-west-2/release/ --no-sign-request`)

### .ini Files

ค่า connection (API URL, MongoDB URI, pwagis path) อ่านจากไฟล์ `.ini`:

```ini
[pwagis]
baseUrl = https://...
username = ...
password = ...

[mongodb]
uri = mongodb://localhost:27017
db = pwagis_test

[insert_api]
base_url = http://localhost:8080

[paths]
pwagis_dir = G:\path\to\pwagis
```

ไฟล์ที่อ่าน (ไฟล์หลังสุดใน list ชนะ):
1. `{plugin_parent}/config_test.ini`
2. `{plugin_parent}/config.ini`
3. `{plugin_package}/config_test.ini`
4. `{plugin_package}/config.ini`

### Collection Naming Convention

ชื่อ collection ตามรูปแบบ pwagis: `b{branch}_bldg`

ตัวอย่าง: branch code `5512011` → collection `b5512011_bldg`

---

## Dependencies

### Packages ที่ต้องมีเสมอ

| Package | หน้าที่ |
|---------|---------|
| `geopandas` | จัดการ GeoDataFrame |
| `fiona` | อ่าน/เขียน GIS formats |
| `pymongo` | เชื่อมต่อ MongoDB |
| `requests` | HTTP client |
| `shapely` | จัดการ geometry |

### Download Backend (ต้องมีอย่างน้อย 1 ตัว)

| Backend | Python | หมายเหตุ |
|---------|--------|---------|
| `overturemaps` | ≥ 3.10 | **ใช้ไม่ได้กับ QGIS 3.34** (Python 3.9) |
| `duckdb` | ≥ 3.9 | **แนะนำสำหรับ QGIS users** — query S3 parquet โดยตรง |

> **หมายเหตุสำหรับ QGIS 3.34:** Python ที่มากับ QGIS 3.34 คือ Python 3.9 ซึ่ง `overturemaps` package ต้องการ Python ≥ 3.10 ดังนั้นต้องใช้ `duckdb` เป็น backend หลัก

### ติดตั้ง Dependencies

ปลั๊กอินจะตรวจสอบ packages ที่ขาดตอนเปิดใช้งาน และเสนอติดตั้งให้อัตโนมัติผ่าน `pip`

---

## DRY_RUN Safety Mechanism

`DRY_RUN` เป็น safety guard สำคัญที่ควบคุมการเขียนข้อมูลทั้งหมด:

| ค่า | ผลลัพธ์ |
|-----|---------|
| `DRY_RUN = True` | **ปลอดภัย** — ไม่มีข้อมูลถูกส่งไปยัง production API / MongoDB, แสดง `[DRY RUN]` log แทน |
| `DRY_RUN = False` | **LIVE** — เขียนข้อมูลจริงเข้า production MongoDB |

### สถานะ DRY_RUN ในแต่ละขั้นตอน

- **ขั้นตอน 1-3** (Download, Export, Topology): ไม่ได้รับผลกระทบจาก DRY_RUN (เป็น read-only)
- **ขั้นตอน 4-5** (pwagis API, MongoDB): ปิดโดยค่าเริ่มต้นอยู่แล้ว (legacy/test)
- **ขั้นตอน 6** (Insert API): เคารพ DRY_RUN — ถ้า `True` จะส่ง `?dryRun=true` ไปยัง API

### สลับไป Safe Mode

```bash
# วิธีที่ 1: คัดลอก safe template
copy config.dryrun.py config.py

# วิธีที่ 2: แก้ไข config.py โดยตรง
# เปลี่ยน DRY_RUN: bool = False  →  DRY_RUN: bool = True
```

> **คำแนะนำ:** ใช้ `config.dryrun.py` เป็น base สำหรับทดสอบเสมอ ก่อนสลับไป `config.py` (LIVE) สำหรับ production

---

## Upload Modes

### 1. Extract + Upload (ขั้นตอน 6)

เปิด checkbox "Upload to Insert API after extract" ใน dialog — หลัง extract จะส่งข้อมูลเข้า Go insert API อัตโนมัติ

- ถ้า `DRY_RUN=True`: ส่ง `?dryRun=true` (preview อย่างเดียว ไม่เขียนจริง)
- ถ้า `DRY_RUN=False`: **จะแสดง dialog ยืนยันก่อน commit เข้า production**

### 2. Upload Existing File

ปุ่ม "Upload to API" ในกลุ่ม "Upload existing file → Insert API" — เลือกไฟล์ `.gpkg` / `.tab` / `.shp` / `.geojson` ที่มีอยู่แล้วอัปโหลดเข้า Insert API ได้โดยตรง

- รองรับไฟล์ที่ export ไปแล้ว หรือไฟล์จากแหล่งอื่น
- แปลงเป็น WGS84 + GeoJSON อัตโนมัติก่อนส่ง

---

## Export Formats

| รูปแบบ | Driver | หมายเหตุ |
|--------|--------|---------|
| `.gpkg` | GPKG | Primary format, โหลดเข้า QGIS ได้ทันที |
| `.geojson` | GeoJSON | ใช้ส่ง API |
| `.shp` | ESRI Shapefile | Field names ≤ 10 chars (auto-rename), encoding UTF-8 |
| `.tab` | MapInfo File | สำหรับระบบ PWA เดิม |

ชื่อไฟล์รูปแบบ: `B{branch}_BLDG_{YYYYMMDD_HHMMSS}.ext`

### prepare_for_export()

ก่อน export ทุกครั้ง ข้อมูลจะถูก normalize ผ่าน `prepare_for_export()`:
- แปลง CRS เป็น WGS84 (EPSG:4326)
- เลือกเฉพาะคอลัมน์ที่จำเป็น: `geometry, id, height, num_floors, class, confidence, names, sources`
- แปลง nested columns (`names`, `sources`) ที่เป็น numpy array/dict → string

ฟังก์ชันนี้ถูกใช้ซ้ำในขั้นตอน 6 (Insert API upload) เพื่อให้ข้อมูลอยู่ในรูปแบบ JSON-serializable
