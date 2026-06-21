"""
bldg_extract_dialog.py — Main UI dialog + background extraction task.

Pipeline (triggered by Extract button):
  1. Download buildings from Overture Maps        → overture_query
  2. Export .gpkg / .geojson / .shp / .tab        → exporter
  3. Topology check                                → topo_runner
  4. POST to pwagis API   (legacy/test, opt-in)   → api_client
  5. Dump to MongoDB      (legacy/test, opt-in)   → mongo_dump
  6. Upload to Insert API (Go, honors DRY_RUN)    → insert_api_client
  + Auto-load .gpkg into QGIS (after task)        → layer_loader
"""

import json
import os
import traceback
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QPlainTextEdit, QGroupBox, QRadioButton,
    QCheckBox, QFileDialog, QMessageBox,
)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal, QObject
from qgis.core import QgsTask, QgsApplication, QgsProject, QgsVectorLayer

from .config import (
    DRY_RUN, DEFAULT_BRANCH, collection_for_branch, DATA_DIR, INSERT_API_BASE_URL,
)
from .core.overture_query import download_buildings
from .core.exporter import export_buildings, prepare_for_export
from .core.api_client import post_buildings
from .core.topo_runner import run_topo_bldg, summarise_topo_results
from .core.mongo_dump import dump_buildings
from .core.insert_api_client import post_features, SOURCE_EXTRACT, SOURCE_UPLOAD
from .core.layer_loader import load_gpkg_layer
from .core.aoi_tools import (
    RectangleAOITool, FreePolygonAOITool, make_rubber_band,
    get_layer_extent_bbox, get_selected_features_bbox,
)
from .core.pwacode_finder import is_meter_layer_name, match_pwacode_field, extract_pwacode
from .progress_dialog import ProgressDialog


class BldgExtractDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface    = iface
        self._bbox    = None
        self._aoi_tool = None
        self._rubber_band = None
        self._task    = None
        self._build_ui()
        self._update_dry_run_label()
        self._autofill_pwacode()  # อ่าน pwaCode จาก layer 'meter' ถ้ามี

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle("Building Footprint Extractor — Overture Maps V202601")
        self.resize(560, 580)
        layout = QVBoxLayout(self)

        # Safety banner
        if DRY_RUN:
            lbl = QLabel("⚠ DRY RUN MODE — จะไม่มีข้อมูลถูกส่งไปยัง production API / MongoDB")
            lbl.setStyleSheet(
                "background:#fff3cd; color:#856404; padding:6px; "
                "border:1px solid #ffc107; border-radius:4px;"
            )
            lbl.setWordWrap(True)
            layout.addWidget(lbl)

        # Collection info — อัปเดตตาม branch code ที่กรอก
        self.lblCollection = QLabel(
            f"Target collection: <b>{collection_for_branch(DEFAULT_BRANCH)}</b>",
            textFormat=Qt.RichText,
        )
        layout.addWidget(self.lblCollection)

        # AOI group
        grp_aoi = QGroupBox("Area of Interest (AOI)")
        aoi_lay = QVBoxLayout(grp_aoi)

        self.radDraw    = QRadioButton("Draw rectangle on map")
        self.radPolygon = QRadioButton("Draw polygon (click vertices)")
        self.radLayer   = QRadioButton("Use active layer extent")
        self.radSelected = QRadioButton("Use selected features extent")
        self.radManual  = QRadioButton("Enter bbox manually")
        self.radDraw.setChecked(True)
        self.radPolygon.setToolTip(
            "คลิกทีละจุดเพื่อวาด polygon, คลิกขวา/ดับเบิลคลิกเพื่อจบ — "
            "ใช้ bounding box ของ polygon เป็น AOI"
        )
        for rb in (self.radDraw, self.radPolygon, self.radLayer,
                   self.radSelected, self.radManual):
            aoi_lay.addWidget(rb)

        bbox_row = QHBoxLayout()
        bbox_row.addWidget(QLabel("xmin,ymin,xmax,ymax:"))
        self.txtBbox = QLineEdit()
        self.txtBbox.setPlaceholderText("e.g. 100.30,13.50,100.90,14.00")
        bbox_row.addWidget(self.txtBbox)
        aoi_lay.addLayout(bbox_row)

        btn_row_aoi = QHBoxLayout()
        self.btnSetAOI = QPushButton("Set AOI")
        self.btnSetAOI.clicked.connect(self._on_set_aoi)
        btn_row_aoi.addStretch()
        btn_row_aoi.addWidget(self.btnSetAOI)
        aoi_lay.addLayout(btn_row_aoi)

        self.lblAOI = QLabel("AOI: not set")
        self.lblAOI.setStyleSheet("color: #555;")
        aoi_lay.addWidget(self.lblAOI)
        layout.addWidget(grp_aoi)

        # Output group
        grp_out = QGroupBox("Output")
        out_lay = QVBoxLayout(grp_out)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Output folder:"))
        self.txtOutDir = QLineEdit(DATA_DIR)
        dir_row.addWidget(self.txtOutDir)
        self.btnBrowse = QPushButton("…")
        self.btnBrowse.setFixedWidth(30)
        self.btnBrowse.clicked.connect(self._on_browse)
        dir_row.addWidget(self.btnBrowse)
        out_lay.addLayout(dir_row)

        branch_row = QHBoxLayout()
        branch_row.addWidget(QLabel("Branch code:"))
        self.txtBranch = QLineEdit(DEFAULT_BRANCH)
        self.txtBranch.textChanged.connect(self._on_branch_changed)
        branch_row.addWidget(self.txtBranch)
        self.btnAutoBranch = QPushButton("Auto-detect")
        self.btnAutoBranch.setToolTip(
            "อ่าน pwaCode จาก layer ที่ชื่อมีคำว่า 'meter' (column pwa_code/pwacode/pwaCode)"
        )
        self.btnAutoBranch.clicked.connect(lambda: self._autofill_pwacode(verbose=True))
        branch_row.addWidget(self.btnAutoBranch)
        out_lay.addLayout(branch_row)

        self.chkLoadLayer = QCheckBox("Auto-load .gpkg into QGIS after extract")
        self.chkLoadLayer.setChecked(True)
        out_lay.addWidget(self.chkLoadLayer)
        layout.addWidget(grp_out)

        # Pipeline options
        grp_pipe = QGroupBox("Pipeline steps")
        pipe_lay = QVBoxLayout(grp_pipe)
        self.chkPostAPI  = QCheckBox("POST to pwagis API (legacy/test)")
        self.chkTopoCheck = QCheckBox("Run topology check")
        self.chkMongo    = QCheckBox("Dump to MongoDB (legacy/test)")
        # Legacy write paths (pwagis REST + direct Mongo, test creds / localhost).
        # Production inserts go through "Upload to API" (Go insert API) below, so
        # default these OFF — a live Extract run = Download → Export → Topology only.
        _legacy_tip = ("เส้นทางเดิมสำหรับทดสอบ (pwagis REST / Mongo local) — "
                       "production ใช้ปุ่ม 'Upload to API'. ปกติปล่อยปิดไว้")
        self.chkPostAPI.setToolTip(_legacy_tip)
        self.chkMongo.setToolTip(_legacy_tip)
        self.chkPostAPI.setChecked(False)
        self.chkTopoCheck.setChecked(True)
        self.chkMongo.setChecked(False)
        for chk in (self.chkPostAPI, self.chkTopoCheck, self.chkMongo):
            pipe_lay.addWidget(chk)
        # Production insert path (Go insert API) — one-click upload after extract.
        # Honors DRY_RUN like the "Upload to API" button; default OFF (opt-in per run).
        self.chkUploadApi = QCheckBox(
            "Upload to Insert API after extract"
            + ("  ·  DRY-RUN preview" if DRY_RUN else "  ·  COMMIT — เขียน production จริง")
        )
        self.chkUploadApi.setToolTip(
            "หลัง extract ส่งอาคารที่ดึงมาเข้า Go insert API (production) อัตโนมัติ — "
            "เคารพ DRY_RUN เหมือนปุ่ม 'Upload to API'. ปกติปล่อยปิดไว้")
        self.chkUploadApi.setChecked(False)
        pipe_lay.addWidget(self.chkUploadApi)
        layout.addWidget(grp_pipe)

        # Upload existing file → Insert API (Go)
        grp_up = QGroupBox("Upload existing file → Insert API")
        up_lay = QVBoxLayout(grp_up)
        up_row = QHBoxLayout()
        up_row.addWidget(QLabel("File:"))
        self.txtUploadFile = QLineEdit()
        self.txtUploadFile.setPlaceholderText("เลือกไฟล์ .gpkg / .tab / .shp / .geojson")
        up_row.addWidget(self.txtUploadFile)
        self.btnUploadBrowse = QPushButton("…")
        self.btnUploadBrowse.setFixedWidth(30)
        self.btnUploadBrowse.clicked.connect(self._on_upload_browse)
        up_row.addWidget(self.btnUploadBrowse)
        up_lay.addLayout(up_row)
        self.lblUploadApi = QLabel(
            f"API: {INSERT_API_BASE_URL}  ·  "
            + ("DRY-RUN preview (ปลอดภัย ไม่เขียน)" if DRY_RUN
               else "COMMIT — เขียน MongoDB จริง")
        )
        self.lblUploadApi.setStyleSheet("color:#555; font-size:11px;")
        up_lay.addWidget(self.lblUploadApi)
        up_btn_row = QHBoxLayout()
        up_btn_row.addStretch()
        self.btnUpload = QPushButton("Upload to API")
        self.btnUpload.clicked.connect(self._on_upload)
        up_btn_row.addWidget(self.btnUpload)
        up_lay.addLayout(up_btn_row)
        layout.addWidget(grp_up)

        # Log
        self.txtLog = QPlainTextEdit()
        self.txtLog.setReadOnly(True)
        self.txtLog.setMaximumBlockCount(500)
        self.txtLog.setFixedHeight(150)
        layout.addWidget(self.txtLog)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btnClose   = QPushButton("Close")
        self.btnExtract = QPushButton("Extract")
        self.btnExtract.setDefault(True)
        self.btnClose.clicked.connect(self.close)
        self.btnExtract.clicked.connect(self._on_extract)
        btn_row.addWidget(self.btnClose)
        btn_row.addWidget(self.btnExtract)
        layout.addLayout(btn_row)

    def _update_dry_run_label(self):
        if DRY_RUN:
            self._log("⚠ DRY_RUN=True: API POST and MongoDB insert are disabled.")

    def _on_branch_changed(self, text: str):
        self.lblCollection.setText(
            f"Target collection: <b>{collection_for_branch(text)}</b>"
        )

    def _autofill_pwacode(self, verbose: bool = False):
        """
        Scan loaded layers for one named like '*meter*' and read pwaCode from a
        pwa_code/pwacode/pwaCode column (first feature). Fills the Branch code
        field but leaves it editable so the operator can override.
        """
        try:
            found = self._scan_meter_layers()
        except Exception as exc:  # pragma: no cover - defensive against odd layers
            if verbose:
                self._log(f"Auto-detect pwaCode failed: {exc}")
            return
        if found:
            code, layer_name, field = found
            self.txtBranch.setText(code)  # field stays editable
            self._log(f"Auto-detected pwaCode={code} from layer '{layer_name}' "
                      f"(column '{field}').")
        elif verbose:
            self._log("Auto-detect: no 'meter' layer with a pwa_code column was found.")

    def _scan_meter_layers(self):
        """
        Walk QgsProject vector layers, return (pwacode, layer_name, field) for the
        first '*meter*' layer whose pwa_code column yields a value, else None.
        """
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            name = layer.name()
            if not is_meter_layer_name(name):
                continue
            field = match_pwacode_field([f.name() for f in layer.fields()])
            if not field:
                continue
            feat = next(layer.getFeatures(), None)
            if feat is None:
                continue
            code = extract_pwacode(feat[field])
            if code:
                return (code, name, field)
        return None

    # ── AOI ────────────────────────────────────────────────────────────────────

    def _on_set_aoi(self):
        if self.radManual.isChecked():
            self._parse_manual_bbox()
        elif self.radDraw.isChecked():
            self._start_draw_tool()
        elif self.radPolygon.isChecked():
            self._start_polygon_tool()
        elif self.radLayer.isChecked():
            lyr = self.iface.activeLayer()
            if lyr:
                self._bbox = get_layer_extent_bbox(lyr)
                self._show_bbox()
            else:
                QMessageBox.warning(self, "No layer", "Please select an active layer first.")
        elif self.radSelected.isChecked():
            lyr = self.iface.activeLayer()
            if lyr:
                bbox = get_selected_features_bbox(lyr)
                if bbox:
                    self._bbox = bbox
                    self._show_bbox()
                else:
                    QMessageBox.warning(self, "No selection", "No features selected.")
            else:
                QMessageBox.warning(self, "No layer", "Please select an active layer first.")

    def _parse_manual_bbox(self):
        txt = self.txtBbox.text().strip()
        try:
            parts = [float(x.strip()) for x in txt.split(",")]
            if len(parts) != 4:
                raise ValueError
            self._bbox = dict(zip(("xmin", "ymin", "xmax", "ymax"), parts))
            self._show_bbox()
        except ValueError:
            QMessageBox.warning(self, "Invalid bbox",
                                "Enter: xmin,ymin,xmax,ymax  (WGS84 decimal degrees)")

    def _start_draw_tool(self):
        canvas = self.iface.mapCanvas()
        if self._rubber_band is None:
            self._rubber_band = make_rubber_band(canvas)
        self._aoi_tool = RectangleAOITool(canvas, self._rubber_band)
        self._aoi_tool.aoi_selected.connect(self._on_aoi_drawn)
        canvas.setMapTool(self._aoi_tool)
        self._log("Draw a rectangle on the map to set AOI…")
        self.hide()

    def _start_polygon_tool(self):
        canvas = self.iface.mapCanvas()
        if self._rubber_band is None:
            self._rubber_band = make_rubber_band(canvas)
        self._aoi_tool = FreePolygonAOITool(canvas, self._rubber_band)
        self._aoi_tool.aoi_selected.connect(self._on_aoi_drawn)
        canvas.setMapTool(self._aoi_tool)
        self._log("Click vertices to draw a polygon; right-click / double-click to finish…")
        self.hide()

    def _on_aoi_drawn(self, bbox: dict):
        self._bbox = bbox
        self._show_bbox()
        self.iface.mapCanvas().unsetMapTool(self._aoi_tool)
        self.show()

    def _show_bbox(self):
        b = self._bbox
        self.lblAOI.setText(
            f"AOI: xmin={b['xmin']:.5f}  ymin={b['ymin']:.5f}  "
            f"xmax={b['xmax']:.5f}  ymax={b['ymax']:.5f}"
        )
        self.lblAOI.setStyleSheet("color: #1a6b3c; font-weight: bold;")

    # ── Extraction ────────────────────────────────────────────────────────────

    def _on_browse(self):
        path = QFileDialog.getExistingDirectory(self, "Select output folder",
                                                self.txtOutDir.text())
        if path:
            self.txtOutDir.setText(path)

    # ── Upload existing file → Insert API ───────────────────────────────────────

    def _on_upload_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select building file", self.txtOutDir.text(),
            "Building files (*.gpkg *.tab *.shp *.geojson);;All files (*.*)",
        )
        if path:
            self.txtUploadFile.setText(path)

    def _confirm_commit(self, branch: str, what: str) -> bool:
        """Confirm a real (non-dry-run) write to production, surfacing the target
        collection alias so a mistyped Branch code is caught *before* hundreds of
        inserts fail (or worse, hit the wrong collection). In DRY_RUN there is no
        write, so it auto-proceeds. Returns True to continue."""
        if DRY_RUN:
            return True
        alias = collection_for_branch(branch)
        reply = QMessageBox.question(
            self, "ยืนยัน commit เข้า production",
            f"{what}เข้า production MongoDB จริง\n\n"
            f"Branch code: {branch}\n"
            f"Collection (alias): {alias}\n"
            f"API: {INSERT_API_BASE_URL}\n\n"
            "โปรดตรวจสอบ Branch code ให้ถูกต้องก่อน — หากพิมพ์ผิด ข้อมูลจะ\n"
            "insert ไม่สำเร็จทั้งหมด (alias not registered)\n\nดำเนินการต่อหรือไม่?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _alias_hint(self, summary: dict) -> str:
        """If the upload failed because the alias is not registered, return a
        friendly Thai hint pointing at a likely Branch-code typo (else '')."""
        errs = summary.get("errors") or []
        if any("not registered" in str(e) for e in errs):
            alias = collection_for_branch(getattr(self, "_last_branch", "") or "")
            return ("\n\n⚠ ไม่พบ collection (alias) ปลายทาง: "
                    f"{alias}\n"
                    "กรุณาตรวจสอบ Branch code (pwaCode) ให้ถูกต้อง — ค่าที่กรอกอาจพิมพ์ผิด")
        return ""

    def _on_upload(self):
        path = self.txtUploadFile.text().strip()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "No file", "Please choose a valid file to upload.")
            return
        branch = self.txtBranch.text().strip() or DEFAULT_BRANCH

        if not self._confirm_commit(branch, "จะอัปโหลดไฟล์นี้"):
            self._log("Upload ยกเลิก (ไม่ยืนยัน commit เข้า production).")
            return
        self._last_branch = branch

        self.btnUpload.setEnabled(False)
        self._progress = ProgressDialog(self)
        self._progress.cancelled.connect(self._on_cancel)
        self._progress.show()

        self._task = _UploadTask(path=path, pwacode=branch)
        self._task.log_message.connect(self._on_task_log)
        self._task.progress_update.connect(self._on_task_progress)
        self._task.finished_ok.connect(self._on_upload_done)
        self._task.finished_err.connect(self._on_task_error)
        self._task.start()

    def _on_upload_done(self, summary: dict):
        self._progress.close()
        self.btnUpload.setEnabled(True)
        self._log(f"Upload complete: {summary}")
        QMessageBox.information(
            self, "Upload done",
            "Upload finished.\n"
            f"dry_run={summary.get('dry_run')}  inserted={summary.get('inserted')}\n"
            f"success={summary.get('success')}  failed={summary.get('failed')}"
            + self._alias_hint(summary),
        )

    def _on_extract(self):
        if self._bbox is None:
            QMessageBox.warning(self, "No AOI", "Please set an AOI first.")
            return

        branch    = self.txtBranch.text().strip() or DEFAULT_BRANCH
        out_dir   = self.txtOutDir.text().strip() or DATA_DIR
        run_api   = self.chkPostAPI.isChecked()
        run_topo  = self.chkTopoCheck.isChecked()
        run_mongo = self.chkMongo.isChecked()
        run_upload = self.chkUploadApi.isChecked()
        load_lyr  = self.chkLoadLayer.isChecked()

        # Confirm before committing to production (LIVE config + upload step enabled).
        # The confirm surfaces the target alias so a mistyped Branch code is caught;
        # DRY_RUN=True is a safe preview, so _confirm_commit auto-proceeds there.
        if run_upload and not self._confirm_commit(branch, "หลัง extract จะอัปโหลดอาคารที่ดึงมา"):
            self._log("Extract ยกเลิก (ไม่ยืนยัน commit เข้า production).")
            return
        self._last_branch = branch

        self.btnExtract.setEnabled(False)
        self._progress = ProgressDialog(self)
        self._progress.cancelled.connect(self._on_cancel)
        self._progress.show()

        self._task = _ExtractionTask(
            bbox=self._bbox,
            branch=branch,
            out_dir=out_dir,
            run_api=run_api,
            run_topo=run_topo,
            run_mongo=run_mongo,
            run_upload=run_upload,
        )
        self._task.log_message.connect(self._on_task_log)
        self._task.progress_update.connect(self._on_task_progress)
        self._task.finished_ok.connect(
            lambda paths: self._on_task_done(paths, load_lyr)
        )
        self._task.finished_err.connect(self._on_task_error)
        self._task.start()

    def _on_cancel(self):
        if self._task:
            self._task.cancel()

    def _on_task_log(self, msg: str):
        self._log(msg)

    def _on_task_progress(self, pct: int, msg: str):
        # pct < 0 is a sentinel for a long blocking phase with no measurable
        # progress (e.g. the DuckDB→S3 query): switch the bar to a busy/marquee
        # animation so the dialog clearly stays alive instead of freezing at 20%.
        if pct < 0:
            self._progress.set_busy(True)
        else:
            self._progress.set_progress(pct)
        self._progress.set_status(msg)
        self._log(msg)

    def _on_task_done(self, paths: dict, load_lyr: bool):
        self._progress.close()
        self.btnExtract.setEnabled(True)
        self._log(f"Extract complete. Files: {paths}")
        if load_lyr and paths.get("gpkg"):
            load_gpkg_layer(paths["gpkg"], "buildings")
            self._log("Layer loaded into QGIS.")
        msg = f"Extraction complete.\nGPKG: {paths.get('gpkg', 'N/A')}"
        up = paths.get("upload")
        if up:
            msg += ("\n\nUpload to Insert API:\n"
                    f"  inserted={up.get('inserted')}  dry_run={up.get('dry_run')}\n"
                    f"  success={up.get('success')}  failed={up.get('failed')}")
            msg += self._alias_hint(up)
        QMessageBox.information(self, "Done", msg)

    def _on_task_error(self, msg: str):
        self._progress.close()
        self.btnExtract.setEnabled(True)
        self.btnUpload.setEnabled(True)
        self._log(f"ERROR: {msg}")
        QMessageBox.critical(self, "Task Failed", msg)

    def _log(self, msg: str):
        self.txtLog.appendPlainText(msg)


