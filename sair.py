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

from khafar_print_portal import KHAFAR_PRINT_PORTAL_CSS


def _js_embed(value: str) -> str:
    """تمرير نص إلى JS عبر json.dumps مع حماية إغلاق وسم script."""
    return json.dumps(value if value is not None else "", ensure_ascii=False).replace("</", "<\\/")

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

VEHICLE_PRESETS = [
    "كامري", "هايلكس", "شاص", "سوناتا", "أكسنت",
    "إلنترا", "كورولا", "لاندكروزر", "كادينزا",
]
ROAD_SPEED_PRESETS = ["80", "90", "100", "110", "120"]
PLATE_CLASS_OPTIONS = ["خاص", "نقل خاص", "نقل عام", "حافلة", "دبلوماسي", "مؤقت"]
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


@st.cache_data(show_spinner=False, max_entries=20)
def _optimize_sair_photo(raw_bytes: bytes) -> str:
    """ضغط ذكي لمرة واحدة مع كاش — يعيد data:image/jpeg;base64,... (~70–100KB)."""
    if not raw_bytes:
        return ""
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((1150, 850), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=78, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return ""


def _render_pdf_first_page_bytes(raw: bytes) -> bytes:
    """صيّر الصفحة الأولى من PDF إلى PNG bytes بدقة معتدلة."""
    if not raw:
        return b""
    # 1) pypdfium2
    try:
        import pypdfium2 as pdfium  # type: ignore

        doc = pdfium.PdfDocument(raw)
        if len(doc) < 1:
            return b""
        page = doc[0]
        scale = 130 / 72.0  # ≈ dpi=130
        pil = page.render(scale=scale).to_pil()
        buf = io.BytesIO()
        pil.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        pass
    # 2) PyMuPDF
    try:
        import fitz  # type: ignore

        doc = fitz.open(stream=raw, filetype="pdf")
        if doc.page_count < 1:
            return b""
        page = doc.load_page(0)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        return pix.tobytes("png")
    except Exception:
        pass
    # 3) pdf2image
    try:
        from pdf2image import convert_from_bytes  # type: ignore

        pages = convert_from_bytes(raw, dpi=130, first_page=1, last_page=1)
        if not pages:
            return b""
        buf = io.BytesIO()
        pages[0].convert("RGB").save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return b""


def compress_photo_bytes(raw: bytes, *, max_px: int = 1400, quality: int = 86) -> str:
    """توافق خلفي — يوجّه للضغط الذكي المخزّن في الكاش ويعيد base64 خام."""
    if not raw:
        return ""
    # PDF؟
    if raw[:5] == b"%PDF-" or raw[:4] == b"%PDF":
        rendered = _render_pdf_first_page_bytes(raw)
        if not rendered:
            return ""
        raw = rendered
    data_url = _optimize_sair_photo(bytes(raw))
    return strip_data_url(data_url)


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
    owner_name: str = "",
) -> str:
    vehicle = str(vehicle or "").strip() or "—"
    plate = str(plate or "").strip() or "—"
    speed = to_western_digits(str(speed or "").strip()) or "—"
    road_speed = to_western_digits(str(road_speed or "").strip()) or "—"
    cls = str(plate_class or "").strip()
    owner = str(owner_name or "").strip()
    cls_part = f"فئة {cls} " if cls else ""
    owner_part = f"والعائدة لمالكها / {owner} " if owner else ""
    return (
        f"بالتوقيت والموقع أعلاه تم الرصد آلياً لمركبة نوع {vehicle} "
        f"تحمل لوحة رقم ( {plate} ) {cls_part}{owner_part}"
        f"تسير بسرعة {speed} كم/ساعة وسرعة الطريق المحددة هي {road_speed} كم/ساعة"
    ).replace("  ", " ").strip()


_SAIR_LOGO_PH = "__SAIR_LOGO_SRC__"
_SAIR_PHOTO_PH = "__SAIR_PHOTO_SRC__"
_SAIR_SIG_PH = "__SAIR_SIG_SRC__"


def _sair_data_uri(*, b64: str, default_mime: str = "image/jpeg") -> str:
    payload = strip_data_url(b64)
    if not payload or len(payload) < 32:
        return ""
    mime = default_mime
    if payload.startswith("iVBOR"):
        mime = "image/png"
    elif payload.startswith("/9j/"):
        mime = "image/jpeg"
    return f"data:{mime};base64,{payload}"


def _img_html(*, b64: str = "", alt: str = "", src: str = "") -> str:
    """يبني وسم صورة — src صريح أو base64، بالأسماء فقط لمنع خلط الصورة/التوقيع."""
    uri = str(src or "").strip() or _sair_data_uri(b64=b64)
    if not uri:
        return "&nbsp;"
    return (
        f'<img src="{uri}" alt="{html.escape(alt)}" '
        f'data-khafar-img="{html.escape(alt)}">'
    )


def _resolve_case_photo_b64(data: dict) -> str:
    """صورة الحالة فقط — لا تقرأ مفتاح التوقيع أبداً."""
    for key in ("photo", "photo_right", "photo_left"):
        raw = strip_data_url(str((data or {}).get(key) or "").strip())
        if raw and len(raw) >= 32:
            return raw
    return ""


