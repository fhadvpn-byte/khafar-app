"""قسم السير — محضر إثبات حالة (واجهة + قالب طباعة A4 مستقل)."""
from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageOps

try:
    from sig_pad_component import sig_pad
except Exception:  # pragma: no cover
    sig_pad = None

try:
    from mobile_uploader import khafar_file_uploader
except Exception:  # pragma: no cover
    khafar_file_uploader = None

KSA_TZ = timezone(timedelta(hours=3))
SAIR_FORM_ID = "sair_case_report"
SAIR_CATEGORY = "السير"
_ARCHIVE_SAVER = None

LOCATION_PRESETS = [
    "طريق العارضة العام",
    "طريق الصوارمة",
    "طريق الخوبة الجديد",
    "الخوبة العقبة",
    "طريق البحر",
]
VEHICLE_PRESETS = [
    "كامري", "سوناتا", "شاص", "هايلكس", "أكسنت", "كادينزا",
    "كورولا", "لاندكروزر", "باترول", "إلنترا", "يارس", "أخرى",
]
ROAD_SPEED_PRESETS = ["80", "90", "100", "110", "120"]
PLATE_CLASS_OPTIONS = ["بدون", "نقل خاص", "نقل عام", "حافلة"]
DESC_MODES = ["رصد سرعة آلي", "صياغة يدوية حرة"]

_AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
_WEST_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def register_archive_saver(fn) -> None:
    global _ARCHIVE_SAVER
    _ARCHIVE_SAVER = fn


def to_arabic_numerals(text) -> str:
    """تحويل الأرقام الغربية إلى مشرقية للطباعة/المعاينة فقط."""
    return str(text if text is not None else "").translate(_AR_DIGITS)


def to_western_digits(text) -> str:
    return str(text if text is not None else "").translate(_WEST_DIGITS)


def _now_ksa() -> datetime:
    return datetime.now(KSA_TZ)


