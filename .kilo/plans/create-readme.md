# Plan: สร้าง README.md สำหรับ bldg_extract_overture

## เป้าหมาย
สร้างไฟล์ `README.md` ใน root ของ project ที่สรุปการทำงานของ QGIS plugin "Building Footprint Extractor (Overture Maps)"

## โครงสร้าง README.md ที่จะเขียน

### 1. Header
- ชื่อ plugin: Building Footprint Extractor (Overture Maps)
- เวอร์ชัน 0.1.0 | QGIS ≥ 3.28
- คำอธิบายสั้น: ดึง building footprints จาก Overture Maps Foundation → export → topology check → upload ผ่าน pwagis API pipeline

### 2. Pipeline Overview (6 ขั้นตอน)
1. **Download** — ดึง building polygons จาก Overture Maps (AWS S3 parquet) ผ่าน `overturemaps` package หรือ `DuckDB` fallback
2. **Export** — ส่งออกเป็น 4 รูปแบบ: .gpkg / .geojson / .shp / .tab
3. **Topology Check** — ตรวจสอบ 7 กฎ topology (area, multipolygon, invalid, duplicates, outregion, overlap, self-intersect)
4. **POST to pwagis API** — ส่งเข้า pwagis REST API (legacy/test, opt-in)
5. **MongoDB Dump** — เขียนลง MongoDB โดยตรง (legacy/test, opt-in)
6. **Upload to Insert API** — ส่งเข้า Go insert API (production path, respects DRY_RUN)
- **Auto-load** — โหลด .gpkg เข้า QGIS อัตโนมัติหลัง extract

### 3. Project Structure
แสดง tree ของไฟล์พร้อมคำอธิบายแต่ละไฟล์

### 4. AOI (Area of Interest)
- วาด rectangle บน map
- ใช้ extent ของ active layer
- ใช้ extent ของ selected features
- กรอก bbox เอง (xmin,ymin,xmax,ymax)

### 5. Configuration
- `config.py` (LIVE) vs `config.dryrun.py` (DRY_RUN=True)
- Overture release: 2026-05-20.0
- ค่า config จาก .ini files (pwagis API, MongoDB, Insert API, paths)

### 6. Dependencies
- Required: geopandas, fiona, pymongo, requests, shapely
- Download backend (อย่างน้อย 1): overturemaps (Python ≥ 3.10) หรือ duckdb

### 7. DRY_RUN Safety
- อธิบาย DRY_RUN flag
- วิธีสลับไป safe mode

## ขั้นตอนการทำงาน
1. เขียน `README.md` ไฟล์เดียวใน root ของ project
2. เนื้อหาเป็นภาษาไทย (ตามภาษาที่ผู้ใช้ใช้) ผสมคำศัพท์เทคนิคภาษาอังกฤษ
3. ไม่ใส่ข้อมูลที่ไม่ได้ยืนยันจาก source code