def _resolve_officer_signature_b64(data: dict) -> str:
    """توقيع معد الحالة فقط — لا يسقط أبداً إلى صورة الحالة."""
    data = data or {}
    raw = strip_data_url(str(data.get("signature") or "").strip())
    if not raw or len(raw) < 32:
        return ""
    # حراسة: إن تطابق التوقيع مع صورة الحالة فهو خلط — أفرغ خانة التوقيع
    case_photo = _resolve_case_photo_b64(data)
    if case_photo and raw == case_photo:
        return ""
    return raw


def build_sair_a4_html(*, data: dict, logo_b64: str = "", logo_mime: str = "image/png") -> str:
    """قالب محضر إثبات حالة مطابق للنموذج الرسمي — بدون QR."""
    logo_b64, logo_mime = resolve_sair_print_logo(logo_b64, logo_mime)
    logo_b64 = strip_data_url(logo_b64)
    logo_uri = _sair_data_uri(b64=logo_b64, default_mime=logo_mime or "image/png")

    case_no_ar = to_arabic_numerals(data.get("case_no") or "—")
    time_ar = to_arabic_numerals(data.get("time") or "—")
    date_hijri_ar = to_arabic_numerals(data.get("hijri") or "—")
    location_text = html.escape(str(data.get("location") or "—"))
    coords_ar = to_arabic_numerals(data.get("coords") or "—")
    classification_text = html.escape(str(data.get("classification") or "مخالفة مرورية"))
    owner_raw = str(data.get("owner_name") or "").strip()
    owner_display = html.escape(owner_raw) if owner_raw else "—"
    description_ar = html.escape(to_arabic_numerals(data.get("description") or "—")).replace("\n", "<br>")
    unit_name = html.escape(str(data.get("unit_name") or "قسم مرور محافظة العارضة"))
    officer_name = html.escape(str(data.get("officer_name") or "—"))
    officer_rank = html.escape(str(data.get("officer_rank") or "—"))
    officer_id_ar = to_arabic_numerals(data.get("officer_id") or "—")

    # فصل صارم: صورة الحالة ≠ التوقيع — URIs مرة واحدة فقط للمعاينة
    case_photo_b64 = _resolve_case_photo_b64(data)
    officer_signature_b64 = _resolve_officer_signature_b64(data)
    photo_uri = _sair_data_uri(b64=case_photo_b64, default_mime="image/jpeg") if case_photo_b64 else ""
    sig_uri = (
        _sair_data_uri(b64=officer_signature_b64, default_mime="image/png")
        if officer_signature_b64
        else ""
    )

    def _logo_block(src: str) -> str:
        if src:
            return f'<img class="sair-logo" src="{src}" alt="شعار محضر إثبات حالة">'
        return '<div style="font-size:28px;font-weight:800;">المرور</div>'

    # معاينة حية: وسائط فعلية مرة واحدة
    logo_html = _logo_block(logo_uri)
    single_photo_html = _img_html(src=photo_uri, alt="صورة الحالة") if photo_uri else "&nbsp;"
    signature_img_html = (
        _img_html(src=sig_uri, alt="توقيع معد الحالة") if sig_uri else "&nbsp;"
    )
    # قوالب طباعة خفيفة: رموز نائبة تُستبدل في المتصفح من عناصر المعاينة
    logo_html_ph = _logo_block(_SAIR_LOGO_PH if logo_uri else "")
    single_photo_html_ph = (
        _img_html(src=_SAIR_PHOTO_PH, alt="صورة الحالة") if photo_uri else "&nbsp;"
    )
    signature_img_html_ph = (
        _img_html(src=_SAIR_SIG_PH, alt="توقيع معد الحالة") if sig_uri else "&nbsp;"
    )

    report_css = f"""
  @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@500;700;800&display=swap');
  *, *::before, *::after {{ box-sizing: border-box; }}
  html, body {{
    margin: 0; padding: 0; background: #0d1316; color: #111111;
    font-family: 'Tajawal', 'Arial', sans-serif !important; direction: rtl;
    -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important;
  }}
  .a4-sheet, .a4-sheet *, .report-frame, .report-frame *,
  .main-grid, .main-grid *, .footer-grid, .footer-grid * {{
    font-family: 'Tajawal', 'Arial', sans-serif !important;
  }}
  .toolbar {{
    max-width: 794px; margin: 10px auto; text-align: center;
  }}
  .print-btn {{
    background: linear-gradient(135deg, #d4a853, #a37a2c); color: #fff; border: none;
    padding: 10px 18px; border-radius: 8px; font-weight: 800; cursor: pointer; font-size: 14px;
  }}
  .a4-sheet {{
    width: 794px; max-width: 100%; margin: 0 auto 16px auto; padding: 10px 14px;
    background: #fff; border: none !important; box-shadow: none !important; outline: none !important;
  }}
  .top-header {{
    width: 100%; border-collapse: collapse; margin-bottom: 10px; table-layout: fixed;
  }}
  .top-header td {{
    border: none; vertical-align: middle; text-align: center;
    font-size: 14.5px; font-weight: 700; line-height: 1.7; color: #1f2937;
  }}
  .top-header .hdr-right {{ width: 35%; }}
  .top-header .hdr-logo  {{ width: 25%; }}
  .top-header .hdr-left  {{ width: 40%; }}
  .top-header .hdr-logo img {{ height: 96px; width: auto; object-fit: contain; }}
  .case-num-line {{ margin-top: 3px; font-size: 14.5px; font-weight: 800; color: #000; }}
  /* إطار واحد فقط — بدون إطار مزدوج مع .a4-sheet */
  .report-frame {{
    border: none !important; border-radius: 0 !important;
    padding: 4px 0 0 0; background: #ffffff;
    box-shadow: none !important; outline: none !important;
  }}
  .report-main-title {{
    text-align: center; color: #a61c1c; font-size: 23px;
    font-weight: 800; margin: 0 0 10px 0; letter-spacing: 0.2px;
  }}
  .main-grid, .footer-grid {{
    width: 100%; border-collapse: collapse; table-layout: fixed;
  }}
  .footer-grid {{ margin-top: -1.2px; page-break-inside: avoid; break-inside: avoid; }}
  .main-grid td, .main-grid th, .footer-grid td, .footer-grid th {{
    border: 1.2px solid #4b5563; padding: 8px 8px;
    text-align: center; vertical-align: middle;
    overflow-wrap: normal; word-wrap: normal; word-break: keep-all;
    hyphens: none; -webkit-hyphens: none;
  }}
  .shaded {{
    background-color: #f2f3f5 !important; font-size: 14.5px; font-weight: 800; color: #111;
  }}
  /* عناوين معد الحالة لا تنكسر أبداً في منتصف الكلمة */
  .footer-grid .shaded {{
    white-space: nowrap !important;
    word-break: keep-all !important;
    overflow-wrap: normal !important;
    line-height: 1.35 !important;
    padding: 8px 4px !important;
    font-size: 13.5px !important;
  }}
  .footer-grid .val {{
    overflow-wrap: anywhere;
    word-break: normal;
  }}
  .val {{
    background-color: #ffffff; font-size: 15px; font-weight: 700; color: #111; min-height: 34px;
  }}
  .coords-val {{
    direction: ltr; unicode-bidi: embed; font-size: 15px; font-weight: 700;
  }}
  .desc-val {{
    min-height: 72px; padding: 12px 14px !important;
    font-size: 15px; font-weight: 700; line-height: 1.75; text-align: right;
  }}
  /* ارتفاع مرن للصورة — بدون فراغ أبيض ثابت يدفع لصفحة ثانية */
  .photo-cell {{
    height: auto !important; min-height: 0 !important; max-height: none !important;
    padding: 8px !important; background: #ffffff;
    vertical-align: middle; text-align: center;
  }}
  .photo-cell img {{
    max-width: 96%; max-height: 210px; width: auto; height: auto;
    object-fit: contain; display: block; margin: 0 auto;
  }}
  .sig-cell {{
    height: 78px; padding: 4px !important; background: #ffffff; vertical-align: middle;
    overflow: hidden !important;
  }}
  .sig-cell img {{
    max-width: 100% !important; max-height: 68px !important; width: auto !important; height: auto !important;
    object-fit: contain !important; display: block !important; margin: 0 auto !important;
  }}
  .sig-cell img[data-khafar-img="صورة الحالة"] {{
    display: none !important; /* حراسة أخيرة: لا تُعرض صورة الحالة داخل خانة التوقيع */
  }}
  @media print {{
    @page {{ size: A4 portrait; margin: 6mm; }}
    html, body {{
      margin: 0 !important; padding: 0 !important; width: 100% !important;
      height: auto !important; min-height: 0 !important; background: #fff !important;
      -webkit-text-size-adjust: 100% !important; text-size-adjust: 100% !important;
      font-family: 'Tajawal', 'Arial', sans-serif !important;
    }}
    .a4-sheet {{
      display: block !important; width: 100% !important; max-width: 100% !important;
      min-width: 0 !important; height: auto !important; min-height: 0 !important;
      margin: 0 !important; padding: 8px 10px !important;
      border: none !important; box-shadow: none !important; outline: none !important;
      page-break-after: avoid !important; break-after: avoid !important;
    }}
    .report-frame {{
      border: none !important; box-shadow: none !important; outline: none !important;
      padding: 2px 0 0 0 !important;
    }}
    .photo-cell {{
      height: auto !important; padding: 6px !important;
    }}
    .photo-cell img {{
      max-height: 190px !important;
    }}
    .main-grid, .footer-grid, .footer-grid tr {{
      page-break-inside: avoid !important; break-inside: avoid !important;
    }}
    .no-print, .toolbar {{ display: none !important; }}
  }}
"""

    def _make_sheet(*, logo_block: str, photo_block: str, sig_block: str) -> str:
        return f"""
<div class="a4-sheet">
  <table class="top-header">
    <tr>
      <td class="hdr-right">
        المملكة العربية السعودية<br>
        وزارة الداخلية<br>
        الأمن العام
      </td>
      <td class="hdr-logo">
        {logo_block}
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
        <td class="shaded">مالك المركبة</td>
        <td class="val" colspan="2">{owner_display}</td>
      </tr>
      <tr>
        <th class="shaded" colspan="3">وصف الحالة</th>
      </tr>
      <tr>
        <td class="val desc-val" colspan="3">{description_ar}</td>
      </tr>
      <tr>
        <th class="shaded" colspan="3">صورة الحالة</th>
      </tr>
      <tr>
        <td class="photo-cell" colspan="3" data-role="case-photo">{photo_block}</td>
      </tr>
    </table>
    <table class="footer-grid">
      <colgroup>
        <col style="width: 11%;">
        <col style="width: 27%;">
        <col style="width: 10%;">
        <col style="width: 14%;">
        <col style="width: 14%;">
        <col style="width: 9%;">
        <col style="width: 15%;">
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
        <td class="shaded">الرقم&nbsp;العام</td>
        <td class="val">{officer_id_ar}</td>
        <td class="sig-cell" rowspan="2" data-role="officer-signature">{sig_block}</td>
      </tr>
      <tr>
        <td class="shaded">الجهة</td>
        <td class="val" colspan="5">{unit_name}</td>
      </tr>
    </table>
  </div>
</div>
""".strip()

    # معاينة حية: وسائط مضمّنة مرة واحدة فقط
    portal_sheet_html = _make_sheet(
        logo_block=logo_html,
        photo_block=single_photo_html,
        sig_block=signature_img_html,
    )
    # قوالب طباعة خفيفة بدون تكرار Base64
    portal_sheet_light = _make_sheet(
        logo_block=logo_html_ph,
        photo_block=single_photo_html_ph,
        sig_block=signature_img_html_ph,
    )

    # مستند مستقل لـ window.open — رموز نائبة فقط (تُملأ من المعاينة)
    full_print_html = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=794">