def _kuwaiti_hijri(g: date) -> tuple[int, int, int]:
    jd = (
        int((1461 * (g.year + 4800 + (g.month - 14) // 12)) / 4)
        + int((367 * (g.month - 2 - 12 * ((g.month - 14) // 12))) / 12)
        - int((3 * ((g.year + 4900 + (g.month - 14) // 12) // 100)) / 4)
        + g.day
        - 32075
    )
    l = jd - 1948440 + 10632
    n = int((l - 1) / 10631)
    l = l - 10631 * n + 354
    j = int((10985 - l) / 5316) * int((50 * l) / 17719) + int(l / 5670) * int((43 * l) / 15238)
    l = l - int((30 - j) / 15) * int((17719 * j) / 50) - int(j / 16) * int((15238 * j) / 43) + 29
    m = int((24 * l) / 709)
    d = l - int((709 * m) / 24)
    y = 30 * n + j - 30
    return y, m, d


def _umm_al_qura_hijri(g: date) -> tuple[int, int, int]:
    try:
        from hijridate import Gregorian

        h = Gregorian(g.year, g.month, g.day).to_hijri()
        return int(h.year), int(h.month), int(h.day)
    except Exception:
        return _kuwaiti_hijri(g)


def default_hijri_str(d: date | None = None) -> str:
    d = d or _now_ksa().date()
    hy, hm, hd = _umm_al_qura_hijri(d)
    return f"{hy}/{hm}/{hd}هـ"


def default_time_24() -> str:
    return _now_ksa().strftime("%H:%M")


def _mime_for_logo_suffix(suffix: str) -> str:
    ext = str(suffix or "").lower().lstrip(".")
    if ext == "png":
        return "image/png"
    if ext in ("jpg", "jpeg"):
        return "image/jpeg"
    if ext == "webp":
        return "image/webp"
    return "image/png"


@st.cache_data(show_spinner=False)
def get_sair_special_logo() -> tuple[str, str]:
    """
    شعار محضر إثبات حالة الخاص (`loooo.*`) — لقسم السير فقط.
    يعيد (base64_خام, mime) بدون بادئة data: حتى لا تتكرر في <img src>.
    """
    base = Path(__file__).resolve().parent
    preferred = ("loooo.png", "loooo.jpg", "loooo.jpeg", "loooo.webp")
    candidates: list[Path] = []
    for fname in preferred:
        p = base / fname
        if p.is_file():
            candidates.append(p)
    # تغطية حالة الأحرف على Linux (Streamlit Cloud) وأي امتداد إضافي
    try:
        for p in sorted(base.glob("loooo.*")):
            if p.is_file() and p not in candidates:
                candidates.append(p)
        for p in sorted(base.glob("LOOOO.*")):
            if p.is_file() and p not in candidates:
                candidates.append(p)
    except Exception:
        pass
    for fpath in candidates:
        mime = _mime_for_logo_suffix(fpath.suffix)
        if mime not in ("image/png", "image/jpeg", "image/webp"):
            continue
        try:
            return base64.b64encode(fpath.read_bytes()).decode("utf-8"), mime
        except Exception:
            continue
    return "", "image/png"


@st.cache_data(show_spinner=False)
def get_sair_header_logo_b64() -> tuple[str, str]:
    """شعار الأمن العام إن وُجد، وإلا شعار المرور الرسمي للمطبوعات (احتياطي إن غاب loooo)."""
    special_b64, special_mime = get_sair_special_logo()
    if special_b64:
        return special_b64, special_mime
    base = Path(__file__).resolve().parent
    for fname, mime in (
        ("amn_logo.png", "image/png"),
        ("amn_logo.jpg", "image/jpeg"),
        ("amn_logo.jpeg", "image/jpeg"),
        ("public_security_logo.png", "image/png"),
        ("public_security_logo.jpg", "image/jpeg"),
        ("traffic_logo.png", "image/png"),
        ("traffic_logo.PNG", "image/png"),
        ("traffic_logo.jpg", "image/jpeg"),
        ("traffic_logo.jpeg", "image/jpeg"),
    ):
        fpath = base / fname
        if fpath.is_file():
            try:
                return base64.b64encode(fpath.read_bytes()).decode("utf-8"), mime
            except Exception:
                continue
    return "", "image/png"


def resolve_sair_print_logo(logo_b64: str = "", logo_mime: str = "image/png") -> tuple[str, str]:
    """
    شعار الطباعة لقسم السير:
    - إن وُجد loooo.* يُستخدم حصراً ويتجاهل logo_b64_global.
    - وإلا الاحتياطي الداخلي ثم الممرَّر من المستدعي.
    """
    special_b64, special_mime = get_sair_special_logo()
    if special_b64:
        return strip_data_url(special_b64), special_mime
    raw = strip_data_url(logo_b64)
    if raw:
        mime = logo_mime or "image/png"
        if raw.startswith("iVBOR"):
            mime = "image/png"
        elif raw.startswith("/9j/"):
            mime = "image/jpeg"
        return raw, mime
    return get_sair_header_logo_b64()


def compress_photo_bytes(raw: bytes, *, max_px: int = 1400, quality: int = 86) -> str:
    if not raw:
        return ""
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        if max(img.size) > max_px:
            img.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return ""


def compress_sig_bytes(raw: bytes) -> str:
    if not raw:
        return ""
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        if max(img.size) > 900:
            img.thumbnail((900, 900), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        if img.mode == "RGBA":
            img.save(buf, format="PNG", optimize=True)
        else:
            img.convert("RGB").save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return ""


def strip_data_url(raw: str) -> str:
    text = str(raw or "").strip()
    if text.startswith("data:") and "," in text:
        return text.split(",", 1)[-1].strip()
    return text


def build_speed_description(
    *,
    vehicle: str,
    plate: str,
    plate_class: str,
    speed: str,
    road_speed: str,
) -> str:
    vehicle = str(vehicle or "").strip() or "—"
    plate = str(plate or "").strip() or "—"
    speed = to_western_digits(str(speed or "").strip()) or "—"
    road_speed = to_western_digits(str(road_speed or "").strip()) or "—"
    cls = str(plate_class or "").strip()
    cls_part = f"{cls} " if cls and cls != "بدون" else ""
    return (
        f"بالتوقيت والموقع أعلاه تم الرصد آلياً لمركبة نوع {vehicle} "
        f"تحمل لوحة رقم ( {plate} ) {cls_part}"
        f"تسير بسرعة {speed} كم / ساعة وسرعة الطريق المحددة هي {road_speed} كم / ساعة"
    ).replace("  ", " ").strip()


def _img_html(b64: str, alt: str) -> str:
    payload = strip_data_url(b64)
    if not payload:
        return "&nbsp;"
    mime = "image/png" if payload.startswith("iVBOR") else "image/jpeg"
    return f'<img src="data:{mime};base64,{payload}" alt="{html.escape(alt)}">'


def build_sair_a4_html(data: dict, logo_b64: str = "", logo_mime: str = "image/png") -> str:
    """قالب محضر إثبات حالة مطابق للنموذج الرسمي — بدون QR."""
    logo_b64, logo_mime = resolve_sair_print_logo(logo_b64, logo_mime)
    logo_b64 = strip_data_url(logo_b64)
    logo_uri = (
        f"data:{logo_mime};base64,{logo_b64}"
        if logo_b64
        else ""
    )
    logo_html = (
        f'<img src="{logo_uri}" alt="شعار محضر إثبات حالة">'
        if logo_uri
        else '<div style="font-size:28px;font-weight:800;">المرور</div>'
    )

    case_no_ar = to_arabic_numerals(data.get("case_no") or "—")
    time_ar = to_arabic_numerals(data.get("time") or "—")
    date_hijri_ar = to_arabic_numerals(data.get("hijri") or "—")
    location_text = html.escape(str(data.get("location") or "—"))
    coords_ar = to_arabic_numerals(data.get("coords") or "—")
    classification_text = html.escape(str(data.get("classification") or "مخالفة مرورية"))
    description_ar = html.escape(to_arabic_numerals(data.get("description") or "—")).replace("\n", "<br>")
    unit_name = html.escape(str(data.get("unit_name") or "قسم مرور محافظة العارضة"))
    officer_name = html.escape(str(data.get("officer_name") or "—"))
    officer_rank = html.escape(str(data.get("officer_rank") or "—"))
    officer_id_ar = to_arabic_numerals(data.get("officer_id") or "—")

    right_photo_html = _img_html(data.get("photo_right") or "", "صورة الرصد")
    left_photo_html = _img_html(data.get("photo_left") or "", "صورة المركبة")
    signature_img_html = _img_html(data.get("signature") or "", "التوقيع")

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=794">
<meta name="format-detection" content="telephone=no">
<title>محضر إثبات حالة - {html.escape(case_no_ar)}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@500;700;800&display=swap');
  *, *::before, *::after {{ box-sizing: border-box; }}
  html, body {{
    margin: 0; padding: 0; background: #0d1316; color: #111111;
    font-family: 'Tajawal', 'Arial', sans-serif; direction: rtl;
    -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important;
  }}
  .toolbar {{
    max-width: 794px; margin: 10px auto; text-align: center;
  }}
  .print-btn {{
    background: linear-gradient(135deg, #d4a853, #a37a2c); color: #fff; border: none;
    padding: 10px 18px; border-radius: 8px; font-weight: 800; cursor: pointer; font-size: 14px;
  }}
  .a4-sheet {{
    width: 794px; max-width: 100%; margin: 0 auto 16px auto; padding: 14px 18px; background: #fff;
  }}
  .top-header {{
    width: 100%; border-collapse: collapse; margin-bottom: 10px; table-layout: fixed;
  }}
  .top-header td {{
    border: none; vertical-align: middle; text-align: center;
    font-size: 14px; font-weight: 700; line-height: 1.65; color: #1f2937;
  }}
  .top-header .hdr-right {{ width: 35%; }}
  .top-header .hdr-logo  {{ width: 25%; }}
  .top-header .hdr-left  {{ width: 40%; }}
  .top-header .hdr-logo img {{ height: 86px; width: auto; object-fit: contain; }}
  .case-num-line {{ margin-top: 3px; font-size: 14.5px; font-weight: 800; color: #000; }}
  .report-frame {{
    border: 1.4px solid #b8c3a8; border-radius: 14px;
    padding: 10px 12px 14px 12px; background: #ffffff;
  }}
  .report-main-title {{
    text-align: center; color: #a61c1c; font-size: 21px;
    font-weight: 800; margin: 0 0 10px 0; letter-spacing: 0.2px;
  }}
  .main-grid, .footer-grid {{
    width: 100%; border-collapse: collapse; table-layout: fixed;
  }}
  .footer-grid {{ margin-top: -1.2px; page-break-inside: avoid; break-inside: avoid; }}
  .main-grid td, .main-grid th, .footer-grid td, .footer-grid th {{
    border: 1.2px solid #4b5563; padding: 6px 8px;
    text-align: center; vertical-align: middle; word-wrap: break-word;
  }}
  .shaded {{
    background-color: #f2f3f5 !important; font-size: 13.5px; font-weight: 800; color: #111;
  }}
  .val {{
    background-color: #ffffff; font-size: 14px; font-weight: 700; color: #111; min-height: 32px;
  }}
  .coords-val {{
    direction: ltr; unicode-bidi: embed; font-size: 14px; font-weight: 700;
  }}
  .desc-val {{
    font-size: 14.5px; font-weight: 700; line-height: 1.85; padding: 10px 14px !important;
    text-align: right;
  }}
  .photo-cell {{
    height: 235px; padding: 8px !important; background: #ffffff; vertical-align: middle;
  }}
  .photo-cell img {{
    max-width: 100%; max-height: 218px; width: auto; height: auto;
    object-fit: contain; display: block; margin: 0 auto;
  }}
  .sig-cell {{
    height: 68px; padding: 4px !important; background: #ffffff; vertical-align: middle;
  }}
  .sig-cell img {{
    max-width: 100%; max-height: 60px; object-fit: contain; display: block; margin: 0 auto;
  }}
  @media print {{
    @page {{ size: A4 portrait; margin: 5mm; }}
    html, body {{
      margin: 0 !important; padding: 0 !important; width: 100% !important;
      height: auto !important; min-height: 0 !important; background: #fff !important;
      -webkit-text-size-adjust: 100% !important; text-size-adjust: 100% !important;
    }}
    .a4-sheet {{
      display: block !important; width: 100% !important; max-width: 100% !important;
      min-width: 0 !important; height: auto !important; min-height: 0 !important;
      margin: 0 !important; padding: 3mm 4mm !important; box-shadow: none !important;
    }}
    .no-print, .toolbar {{ display: none !important; }}
  }}
</style>
</head>
<body>
<div class="toolbar no-print">
  <button class="print-btn" type="button" onclick="window.print()">🖨️ طباعة / حفظ PDF (1/1)</button>
</div>
<div class="a4-sheet">
  <table class="top-header">
    <tr>
      <td class="hdr-right">
        المملكة العربية السعودية<br>
        وزارة الداخلية<br>
        الأمن العام
      </td>
      <td class="hdr-logo">
        {logo_html}
      </td>
      <td class="hdr-left">
        الإدارة العامة للمرور<br>
        إدارة مرور منطقة جازان<br>
        {unit_name}<br>
        <div class="case-num-line">رقم الحالة : {case_no_ar}</div>
      </td>
    </tr>
  </table>
  <div class="report-frame">
    <div class="report-main-title">محضر إثبات حالة</div>
    <table class="main-grid">
      <colgroup>
        <col style="width: 24%;">
        <col style="width: 26%;">
        <col style="width: 50%;">
      </colgroup>
      <tr>
        <th class="shaded">الوقت</th>
        <th class="shaded">التاريخ</th>
        <th class="shaded">الموقع</th>
      </tr>
      <tr>
        <td class="val">{time_ar}</td>
        <td class="val">{date_hijri_ar}</td>
        <td class="val">{location_text}</td>
      </tr>
      <tr>
        <th class="shaded" colspan="2">إحداثي الموقع</th>
        <th class="shaded">تصنيف الحالة</th>
      </tr>
      <tr>
        <td class="val coords-val" colspan="2">{html.escape(coords_ar)}</td>
        <td class="val">{classification_text}</td>
      </tr>
      <tr>
        <th class="shaded" colspan="3">وصف الحالة</th>
      </tr>
      <tr>
        <td class="val desc-val" colspan="3">{description_ar}</td>
      </tr>
      <tr>
        <th class="shaded" colspan="3">صور الحالة</th>
      </tr>
      <tr>
        <td class="photo-cell" colspan="2">{right_photo_html}</td>
        <td class="photo-cell">{left_photo_html}</td>
      </tr>
    </table>
    <table class="footer-grid">
      <colgroup>
        <col style="width: 9%;">
        <col style="width: 31%;">
        <col style="width: 8%;">
        <col style="width: 11%;">
        <col style="width: 12%;">
        <col style="width: 11%;">
        <col style="width: 18%;">
      </colgroup>
      <tr>
        <th class="shaded" colspan="6">معد الحالة</th>
        <th class="shaded">التوقيع</th>
      </tr>
      <tr>
        <td class="shaded">الإسم</td>
        <td class="val">{officer_name}</td>
        <td class="shaded">الرتبة</td>
        <td class="val">{officer_rank}</td>
        <td class="shaded">الرقم العام</td>
        <td class="val">{officer_id_ar}</td>
        <td class="sig-cell" rowspan="2">{signature_img_html}</td>
      </tr>
      <tr>
        <td class="shaded">الجهة</td>
        <td class="val" colspan="5">{unit_name}</td>
      </tr>
    </table>
  </div>
</div>
</body>
</html>"""


def _signed_gps_pair(text: str):
    raw = to_western_digits(str(text or "")).strip()
    m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*[,،]\s*([+-]?\d+(?:\.\d+)?)", raw)
    if not m:
        return None
    try:
        lat, lng = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            return lat, lng
    except ValueError:
        return None
    return None


def _fmt_coord(n: float) -> str:
    return f"{float(n):.6f}".rstrip("0").rstrip(".")


def _session_gps_coords(shift: dict | None = None) -> str:
    live = str(st.session_state.get("gps_live_value") or "").strip()
    pair = _signed_gps_pair(live)
    if pair:
        return f"{_fmt_coord(pair[0])}, {_fmt_coord(pair[1])}"
    shift_gps = str((shift or {}).get("default_gps") or "").strip()
    pair = _signed_gps_pair(shift_gps)
    if pair:
        return f"{_fmt_coord(pair[0])}, {_fmt_coord(pair[1])}"
    return ""


def _default_unit_name(shift: dict | None = None) -> str:
    dept = str((shift or {}).get("dept_name") or "").strip()
    if dept:
        if "قسم" in dept or "شعبة" in dept:
            return dept
        return f"قسم مرور {dept}" if "مرور" not in dept else dept
    return "قسم مرور محافظة العارضة"


def ensure_sair_session(shift: dict | None = None) -> None:
    defaults = {
        "sair_case_no": "4800000054",
        "sair_location": LOCATION_PRESETS[0],
        "sair_hijri": default_hijri_str(),
        "sair_time": default_time_24(),
        "sair_classification": "مخالفة مرورية",
        "sair_coords": _session_gps_coords(shift),
        "sair_desc_mode": DESC_MODES[0],
        "sair_vehicle_type": "كامري",
        "sair_plate": "",
        "sair_plate_class": "بدون",
        "sair_speed": "",
        "sair_road_speed": "100",
        "sair_description": "",
        "sair_photo_right_b64": "",
        "sair_photo_left_b64": "",
        "sair_officer_name": str((shift or {}).get("officer_name") or "").strip(),
        "sair_officer_rank": str((shift or {}).get("officer_rank") or "").strip(),
        "sair_officer_id": "",
        "sair_unit_name": _default_unit_name(shift),
        "sair_officer_sig_b64": "",
        "sair_desc_manual_lock": False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val
    # تحديث الإحداثيات من GPS الجلسة إن كان الحقل فارغاً أو غير صالح
    if not _signed_gps_pair(st.session_state.get("sair_coords")):
        gps_now = _session_gps_coords(shift)
        if gps_now:
            st.session_state["sair_coords"] = gps_now


def _compute_auto_desc() -> str:
    """حساب نص الوصف التلقائي من حقول السرعة الحالية (قراءة فقط)."""
    return build_speed_description(
        vehicle=st.session_state.get("sair_vehicle_type"),
        plate=st.session_state.get("sair_plate"),
        plate_class=st.session_state.get("sair_plate_class"),
        speed=st.session_state.get("sair_speed"),
        road_speed=st.session_state.get("sair_road_speed"),
    )


def collect_sair_data() -> dict:
    """قراءة بيانات النموذج فقط — ممنوع الكتابة على مفاتيح الـ widgets هنا."""
    mode = str(st.session_state.get("sair_desc_mode") or DESC_MODES[0])
    desc = str(st.session_state.get("sair_description") or "").strip()
    return {
        "case_no": to_western_digits(st.session_state.get("sair_case_no") or "").strip(),
        "location": str(st.session_state.get("sair_location") or "").strip(),
        "hijri": str(st.session_state.get("sair_hijri") or "").strip(),
        "time": to_western_digits(st.session_state.get("sair_time") or "").strip(),
        "classification": str(st.session_state.get("sair_classification") or "مخالفة مرورية").strip(),
        "coords": to_western_digits(st.session_state.get("sair_coords") or "").strip(),
        "description": desc,
        "photo_right": strip_data_url(st.session_state.get("sair_photo_right_b64") or ""),
        "photo_left": strip_data_url(st.session_state.get("sair_photo_left_b64") or ""),
        "officer_name": str(st.session_state.get("sair_officer_name") or "").strip(),
        "officer_rank": str(st.session_state.get("sair_officer_rank") or "").strip(),
        "officer_id": to_western_digits(st.session_state.get("sair_officer_id") or "").strip(),
        "unit_name": str(st.session_state.get("sair_unit_name") or "").strip(),
        "signature": strip_data_url(st.session_state.get("sair_officer_sig_b64") or ""),
        "vehicle_type": str(st.session_state.get("sair_vehicle_type") or "").strip(),
        "plate": str(st.session_state.get("sair_plate") or "").strip(),
        "plate_class": str(st.session_state.get("sair_plate_class") or "").strip(),
        "speed": to_western_digits(st.session_state.get("sair_speed") or "").strip(),
        "road_speed": to_western_digits(st.session_state.get("sair_road_speed") or "").strip(),
        "desc_mode": mode,
    }


def push_sair_to_archive(data: dict, html_doc: str, shift: dict | None = None) -> bool:
    if not callable(_ARCHIVE_SAVER):
        return False
    case_no = to_western_digits(data.get("case_no") or "").strip() or _now_ksa().strftime("%y%m%d%H%M%S")
    doc_no = f"SAIR-{case_no}"
    raw_seal = f"{doc_no}|{SAIR_FORM_ID}|{case_no}"
    verify_hash = "KHF-" + hashlib.sha256(raw_seal.encode("utf-8")).hexdigest()[:16].upper()
    fields = dict(data)
    fields["photo_right"] = data.get("photo_right") or ""
    fields["photo_left"] = data.get("photo_left") or ""
    fields["signature"] = data.get("signature") or ""
    rec = {
        "doc_no": doc_no,
        "auto_doc_no": doc_no,
        "form_id": SAIR_FORM_ID,
        "form_title": "محضر إثبات حالة",
        "category": SAIR_CATEGORY,
        "party_name": data.get("officer_name") or "معد الحالة",
        "party_id": data.get("officer_id") or "-",
        "plate_no": data.get("plate") or "-",
        "gps_coords": data.get("coords") or "بانتظار رصد الموقع",
        "created_at": _now_ksa().strftime("%Y/%m/%d - %H:%M"),
        "fields": fields,
        "legal_text": data.get("description") or "",
        "citizen_stamp_b64": "",
        "citizen_auth_mode": "محضر سير",
        "officer_stamp_b64": data.get("signature") or "",
        "attachment_b64": "",
        "attachments": [],
        "show_attachments_in_print": False,
        "officer_full": data.get("officer_name") or "",
        "duty_full": "",
        "dept_name": data.get("unit_name") or _default_unit_name(shift),
        "verify_hash": verify_hash,
        "officer_auth_mode": "توقيع معد الحالة",
        "duty_auth_mode": "",
        "duty_stamp_b64": "",
        "receiver_name": "",
        "receiver_role": "",
        "party_stamps": {},
        "live_sig_pads": {"officer": data.get("signature") or ""},
        "signatures_json": json.dumps({"officer": data.get("signature") or ""}, ensure_ascii=False),
        "archived_html": str(html_doc or ""),
    }
    try:
        return bool(_ARCHIVE_SAVER(rec))
    except Exception:
        return False


def clear_vehicle_fields_keep_officer(*, bump_case: bool = True) -> None:
    """يُستدعى فقط من on_click أو من بداية render قبل أي Widget."""
    if bump_case:
        raw = to_western_digits(st.session_state.get("sair_case_no") or "0").strip()
        digits = re.sub(r"\D", "", raw)
        if digits:
            st.session_state["sair_case_no"] = str(int(digits) + 1)
    st.session_state["sair_vehicle_type"] = "كامري"
    st.session_state["sair_plate"] = ""
    st.session_state["sair_plate_class"] = "بدون"
    st.session_state["sair_speed"] = ""
    st.session_state["sair_photo_right_b64"] = ""
    st.session_state["sair_photo_left_b64"] = ""
    st.session_state["sair_desc_manual_lock"] = False
    st.session_state["sair_description"] = ""
    st.session_state["_sair_last_auto_desc"] = ""
    st.session_state["sair_time"] = default_time_24()
    st.session_state["sair_hijri"] = default_hijri_str()


def _bump_sair_case_no() -> None:
    raw = to_western_digits(st.session_state.get("sair_case_no") or "0")
    digits = re.sub(r"\D", "", raw) or "0"
    st.session_state["sair_case_no"] = str(int(digits) + 1)


def _sync_sair_gps_from_cache() -> None:
    synced = str(st.session_state.get("_sair_gps_cache") or "").strip()
    if synced:
        st.session_state["sair_coords"] = synced
        st.session_state.pop("_sair_gps_sync_fail", None)
    else:
        st.session_state["_sair_gps_sync_fail"] = True


def _regen_sair_description() -> None:
    auto_desc = _compute_auto_desc()
    st.session_state["sair_desc_manual_lock"] = False
    st.session_state["sair_description"] = auto_desc
    st.session_state["_sair_last_auto_desc"] = auto_desc


def _on_location_preset_change() -> None:
    preset = str(st.session_state.get("sair_location_preset") or "")
    if preset and preset != "— كتابة حرة —":
        st.session_state["sair_location"] = preset


def _on_road_speed_choice_change() -> None:
    choice = str(st.session_state.get("sair_road_speed_choice") or "")
    if choice and choice != "إدخال يدوي":
        st.session_state["sair_road_speed"] = choice


def _clear_sair_photo(side: str) -> None:
    key = "sair_photo_right_b64" if side == "right" else "sair_photo_left_b64"
    st.session_state[key] = ""


def _save_sair_then_next(logo_b64: str = "", logo_mime: str = "image/png") -> None:
    """on_click: حفظ ثم تفريغ حقول المركبة قبل إعادة الرسم."""
    data = collect_sair_data()
    html_doc = build_sair_a4_html(data, logo_b64=logo_b64, logo_mime=logo_mime)
    ok = push_sair_to_archive(data, html_doc)
    clear_vehicle_fields_keep_officer(bump_case=True)
    st.session_state["_sair_flash_save_next"] = "ok" if ok else "partial"


def _apply_sair_pending_before_widgets(shift: dict | None = None) -> None:
    """تنفيذ أي طفرات معلّقة قبل رسم عناصر الواجهة."""
    # كاش GPS للقراءة داخل on_click دون إغلاق على shift
    st.session_state["_sair_gps_cache"] = _session_gps_coords(shift)
    pending = st.session_state.pop("_sair_pending", None)
    if not isinstance(pending, dict):
        return
    if pending.get("bump_case"):
        _bump_sair_case_no()
    if pending.get("sync_gps"):
        _sync_sair_gps_from_cache()
    if pending.get("regen_desc"):
        _regen_sair_description()
    if pending.get("clear_right_photo"):
        _clear_sair_photo("right")
    if pending.get("clear_left_photo"):
        _clear_sair_photo("left")
    if pending.get("clear_vehicle"):
        clear_vehicle_fields_keep_officer(bump_case=bool(pending.get("bump_case_with_clear")))


def apply_sair_archive_recall(rec: dict) -> None:
    """استدعاء محضر سير من الأرشيف إلى حقول الجلسة."""
    fields = rec.get("fields") if isinstance(rec.get("fields"), dict) else {}
    if not fields:
        try:
            fields = json.loads(rec.get("fields_json") or "{}")
        except Exception:
            fields = {}
    mapping = {
        "case_no": "sair_case_no",
        "location": "sair_location",
        "hijri": "sair_hijri",
        "time": "sair_time",
        "classification": "sair_classification",
        "coords": "sair_coords",
        "description": "sair_description",
        "photo_right": "sair_photo_right_b64",
        "photo_left": "sair_photo_left_b64",
        "officer_name": "sair_officer_name",
        "officer_rank": "sair_officer_rank",
        "officer_id": "sair_officer_id",
        "unit_name": "sair_unit_name",
        "signature": "sair_officer_sig_b64",
        "vehicle_type": "sair_vehicle_type",
        "plate": "sair_plate",
        "plate_class": "sair_plate_class",
        "speed": "sair_speed",
        "road_speed": "sair_road_speed",
        "desc_mode": "sair_desc_mode",
    }
    for src, dst in mapping.items():
        val = fields.get(src)
        if val is None or val == "":
            continue
        st.session_state[dst] = val
    if fields.get("description"):
        st.session_state["sair_desc_manual_lock"] = True
        st.session_state["_sair_last_auto_desc"] = str(fields.get("description") or "")
    st.session_state.nav_tab = "النماذج الميدانية"
    st.session_state.opened_form_id = None
    st.session_state["forms_quick_search"] = ""
    st.session_state.forms_category_tab = "🛣️ السير"
    st.session_state.active_category_tab = "🛣️ السير"
    st.session_state["_recall_flash_ok"] = True


def _ingest_upload_to_b64(uploaded, *, purpose: str = "photo") -> str:
    if uploaded is None:
        return ""
    raw = uploaded.getvalue() if hasattr(uploaded, "getvalue") else None
    if raw is None and hasattr(uploaded, "read"):
        raw = uploaded.read()
    if not raw:
        return ""
    if purpose == "signature":
        return compress_sig_bytes(raw)
    return compress_photo_bytes(raw)


def _handle_sig_pad(shift: dict | None = None) -> None:
    if sig_pad is None:
        st.caption("لوحة التوقيع غير متاحة في هذه البيئة.")
        return
    saved = str(st.session_state.get("sair_officer_sig_b64") or "").strip()
    val = sig_pad(
        key="sair_officer_sig_pad",
        title="توقيع معد الحالة (حي)",
        subtitle="ارسم ثم ارفع الإصبع — يُحفظ في الجلسة للحالات المتتالية.",
        saved=saved,
        ls_key="khafar_sair_officer_sig",
        pad_id="sair_officer",
        accent="#0038A8",
    )
    if val is None or val == "":
        return
    if isinstance(val, str) and val.strip() == "__CLEARED__":
        st.session_state["sair_officer_sig_b64"] = ""
        return
    if isinstance(val, dict):
        action = str(val.get("action") or "")
        data_url = str(val.get("data_url") or "").strip()
        if action == "clear" or data_url == "__CLEARED__":
            st.session_state["sair_officer_sig_b64"] = ""
            return
        payload = strip_data_url(data_url)
    else:
        payload = strip_data_url(str(val))
    if payload and len(payload) > 40:
        st.session_state["sair_officer_sig_b64"] = payload[:300000]


def render_sair_section(logo_b64: str, shift: dict | None = None, device_hash: str = "") -> None:
    """واجهة قسم السير داخل تبويب النماذج."""
    ensure_sair_session(shift)
    _apply_sair_pending_before_widgets(shift)

    if st.session_state.pop("_recall_flash_ok", None):
        st.success("✅ تم استدعاء محضر السير من الأرشيف — يمكنك التعديل وإعادة الحفظ/الطباعة.")
    flash_next = st.session_state.pop("_sair_flash_save_next", None)
    if flash_next == "ok":
        st.success("حُفظ المحضر وجُهّزت الحالة التالية (+1) مع الإبقاء على بيانات المعد.")
    elif flash_next == "partial":
        st.warning("فُرّغت بيانات المركبة، لكن الحفظ في الأرشيف لم يكتمل.")
    if st.session_state.pop("_sair_gps_sync_fail", None):
        st.warning("لا يوجد موقع فعلي معتمد في الجلسة بعد.")

    # loooo.* إن وُجد يتجاهل logo_b64_global بالكامل (قسم السير فقط)
    logo_hdr, logo_mime = resolve_sair_print_logo(logo_b64, "image/png")

    st.markdown(
        """
        <div class="sec-heading-green" style="margin-bottom:10px;">
          <span style="font-size:18px;font-weight:800;color:#ffffff;">🛣️ السير — محضر إثبات حالة</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # —— بيانات الحالة والموقع ——
    st.markdown("##### 1) بيانات الحالة والموقع")
    c1, c2 = st.columns([3, 1])
    with c1:
        st.text_input("رقم الحالة", key="sair_case_no")
    with c2:
        st.write("")
        st.write("")
        st.button(
            "+1",
            key="sair_case_plus",
            use_container_width=True,
            help="زيادة رقم الحالة بمقدار 1",
            on_click=_bump_sair_case_no,
        )

    loc_col, _ = st.columns([1, 0.01])
    with loc_col:
        st.selectbox(
            "اقتراح موقع سريع",
            options=["— كتابة حرة —"] + LOCATION_PRESETS,
            key="sair_location_preset",
            on_change=_on_location_preset_change,
        )
        st.text_input("الموقع", key="sair_location")

    d1, d2 = st.columns(2)
    with d1:
        st.text_input("التاريخ الهجري", key="sair_hijri", help="مثال: 1448/6/14هـ")
    with d2:
        st.text_input("الوقت (24 ساعة)", key="sair_time", help="مثال: 16:58")

    st.text_input("تصنيف الحالة", key="sair_classification")
    gps_hint = st.session_state.get("_sair_gps_cache") or _session_gps_coords(shift)
    st.text_input(
        "إحداثي الموقع",
        key="sair_coords",
        help=f"يُملأ من GPS الجلسة عند التوفر. الحالي: {gps_hint or '—'}",
    )
    st.button(
        "📍 مزامنة الإحداثيات من GPS الجلسة",
        key="sair_sync_gps",
        on_click=_sync_sair_gps_from_cache,
    )

    # —— وصف الحالة ——
    st.markdown("##### 2) وصف الحالة")
    st.radio("وضع الوصف", options=DESC_MODES, key="sair_desc_mode", horizontal=True)
    mode = st.session_state.get("sair_desc_mode") or DESC_MODES[0]
    auto_desc = ""
    if mode == DESC_MODES[0]:
        v1, v2 = st.columns(2)
        with v1:
            st.selectbox("نوع المركبة", options=VEHICLE_PRESETS, key="sair_vehicle_type")
            st.text_input("رقم اللوحة", key="sair_plate", placeholder="أ ق ب 7894 أو س 219711")
            st.selectbox("فئة اللوحة (اختياري)", options=PLATE_CLASS_OPTIONS, key="sair_plate_class")
        with v2:
            st.text_input("سرعة المركبة المرصودة (كم/ساعة)", key="sair_speed")
            st.selectbox(
                "سرعة الطريق المحددة (كم/ساعة)",
                options=ROAD_SPEED_PRESETS + ["إدخال يدوي"],
                key="sair_road_speed_choice",
                on_change=_on_road_speed_choice_change,
            )
            # مزامنة اختيار القائمة إلى حقل السرعة قبل إنشاء text_input
            road_choice = str(st.session_state.get("sair_road_speed_choice") or "")
            if road_choice and road_choice != "إدخال يدوي":
                st.session_state["sair_road_speed"] = road_choice
            st.text_input("سرعة الطريق (يدوي إن لزم)", key="sair_road_speed")

        auto_desc = _compute_auto_desc()
        last_auto = str(st.session_state.get("_sair_last_auto_desc") or "")
        # تحديث الوصف التلقائي قبل رسم text_area فقط
        if not st.session_state.get("sair_desc_manual_lock"):
            if ("sair_description" not in st.session_state) or (auto_desc != last_auto):
                st.session_state["sair_description"] = auto_desc
                st.session_state["_sair_last_auto_desc"] = auto_desc
        st.caption("النص يتولد تلقائياً — يمكنك تعديله يدوياً قبل الطباعة.")

    desc_val = st.text_area("وصف الحالة", key="sair_description", height=110)
    if mode == DESC_MODES[0]:
        auto_now = auto_desc or _compute_auto_desc()
        if str(desc_val or "").strip() and str(desc_val).strip() != auto_now:
            st.session_state["sair_desc_manual_lock"] = True
        b_unlock, _ = st.columns([1, 2])
        with b_unlock:
            st.button(
                "🔄 إعادة توليد الوصف من الحقول",
                key="sair_regen_desc",
                on_click=_regen_sair_description,
            )

    # —— الصور ——
    st.markdown("##### 3) صور الحالة")
    p1, p2 = st.columns(2)
    with p1:
        st.caption("الصورة اليمنى (الرصد / اللوحة)")
        if khafar_file_uploader:
            right_up = khafar_file_uploader(
                "رفع/التقاط الصورة اليمنى",
                key="sair_photo_right_mu",
                accept_multiple_files=False,
                allow_pdf=False,
            )
        else:
            right_up = st.file_uploader("الصورة اليمنى", type=["jpg", "jpeg", "png", "webp"], key="sair_photo_right_up")
        if right_up is not None:
            files = right_up if isinstance(right_up, list) else [right_up]
            if files:
                b64 = _ingest_upload_to_b64(files[0], purpose="photo")
                if b64:
                    st.session_state["sair_photo_right_b64"] = b64
        if st.session_state.get("sair_photo_right_b64"):
            st.image(
                f"data:image/jpeg;base64,{st.session_state['sair_photo_right_b64']}",
                use_container_width=True,
            )
            st.button(
                "🗑️ حذف اليمنى",
                key="sair_del_right",
                on_click=_clear_sair_photo,
                kwargs={"side": "right"},
            )
    with p2:
        st.caption("الصورة اليسرى (المركبة / الطريق)")
        if khafar_file_uploader:
            left_up = khafar_file_uploader(
                "رفع/التقاط الصورة اليسرى",
                key="sair_photo_left_mu",
                accept_multiple_files=False,
                allow_pdf=False,
            )
        else:
            left_up = st.file_uploader("الصورة اليسرى", type=["jpg", "jpeg", "png", "webp"], key="sair_photo_left_up")
        if left_up is not None:
            files = left_up if isinstance(left_up, list) else [left_up]
            if files:
                b64 = _ingest_upload_to_b64(files[0], purpose="photo")
                if b64:
                    st.session_state["sair_photo_left_b64"] = b64
        if st.session_state.get("sair_photo_left_b64"):
            st.image(
                f"data:image/jpeg;base64,{st.session_state['sair_photo_left_b64']}",
                use_container_width=True,
            )
            st.button(
                "🗑️ حذف اليسرى",
                key="sair_del_left",
                on_click=_clear_sair_photo,
                kwargs={"side": "left"},
            )

    if khafar_file_uploader:
        batch = khafar_file_uploader(
            "رفع صورتين دفعة واحدة (الأولى يمين / الثانية يسار)",
            key="sair_photo_batch_mu",
            accept_multiple_files=True,
            allow_pdf=False,
        )
    else:
        batch = st.file_uploader(
            "رفع صورتين دفعة واحدة",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            key="sair_photo_batch_up",
        )
    if batch:
        files = batch if isinstance(batch, list) else [batch]
        if len(files) >= 1:
            b64 = _ingest_upload_to_b64(files[0], purpose="photo")
            if b64:
                st.session_state["sair_photo_right_b64"] = b64
        if len(files) >= 2:
            b64 = _ingest_upload_to_b64(files[1], purpose="photo")
            if b64:
                st.session_state["sair_photo_left_b64"] = b64

    # —— معد الحالة ——
    st.markdown("##### 4) بيانات معد الحالة والتوقيع (تُثبَّت في الجلسة)")
    o1, o2 = st.columns(2)
    with o1:
        st.text_input("الإسم", key="sair_officer_name")
        st.text_input("الرتبة", key="sair_officer_rank")
    with o2:
        st.text_input("الرقم العام", key="sair_officer_id")
        st.text_input("الجهة", key="sair_unit_name", help="تظهر في الترويسة اليسرى وفي خانة الجهة أسفل الجدول")

    _handle_sig_pad(shift)
    if khafar_file_uploader:
        sig_up = khafar_file_uploader(
            "أو ارفع صورة توقيع جاهزة (شفافة/بيضاء)",
            key="sair_sig_upload_mu",
            accept_multiple_files=False,
            allow_pdf=False,
            preserve_alpha=True,
        )
    else:
        sig_up = st.file_uploader(
            "رفع صورة توقيع",
            type=["png", "jpg", "jpeg", "webp"],
            key="sair_sig_upload",
        )
    if sig_up is not None:
        files = sig_up if isinstance(sig_up, list) else [sig_up]
        if files:
            b64 = _ingest_upload_to_b64(files[0], purpose="signature")
            if b64:
                st.session_state["sair_officer_sig_b64"] = b64
                st.success("تم اعتماد صورة التوقيع في الجلسة.")

    if st.session_state.get("sair_officer_sig_b64"):
        st.image(
            f"data:image/png;base64,{strip_data_url(st.session_state['sair_officer_sig_b64'])}",
            width=220,
        )

    data = collect_sair_data()
    a4_html = build_sair_a4_html(data, logo_b64=logo_hdr, logo_mime=logo_mime)

    st.markdown("##### 5) الحفظ والمعاينة والطباعة")
    a, b, c = st.columns(3)
    with a:
        if st.button("💾 حفظ في الأرشيف", key="sair_save_arch", use_container_width=True, type="primary"):
            ok = push_sair_to_archive(data, a4_html, shift=shift)
            if ok:
                st.success(f"تم حفظ المحضر في الأرشيف برقم {data.get('case_no')}.")
            else:
                st.error("تعذر الحفظ في الأرشيف — تأكد من ربط الجهاز.")
    with b:
        st.button(
            "🔄 حفظ وتفريغ بيانات المركبة لحالة تالية",
            key="sair_save_next",
            use_container_width=True,
            on_click=_save_sair_then_next,
            kwargs={"logo_b64": logo_hdr, "logo_mime": logo_mime},
        )
    with c:
        st.download_button(
            "⬇️ تنزيل HTML",
            data=a4_html.encode("utf-8"),
            file_name=f"SAIR-{data.get('case_no') or 'case'}.html",
            mime="text/html",
            use_container_width=True,
            key="sair_dl_html",
        )

    st.markdown("#### 📄 معاينة محضر إثبات حالة (A4)")
    components.html(a4_html, height=1180, scrolling=True)
