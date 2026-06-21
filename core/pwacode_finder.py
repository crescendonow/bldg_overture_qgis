"""
pwacode_finder.py — auto-detect the branch pwaCode from a loaded QGIS layer.

ตาม requirement (note 5):
  - หา layer ที่ชื่อมีคำว่า "meter" (ไม่สน case): METER, meter, _meter, water_meter_x …
  - หา column ชื่อ pwa_code / pwacode / pwaCode (ไม่สน case)
  - อ่านค่าจาก feature แรกมาใช้เป็น branch code

ตรรกะการ match ทั้งหมดเป็น pure function (ไม่ import qgis) เพื่อให้ unit-test ได้
ส่วน glue ที่อ่าน QgsVectorLayer จริงอยู่ใน bldg_extract_dialog.py
"""

from typing import Callable, Iterable, List, Optional, Tuple

# ชื่อ column ที่ยอมรับ (เทียบแบบ lower-case)
_PWACODE_FIELDS = {"pwa_code", "pwacode"}  # pwaCode.lower() == "pwacode"

# ส่วนของชื่อ layer ที่บ่งบอกว่าเป็นชั้นมิเตอร์
_METER_TOKEN = "meter"


def is_meter_layer_name(name: str) -> bool:
    """True ถ้าชื่อ layer มีคำว่า 'meter' อยู่ส่วนใดส่วนหนึ่ง (ไม่สน case)."""
    if not name:
        return False
    return _METER_TOKEN in name.lower()


def match_pwacode_field(field_names: Iterable[str]) -> Optional[str]:
    """
    คืนชื่อ field จริง (ตามที่ปรากฏใน layer) ที่ตรงกับ pwa_code/pwacode/pwaCode
    โดยไม่สน case; ไม่พบ → None. ถ้ามีหลายตัวจะคืนตัวแรกที่เจอ.
    """
    for fname in field_names:
        if fname and fname.strip().lower() in _PWACODE_FIELDS:
            return fname
    return None


def extract_pwacode(value) -> Optional[str]:
    """
    แปลงค่าใน cell ให้เป็น branch code สะอาด ๆ (string ของตัวเลข):
      "5521040"   → "5521040"
      5521040     → "5521040"
      5521040.0   → "5521040"   (field ที่อ่านกลับมาเป็น float)
      " 5521040 " → "5521040"
      None / ""   → None
    """
    if value is None:
        return None
    # ตัวเลขจำนวนเต็มที่มาในรูป float (เช่นจาก shapefile) → ตัด .0 ทิ้ง
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        if value.is_integer():
            return str(int(value))
        return str(value).strip()
    if isinstance(value, int):
        return str(value)
    s = str(value).strip()
    if not s:
        return None
    # "5521040.0" → "5521040"
    if s.endswith(".0") and s[:-2].isdigit():
        return s[:-2]
    return s


def find_pwacode_from_layers(
    layers: Iterable[Tuple[str, List[str], Callable[[str], object]]],
) -> Optional[Tuple[str, str, str]]:
    """
    Pure orchestrator. รับ iterable ของ layer view แบบ tuple:
        (layer_name, [field_names...], get_first_value)
    โดย get_first_value() เป็น callable ที่คืนค่าของ field pwa_code จาก feature แรก
    (ผู้เรียกเป็นคน bind field name ที่ match ได้ให้แล้ว) — แต่เพื่อให้ test ได้ง่าย
    เรา resolve field ที่นี่และเรียก getter โดยส่งชื่อ field ที่ match.

    คืน (pwacode, layer_name, field_name) ของ layer แรกที่หาเจอครบ; ไม่เจอ → None.
    """
    for name, field_names, get_value in layers:
        if not is_meter_layer_name(name):
            continue
        field = match_pwacode_field(field_names)
        if field is None:
            continue
        code = extract_pwacode(get_value(field))
        if code:
            return (code, name, field)
    return None