<meta name="format-detection" content="telephone=no">
<title>محضر إثبات حالة - {html.escape(case_no_ar)}</title>
<link id="khafar-tajawal-font" rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tajawal:wght@500;700;800&display=swap">
<style>{report_css}</style>
</head>
<body style="background:#fff;color:#111;">
{portal_sheet_light}
<script>
(function(){{
  function go(){{
    try {{
      var isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
        || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
      document.body.style.zoom = "1";
      var contentH = document.documentElement.scrollHeight || document.body.scrollHeight || 0;
      var zoom = 1;
      if (isIOS) {{ if (contentH > 900) zoom = Math.min(1, 900 / contentH); }}
      else if (contentH > 1120) {{ zoom = 1120 / contentH; }}
      document.body.style.zoom = String(zoom);
    }} catch (e0) {{}}
    try {{ window.focus(); }} catch (e1) {{}}
    try {{ window.print(); }} catch (e2) {{}}
  }}
  window.addEventListener("load", function(){{ setTimeout(go, 280); }});
  setTimeout(go, 600);
}})();
</script>
</body>
</html>"""

    # تحميل Tajawal في الصفحة الأب فوراً (خارج @media print) ثم أنماط المحضر عند الطباعة
    portal_print_css = (
        "@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@500;700;800&display=swap');\n"
        + "#khafar-print-portal, #khafar-print-portal * {"
        " font-family: 'Tajawal', 'Arial', sans-serif !important;"
        "}\n"
        + KHAFAR_PRINT_PORTAL_CSS.replace("margin: 5mm;", "margin: 6mm;")
        + "\n@media print {\n"
        + report_css
        + "\n}\n"
    )

    safe_full_html_js = _js_embed(full_print_html)
    safe_portal_sheet_js = _js_embed(portal_sheet_light)
    safe_portal_css_js = _js_embed(portal_print_css)

    safe_print_js = f"""