# ── Background task ────────────────────────────────────────────────────────────

class _ExtractionTask(QThread):
    """
    Runs the full extraction pipeline off the main thread.
    Emits signals back to the dialog.
    """
    log_message    = pyqtSignal(str)
    progress_update = pyqtSignal(int, str)
    finished_ok    = pyqtSignal(dict)
    finished_err   = pyqtSignal(str)

    def __init__(self, bbox, branch, out_dir,
                 run_api, run_topo, run_mongo, run_upload=False):
        super().__init__()
        self._bbox       = bbox
        self._branch     = branch
        self._out_dir    = out_dir
        self._run_api    = run_api
        self._run_topo   = run_topo
        self._run_mongo  = run_mongo
        self._run_upload = run_upload
        self._cancelled  = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            self._execute()
        except Exception as exc:
            self.finished_err.emit(f"{exc}\n{traceback.format_exc()}")

    def _execute(self):
        def cb(pct, msg):
            self.progress_update.emit(pct, msg)

        # Step 1: Download
        self.log_message.emit("Step 1/6 — Downloading buildings from Overture Maps…")
        cb(0, "Downloading from Overture Maps…")
        gdf = download_buildings(self._bbox, progress_cb=cb)
        if self._cancelled:
            return
        self.log_message.emit(f"  → {len(gdf):,} buildings downloaded.")

        # Step 2: Export — busy sentinel: writing 4 formats is a single blocking
        # phase, so animate the bar instead of pinning it at 20%.
        self.log_message.emit("Step 2/6 — Exporting to .gpkg / .geojson / .shp / .tab…")
        cb(-1, "Exporting formats (gpkg / geojson / shp / tab)…")
        paths = export_buildings(gdf, self._branch, self._out_dir, progress_cb=cb)
        if self._cancelled:
            return

        topo_gdf = gdf
        topo_results = {}

        # Step 3: Topology check
        if self._run_topo:
            self.log_message.emit("Step 3/6 — Running topology check…")
            cb(40, "Topology check…")
            try:
                topo_gdf = run_topo_bldg(gdf, progress_cb=cb)
                summary  = summarise_topo_results(topo_gdf)
                self.log_message.emit(f"  → Topology summary: {summary}")
                topo_results = {
                    str(row.get("id", i)): not any(
                        str(topo_gdf.at[i, c]).lower() == "true"
                        for c in topo_gdf.columns if c.startswith("topo_")
                    )
                    for i, row in topo_gdf.iterrows()
                }
            except Exception as exc:
                self.log_message.emit(f"  ⚠ Topology check failed: {exc}")
        else:
            self.log_message.emit("Step 3/6 — Topology check skipped.")

        if self._cancelled:
            return

        # Step 4: POST to API
        if self._run_api:
            collection = collection_for_branch(self._branch)
            self.log_message.emit(f"Step 4/6 — POST to pwagis API → {collection}…")
            cb(60, "Posting to API…")
            api_result = post_buildings(topo_gdf, progress_cb=cb,
                                        collection_name=collection)
            self.log_message.emit(
                f"  → API result: success={api_result['success']}  "
                f"failed={api_result['failed']}  dry_run={api_result['dry_run']}"
            )
        else:
            self.log_message.emit("Step 4/6 — API POST skipped.")

        if self._cancelled:
            return

        # Step 5: MongoDB
        if self._run_mongo:
            self.log_message.emit("Step 5/6 — Dumping to MongoDB…")
            cb(80, "Dumping to MongoDB…")
            mongo_result = dump_buildings(
                topo_gdf, self._branch, topo_results, progress_cb=cb
            )
            self.log_message.emit(
                f"  → MongoDB: inserted={mongo_result['inserted']}  "
                f"collection={mongo_result['collection']}  "
                f"dry_run={mongo_result['dry_run']}"
            )
        else:
            self.log_message.emit("Step 5/6 — MongoDB dump skipped.")

        if self._cancelled:
            return

        # Step 6: Upload to Insert API (Go) — production insert path, honors DRY_RUN.
        # Sanitise the downloaded buildings the SAME way export does
        # (prepare_for_export: force WGS84 + keep/flatten cols) so Overture's nested
        # numpy-array columns (e.g. `sources`) become JSON-serialisable — this is the
        # same data shape the upload-from-file path sends. Use gdf (not topo_gdf) so
        # topology diagnostic columns don't leak into MongoDB.
        if self._run_upload:
            self.log_message.emit("Step 6/6 — Uploading to Insert API (Go)…")
            cb(85, "Uploading to Insert API…")
            up_gdf = prepare_for_export(gdf)
            fc = json.loads(up_gdf.to_json())
            summary = post_features(fc, pwacode=self._branch,
                                    dry_run_override=DRY_RUN, source=SOURCE_EXTRACT,
                                    progress_cb=cb)
            paths["upload"] = summary
            self.log_message.emit(
                f"  → Insert API: inserted={summary.get('inserted')}  "
                f"dry_run={summary.get('dry_run')}  "
                f"success={summary.get('success')}  failed={summary.get('failed')}"
            )
            if summary.get("errors"):
                self.log_message.emit(f"  ⚠ errors: {summary['errors'][:5]}")
        else:
            self.log_message.emit("Step 6/6 — Insert API upload skipped.")

        cb(100, "Done.")
        self.finished_ok.emit(paths)