<script>
(function(){{
  var FULL_HTML = {safe_full_html_js};
  var PORTAL_SHEET = {safe_portal_sheet_js};
  var PORTAL_CSS = {safe_portal_css_js};

  function readPreviewMedia(){{
    var logoEl = document.querySelector(".a4-sheet .hdr-logo img.sair-logo, .a4-sheet .hdr-logo img");
    var photoEl = document.querySelector('[data-role="case-photo"] img');
    var sigEl = document.querySelector('[data-role="officer-signature"] img');
    return {{
      logo: logoEl ? (logoEl.getAttribute("src") || "") : "",
      photo: photoEl ? (photoEl.getAttribute("src") || "") : "",
      sig: sigEl ? (sigEl.getAttribute("src") || "") : ""
    }};
  }}

  function withMedia(s){{
    var m = readPreviewMedia();
    return String(s || "")
      .split("{_SAIR_LOGO_PH}").join(m.logo || "")
      .split("{_SAIR_PHOTO_PH}").join(m.photo || "")
      .split("{_SAIR_SIG_PH}").join(m.sig || "");
  }}

  function getParentCtx(){{
    try {{
      if (window.parent && window.parent !== window) {{
        var d = null;
        try {{ d = window.parent.document; }} catch (eP) {{ d = null; }}
        if (d && d.body) return {{ win: window.parent, doc: d }};
      }}
    }} catch (e0) {{}}
    try {{
      if (window.top && window.top !== window) {{
        var d2 = null;
        try {{ d2 = window.top.document; }} catch (eT) {{ d2 = null; }}
        if (d2 && d2.body) return {{ win: window.top, doc: d2 }};
      }}
    }} catch (e1) {{}}
    return null;
  }}

  function ensureTajawal(doc){{
    try {{
      if (!doc.getElementById("khafar-tajawal-font")) {{
        var link = doc.createElement("link");
        link.id = "khafar-tajawal-font";
        link.rel = "stylesheet";
        link.href = "https://fonts.googleapis.com/css2?family=Tajawal:wght@500;700;800&display=swap";
        (doc.head || doc.documentElement).appendChild(link);
      }}
    }} catch (eFont) {{}}
  }}

  function injectPortal(ctx){{
    var doc = ctx.doc;
    ensureTajawal(doc);
    var cssEl = doc.getElementById("khafar-print-portal-css");
    if (!cssEl) {{
      cssEl = doc.createElement("style");
      cssEl.id = "khafar-print-portal-css";
      (doc.head || doc.documentElement).appendChild(cssEl);
    }}
    cssEl.textContent = PORTAL_CSS;
    var portal = doc.getElementById("khafar-print-portal");
    if (!portal) {{
      portal = doc.createElement("div");
      portal.id = "khafar-print-portal";
      doc.body.appendChild(portal);
    }}
    portal.setAttribute("dir", "rtl");
    portal.innerHTML = withMedia(PORTAL_SHEET);
    return portal;
  }}

  function applyZoom(ctx, portal){{
    try {{
      var isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
        || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
      try {{ ctx.doc.body.style.zoom = "1"; }} catch (eZ0) {{}}
      if (portal) {{ try {{ portal.style.zoom = "1"; }} catch (eZ1) {{}} }}
      void (portal && portal.offsetHeight);
      var contentH = (portal && (portal.scrollHeight || portal.offsetHeight)) || 0;
      if (!contentH) {{
        try {{ contentH = ctx.doc.documentElement.scrollHeight || ctx.doc.body.scrollHeight || 0; }} catch (eZ2) {{ contentH = 0; }}
      }}
      var zoom = 1;
      if (isIOS) {{
        if (contentH > 900) zoom = Math.min(1, 900 / contentH);
      }} else if (contentH > 1120) {{
        zoom = 1120 / contentH;
      }}
      try {{ ctx.doc.body.style.zoom = String(zoom); }} catch (eZ3) {{}}
      if (portal) {{ try {{ portal.style.zoom = String(zoom); }} catch (eZ4) {{}} }}
    }} catch (e) {{}}
  }}

  function preloadParentAssets(){{
    try {{
      var ctx = getParentCtx();
      if (!ctx) return;
      ensureTajawal(ctx.doc);
      injectPortal(ctx);
    }} catch (ePre) {{}}
  }}

  function sairSafePrint(ev){{
    try {{ if (ev && ev.preventDefault) ev.preventDefault(); }} catch (ePrev) {{}}
    try {{ if (ev && ev.stopPropagation) ev.stopPropagation(); }} catch (eStop) {{}}
    var now = Date.now();
    if (window.__sairSafePrintAt && (now - window.__sairSafePrintAt) < 900) return false;
    window.__sairSafePrintAt = now;

    // أ) بوابة الصفحة الأب — محمية بالكامل من SecurityError
    try {{
      var ctx = getParentCtx();
      if (ctx) {{
        var portal = injectPortal(ctx);
        applyZoom(ctx, portal);
        try {{ ctx.win.focus(); }} catch (eF) {{}}
        try {{ ctx.win.print(); return false; }} catch (ePr) {{}}
      }}
    }} catch (eA) {{}}

    // ب) نافذة منبثقة بمستند كامل مع تعبئة الوسائط من المعاينة
    try {{
      var printWin = null;
      try {{ printWin = window.open("", "_blank"); }} catch (eOpen) {{ printWin = null; }}
      if (printWin && !printWin.closed) {{
        try {{
          printWin.document.open();
          printWin.document.write(withMedia(FULL_HTML));
          printWin.document.close();
          return false;
        }} catch (eWrite) {{
          try {{ printWin.close(); }} catch (eClose) {{}}
        }}
      }}
    }} catch (eB) {{}}

    // ج) طباعة الإطار الحالي كآخر مسار
    try {{ window.focus(); }} catch (eC0) {{}}
    try {{ window.print(); }} catch (eC1) {{}}
    return false;
  }}

  window.sairSafePrint = sairSafePrint;
  window.khafarPortalPrint = sairSafePrint;

  function bind(){{
    var btns = document.querySelectorAll(".print-btn, [data-khafar-print]");
    for (var i = 0; i < btns.length; i++) {{
      btns[i].onclick = sairSafePrint;
      try {{ btns[i].setAttribute("onclick", "sairSafePrint(event)"); }} catch (eAttr) {{}}
    }}
  }}
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function(){{ bind(); preloadParentAssets(); }});
  else {{ bind(); preloadParentAssets(); }}
  window.addEventListener("load", function(){{ bind(); preloadParentAssets(); }});
}})();
</script>
"""

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=794">
<meta name="format-detection" content="telephone=no">
<title>محضر إثبات حالة - {html.escape(case_no_ar)}</title>
<link id="khafar-tajawal-font" rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tajawal:wght@500;700;800&display=swap">
<style>{report_css}</style>
</head>
<body>
<div class="toolbar no-print">
  <button class="print-btn" type="button" data-khafar-print="1" onclick="sairSafePrint(event)">🖨️ طباعة / حفظ PDF (1/1)</button>
</div>
{portal_sheet_html}
{safe_print_js}
</body>
</html>"""


_GPS_SIMPLE = re.compile(
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*[,،]\s*([+-]?\d+(?:\.\d+)?)\s*$"
)
_GPS_DISPLAY = re.compile(
    r"(\d+(?:\.\d+)?)\s*°\s*([NSns])\s*[,،]\s*(\d+(?:\.\d+)?)\s*°\s*([EWew])"
)


def _signed_gps_pair(text: str):
    """يفهم صيغة app.py المعتمدة (16.86° N, 43.12° E) وصيغة lat, lon."""
    raw = to_western_digits(str(text or "")).strip()
    raw = raw.replace("\u2212", "-").replace("٫", ".")
    if not raw or "بانتظار" in raw:
        return None
    m = _GPS_SIMPLE.match(raw)
    if m:
        try:
            lat, lng = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
        except ValueError:
            return None
    shown = _GPS_DISPLAY.search(raw)
    if shown:
        try:
            lat = float(shown.group(1)) * (1 if shown.group(2).upper() == "N" else -1)
            lng = float(shown.group(3)) * (1 if shown.group(4).upper() == "E" else -1)
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
        except ValueError:
            return None
    # التقاط فضفاض لرقمين عشريين متتاليين
    loose = re.findall(r"[+-]?\d+(?:\.\d+)?", raw)
    if len(loose) >= 2:
        try:
            lat, lng = float(loose[0]), float(loose[1])
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
        except ValueError:
            return None
    return None