# ── Upload task ──────────────────────────────────────────────────────────────────

class _UploadTask(QThread):
    """
    Read an existing building file (.gpkg/.tab/.shp/.geojson), convert to a
    GeoJSON FeatureCollection (WGS84), and POST it to the Go insert API.
    """
    log_message     = pyqtSignal(str)
    progress_update = pyqtSignal(int, str)
    finished_ok     = pyqtSignal(dict)
    finished_err    = pyqtSignal(str)

    def __init__(self, path, pwacode):
        super().__init__()
        self._path = path
        self._pwacode = pwacode
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            self._execute()
        except Exception as exc:
            self.finished_err.emit(f"{exc}\n{traceback.format_exc()}")

    def _execute(self):
        import geopandas as gpd

        def cb(pct, msg):
            self.progress_update.emit(pct, msg)

        self.log_message.emit(f"Reading {self._path} …")
        cb(5, "Reading file…")
        gdf = gpd.read_file(self._path)
        if self._cancelled:
            return
        if gdf.empty:
            self.finished_ok.emit({"inserted": 0, "dry_run": None,
                                   "success": 0, "failed": 0,
                                   "errors": ["empty file"]})
            return

        # Ensure WGS84
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        elif gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs("EPSG:4326")

        cb(20, f"Converting {len(gdf):,} features to GeoJSON…")
        fc = json.loads(gdf.to_json())
        if self._cancelled:
            return

        n = len(fc.get("features", []))
        self.log_message.emit(f"Uploading {n:,} features to insert API…")
        summary = post_features(fc, pwacode=self._pwacode,
                                dry_run_override=DRY_RUN, source=SOURCE_UPLOAD,
                                progress_cb=cb)
        cb(100, "Done.")
        self.finished_ok.emit(summary)