def _fmt_coord(n: float) -> str:
    return f"{float(n):.6f}".rstrip("0").rstrip(".")


def _session_gps_coords(shift: dict | None = None) -> str:
    """قراءة إحداثيات الجلسة من app.py: gps_live_value ثم default_gps."""
    candidates = [
        st.session_state.get("gps_live_value"),
        (shift or {}).get("default_gps"),
        st.session_state.get("pending_live_gps"),
    ]
    for cand in candidates:
        pair = _signed_gps_pair(cand)
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
    """تهيئة لمرة واحدة فقط لكل مفتاح — لا تُعاد الكتابة فوق إدخال المستخدم في كل rerun."""
    defaults = {
        "sair_case_no": "4800000054",
        "sair_location": "",
        "sair_hijri": default_hijri_str(),
        "sair_time": default_time_24(),
        "sair_classification": "مخالفة مرورية",
        "sair_coords": "",
        "sair_desc_mode": DESC_MODES[0],
        "sair_vehicle_type": "كامري",
        "sair_plate": "",
        "sair_plate_class": "خاص",
        "sair_owner_name": "",
        "sair_speed": "",
        "sair_road_speed": "100",
        "sair_description": "",
        "sair_photo_b64": "",
        "sair_photo_right_b64": "",
        "sair_photo_left_b64": "",
        "sair_officer_name": str((shift or {}).get("officer_name") or "").strip(),
        "sair_officer_rank": str((shift or {}).get("officer_rank") or "").strip(),
        "sair_officer_id": "",
        "sair_unit_name": _default_unit_name(shift),
        "sair_officer_sig_b64": "",
        "sair_desc_manual_lock": False,
        "_sair_last_auto_desc": "",
        "_sair_desc_seeded": False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val
    # ترحيل قيمة فئة اللوحة القديمة
    if str(st.session_state.get("sair_plate_class") or "").strip() == "بدون":
        st.session_state["sair_plate_class"] = "خاص"
    # ترحيل الصورة الوحيدة من المفاتيح القديمة
    if not str(st.session_state.get("sair_photo_b64") or "").strip():
        legacy = str(st.session_state.get("sair_photo_right_b64") or "").strip() or str(
            st.session_state.get("sair_photo_left_b64") or ""
        ).strip()
        if legacy:
            st.session_state["sair_photo_b64"] = legacy
    # تحديث صياغة الوصف القديمة (كم / ساعة → كم/ساعة مع فئة/مالك)
    cur_desc = str(st.session_state.get("sair_description") or "")
    if cur_desc and "كم / ساعة" in cur_desc:
        if str(st.session_state.get("sair_desc_mode") or "") == DESC_MODES[0]:
            if not st.session_state.get("sair_desc_manual_lock"):
                fresh = build_speed_description(
                    vehicle=st.session_state.get("sair_vehicle_type"),
                    plate=st.session_state.get("sair_plate"),
                    plate_class=st.session_state.get("sair_plate_class"),
                    speed=st.session_state.get("sair_speed"),
                    road_speed=st.session_state.get("sair_road_speed"),
                    owner_name=st.session_state.get("sair_owner_name"),
                )
                st.session_state["sair_description"] = fresh
                st.session_state["_sair_last_auto_desc"] = fresh
    # تعبئة الإحداثيات من GPS الجلسة فقط إذا كان الحقل فارغاً / بانتظار
    cur_coords = str(st.session_state.get("sair_coords") or "").strip()
    if (not cur_coords) or ("بانتظار" in cur_coords) or (cur_coords in ("—", "-")):
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
        owner_name=st.session_state.get("sair_owner_name"),
    )


def collect_sair_data() -> dict:
    """قراءة بيانات النموذج فقط — ممنوع الكتابة على مفاتيح الـ widgets هنا."""
    mode = str(st.session_state.get("sair_desc_mode") or DESC_MODES[0])
    desc = str(st.session_state.get("sair_description") or "").strip()
    photo_now = strip_data_url(
        st.session_state.get("sair_photo_b64")
        or st.session_state.get("sair_photo_right_b64")
        or st.session_state.get("sair_photo_left_b64")
        or ""
    )
    sig_now = strip_data_url(st.session_state.get("sair_officer_sig_b64") or "")
    # إن تطابق التوقيع مع صورة الحالة فهو خلط سابق — أفرغ التوقيع فقط
    if sig_now and photo_now and sig_now == photo_now:
        st.session_state["sair_officer_sig_b64"] = ""
        sig_now = ""
    return {
        "case_no": to_western_digits(st.session_state.get("sair_case_no") or "").strip(),
        "location": str(st.session_state.get("sair_location") or "").strip(),
        "hijri": str(st.session_state.get("sair_hijri") or "").strip(),
        "time": to_western_digits(st.session_state.get("sair_time") or "").strip(),
        "classification": str(st.session_state.get("sair_classification") or "مخالفة مرورية").strip(),
        "coords": to_western_digits(st.session_state.get("sair_coords") or "").strip(),
        "description": desc,
        "photo": photo_now,
        "photo_right": photo_now,
        "photo_left": "",
        "officer_name": str(st.session_state.get("sair_officer_name") or "").strip(),
        "officer_rank": str(st.session_state.get("sair_officer_rank") or "").strip(),
        "officer_id": to_western_digits(st.session_state.get("sair_officer_id") or "").strip(),
        "unit_name": str(st.session_state.get("sair_unit_name") or "").strip(),
        "signature": sig_now,
        "vehicle_type": str(st.session_state.get("sair_vehicle_type") or "").strip(),
        "plate": str(st.session_state.get("sair_plate") or "").strip(),
        "plate_class": str(st.session_state.get("sair_plate_class") or "").strip(),
        "owner_name": str(st.session_state.get("sair_owner_name") or "").strip(),
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
    fields["photo"] = data.get("photo") or data.get("photo_right") or ""
    fields["photo_right"] = fields["photo"]
    fields["photo_left"] = ""
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
    st.session_state["sair_plate_class"] = "خاص"
    st.session_state["sair_owner_name"] = ""
    st.session_state["sair_speed"] = ""
    st.session_state["sair_photo_b64"] = ""
    st.session_state["sair_photo_right_b64"] = ""
    st.session_state["sair_photo_left_b64"] = ""
    st.session_state["sair_desc_manual_lock"] = False
    st.session_state["sair_description"] = ""
    st.session_state["_sair_last_auto_desc"] = ""
    st.session_state["_sair_desc_seeded"] = False
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
    st.session_state["_sair_desc_seeded"] = True


def _set_sair_road_speed(value: str) -> None:
    st.session_state["sair_road_speed"] = str(value or "")
    if str(st.session_state.get("sair_desc_mode") or "") == DESC_MODES[0]:
        _regen_sair_description()


def _set_sair_vehicle(value: str) -> None:
    st.session_state["sair_vehicle_type"] = str(value or "")
    if str(st.session_state.get("sair_desc_mode") or "") == DESC_MODES[0]:
        _regen_sair_description()


def _set_sair_plate_class(value: str) -> None:
    st.session_state["sair_plate_class"] = str(value or "")
    if str(st.session_state.get("sair_desc_mode") or "") == DESC_MODES[0]:
        _regen_sair_description()


def _on_auto_desc_source_change() -> None:
    """يُستدعى عند تغيّر حقول المركبة/اللوحة/السرعة فقط — لا يلمس الكتابة اليدوية إلا بإعادة التوليد."""
    if str(st.session_state.get("sair_desc_mode") or "") != DESC_MODES[0]:
        return
    _regen_sair_description()


def _clear_sair_photo(side: str = "single") -> None:
    st.session_state["sair_photo_b64"] = ""
    st.session_state["sair_photo_right_b64"] = ""
    st.session_state["sair_photo_left_b64"] = ""


def _render_quick_buttons(options: list[str], *, key_prefix: str, on_pick) -> None:
    """أزرار اقتراح سريعة عبر on_click فقط — بدون selectbox."""
    if not options:
        return
    cols = st.columns(min(5, len(options)))
    for i, label in enumerate(options):
        with cols[i % len(cols)]:
            st.button(
                label,
                key=f"{key_prefix}_{i}",
                use_container_width=True,
                on_click=on_pick,
                args=(label,),
            )


def _save_sair_then_next(logo_b64: str = "", logo_mime: str = "image/png") -> None:
    """on_click: حفظ ثم تفريغ حقول المركبة قبل إعادة الرسم."""
    data = collect_sair_data()
    html_doc = build_sair_a4_html(data=data, logo_b64=logo_b64, logo_mime=logo_mime)
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
    if pending.get("clear_right_photo") or pending.get("clear_left_photo") or pending.get("clear_photo"):
        _clear_sair_photo()
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
        "photo": "sair_photo_b64",
        "photo_right": "sair_photo_b64",
        "photo_left": "sair_photo_b64",
        "officer_name": "sair_officer_name",
        "officer_rank": "sair_officer_rank",
        "officer_id": "sair_officer_id",
        "unit_name": "sair_unit_name",
        "signature": "sair_officer_sig_b64",
        "vehicle_type": "sair_vehicle_type",
        "plate": "sair_plate",
        "plate_class": "sair_plate_class",
        "owner_name": "sair_owner_name",
        "speed": "sair_speed",
        "road_speed": "sair_road_speed",
        "desc_mode": "sair_desc_mode",
    }
    for src, dst in mapping.items():
        val = fields.get(src)
        if val is None or val == "":
            continue
        # لا تستبدل الصورة الوحيدة بصورة يسرى فارغة لاحقاً
        if dst == "sair_photo_b64" and st.session_state.get("sair_photo_b64") and src == "photo_left":
            continue
        st.session_state[dst] = val
    if str(st.session_state.get("sair_plate_class") or "").strip() == "بدون":
        st.session_state["sair_plate_class"] = "خاص"
    # حراسة بعد الاستدعاء: لا تسمح لخلط صورة الحالة مع التوقيع
    photo_now = strip_data_url(st.session_state.get("sair_photo_b64") or "")
    sig_now = strip_data_url(st.session_state.get("sair_officer_sig_b64") or "")
    if photo_now and sig_now and photo_now == sig_now:
        st.session_state["sair_officer_sig_b64"] = ""
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

    st.text_input(
        "الموقع",
        key="sair_location",
        placeholder="اكتب الموقع يدوياً... مثال: العارضة طريق عرق أبو سبيلة",
    )

    d1, d2 = st.columns(2)
    with d1:
        st.text_input("التاريخ الهجري", key="sair_hijri", help="مثال: 1448/6/14هـ")
    with d2:
        st.text_input("الوقت (24 ساعة)", key="sair_time", help="مثال: 16:58")

    st.text_input("تصنيف الحالة", key="sair_classification")
    # تعبئة GPS قبل رسم الحقل إن كان فارغاً (بعد وصول الإحداثيات للجلسة)
    _gps_now = _session_gps_coords(shift)
    st.session_state["_sair_gps_cache"] = _gps_now
    _coords_cur = str(st.session_state.get("sair_coords") or "").strip()
    if _gps_now and ((not _coords_cur) or ("بانتظار" in _coords_cur)):
        st.session_state["sair_coords"] = _gps_now
    st.text_input(
        "إحداثي الموقع",
        key="sair_coords",
        placeholder="مثال: 16.861514, 43.122711",
        help=f"يُملأ من GPS الجلسة عند التوفر. المرجع: {_gps_now or '—'}",
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
    if mode == DESC_MODES[0]:
        st.text_input(
            "نوع المركبة",
            key="sair_vehicle_type",
            placeholder="اكتب أي نوع مركبة بحرية (مثال: BMW / كامري / شاص)...",
            on_change=_on_auto_desc_source_change,
        )
        st.caption("اقتراحات سريعة لأنواع المركبات المتكررة")
        _render_quick_buttons(VEHICLE_PRESETS, key_prefix="sair_veh_btn", on_pick=_set_sair_vehicle)
        st.text_input(
            "رقم اللوحة",
            key="sair_plate",
            placeholder="أ ق ب 7894 أو س 219711",
            on_change=_on_auto_desc_source_change,
        )
        st.caption("فئة اللوحة / نوع التسجيل")
        _render_quick_buttons(PLATE_CLASS_OPTIONS, key_prefix="sair_pcls_btn", on_pick=_set_sair_plate_class)
        st.text_input(
            "فئة اللوحة",
            key="sair_plate_class",
            placeholder="خاص / نقل خاص / نقل عام / حافلة / دبلوماسي / مؤقت",
            on_change=_on_auto_desc_source_change,
        )
        s1, s2 = st.columns(2)
        with s1:
            st.text_input(
                "سرعة المركبة المرصودة (كم/ساعة)",
                key="sair_speed",
                on_change=_on_auto_desc_source_change,
            )
        with s2:
            st.caption("سرعة الطريق — اقتراحات سريعة")
            _render_quick_buttons(ROAD_SPEED_PRESETS, key_prefix="sair_rspd_btn", on_pick=_set_sair_road_speed)
            st.text_input(
                "سرعة الطريق المحددة (كم/ساعة)",
                key="sair_road_speed",
                on_change=_on_auto_desc_source_change,
            )
        # بذرة أولية لمرة واحدة فقط — بعدها التحديث عبر on_change/أزرار فقط
        if not st.session_state.get("_sair_desc_seeded"):
            auto_desc = _compute_auto_desc()
            if not str(st.session_state.get("sair_description") or "").strip():
                st.session_state["sair_description"] = auto_desc
                st.session_state["_sair_last_auto_desc"] = auto_desc
            st.session_state["_sair_desc_seeded"] = True
        st.caption("يتحدّث الوصف تلقائياً عند تغيير حقول المركبة/السرعة — ويبقى قابلاً للكتابة الحرة.")

    st.text_input(
        "اسم مالك المركبة",
        key="sair_owner_name",
        placeholder="اكتب اسم مالك المركبة (اختياري)...",
        on_change=_on_auto_desc_source_change,
    )
    st.text_area("وصف الحالة", key="sair_description", height=110)
    if mode == DESC_MODES[0]:
        st.button(
            "🔄 إعادة توليد الوصف من الحقول",
            key="sair_regen_desc",
            on_click=_regen_sair_description,
        )

    # —— صورة الحالة (واحدة فقط) ——
    st.markdown("##### 3) صورة الحالة")
    st.caption("ارفع أو التقط صورة واحدة فقط للمحضر (معرض / كاميرا / PDF).")
    if khafar_file_uploader:
        photo_up = khafar_file_uploader(
            "رفع / التقاط صورة الحالة",
            key="sair_photo_single_mu",
            accept_multiple_files=False,
            allow_pdf=True,
        )
    else:
        photo_up = st.file_uploader(
            "صورة الحالة",
            type=["jpg", "jpeg", "png", "webp", "pdf"],
            key="sair_photo_single_up",
        )
    if photo_up is not None:
        files = photo_up if isinstance(photo_up, list) else [photo_up]
        if files:
            b64 = _ingest_upload_to_b64(files[0], purpose="photo")
            if b64:
                st.session_state["sair_photo_b64"] = b64
                st.session_state["sair_photo_right_b64"] = b64
                st.session_state["sair_photo_left_b64"] = ""
    if st.session_state.get("sair_photo_b64"):
        st.image(
            f"data:image/jpeg;base64,{strip_data_url(st.session_state['sair_photo_b64'])}",
            use_container_width=True,
        )
        st.button(
            "🗑️ حذف الصورة",
            key="sair_del_photo",
            on_click=_clear_sair_photo,
        )

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
    a4_html = build_sair_a4_html(data=data, logo_b64=logo_hdr, logo_mime=logo_mime)

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
