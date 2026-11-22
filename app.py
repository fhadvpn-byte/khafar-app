import streamlit as st
import streamlit.components.v1 as components
import sqlite3
import json
import base64
import io
import html
import os
import random
import hashlib
import re
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageOps
from abu_arish_impound import ABU_ARISH_IMPOUND_TEMPLATE
from takmeel import TAKMEEL_FORMS, init_takmeel_db, render_takmeel_form

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

KSA_TZ = timezone(timedelta(hours=3))

st.set_page_config(
    page_title="قسم مرور العارضة | الإقرارات والمحاضر",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def get_traffic_logo_b64() -> str:
    """قراءة شعار المرور تلقائياً من مجلد المشروع، مع شعار احتياطي مضمّن إن لم يوجد الملف."""
    base_dir = Path(__file__).resolve().parent
    for fname in (
        "traffic_logo.png", "traffic_logo.PNG", "traffic_logo.jpg", "traffic_logo.jpeg",
        "logo.png", "logo.PNG", "passer_logo.png", "moi_logo.png",
    ):
        fpath = base_dir / fname
        if fpath.exists():
            return base64.b64encode(fpath.read_bytes()).decode("utf-8")
    # شعار احتياطي مرسوم محلياً ليظهر دائماً في المعاينة والطباعة كـ data URI
    try:
        img = Image.new("RGBA", (180, 180), (255, 255, 255, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((8, 8, 172, 172), fill=(15, 61, 46, 255), outline=(212, 168, 83, 255), width=6)
        draw.ellipse((28, 28, 152, 152), outline=(255, 255, 255, 230), width=3)
        draw.text((52, 68), "المرور", fill=(255, 255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return ""


def format_entity(role_label: str, optional_name: str) -> str:
    r = (role_label or "").strip()
    n = (optional_name or "").strip()
    return f"{r} / {n}" if (r and n) else (r or n)


ATTACH_MAX_PX = 1200
ATTACH_JPEG_QUALITY = 85
ATTACH_TYPES = ["png", "jpg", "jpeg", "webp", "pdf"]


def parse_attachments(raw) -> list:
    """قراءة المرفقات من الجلسة أو قاعدة البيانات (يدعم الصيغة القديمة: صورة واحدة Base64)."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [a for a in raw if isinstance(a, dict) and a.get("b64")]
    if not isinstance(raw, str):
        return []
    s = raw.strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            data = json.loads(s)
            if isinstance(data, list):
                return [a for a in data if isinstance(a, dict) and a.get("b64")]
        except Exception:
            return []
    return [{"name": "مرفق.png", "mime": "image/png", "b64": s, "kind": "image"}]


def serialize_attachments(items: list) -> str:
    return json.dumps(items or [], ensure_ascii=False)


def process_uploaded_attachment(uploaded_file) -> dict | None:
    """معالجة مرفق جوال: تصحيح اتجاه EXIF وتصغير الصور، وحفظ PDF كما هو."""
    if uploaded_file is None:
        return None
    fname = (getattr(uploaded_file, "name", None) or "مرفق").strip()
    lower = fname.lower()
    try:
        if lower.endswith(".pdf") or (getattr(uploaded_file, "type", "") or "").lower() == "application/pdf":
            raw = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()
            if not raw:
                return None
            return {
                "name": fname if lower.endswith(".pdf") else f"{Path(fname).stem}.pdf",
                "mime": "application/pdf",
                "b64": base64.b64encode(raw).decode("utf-8"),
                "kind": "pdf",
                "orig_name": fname,
            }

        img = Image.open(uploaded_file)
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA") if "A" in (img.getbands() or ()) else img.convert("RGB")
        img.thumbnail((ATTACH_MAX_PX, ATTACH_MAX_PX), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        if img.mode == "RGBA":
            img.save(buf, format="PNG", optimize=True)
            mime, ext = "image/png", "png"
        else:
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=ATTACH_JPEG_QUALITY, optimize=True)
            mime, ext = "image/jpeg", "jpg"
        out_name = f"{Path(fname).stem}.{ext}"
        return {
            "name": out_name,
            "mime": mime,
            "b64": base64.b64encode(buf.getvalue()).decode("utf-8"),
            "kind": "image",
            "orig_name": fname,
        }
    except Exception:
        return None


def attachment_fingerprint(item: dict) -> str:
    return hashlib.sha1(f"{item.get('orig_name') or item.get('name')}|{item.get('b64', '')[:64]}".encode("utf-8")).hexdigest()


# =====================================================================
# 1. الهوية البصرية الخضراء الداكنة والذهبية
# =====================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@600;700;800;900&family=Tajawal:wght@700;800;900&family=JetBrains+Mono:wght@600&display=swap');

:root {
    --bg-main: #0f1417;
    --bg-card: #161e22;
    --bg-emerald-dark: #092c20;
    --bg-emerald-mid: #0f3d2e;
    --emerald-accent: #15805c;
    --emerald-bright: #34d399;
    --gold-main: #d4a853;
    --gold-soft: #f3cc7a;
    --med-main: #38bdf8;
    --med-soft: #bae6fd;
    --text-light: #f1f5f9;
    --text-muted: #94a3b8;
}

html, body, .stApp {
    font-family: 'Cairo', sans-serif !important;
    direction: rtl;
    text-align: right;
    color-scheme: dark !important;
}
/* فرض الثيم الداكن ومنع قلب ألوان المتصفح في الوضع الفاتح — دون المساس بـ iframe ورقة A4 */
.stApp {
    color: #ffffff !important;
    background-color: #0b1512 !important;
}
.stApp [data-testid="stMarkdownContainer"] p,
.stApp [data-testid="stMarkdownContainer"] span,
.stApp [data-testid="stMarkdownContainer"] li {
    color: inherit;
}

/* إخفاء شريط Streamlit العلوي وشارات Cloud (التاج / GitHub) دون المساس بـ #root */
header[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
[data-testid="manage-app-button"],
.stDeployButton,
#MainMenu,
footer,
footer[data-testid="stFooter"],
.stAppDeployButton,
[class*="viewerBadge"],
[class*="_viewerBadge"],
[class*="_link_gzau3"],
[class*="profileContainer"],
[class*="_profileContainer"],
[class*="profilePreview"],
[class*="_profilePreview"],
a[href*="streamlit.io"],
a[href*="share.streamlit.io/user"],
img[src*="avatars.githubusercontent.com"] {
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
    height: 0 !important;
    min-height: 0 !important;
    width: 0 !important;
    opacity: 0 !important;
    pointer-events: none !important;
}
iframe[height="0"] {
    height: 0px !important;
    margin: -1rem 0 0 0 !important;
    display: block !important;
    border: none !important;
    overflow: hidden !important;
}
textarea[placeholder*="DUTY_SIG_BRIDGE"],
div[data-testid="stTextArea"]:has(textarea[placeholder*="DUTY_SIG_BRIDGE"]) {
    height: 0 !important;
    min-height: 0 !important;
    max-height: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
    border: none !important;
    opacity: 0 !important;
    overflow: hidden !important;
    pointer-events: none !important;
}
[data-testid="collapsedControl"] { display: none !important; }
section[data-testid="stSidebar"] { display: none !important; }
.block-container {
    padding-top: 0.35rem !important;
    padding-bottom: 1.4rem !important;
    padding-left: 12px !important;
    padding-right: 12px !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
    overflow-x: hidden !important;
}
@media only screen and (max-width: 820px) {
    .block-container,
    .block-container h1,
    .block-container h2,
    .block-container h3,
    .block-container label,
    .block-container p,
    [data-testid="stMarkdownContainer"],
    [data-testid="stWidgetLabel"],
    [data-testid="stWidgetLabel"] p {
        max-width: 100% !important;
        box-sizing: border-box !important;
        overflow-wrap: anywhere !important;
        word-break: normal !important;
        margin-left: 0 !important;
        margin-right: 0 !important;
    }
    .main, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
        overflow-x: hidden !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
    }
}

.stApp, [data-testid="stAppViewContainer"], [data-testid="stAppViewBlockContainer"] {
    background-color: #0b1512 !important;
    color: #ffffff !important;
}

.khafar-top-header {
    background: linear-gradient(135deg, #0d4432 0%, #08291e 100%);
    border: 1px solid #1e6b50;
    border-radius: 14px 14px 0 0;
    padding: 10px 12px 8px 12px;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.28);
}
.header-brand-row {
    display: flex;
    justify-content: flex-start;
    align-items: center;
    gap: 10px;
}
.header-brand-inline {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
}
.official-5lines,
.official-5lines-compact {
    line-height: 1.35;
    font-weight: 800;
    color: #ffffff;
    font-size: 12px;
    text-align: right;
    flex: 1;
}
.official-5lines-compact .dept-line {
    color: #f3cc7a;
    font-size: 12.5px;
    margin-top: 1px;
}
.logo-frame {
    width: 54px;
    height: 54px;
    min-width: 54px;
    border-radius: 12px;
    background: #ffffff;
    border: 2px solid var(--gold-main);
    padding: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 3px 10px rgba(0, 0, 0, 0.22);
}
.logo-frame img {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
}

.compact-status-bar {
    background: #0b1015;
    border-left: 1px solid #1e293b;
    border-right: 1px solid #1e293b;
    border-bottom: 2px solid #9a7432;
    border-radius: 0 0 12px 12px;
    padding: 7px 10px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 8px;
    margin-bottom: 10px;
}
.compact-status-bar .status-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: #12201c;
    border: 1px solid #1f5c46;
    color: #a7f3d0;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    line-height: 1.35;
}
.compact-status-bar .status-chip.gold {
    background: #1a1810;
    border-color: rgba(212, 168, 83, 0.45);
    color: var(--gold-soft);
}
.compact-status-bar .status-chip.gps {
    font-family: 'JetBrains Mono', monospace !important;
    direction: ltr;
    unicode-bidi: isolate;
    color: #4ade80;
    background: #102422;
}
.compact-status-bar .status-chip.time {
    background: #161d24;
    border-color: #2d3846;
    color: #cbd5e1;
}
.gps-locate-btn {
    border: 1px solid rgba(212, 168, 83, 0.7);
    background: #1a1810;
    color: #f3cc7a;
    border-radius: 999px;
    font-family: 'Cairo', sans-serif;
    font-weight: 800;
    font-size: 11px;
    line-height: 1.35;
    padding: 3px 10px;
    cursor: pointer;
}
.gps-locate-btn:disabled { opacity: 0.7; cursor: wait; }
.gps-map-link {
    color: #7dd3fc;
    font-size: 11px;
    font-weight: 800;
    text-decoration: none;
    padding: 2px 4px;
}
.gps-mono-box {
    font-family: 'JetBrains Mono', monospace !important;
    direction: ltr;
    display: inline-block;
    background: #102422;
    border: 1px solid #1f5c46;
    color: #4ade80;
    padding: 2px 10px;
    border-radius: 6px;
    font-size: 12.5px;
}
.time-auto-box {
    background: #161d24;
    border: 1px solid #2d3846;
    color: #cbd5e1;
    padding: 2px 10px;
    border-radius: 6px;
    font-size: 12px;
}

.hero-shift-card {
    background: linear-gradient(135deg, #0f3d2c 0%, #112421 65%, #151d21 100%);
    border: 1px solid #21634b;
    border-radius: 16px;
    padding: 20px 24px;
    margin-bottom: 18px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
}
.hero-eyebrow {
    color: var(--gold-main);
    font-size: 13.5px;
    font-weight: 800;
    margin-bottom: 4px;
}
.hero-title {
    color: #ffffff;
    font-size: 22px;
    font-weight: 900;
    margin: 0 0 8px 0;
}
.hero-desc {
    color: #cbd5e1;
    font-size: 13.5px;
    line-height: 1.75;
    margin-bottom: 14px;
}
.shift-summary-inner {
    background: rgba(11, 20, 22, 0.65);
    border: 1px solid rgba(45, 106, 84, 0.45);
    border-radius: 12px;
    padding: 12px 18px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
}

.sec-heading-green {
    border-right: 4px solid #10b981;
    padding-right: 12px;
    margin: 20px 0 12px 0;
    display: flex;
    align-items: center;
    gap: 12px;
}
.sec-heading-gold {
    border-right: 4px solid var(--gold-main);
    padding-right: 12px;
    margin: 24px 0 12px 0;
    display: flex;
    align-items: center;
    gap: 12px;
}
.sec-heading-med {
    border-right: 4px solid var(--med-main);
    padding-right: 12px;
    margin: 24px 0 12px 0;
    display: flex;
    align-items: center;
    gap: 12px;
}
.badge-green {
    background: rgba(16, 185, 129, 0.14);
    border: 1px solid rgba(16, 185, 129, 0.4);
    color: #6ee7b7;
    font-size: 12px;
    font-weight: 700;
    padding: 2px 11px;
    border-radius: 20px;
}
.badge-gold {
    background: rgba(212, 168, 83, 0.14);
    border: 1px solid rgba(212, 168, 83, 0.4);
    color: var(--gold-soft);
    font-size: 12px;
    font-weight: 700;
    padding: 2px 11px;
    border-radius: 20px;
}
.badge-med {
    background: rgba(56, 189, 248, 0.14);
    border: 1px solid rgba(56, 189, 248, 0.45);
    color: var(--med-soft);
    font-size: 12px;
    font-weight: 700;
    padding: 2px 11px;
    border-radius: 20px;
}
.badge-tak {
    background: rgba(167, 139, 250, 0.14);
    border: 1px solid rgba(167, 139, 250, 0.5);
    color: #c4b5fd;
    font-size: 12px;
    font-weight: 700;
    padding: 2px 11px;
    border-radius: 20px;
}

.form-item-card {
    background: linear-gradient(180deg, #162024 0%, #12191c 100%);
    border: 1px solid #24353b;
    border-radius: 12px;
    padding: 8px 12px;
    margin-bottom: 4px;
    transition: all 0.2s ease;
}
.form-item-card:hover {
    border-color: #2b8a68;
}
.form-open-hint {
    font-size: 11px;
    color: #94a3b8;
    margin: 0 0 2px 0;
}
/* أزرار النماذج والتنقل أكثر إحكاماً على الجوال */
div[data-testid="stHorizontalBlock"] div.stButton > button {
    padding: 0.48rem 0.55rem !important;
    font-size: 13px !important;
    min-height: 2.55rem !important;
    white-space: normal !important;
    line-height: 1.35 !important;
}
div[data-baseweb="tab-list"],
[data-testid="stTabs"] [role="tablist"] {
    display: grid !important;
    grid-template-columns: repeat(4, 1fr) !important;
    gap: 12px !important;
    width: 100% !important;
    background: rgba(8, 24, 21, 0.75) !important;
    padding: 10px !important;
    border-radius: 16px !important;
    border: 1.5px solid rgba(16, 185, 129, 0.35) !important;
    margin: 14px 0 18px 0 !important;
}
div[data-baseweb="tab-highlight"],
[data-testid="stTabs"] .react-aria-SelectionIndicator {
    display: none !important;
}
div[data-testid="stTabs"] button[data-baseweb="tab"],
[data-testid="stTabs"] [data-testid="stTab"] {
    display: flex !important;
    align-items: center !important;
    min-height: 74px !important;
    width: 100% !important;
    border-radius: 12px !important;
    padding: 12px 10px !important;
    background: linear-gradient(145deg, rgba(20, 48, 42, 0.92), rgba(13, 33, 29, 0.95)) !important;
    border: 1.5px solid rgba(255, 255, 255, 0.22) !important;
    color: #f1f5f9 !important;
    -webkit-text-fill-color: #f1f5f9 !important;
    justify-content: center !important;
    text-align: center !important;
    white-space: normal !important;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25) !important;
    transition: all 0.2s ease-in-out !important;
}
div[data-testid="stTabs"] button[data-baseweb="tab"] p,
div[data-testid="stTabs"] button[data-baseweb="tab"] span,
[data-testid="stTabs"] [data-testid="stTab"] p {
    font-size: 17px !important;
    font-weight: 800 !important;
    line-height: 1.35 !important;
    color: #f1f5f9 !important;
    -webkit-text-fill-color: #f1f5f9 !important;
    text-align: center !important;
    white-space: normal !important;
    margin: 0 !important;
}
div[data-baseweb="tab-list"] button[data-baseweb="tab"]:nth-child(1),
[data-testid="stTabs"] [role="tablist"] > [data-testid="stTab"]:nth-child(1) {
    border: 1.5px solid #10b981 !important;
}
div[data-baseweb="tab-list"] button[data-baseweb="tab"]:nth-child(1)[aria-selected="true"],
[data-testid="stTabs"] [role="tablist"] > [data-testid="stTab"]:nth-child(1)[aria-selected="true"] {
    background: linear-gradient(145deg, #059669, #10b981) !important;
    border: 2px solid #fde68a !important;
    color: #ffffff !important;
    box-shadow: 0 0 0 1px rgba(253, 230, 138, 0.45), 0 8px 22px rgba(16, 185, 129, 0.45) !important;
}
div[data-baseweb="tab-list"] button[data-baseweb="tab"]:nth-child(2),
[data-testid="stTabs"] [role="tablist"] > [data-testid="stTab"]:nth-child(2) {
    border: 1.5px solid rgba(56, 189, 248, 0.5) !important;
}
div[data-baseweb="tab-list"] button[data-baseweb="tab"]:nth-child(2)[aria-selected="true"],
[data-testid="stTabs"] [role="tablist"] > [data-testid="stTab"]:nth-child(2)[aria-selected="true"] {
    background: linear-gradient(145deg, #0284c7, #0ea5e9) !important;
    border: 2px solid #fde68a !important;
    color: #ffffff !important;
    box-shadow: 0 0 0 1px rgba(253, 230, 138, 0.45), 0 8px 22px rgba(14, 165, 233, 0.4) !important;
}
div[data-baseweb="tab-list"] button[data-baseweb="tab"]:nth-child(3),
[data-testid="stTabs"] [role="tablist"] > [data-testid="stTab"]:nth-child(3) {
    border: 1.5px solid rgba(244, 63, 94, 0.6) !important;
}
div[data-baseweb="tab-list"] button[data-baseweb="tab"]:nth-child(3)[aria-selected="true"],
[data-testid="stTabs"] [role="tablist"] > [data-testid="stTab"]:nth-child(3)[aria-selected="true"] {
    background: linear-gradient(145deg, #be123c, #e11d48) !important;
    border: 2px solid #fde68a !important;
    color: #ffffff !important;
    box-shadow: 0 0 0 1px rgba(253, 230, 138, 0.5), 0 8px 22px rgba(225, 29, 72, 0.45) !important;
}
div[data-baseweb="tab-list"] button[data-baseweb="tab"]:nth-child(4),
[data-testid="stTabs"] [role="tablist"] > [data-testid="stTab"]:nth-child(4) {
    border: 1.5px solid rgba(167, 139, 250, 0.65) !important;
}
div[data-baseweb="tab-list"] button[data-baseweb="tab"]:nth-child(4)[aria-selected="true"],
[data-testid="stTabs"] [role="tablist"] > [data-testid="stTab"]:nth-child(4)[aria-selected="true"] {
    background: linear-gradient(145deg, #6d28d9, #8b5cf6) !important;
    border: 2px solid #fde68a !important;
    color: #ffffff !important;
    box-shadow: 0 0 0 1px rgba(253, 230, 138, 0.5), 0 8px 22px rgba(139, 92, 246, 0.45) !important;
}
div[data-baseweb="tab-list"] button[data-baseweb="tab"][aria-selected="true"] p,
[data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"] p {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
}
div[data-testid="stTabs"] div.stButton > button,
div[data-testid="stTabs"] div.stButton > button[kind="primary"] {
    background: #112924 !important;
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
    border: 1.5px solid rgba(255, 255, 255, 0.28) !important;
    border-right: 6px solid #d4a853 !important;
    border-radius: 12px !important;
    font-weight: 800 !important;
    font-size: 15px !important;
    min-height: 52px !important;
    box-shadow: none !important;
    text-align: right !important;
}
div[data-testid="stTabs"] div.stButton > button:hover,
div[data-testid="stTabs"] div.stButton > button[kind="primary"]:hover {
    background: #17382f !important;
    border-color: #fde68a !important;
    border-right: 6px solid #fde68a !important;
    color: #ffffff !important;
    box-shadow: 0 0 16px rgba(253, 230, 138, 0.22) !important;
}
@media only screen and (max-width: 640px) {
    div[data-testid="stTabs"] button[data-baseweb="tab"],
    [data-testid="stTabs"] [data-testid="stTab"] {
        min-height: 68px !important;
        padding: 8px 6px !important;
    }
    div[data-testid="stTabs"] button[data-baseweb="tab"] p,
    [data-testid="stTabs"] [data-testid="stTab"] p {
        font-size: 13.5px !important;
    }
}

.legal-dark-box {
    background: #111c19;
    border: 1px solid #23634c;
    border-right: 5px solid var(--gold-main);
    border-radius: 12px;
    padding: 14px 16px !important;
    margin: 14px 0;
    color: #e2e8f0;
    font-size: 14.5px;
    line-height: 1.9 !important;
    direction: rtl !important;
    text-align: justify !important;
    text-justify: inter-word !important;
    text-align-last: right !important;
    width: 100% !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
    overflow-wrap: anywhere !important;
    word-break: normal !important;
    white-space: normal !important;
}
.legal-dark-box .legal-title {
    direction: rtl !important;
    text-align: right !important;
    color: #d4a853 !important;
    font-weight: 800 !important;
    margin-bottom: 8px !important;
    white-space: normal !important;
}
.legal-dark-box .legal-body {
    direction: rtl !important;
    unicode-bidi: embed !important;
    text-align: justify !important;
    text-justify: inter-word !important;
    text-align-last: right !important;
    line-height: 1.9 !important;
    width: 100% !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
    overflow-wrap: anywhere !important;
    word-break: normal !important;
    white-space: normal !important;
    color: #e2e8f0 !important;
}
.lock-emerald-banner {
    background: rgba(16, 185, 129, 0.14);
    border: 1px solid #10b981;
    color: #a7f3d0;
    padding: 12px 16px;
    border-radius: 12px;
    font-weight: 700;
    margin-bottom: 14px;
}
.auth-panel {
    background: #141d20;
    border: 1px solid #25383c;
    border-radius: 14px;
    padding: 16px;
    height: 100%;
}

/* حقول الإدخال والقوائم — خلفية داكنة ونص أبيض ناصع (مقاومة للوضع الفاتح) */
div[data-testid="stTextInput"] div[data-baseweb="input"] > div,
div[data-testid="stTextArea"] div[data-baseweb="textarea"] > div,
div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
div[data-baseweb="input"] > div,
div[data-baseweb="textarea"] > div,
div[data-baseweb="select"] > div {
    background-color: #152620 !important;
    background: #152620 !important;
    border: 1px solid rgba(255, 255, 255, 0.22) !important;
    border-radius: 10px !important;
    color: #ffffff !important;
}
div[data-baseweb="input"] input,
div[data-baseweb="textarea"] textarea,
div[data-baseweb="select"] span,
div[data-baseweb="select"] div,
div[data-testid="stTextInput"] input,
div[data-testid="stTextArea"] textarea,
div[data-testid="stSelectbox"] div {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
    caret-color: #ffffff !important;
    font-family: 'Cairo', sans-serif !important;
    font-size: 15.5px !important;
    font-weight: 700 !important;
    opacity: 1 !important;
}
div[data-baseweb="input"] input::placeholder,
div[data-baseweb="textarea"] textarea::placeholder {
    color: #94a3b8 !important;
    -webkit-text-fill-color: #94a3b8 !important;
    opacity: 1 !important;
}
/* عناوين الحقول والنصوص الفرعية */
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] span,
[data-testid="stWidgetLabel"] label,
.stCaption, [data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p,
small, .stMarkdown small {
    color: #e2e8f0 !important;
    -webkit-text-fill-color: #e2e8f0 !important;
    font-weight: 700 !important;
    opacity: 1 !important;
}
label[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] p {
    font-size: 15.5px !important;
    font-weight: 700 !important;
    line-height: 1.45 !important;
}

div.stButton > button {
    background: #172628 !important;
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
    border: 1px solid #2c4a47 !important;
    border-radius: 10px !important;
    font-weight: 700 !important;
    padding: 0.5rem 1rem !important;
    transition: 0.2s all !important;
    opacity: 1 !important;
}
div.stButton > button:hover {
    background: #134e3a !important;
    border-color: #34d399 !important;
    color: #ffffff !important;
}
div.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #136f50 0%, #0c4a35 100%) !important;
    color: #ffffff !important;
    border: 1px solid #2bb585 !important;
    box-shadow: 0 4px 14px rgba(19, 111, 80, 0.35) !important;
}
div.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #178761 0%, #105e43 100%) !important;
    border-color: var(--gold-main) !important;
}
div.stDownloadButton > button {
    background: linear-gradient(135deg, #9a7432 0%, #785820 100%) !important;
    color: #ffffff !important;
    border: 1px solid var(--gold-soft) !important;
    border-radius: 10px !important;
    font-weight: 800 !important;
}

/* خيارات st.radio — نص أبيض واضح وخلفية داكنة مع إبراز الخيار المحدد */
div[data-testid="stRadio"],
div[data-testid="stRadio"] label,
div[data-testid="stRadio"] label p,
div[data-testid="stRadio"] label span,
div[data-testid="stRadio"] p,
div[data-testid="stRadio"] span,
div[role="radiogroup"],
div[role="radiogroup"] *,
div[role="radiogroup"] label,
div[role="radiogroup"] label p,
div[role="radiogroup"] label span,
div[role="radiogroup"] p,
div[role="radiogroup"] span,
div[role="radiogroup"] div {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
    font-weight: 700 !important;
    opacity: 1 !important;
}
div[role="radiogroup"] {
    background: #101a17 !important;
    padding: 8px !important;
    border-radius: 12px !important;
    border: 1px solid #25353b !important;
    display: flex !important;
    flex-direction: column !important;
    gap: 8px !important;
}
div[role="radiogroup"] > label,
div[data-testid="stRadio"] label {
    background: #172a24 !important;
    border: 1px solid rgba(255, 255, 255, 0.25) !important;
    border-radius: 8px !important;
    padding: 8px 12px !important;
    margin: 0 !important;
    width: 100% !important;
    box-sizing: border-box !important;
}
div[role="radiogroup"] > label:has(input:checked),
div[data-testid="stRadio"] label:has(input:checked) {
    border: 2px solid #10b981 !important;
    background: #1a3a30 !important;
    box-shadow: 0 0 0 1px rgba(16, 185, 129, 0.35) !important;
}
/* حماية ورقة التقرير الرسمي A4 داخل iframe من قواعد النص الأبيض في الواجهة */
iframe[title="components.a4"],
iframe[data-testid="stIFrame"],
[data-testid="stCustomComponentV1"],
[data-testid="element-container"] iframe,
.stElementContainer iframe {
    color-scheme: normal !important;
    background: transparent !important;
}
/* لا تُطبَّق قواعد اللون الأبيض على محتوى معاينة A4 (مستند iframe منفصل أصلاً) */

/* RTL_JUSTIFY_FIX */
[data-testid="stAppViewContainer"], [data-testid="stMarkdownContainer"], .stMarkdown { direction: rtl !important; text-align: right !important; }
.official-5lines, .official-5lines div,
.official-5lines-compact, .official-5lines-compact div { text-align: right !important; }
.auth-panel:empty { display: none !important; }
.legal-dark-box {
    direction: rtl !important; text-align: justify !important; text-justify: inter-word !important;
    text-align-last: right !important; unicode-bidi: embed !important; color: #e2e8f0 !important;
    width: 100% !important; max-width: 100% !important; box-sizing: border-box !important;
    padding: 14px 16px !important; line-height: 1.9 !important;
    overflow-wrap: anywhere !important; word-break: normal !important; white-space: normal !important;
}
.legal-dark-box .legal-title { direction: rtl !important; text-align: right !important; color: #d4a853 !important; font-weight: 800 !important; margin-bottom: 8px !important; }
.legal-dark-box .legal-body {
    direction: rtl !important; unicode-bidi: embed !important;
    text-align: justify !important; text-justify: inter-word !important; text-align-last: right !important;
    line-height: 1.9 !important; width: 100% !important; max-width: 100% !important;
    box-sizing: border-box !important; overflow-wrap: anywhere !important;
    word-break: normal !important; white-space: normal !important; color: #e2e8f0 !important;
}
@media print {
    @page { size: A4 portrait; margin: 6mm 8mm !important; }
    html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], .main, .block-container {
        direction: rtl !important;
        transform: none !important;
        height: auto !important;
        min-height: 0 !important;
        max-height: none !important;
        overflow: visible !important;
        padding: 0 !important;
        margin: 0 !important;
        background: #ffffff !important;
    }
    .stButton, [data-testid="stHorizontalBlock"], [data-testid="stVerticalBlockBorderWrapper"],
    .stTabs, header, footer, [data-testid="stHeader"], [data-testid="stToolbar"],
    [data-testid="stSidebar"], [data-testid="stDecoration"] {
        display: none !important;
    }
}
</style>
""", unsafe_allow_html=True)


# =====================================================================
# 2. تعريف النماذج الـ 12 والصيغ النظامية المحكمة
# =====================================================================
def _rtl_isolate(text: str, *, as_html: bool = True) -> str:
    """عزل القيم المختلطة (لوحة/هوية) لمنع انعكاس الأقواس في PDF."""
    v = str(text or "").strip()
    if not v:
        return "...................."
    if not as_html:
        return "\u200f" + v + "\u200f"
    return (
        '<span dir="rtl" style="unicode-bidi:isolate; white-space:normal;">'
        + html.escape(v)
        + "</span>"
    )


def render_print_button(report_html: str, btn_label: str = "🖨️ طباعة / حفظ التقرير PDF") -> None:
    """زر طباعة آمن للآيفون: يفتح نافذة جديدة داخل ضغطة المستخدم ثم يستدعي print()."""
    b64_report = base64.b64encode(str(report_html or "").encode("utf-8")).decode("utf-8")
    safe_label = html.escape(btn_label)
    component_code = f"""
    <div dir="rtl" style="text-align: center; font-family: Cairo, Tahoma, sans-serif; margin: 5px 0;">
        <button type="button" onclick="openIosSafePrint()" style="
            width: 100%;
            background-color: #14532d;
            color: #ffffff;
            border: 1px solid #c5a059;
            padding: 12px 20px;
            font-size: 16px;
            font-weight: bold;
            border-radius: 8px;
            cursor: pointer;">
            {safe_label}
        </button>
        <div id="ios-msg" style="display:none; color:#b91c1c; background:#fef2f2; border:1px solid #f87171; padding:8px; margin-top:8px; border-radius:6px; font-size:13px;">
            ⚠️ المتصفح يمنع فتح صفحة الطباعة: فضلاً افتح الرابط في متصفح <b>Safari</b> (أيقونة البوصلة بالأسفل) وأوقف "حظر النوافذ المنبثقة" من إعدادات سفاري.
        </div>
    </div>
    <script>
    function openIosSafePrint() {{
        try {{
            const binary = atob("{b64_report}");
            const bytes = Uint8Array.from(binary, c => c.charCodeAt(0));
            let htmlContent = new TextDecoder("utf-8").decode(bytes);
            const topBar = `
                <style>
                    @media print {{ .no-print-bar {{ display: none !important; }} }}
                    .no-print-bar {{
                        position: sticky; top: 0; z-index: 9999;
                        background: #14532d; color: #fff; padding: 12px;
                        display: flex; justify-content: space-around; align-items: center;
                        font-family: sans-serif; direction: rtl; margin-bottom: 10px;
                        font-weight: bold;
                    }}
                    .no-print-bar button {{
                        padding: 8px 16px; border: none; border-radius: 6px;
                        font-weight: bold; font-size: 15px; cursor: pointer;
                        background: #eab308; color: #000;
                    }}
                </style>
                <div class="no-print-bar">
                    <span>جاهز للطباعة أو الحفظ عبر زر المشاركة (⬆️) بالأسفل</span>
                    <button type="button" onclick="window.print()">🖨️ أمر الطباعة</button>
                </div>
            `;
            if (/<body[^>]*>/i.test(htmlContent)) {{
                htmlContent = htmlContent.replace(/(<body[^>]*>)/i, "$1" + topBar);
            }} else {{
                htmlContent = topBar + htmlContent;
            }}
            const autoPrint = "<script>window.addEventListener('load',function(){{setTimeout(function(){{try{{window.print();}}catch(e){{}}}},700);}});<\\/script>";
            if (/<\\/body>/i.test(htmlContent)) {{
                htmlContent = htmlContent.replace(/<\\/body>/i, autoPrint + "</body>");
            }} else {{
                htmlContent += autoPrint;
            }}
            const blob = new Blob([htmlContent], {{ type: "text/html;charset=utf-8" }});
            const blobUrl = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = blobUrl;
            link.target = "_blank";
            link.rel = "noopener";
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            document.getElementById("ios-msg").style.display = "none";
            setTimeout(function() {{ try {{ URL.revokeObjectURL(blobUrl); }} catch (e) {{}} }}, 8000);
        }} catch (err) {{
            document.getElementById("ios-msg").style.display = "block";
        }}
    }}
    </script>
    """
    components.html(component_code, height=110)


def normalize_official_legal_text(text: str) -> str:
    """وحّد المسافات والصق الأقواس بالنص حتى لا تنفصل على الجوال أو داخل A4."""
    raw = str(text or "")
    if not raw.strip():
        return ""
    raw = (
        raw.replace("\xa0", " ")
        .replace("\u202f", " ")
        .replace("\u200b", "")
        .replace("&nbsp;", " ")
        .replace("&#160;", " ")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    chunks = re.split(r"(<[^>]+>)", raw)
    cleaned = []
    for chunk in chunks:
        if not chunk:
            continue
        if chunk.startswith("<") and chunk.endswith(">"):
            cleaned.append(chunk)
            continue
        part = " ".join(chunk.splitlines())
        part = re.sub(r"[ \t\f\v]+", " ", part)
        # الصق القوس المفتوح بأول كلمة والمغلق بآخر كلمة
        part = re.sub(r"\(\s+", "(", part)
        part = re.sub(r"\s+\)", ")", part)
        part = re.sub(r"（\s+", "（", part)
        part = re.sub(r"\s+）", "）", part)
        # امنع انفصال القوس عن الكلمة المجاورة عند الالتفاف
        part = re.sub(r"\((\S)", lambda m: "(\u2060" + m.group(1), part)
        part = re.sub(r"(\S)\)", lambda m: m.group(1) + "\u2060)", part)
        cleaned.append(part)
    out = "".join(cleaned)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\s+([،,.؛;:!؟?])", r"\1", out)
    return out.strip()


def _val(values: dict, key: str) -> str:
    v = str(values.get(key, "")).strip()
    return _rtl_isolate(v, as_html=True) if v else "...................."


OTHER_OPTION = "أخرى (تحديد يدوي)"


def _sel(values: dict, key: str, other_key: str | None = None) -> str:
    """قيمة القائمة مع اعتماد النص اليدوي عند اختيار أخرى."""
    v = str((values or {}).get(key, "") or "").strip()
    ok = other_key or f"{key}_other"
    if "أخرى" in v:
        other = str((values or {}).get(ok, "") or "").strip()
        if other:
            return _rtl_isolate(other, as_html=True)
    return _rtl_isolate(v, as_html=True) if v else "...................."


def _other_field(select_key: str, label: str = "التحديد اليدوي (أخرى)") -> dict:
    return {
        "key": f"{select_key}_other",
        "label": label,
        "type": "text",
        "sample": "",
        "placeholder": "اكتب التفاصيل هنا",
        "visible_if": {"key": select_key, "contains_any": ["أخرى"]},
        "a4_hidden": True,
        "stack_under": True,
    }


def _resolve_select_display(fields_map: dict, key: str, shown: str) -> str:
    text = str(shown or "").strip()
    if "أخرى" in text:
        other = str((fields_map or {}).get(f"{key}_other", "") or "").strip()
        if other:
            return other
    return text or "-"


def _should_normalize_digits(field: dict) -> bool:
    if field.get("normalize_digits"):
        return True
    key = str(field.get("key") or "")
    label = str(field.get("label") or "")
    hints = ("_id", "phone", "incident_no", "wakala", "viol", "جوال", "هوية", "وكالة", "مخالف")
    return any(h in key for h in ("_id", "phone", "incident_no", "wakala", "viol")) or any(
        h in label for h in ("جوال", "هوية", "وكالة", "رقم الحادث", "رقم المخالف", "رقم البلاغ")
    )


_ARABIC_INDIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize_western_digits(text: str) -> str:
    """تحويل الأرقام العربية/الفارسية الهندية إلى إنجليزية مع الإبقاء على الحروف والرموز."""
    return str(text or "").translate(_ARABIC_INDIC_DIGITS)


_REF_FIELD_KEYS = {"incident_no", "ref_no", "reference_no", "case_no", "report_no"}
_REF_LABEL_TOKENS = (
    "رقم مرجعي",
    "الرقم المرجعي",
    "رقم الحادث",
    "رقم البلاغ",
    "رقم المحضر",
    "رقم المخالف",
    "رقم المعاملة",
    "رقم الواقعة",
)


def form_uses_reference_number(form_def: dict | None) -> bool:
    """هل النموذج يعتمد رقماً مرجعياً (حادث/بلاغ/محضر/إحالة)؟"""
    if not form_def:
        return False
    if form_def.get("category") == "تكميل":
        return False
    for fld in form_def.get("fields") or []:
        key = str(fld.get("key") or "")
        label = str(fld.get("label") or "")
        if key in _REF_FIELD_KEYS:
            return True
        if any(tok in label for tok in _REF_LABEL_TOKENS):
            return True
    return False


def form_primary_ref_field_key(form_def: dict | None) -> str:
    """مفتاح حقل الرقم المرجعي الأساسي داخل النموذج (غالباً incident_no)."""
    if not form_def:
        return "incident_no"
    for fld in form_def.get("fields") or []:
        key = str(fld.get("key") or "")
        if key in _REF_FIELD_KEYS:
            return key
    for fld in form_def.get("fields") or []:
        label = str(fld.get("label") or "")
        if any(tok in label for tok in _REF_LABEL_TOKENS):
            return str(fld.get("key") or "incident_no")
    return "incident_no"


def apply_manual_reference(values: dict | None, manual_ref: str, form_def: dict | None = None) -> dict:
    """دمج الرقم المرجعي اليدوي في قيم النموذج دون طمس الإدخال إن كان فارغاً."""
    out = dict(values or {})
    ref = normalize_western_digits(str(manual_ref or "").strip())
    out["manual_ref_no"] = ref
    if ref:
        primary = form_primary_ref_field_key(form_def)
        out[primary] = ref
        out["incident_no"] = ref
    return out


def sync_doc_no_with_manual_ref(manual_ref: str) -> str:
    """اعتماد الرقم اليدوي كـ doc_no عند تعبئته، وإلا الإبقاء على الرقم التلقائي المخزّن."""
    ref = normalize_western_digits(str(manual_ref or "").strip())
    st.session_state["manual_ref_no"] = ref
    auto = str(st.session_state.get("auto_doc_no") or "").strip()
    if not auto:
        auto = str(st.session_state.get("doc_no") or "").strip() or f"KH-{datetime.now(KSA_TZ).strftime('%y%m%d-%H%M%S')}"
        st.session_state["auto_doc_no"] = auto
    if ref:
        st.session_state.doc_no = ref
        return ref
    st.session_state.doc_no = auto
    return auto


def _is_agent_role(value: str) -> bool:
    text = str(value or "")
    return ("وكيل" in text) or ("وكالة" in text)


def _field_rule_matches(rule: dict, fields_map: dict) -> bool:
    if not rule:
        return False
    nested = rule.get("all")
    if isinstance(nested, list):
        return bool(nested) and all(_field_rule_matches(part, fields_map) for part in nested)
    source = str(fields_map.get(rule.get("key"), "") or "")
    tokens = rule.get("contains_any") or []
    return any(token in source for token in tokens)


def _field_is_visible(field: dict, fields_map: dict) -> bool:
    if _field_rule_matches(field.get("hide_if") or {}, fields_map):
        return False
    rule = field.get("visible_if") or {}
    if rule and not _field_rule_matches(rule, fields_map):
        return False
    return True


_PARTY_ORDINALS = ["", "الأول", "الثاني", "الثالث", "الرابع", "الخامس"]
_COUNT_TOKEN = {1: "(2)", 2: "(2)", 3: "(3)", 4: "(4)", 5: "(5)"}


def _count_parties(values: dict) -> int:
    label = str((values or {}).get("party_count") or "")
    for count in (5, 4, 3, 2):
        if _COUNT_TOKEN[count] in label:
            return count
    return 2


def _count_visible_tokens(index: int) -> list[str]:
    return [_COUNT_TOKEN[n] for n in range(index, 6)]


def _agr(singular: str, plural: str, is_plural: bool) -> str:
    """اختيار صياغة المفرد أو الجمع."""
    return plural if is_plural else singular


def _text_suggests_plural(text: str) -> bool | None:
    """True=جمع، False=مفرد، None=غير محسوم من النص."""
    raw = str(text or "").strip()
    if not raw:
        return None
    if any(tok in raw for tok in ("عدة", "أكثر من", "مصابين", "جثامين", "أطراف", "متعددين", "جماعة")):
        if "واحد" in raw and "عدة" not in raw and "أكثر" not in raw:
            return False
        return True
    if any(tok in raw for tok in ("واحد", "واحدة", "فرد", "مفرد", "جثمان واحد", "مصاب واحد", "طرف واحد")):
        return False
    return None


def _extra_people_listed(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    lowered = raw.replace("لا يوجد", "").replace("-", "").strip()
    if not lowered or lowered in {".", "لا", "بدون"}:
        return False
    return len(lowered) > 2


def _detect_people_count(values: dict, form_id: str = "") -> int:
    """استنتاج عدد الأشخاص/الأطراف لصياغة المفرد والجمع في الخطاب والحقول."""
    values = values or {}
    fid = str(form_id or "")

    if fid == "decl_settlement" or values.get("party_count"):
        return max(1, _count_parties(values))

    if fid == "med_injury" or values.get("cases_mode"):
        hint = _text_suggests_plural(values.get("cases_mode"))
        if hint is True or _extra_people_listed(values.get("other_injured")):
            return 2
        return 1

    if fid == "med_morgue" or values.get("deceased_count"):
        hint = _text_suggests_plural(values.get("deceased_count"))
        if hint is True or _extra_people_listed(values.get("other_deceased")):
            return 2
        return 1

    if fid == "decl_flee_waiver":
        return 2 if _flee_is_present(values) else 1

    if fid == "decl_animal_hit":
        return 2 if _animal_owner_present(values) else 1

    # نماذج الطرف الواحد افتراضياً (إقرار/محضر/تحليل سموم)
    for key in ("party_count", "cases_mode", "deceased_count", "people_count", "violators_count"):
        hint = _text_suggests_plural(values.get(key))
        if hint is True:
            return 2
        if hint is False:
            return 1
    return 1


def _is_plural_case(values: dict, form_id: str = "") -> bool:
    return _detect_people_count(values, form_id) >= 2


def _field_display_label(form_id: str, field: dict, values: dict) -> str:
    """تبديل تسميات الحقول بين المفرد والجمع حسب العدد الفعلي."""
    base = str((field or {}).get("label") or "")
    key = str((field or {}).get("key") or "")
    plural = _is_plural_case(values, form_id)
    if form_id == "med_injury":
        mapping = {
            "party_name": ("اسم المصاب الرباعي", "اسم المصاب الأول الرباعي"),
            "party_id": ("رقم الهوية / الإقامة والجنسية", "رقم الهوية / الإقامة والجنسية للمصاب الأول"),
            "plate_no": ("بيانات المركبة وصفته بالحادث", "بيانات المركبة وصفته بالحادث (المصاب الأول)"),
            "security_hold": ("التوجيه الأمني بعد تلقي العلاج", "التوجيه الأمني بعد تلقي العلاج للمصابين"),
            "other_injured": ("بيان المصابين الإضافيين (الاسم، الهوية، الصفة، الإصابة الظاهرة)",) * 2,
        }
        if key in mapping:
            return mapping[key][1] if plural else mapping[key][0]
    if form_id == "med_morgue":
        mapping = {
            "party_name": ("اسم المتوفى (أو مجهول الهوية مع أوصافه)", "اسم المتوفى الأول (أو مجهول الهوية مع أوصافه)"),
            "party_id": ("رقم الهوية / الإقامة والجنسية والعمر", "رقم الهوية / الإقامة والجنسية والعمر للمتوفى الأول"),
            "plate_no": ("المركبة ورقم اللوحة وصفة المتوفى بالحادث", "المركبة ورقم اللوحة وصفة المتوفى الأول بالحادث"),
            "forensic_order": ("التوجيه النظامي حيال التحفظ والكشف الطبي", "التوجيه النظامي حيال التحفظ والكشف الطبي للجثامين"),
            "other_deceased": ("بيانات الجثامين الإضافية عند تعدد الوفيات (الاسم، الهوية، الصفة)",) * 2,
        }
        if key in mapping:
            return mapping[key][1] if plural else mapping[key][0]
    if form_id == "decl_settlement" and key == "party_count":
        return base
    return base


def _form_display_title(form_def: dict, values: dict, form_id: str = "") -> str:
    title = str((form_def or {}).get("title") or "")
    fid = str(form_id or (form_def or {}).get("id") or "")
    plural = _is_plural_case(values, fid)
    if fid == "med_injury" or "مصاب / مصابين" in title:
        return "نموذج معالجة مصابين" if plural else "نموذج معالجة مصاب"
    if fid == "med_morgue" or "جثمان / جثامين" in title:
        return "نموذج إيداع جثامين" if plural else "نموذج إيداع جثمان"
    return title


def _med_injury_legal(m: dict) -> str:
    plural = _is_plural_case(m, "med_injury")
    mode_raw = str((m or {}).get("cases_mode") or "").strip()
    # صياغة واضحة للمفرد دون تكرار جمع/أول
    if plural:
        mode_text = mode_raw or "عدة مصابين في حادث مروري"
        data_label = "وبيانات المصاب الرئيسي"
        extras = ""
        if str(m.get("other_injured") or "").strip():
            extras = f"، وبيان المصابين الإضافيين: ({_val(m, 'other_injured')})"
        aid_clause = "وإسعافهم ومعالجتهم وتنويم من تستدعي حالته الصحية ذلك"
        report_clause = "وموافاتنا بتقرير طبي مفصل ومعتمد لكل حالة يوضح نوع الإصابات ومدة الشفاء المقررة"
        exit_clause = "حيال خروجهم"
        arrive_clause = "والواصلين إليكم"
    else:
        mode_text = "مصاب واحد في حادث مروري" if ("واحد" in mode_raw or not mode_raw) else mode_raw
        data_label = "وبيانات المصاب"
        extras = ""
        aid_clause = "وإسعافه ومعالجته وتنويمه إن تستدعي حالته الصحية ذلك"
        report_clause = "وموافاتنا بتقرير طبي مفصل ومعتمد يوضح نوع الإصابة ومدة الشفاء المقررة"
        exit_clause = "حيال خروجه"
        arrive_clause = "والواصل إليكم"
    mode = _rtl_isolate(mode_text, as_html=True) if mode_text else _val(m, "cases_mode")
    return (
        f"سعادة مدير ({_val(m, 'hospital_name')}) المحترم، السلام عليكم ورحمة الله وبركاته.. "
        f"إشارةً إلى الحادث المروري رقم ({_val(m, 'incident_no')})، نبعث لسعادتكم ({mode})، {data_label}: "
        f"({_val(m, 'party_name')} - هوية: {_val(m, 'party_id')} - {_val(m, 'plate_no')})"
        f"{extras}، {arrive_clause} ({_sel(m, 'transport_way')}). "
        f"نأمل الأمر بإجراء الكشف الطبي اللازم {aid_clause}، {report_clause}، "
        f"مع اعتماد التوجيه الأمني التالي {exit_clause}: ({_sel(m, 'security_hold')})."
    )


def _med_morgue_legal(m: dict) -> str:
    plural = _is_plural_case(m, "med_morgue")
    mode = _val(m, "deceased_count")
    extras = ""
    if plural and str(m.get("other_deceased") or "").strip():
        extras = f"، والبيان الإضافي للوفيات: ({_val(m, 'other_deceased')})"
    body_label = _agr("وبيانات الجثمان", "وبيانات الجثمان الأول", plural)
    receive_clause = _agr(
        "استلام وإيداع الجثمان في الثلاجة رسمياً",
        "استلام وإيداع الجثامين في الثلاجة رسمياً",
        plural,
    )
    report_clause = _agr(
        "وإجراء الكشف الطبي اللازم وموافاتنا بتقرير الوفاة المعتمد",
        "وإجراء الكشف الطبي اللازم وموافاتنا بتقارير الوفاة المعتمدة لكل حالة",
        plural,
    )
    return (
        f"سعادة مدير ({_val(m, 'hospital_name')}) المحترم، السلام عليكم ورحمة الله وبركاته.. "
        f"على إثر الحادث المروري الجسيم رقم ({_val(m, 'incident_no')})، جرى بعث ({mode}) للإيداع بثلاجة الموتى طرفكم، "
        f"{body_label}: ({_val(m, 'party_name')} - هوية: {_val(m, 'party_id')} - {_val(m, 'plate_no')})"
        f"{extras}، حيث كانت واقعة الوفاة والنقل: ({_sel(m, 'transport_death')}). "
        f"نأمل من سعادتكم الأمر بـ{receive_clause}، {report_clause}، "
        f"مع التقيد التام بالتوجيه النظامي التالي: ({_sel(m, 'forensic_order')})."
    )


def _settlement_legal(values: dict) -> str:
    count = _count_parties(values)
    clauses = []
    for index in range(1, count + 1):
        ordinal = _PARTY_ORDINALS[index]
        role = str(values.get(f"p{index}_role") or "")
        if "مبلغ مالي" in role:
            role_text = f"بصفته في الإقرار (صلح وتنازل عن مبلغ مالي وقدره: {_val(values, f'p{index}_amount')})"
        else:
            role_text = f"صفته ({_val(values, f'p{index}_role')})"
        clause = (
            f"الطرف {ordinal}: ({_val(values, f'p{index}_name')})، هوية رقم ({_val(values, f'p{index}_id')})، "
            f"جوال ({_val(values, f'p{index}_phone')})، مركبة ({_val(values, f'p{index}_vehicle')})، "
            f"{role_text}، وتوقيعه ({_val(values, f'p{index}_capacity')})"
        )
        if "وكيل" in str(values.get(f"p{index}_capacity") or ""):
            clause += (
                f"، بموجب الوكالة الشرعية المخولة بالصلح والتنازل رقم ({_val(values, f'p{index}_wakala_no')}) "
                f"وتاريخ ({_val(values, f'p{index}_wakala_date')})، والوكيل الحاضر ({_val(values, f'p{index}_agent')})"
            )
        clauses.append(clause)
    compensation = ""
    if "عوض" in str(values.get("settlement_basis") or ""):
        compensation = f" وتفاصيل العوض أو الإصلاح: ({_val(values, 'compensation')})."
    if count <= 1:
        opener = (
            f"أقر أنا الطرف الموقع أدناه في الحادث المروري رقم ({_val(values, 'incident_no')}) "
            f"الواقع في ({_val(values, 'incident_loc')})، بصفتي الطرف الوحيد المشمول بهذا الصلح، وهو: "
        )
        closer = (
            f". وأساس الصلح والتنازل: ({_val(values, 'settlement_basis')}).{compensation} "
            f"وأقر بأن ({_val(values, 'injury_statement')}). "
            "وبموجب هذا الإقرار أُسقط مطالبتي بالحق الخاص إسقاطاً نهائياً لا رجعة فيه أمام قسم مرور العارضة "
            "وأمام الجهات القضائية، وأُبرئ الذمة فيما شمله هذا الصلح من التلفيات المادية."
        )
    else:
        opener = (
            f"نقر نحن الأطراف الموقعة أدناه في الحادث المروري رقم ({_val(values, 'incident_no')}) "
            f"الواقع في ({_val(values, 'incident_loc')})، وعدد الأطراف المشمولين بهذا الصلح ({count})، وهم: "
        )
        closer = (
            f". وأساس الصلح والتنازل: ({_val(values, 'settlement_basis')}).{compensation} "
            f"ونقر بأن ({_val(values, 'injury_statement')}). "
            "وبموجب هذا الإقرار نُسقط مطالبتنا بالحق الخاص إسقاطاً نهائياً لا رجعة فيه أمام قسم مرور العارضة "
            "وأمام الجهات القضائية، ونُبرئ ذمة بعضنا فيما شمله هذا الصلح من التلفيات المادية."
        )
    return opener + "؛ ".join(clauses) + closer


def _flee_is_present(values: dict) -> bool:
    return "حضور" in str((values or {}).get("waiver_status") or "")


def _animal_owner_present(values: dict) -> bool:
    return "حضور مالك" in str((values or {}).get("legal_mode") or "")


def _animal_type_text(values: dict) -> str:
    kind = str((values or {}).get("animal_type") or "").strip()
    if "أخرى" in kind:
        custom = str((values or {}).get("animal_type_other") or "").strip()
        return custom or kind
    return kind or "-"


def _animal_hit_legal(values: dict) -> str:
    animal = _rtl_isolate(_animal_type_text(values), as_html=True)
    count = _val(values, "animal_count")
    damages = _val(values, "vehicle_damage")
    health = _val(values, "health_status")
    animal_state = _val(values, "animal_state")
    mode = str(values.get("legal_mode") or "")
    harm_line = f"{damages} — الحالة الصحية: {health}"
    if "مجهول المالك" in mode or "سائب" in mode:
        return (
            f"أقر أنا السائق الموضح اسمي وهويتي أعلاه، وأنا بكامل أهليتي المعتبرة شرعاً ونظاماً، "
            f"بأنه أثناء قيادتي للمركبة المذكورة في الموقع والتاريخ المحددين أعلاه وقع لي حادث صدم حيوان من نوع "
            f"({animal} - العدد: {count}) خرج فجأة إلى نهر الطريق، ونتج عن الحادث ({harm_line}) "
            f"وحالة الحيوان ({animal_state}). كما أقر بعد المعاينة عدم وجود وسم ظاهر أو معرفة بمالك للحيوان في حينه، "
            f"ولا أتهم أحداً بالتسبب العمد، وأطلب استكمال الإجراءات النظامية ومنحي إذن إصلاح للمركبة، "
            f"مع احتفاظي بحقي النظامي في حال ظهور مالك للحيوان يثبت تفريطه وفق نظام المرور ولائحته التنفيذية، "
            f"وعلى ذلك أقر وأوقع."
        )
    if "صلح" in mode and "تنازل" in mode:
        return (
            f"نقر نحن الطرفين الموقعين أدناه: السائق المقر ({_val(values, 'party_name')}) هوية رقم ({_val(values, 'party_id')}) "
            f"جوال ({_val(values, 'party_phone')}) قائد المركبة ({_val(values, 'vehicle_desc')}) لوحة ({_val(values, 'plate_no')})، "
            f"ومالك الحيوان ({_val(values, 'owner_name')}) هوية رقم ({_val(values, 'owner_id')}) جوال ({_val(values, 'owner_phone')})، "
            f"بوقوع حادث صدم حيوان من نوع ({animal} - العدد: {count}) في البلاغ رقم ({_val(values, 'incident_no')}) "
            f"بتاريخ ({_val(values, 'incident_datetime')}) بموقع ({_val(values, 'incident_loc')}) وحالة الطريق ({_val(values, 'road_condition')})، "
            f"وحالة الحيوان ({animal_state}) ووسمه/شريحته ({_val(values, 'tag_status')} — {_val(values, 'tag_detail')})، "
            f"ونتج عن الحادث ({harm_line}). وقد تصالحنا تصالحاً تاماً بـ ({_val(values, 'settlement_detail')})، "
            f"وتنازل كل طرف عن الآخر تنازلاً نهائياً مبرئاً للذمة في الحق الخاص المتعلق بالمركبة والحيوان، "
            f"دون الإخلال بما تقضي به التعليمات النظامية بشأن الحق العام، وعلى ذلك نقر ونوقع."
        )
    return (
        f"جري إثبات واقعة صدم حيوان رسمياً بين السائق المقر ({_val(values, 'party_name')}) هوية رقم ({_val(values, 'party_id')}) "
        f"جوال ({_val(values, 'party_phone')}) قائد المركبة ({_val(values, 'vehicle_desc')}) لوحة ({_val(values, 'plate_no')})، "
        f"ومالك الحيوان ({_val(values, 'owner_name')}) هوية رقم ({_val(values, 'owner_id')}) جوال ({_val(values, 'owner_phone')})، "
        f"وذلك في البلاغ رقم ({_val(values, 'incident_no')}) بتاريخ ({_val(values, 'incident_datetime')}) "
        f"بموقع ({_val(values, 'incident_loc')}) وحالة الطريق ({_val(values, 'road_condition')})، "
        f"ونوع الحيوان ({animal} - العدد: {count}) وحالته ({animal_state}) ووسمه/شريحته "
        f"({_val(values, 'tag_status')} — {_val(values, 'tag_detail')})، وما نتج عن الحادث ({harm_line}). "
        f"وأقوال الطرفين وتفاصيل المطالبة بالحق الخاص: ({_val(values, 'settlement_detail')}). "
        f"ويُوثَّق ذلك لاستكمال إجراءات الفصل في الحق الخاص وفق نظام المرور ولائحته التنفيذية، دون إخلال بالحق العام."
    )


def _flee_waiver_legal(values: dict) -> str:
    capacity = str(values.get("signer_capacity") or "")
    if "وكيل" in capacity:
        capacity_text = (
            f"بصفتي وكيلاً شرعياً مخولاً بالتنازل بموجب الوكالة رقم ({_val(values, 'wakala_no')}) "
            f"وتاريخ ({_val(values, 'wakala_date')})، والوكيل الحاضر ({_val(values, 'agent_present')})،"
        )
    else:
        capacity_text = "بصفتي أصالة عن نفسي،"
    if _flee_is_present(values):
        branch = (
            f"وذلك بعد معرفة/حضور الطرف المتسبب ({_val(values, 'cause_name')})، هوية رقم ({_val(values, 'cause_id')})، "
            f"جوال ({_val(values, 'cause_phone')})، ومركبته ({_val(values, 'cause_vehicle')})، "
            f"وتفاصيل التسوية أو العوض المستلم: ({_val(values, 'settlement_detail')}). "
        )
    else:
        branch = f"وأطلب حفظ وإقفال البلاغ بسبب ({_val(values, 'close_reason')}). "
    return (
        f"أقر أنا المُبلّغ المتضرر ({_val(values, 'party_name')})، هوية رقم ({_val(values, 'party_id')})، "
        f"جوال ({_val(values, 'party_phone')})، والمركبة المتضررة ({_val(values, 'plate_no')})، {capacity_text} "
        f"بشأن بلاغ الصدم والهروب رقم ({_val(values, 'incident_no')}) الواقع في ({_val(values, 'incident_loc')})، "
        f"وحالة التنازل: ({_val(values, 'waiver_status')}). {branch}"
        "وبموجب هذا الإقرار أتنازل تنازلاً نهائياً لا رجعة فيه عن حقي الخاص في واقعة الصدم والهروب المشار إليها، "
        "وأُبرئ ذمة الطرف الآخر من التلفيات المادية محل هذا التنازل. "
        "(علماً بأن هذا التنازل يقتصر على الحق الخاص فقط ولا يخل بتطبيق الإجراءات النظامية المقررة بالحق العام "
        "حيال مخالفة الهروب من موقع الحادث وفق نظام المرور ولائحته التنفيذية)."
    )


def _waiver_signers(form_id: str, fields_map: dict) -> list[dict]:
    if form_id == "decl_settlement":
        signers = []
        for index in range(1, _count_parties(fields_map) + 1):
            ordinal = _PARTY_ORDINALS[index]
            name = str(fields_map.get(f"p{index}_name") or "").strip()
            capacity = str(fields_map.get(f"p{index}_capacity") or "").strip()
            agent = str(fields_map.get(f"p{index}_agent") or "").strip()
            role = f"{capacity} — {agent}" if ("وكيل" in capacity and agent) else capacity
            signers.append({
                "pad": f"p{index}",
                "header": f"توقيع الطرف {ordinal}",
                "name": name,
                "role": role,
                "pad_title": f"لوحة توقيع: الطرف {ordinal}",
                "sub": " — ".join(part for part in (name, role) if part) or f"الطرف {ordinal}",
            })
        return signers
    if form_id == "decl_flee_waiver":
        name = str(fields_map.get("party_name") or "").strip()
        capacity = str(fields_map.get("signer_capacity") or "").strip()
        agent = str(fields_map.get("agent_present") or "").strip()
        role = f"{capacity} — {agent}" if ("وكيل" in capacity and agent) else capacity
        signers = [{
            "pad": "p1",
            "header": "توقيع المُبلّغ المتنازل",
            "name": name,
            "role": role,
            "pad_title": "لوحة توقيع: المُبلّغ المتنازل",
            "sub": " — ".join(part for part in (name, role) if part) or "المُبلّغ المتنازل",
        }]
        if _flee_is_present(fields_map):
            cause_name = str(fields_map.get("cause_name") or "").strip()
            signers.append({
                "pad": "p2",
                "header": "توقيع الطرف المتسبب",
                "name": cause_name,
                "role": "الطرف المتسبب الحاضر",
                "pad_title": "لوحة توقيع: الطرف المتسبب",
                "sub": cause_name or "الطرف المتسبب",
            })
        return signers
    if form_id == "decl_animal_hit":
        driver = str(fields_map.get("party_name") or "").strip()
        signers = [{
            "pad": "p1",
            "header": "توقيع وبصمة السائق المقر",
            "name": driver,
            "role": "السائق المقر",
            "pad_title": "لوحة توقيع: السائق المقر",
            "sub": driver or "السائق المقر",
        }]
        if _animal_owner_present(fields_map):
            owner = str(fields_map.get("owner_name") or "").strip()
            signers.append({
                "pad": "p2",
                "header": "توقيع وبصمة مالك الحيوان",
                "name": owner,
                "role": "مالك الحيوان",
                "pad_title": "لوحة توقيع: مالك الحيوان",
                "sub": owner or "مالك الحيوان",
            })
        return signers
    return []


def _party_block(index: int, sample: dict) -> list[dict]:
    ordinal = _PARTY_ORDINALS[index]
    count_rule = {"key": "party_count", "contains_any": _count_visible_tokens(index)}
    agent_rule = {"all": [count_rule, {"key": f"p{index}_capacity", "contains_any": ["وكيل"]}]}
    money_rule = {"all": [count_rule, {"key": f"p{index}_role", "contains_any": ["مبلغ مالي"]}]}
    prefix = f"p{index}_"
    return [
        {"key": f"{prefix}name", "label": f"الاسم الرباعي للطرف {ordinal}", "type": "text", "sample": sample["name"],
         "visible_if": count_rule, "a4_label": f"الطرف {ordinal}", "a4_keep_pair": True,
         "a4_compose": {"keys": [f"{prefix}id"], "fmt": "{value} — هوية: {" + prefix + "id}"}},
        {"key": f"{prefix}id", "label": f"رقم الهوية أو الإقامة للطرف {ordinal}", "type": "text", "sample": sample["nid"],
         "visible_if": count_rule, "a4_hidden": True},
        {"key": f"{prefix}phone", "label": f"رقم جوال الطرف {ordinal}", "type": "text", "sample": sample["phone"],
         "visible_if": count_rule, "a4_label": f"جوال الطرف {ordinal}", "a4_keep_pair": True},
        {"key": f"{prefix}vehicle", "label": f"نوع المركبة ورقم لوحتها — الطرف {ordinal}", "type": "text", "sample": sample["vehicle"],
         "visible_if": count_rule, "a4_label": f"مركبة الطرف {ordinal}", "a4_keep_pair": True},
        {"key": f"{prefix}role", "label": f"صفته في الإقرار — الطرف {ordinal}", "type": "select",
         "options": ["متنازل ومبرئ للذمة", "متنازل له", "صلح وتنازل متبادل", "صلح وتنازل عن مبلغ مالي"],
         "sample": sample["role"],
         "visible_if": count_rule, "a4_label": f"صفة الطرف {ordinal}", "a4_keep_pair": True,
         "a4_compose": {
             "keys": [f"{prefix}capacity"],
             "fmt": "{value} — التوقيع: {" + prefix + "capacity}",
             "append_if": f"{prefix}amount",
             "append_fmt": " — وقدره: {extra}",
         }},
        {"key": f"{prefix}amount", "label": f"💰 مقدار المبلغ المالي — الطرف {ordinal}", "type": "text",
         "placeholder": "اكتب المبلغ رقماً أو كتابة (مثال: 5000 ريال سعودي)",
         "sample": "5000 ريال سعودي", "visible_if": money_rule, "stack_under": True, "a4_hidden": True},
        {"key": f"{prefix}capacity", "label": f"صفة التوقيع — الطرف {ordinal}", "type": "select",
         "options": ["أصالة عن نفسه", "وكيل شرعي مخول بالتنازل"], "sample": sample["cap"],
         "visible_if": count_rule, "a4_hidden": True},
        {"key": f"{prefix}wakala_no", "label": f"رقم الوكالة الشرعية المخولة بالصلح والتنازل — الطرف {ordinal}", "type": "text",
         "sample": sample.get("wakala", "461829405"), "visible_if": agent_rule, "a4_label": f"وكالة الطرف {ordinal}", "a4_keep_pair": True,
         "a4_compose": {"keys": [f"{prefix}wakala_date", f"{prefix}agent"], "fmt": "رقم {value} بتاريخ {" + prefix + "wakala_date} — الوكيل: {" + prefix + "agent}"}},
        {"key": f"{prefix}wakala_date", "label": f"تاريخ الوكالة — الطرف {ordinal}", "type": "text",
         "sample": sample.get("wakala_date", "1448/04/15 هـ"), "visible_if": agent_rule, "a4_hidden": True},
        {"key": f"{prefix}agent", "label": f"اسم وهوية الوكيل الحاضر — الطرف {ordinal}", "type": "text",
         "sample": sample.get("agent", "فهد بن سعيد القحطاني — هوية 1099887766"), "visible_if": agent_rule, "a4_hidden": True},
    ]


_SETTLEMENT_PARTY_SAMPLES = [
    {},
    {"name": "محمد بن علي بن سعد السبيعي", "nid": "1023456789", "phone": "0551112233", "vehicle": "تويوتا كامري أبيض - ح ط ر 4512", "role": "صلح وتنازل متبادل", "cap": "أصالة عن نفسه"},
    {"name": "عبدالرحمن بن محمد بن علي السبيعي", "nid": "1087654321", "phone": "0551234567", "vehicle": "هيونداي سوناتا رمادي - ب د ع 8821", "role": "صلح وتنازل متبادل", "cap": "وكيل شرعي مخول بالتنازل", "wakala": "461829405", "wakala_date": "1448/04/15 هـ", "agent": "فهد بن سعيد القحطاني — هوية 1099887766"},
    {"name": "خالد بن سعيد بن أحمد الزهراني", "nid": "1065432189", "phone": "0509876543", "vehicle": "كيا سيراتو أبيض - ع م ن 2039", "role": "متنازل ومبرئ للذمة", "cap": "أصالة عن نفسه"},
    {"name": "سلطان بن فهد بن ناصر الحربي", "nid": "1092233445", "phone": "0543322110", "vehicle": "فورد تورس أسود - د ص ق 7740", "role": "متنازل له", "cap": "أصالة عن نفسه"},
    {"name": "ياسر بن إبراهيم بن حمد الشهري", "nid": "1078899001", "phone": "0567788990", "vehicle": "نيسان باترول بيج - أ ك س 1190", "role": "صلح وتنازل متبادل", "cap": "أصالة عن نفسه"},
]


def _settlement_fields() -> list[dict]:
    fields = [
        {"key": "incident_no", "label": "رقم الحادث المرجعي وتاريخه", "type": "text", "sample": "460990101 - 1448/06/12 هـ", "a4_keep_pair": True},
        {"key": "incident_loc", "label": "موقع الحادث", "type": "text", "sample": "تقاطع طريق الملك فهد مع شارع السوق بالعارضة", "a4_keep_pair": True},
        {"key": "party_count", "label": "عدد أطراف الحادث المشمولين بالتنازل", "type": "select",
         "options": ["طرفان (2)", "ثلاثة أطراف (3)", "أربعة أطراف (4)", "خمسة أطراف (5)"],
         "sample": "طرفان (2)", "a4_keep_pair": True},
    ]
    for index in range(1, 6):
        fields.extend(_party_block(index, _SETTLEMENT_PARTY_SAMPLES[index]))
    fields.extend([
        {"key": "settlement_basis", "label": "أساس الصلح والتنازل", "type": "select", "options": [
            "صلح وتنازل متبادل بين الأطراف وإصلاح كل طرف لمركبته على حسابه الخاص",
            "تنازل تام بدون مقابل إبراءً للذمة",
            "تنازل بعد استلام عوض مالي / اتفاق إصلاح التلفيات",
        ], "sample": "صلح وتنازل متبادل بين الأطراف وإصلاح كل طرف لمركبته على حسابه الخاص"},
        {"key": "compensation", "label": "مقدار العوض المالي المستلم أو تفاصيل اتفاق الإصلاح", "type": "textarea",
         "sample": "استلم الطرف الأول مبلغ (1500) ريال مقابل إصلاح الصدام، وأصلح الطرف الثاني مركبته على حسابه.",
         "visible_if": {"key": "settlement_basis", "contains_any": ["عوض"]}},
        {"key": "injury_statement", "label": "الإقرار المروري", "type": "textarea", "prefill_sample": True,
         "sample": "الحادث تلفيات مادية فقط ولا توجد أي إصابات بشرية أو وفيات أو تلفيات في الممتلكات العامة"},
    ])
    return fields


def _toxicology_legal(values: dict) -> str:
    awtar = normalize_western_digits(str((values or {}).get("awtar_no") or "").strip())
    awtar_clause = (
        f" والمقيد بمنصة (أوتار) برقم: ({_rtl_isolate(awtar, as_html=True)})"
        if awtar
        else ""
    )
    return (
        f"سعادة مدير ({_val(values, 'lab_dest')}) المحترم، السلام عليكم ورحمة الله وبركاته.. "
        f"استناداً إلى أحكام نظام المرور ولائحته التنفيذية وإجراءات الاستدلال في الحادث/المحضر رقم ({_val(values, 'incident_no')})"
        f"{awtar_clause}، "
        f"نبعث لسعادتكم المدعو ({_val(values, 'party_name')})، حامل الهوية رقم ({_val(values, 'party_id')})، وعلاقته بالواقعة ({_val(values, 'plate_no')})، "
        f"وذلك بناءً على المسوغ النظامي: ({_sel(values, 'suspicion_signs')}). نأمل توجيه المختصين بإجراء ({_sel(values, 'sample_type')}) وفق الأصول الفنية المعتمدة "
        f"وتوثيق وقت أخذ العينة وسلسلة الحيازة النظامية، وموافاتنا بالتقرير المخبري القطعي السري في مظروف رسمي مختوم، مع مراعاة الترتيب الأمني: ({_val(values, 'escort_info')})."
    )


def _statement_legal(values: dict) -> str:
    role = str((values or {}).get("speaker_role") or "")
    name = _val(values, "party_name")
    nid = _val(values, "party_id")
    incident = _val(values, "incident_no")
    statement = _val(values, "statement_text")
    plate = str((values or {}).get("plate_no") or "").strip()
    lane = str((values or {}).get("lane_speed") or "").strip()
    non_driver = any(
        token in role
        for token in ("شاهد", "مشاة", "عابر", "مالك مركبة متوقفة", "عين متضررة", "راكب", "مرافق")
    )
    if non_driver:
        plate_clause = f"، وبخصوص المركبة/العين ({_rtl_isolate(plate, as_html=True)})" if plate else ""
        lane_clause = f"، وموضعي/ملاحظتي مرتبطة بـ ({_rtl_isolate(lane, as_html=True)})" if lane else ""
        return (
            f"أقر أنا ({name})، حامل الهوية رقم ({nid})، بصفتي ({_val(values, 'speaker_role')})"
            f"{plate_clause} في الحادث رقم ({incident}){lane_clause}، "
            f"بأن إفادتي الفورية بالموقع تتلخص في الآتي: \"{statement}\". "
            f"وقد أدليت بهذه الأقوال طواعية وبكامل أهليتي فور مباشرة الحادث ودون إكراه لاعتمادها ضمن محاضر الاستدلال المروري."
        )
    lane_txt = _rtl_isolate(lane, as_html=True) if lane else "...................."
    return (
        f"أقر أنا ({name})، حامل الهوية رقم ({nid})، بصفتي ({_val(values, 'speaker_role')}) للمركبة ({_val(values, 'plate_no')}) "
        f"في الحادث رقم ({incident})، بأنني كنت أسير في ({lane_txt})، وتتلخص إفادتي الفورية بالموقع في الآتي: "
        f"\"{statement}\". وقد أدليت بهذه الأقوال طواعية وبكامل أهليتي فور مباشرة الحادث ودون إكراه لاعتمادها ضمن محاضر الاستدلال المروري."
    )


def _handover_legal(values: dict) -> str:
    closing = (
        " وبكامل مقتنياتها الشخصية دون نقص، "
        "وبموجبه أخلي مسؤولية قسم مرور العارضة والفرقة المباشرة من سحب المركبة أو حجزها، "
        "وأتعهد بعدم قيادتها في حال وجود أي خلل يؤثر على السلامة العامة."
    )
    if _is_agent_role(values.get("receiver_role")):
        return (
            f"أقر أنا الموقع أدناه ({_val(values, 'agent_name')})، هوية رقم ({_val(values, 'agent_id')})، "
            f"جوال رقم ({_val(values, 'party_phone')})، "
            f"بصفتي وكيلاً شرعياً عن مالك المركبة ({_val(values, 'principal_name')} - هوية رقم: {_val(values, 'principal_id')}) "
            f"بموجب الوكالة الشرعية السارية رقم ({_val(values, 'wakala_no')}) وتاريخ ({_val(values, 'wakala_date')})، "
            f"بأنني استلمت المركبة ({_val(values, 'vehicle_desc')}) التي تحمل اللوحة رقم ({_val(values, 'plate_no')}) "
            f"في موقع الحادث رقم ({_val(values, 'incident_no')}) بحالتها الراهنة ({_val(values, 'vehicle_state')})"
            + closing
        )
    return (
        f"أقر أنا الموقع والمبصم أدناه ({_val(values, 'party_name')})، حامل الهوية رقم ({_val(values, 'party_id')})، "
        f"بصفتي ({_val(values, 'receiver_role')})، بأنني استلمت المركبة ({_val(values, 'vehicle_desc')}) التي تحمل اللوحة رقم ({_val(values, 'plate_no')}) "
        f"في موقع الحادث رقم ({_val(values, 'incident_no')}) مباشرةً بحالتها الراهنة ({_val(values, 'vehicle_state')})"
        + closing
    )


def _include_field_on_a4(field: dict, fields_map: dict) -> bool:
    if field.get("a4_hidden"):
        return False
    if _field_rule_matches(field.get("hide_if") or {}, fields_map):
        return False
    rule = field.get("visible_if") or {}
    if not rule:
        return True
    if not _field_rule_matches(rule, fields_map):
        return False
    return field.get("key") in fields_map


def _minutes_form_from_template(src: dict) -> dict:
    """يحوّل قالب abu_arish_impound إلى نموذج محضر بنفس محرك الحقول والخطاب."""
    fields = []
    for raw in src["fields"]:
        item = {
            "key": raw["key"],
            "label": raw["label"],
            "type": raw.get("type") or "text",
            "sample": raw.get("default", raw.get("sample", "")),
        }
        if raw.get("options"):
            item["options"] = list(raw["options"])
        fields.append(item)
    statement = src["statement_template"]
    field_keys = [item["key"] for item in fields]

    def legal_fn(values, template=statement, keys=tuple(field_keys)):
        return template.format_map({key: _val(values, key) for key in keys})

    return {
        "title": src["title"],
        "official_title": src["official_title"],
        "icon": src.get("icon") or "🅿️",
        "subtitle": src["subtitle"],
        "category": "محضر",
        "allow_absence": False,
        "require_image": False,
        "is_official_letter": True,
        "recipient_role_title": src["recipient_role_title"],
        "fields": fields,
        "legal_fn": legal_fn,
    }


TRAFFIC_FORMS = {
    # ==================== أولاً: قائمة الإقرارات الميدانية ====================
    "decl_handover": {
        "title": "إقرار تسليم مركبة في الموقع",
        "icon": "🚗",
        "subtitle": "توثيق تسليم المركبة لمالكها أو المفوض بالموقع وإخلاء مسؤولية الفرقة من السحب",
        "category": "إقرار",
        "allow_absence": False,
        "require_image": False,
        "fields": [
            {"key": "incident_no", "label": "رقم الحادث المرجعي", "type": "text", "sample": "460982341"},
            {"key": "receiver_role", "label": "صفة المستلم", "type": "select", "options": [
                "مالك المركبة بموجب رخصة السير",
                "مفوض رسمي بقيادة المركبة",
                "وكيل شرعي بموجب وكالة سارية",
                "مندوب جهة حكومية / شركة / مكتب تأجير بموجب تفويض رسمي",
            ], "sample": "مالك المركبة بموجب رخصة السير"},
            {"key": "party_name", "label": "اسم المستلم الرباعي", "type": "text", "sample": "عبدالرحمن بن محمد بن علي السبيعي",
             "hide_if": {"key": "receiver_role", "contains_any": ["وكيل", "وكالة"]}},
            {"key": "party_id", "label": "رقم الهوية / الإقامة", "type": "text", "sample": "1087654321",
             "hide_if": {"key": "receiver_role", "contains_any": ["وكيل", "وكالة"]}},
            {"key": "agent_name", "label": "اسم الوكيل الشرعي (المستلم)", "type": "text", "sample": "عبدالرحمن بن محمد بن علي السبيعي", "prefill_sample": True,
             "visible_if": {"key": "receiver_role", "contains_any": ["وكيل", "وكالة"]},
             "a4_label": "الوكيل الشرعي (المستلم)",
             "a4_compose": {"keys": ["agent_id"], "fmt": "{value} — هوية: {agent_id}"}},
            {"key": "agent_id", "label": "رقم هوية الوكيل", "type": "text", "sample": "1087654321", "prefill_sample": True,
             "visible_if": {"key": "receiver_role", "contains_any": ["وكيل", "وكالة"]},
             "a4_hidden": True},
            {"key": "principal_name", "label": "اسم الموكّل (مالك المركبة الأصلي)", "type": "text", "sample": "محمد بن علي بن سعد السبيعي", "prefill_sample": True,
             "visible_if": {"key": "receiver_role", "contains_any": ["وكيل", "وكالة"]},
             "a4_label": "الموكّل (مالك المركبة)",
             "a4_compose": {"keys": ["principal_id"], "fmt": "{value} — هوية: {principal_id}"}},
            {"key": "principal_id", "label": "رقم هوية / إقامة الموكّل", "type": "text", "sample": "1023456789", "prefill_sample": True,
             "visible_if": {"key": "receiver_role", "contains_any": ["وكيل", "وكالة"]},
             "a4_hidden": True},
            {"key": "wakala_no", "label": "رقم الوكالة الشرعية / الإلكترونية", "type": "text", "sample": "461829405", "prefill_sample": True,
             "visible_if": {"key": "receiver_role", "contains_any": ["وكيل", "وكالة"]},
             "a4_label": "الوكالة الشرعية",
             "a4_compose": {"keys": ["wakala_date"], "fmt": "رقم {value} بتاريخ {wakala_date}"}},
            {"key": "wakala_date", "label": "تاريخ إصدار الوكالة", "type": "text", "sample": "1448/04/15 هـ", "prefill_sample": True,
             "visible_if": {"key": "receiver_role", "contains_any": ["وكيل", "وكالة"]},
             "a4_hidden": True},
            {"key": "party_phone", "label": "رقم الجوال", "type": "text", "sample": "0551234567"},
            {"key": "vehicle_desc", "label": "نوع المركبة وموديلها ولونها", "type": "text", "sample": "تويوتا كامري 2024 - أبيض"},
            {"key": "plate_no", "label": "رقم اللوحة", "type": "text", "sample": "ح ط ر 4512"},
            {"key": "vehicle_state", "label": "حالة المركبة عند التسليم بالموقع", "type": "select", "options": [
                "أضرار سطحية لا تمنع السير الآمن",
                "صالحة للسير دون عوائق ميكانيكية ظاهرة",
                "سليمة ظاهرياً ولا يوجد ما يوجب حجزها",
                "غير صالحة للسير وتُنقل بسطحة خاصة بمعرفة المستلم",
            ], "sample": "أضرار سطحية لا تمنع السير الآمن"},
        ],
        "legal_fn": _handover_legal,
    },

    "decl_fault": {
        "title": "إقرار بنسبة خطأ في حادث مروري",
        "icon": "⚖️",
        "subtitle": "موافقة الطرف المقر على نسبة المسؤولية المرورية المقررة ميدانياً وفق نظام المرور",
        "category": "إقرار",
        "allow_absence": False,
        "require_image": False,
        "fields": [
            {"key": "incident_no", "label": "رقم الحادث المرجعي", "type": "text", "sample": "460982519"},
            {"key": "party_name", "label": "اسم الطرف المقر الرباعي", "type": "text", "sample": "خالد بن سعيد بن أحمد الزهراني"},
            {"key": "party_id", "label": "رقم الهوية / الإقامة", "type": "text", "sample": "1065432189"},
            {"key": "party_phone", "label": "رقم الجوال", "type": "text", "sample": "0509876543"},
            {"key": "plate_no", "label": "مركبة الطرف المقر ورقم اللوحة", "type": "text", "sample": "هيونداي سوناتا - ب د ع 8821"},
            {"key": "other_party", "label": "بيانات الطرف الآخر ومركبته", "type": "text", "sample": "ماجد بن حسن العتيبي - نيسان باترول (أ ك س 1190)"},
            {"key": "fault_ratio", "label": "نسبة الخطأ المعتمدة على المقر", "type": "select", "options": ["100%", "75%", "50%", "25%", "0%"], "sample": "75%"},
            {"key": "fault_cause", "label": "المخالفة / السبب المباشر للحادث", "type": "select", "options": [
                "الانحراف المفاجئ دون التأكد من خلو المسار",
                "عدم ترك مسافة آمنة بين المركبات",
                "الدخول لطريق رئيسي دون إعطاء الأفضلية",
                "التجاوز الخاطئ في مسار غير مسموح",
                "الرجوع إلى الخلف دون انتباه وحذر",
                "عدم التقيد بإشارات وتنظيمات المرور",
                "السير عكس الاتجاه",
                "قطع الإشارة الحمراء",
                "السرعة الزائدة وعدم السيطرة",
                "الدوران غير النظامي",
                "عدم إعطاء أفضلية المشاة",
                "الوقوف الخاطئ دون تحذير",
                "الانشغال بالجوال",
                "لا يوجد طرف آخر - حادث مفرد",
                OTHER_OPTION,
            ], "sample": "الانحراف المفاجئ دون التأكد من خلو المسار",
             "a4_compose": {"fmt": "{value}", "append_if": "fault_cause_other", "append_fmt": " — {extra}"}},
            _other_field("fault_cause", "اكتب سبب الخطأ يدوياً"),
        ],
        "legal_fn": lambda m: (
            f"أقر أنا ({_val(m, 'party_name')})، حامل الهوية رقم ({_val(m, 'party_id')})، قائد المركبة ({_val(m, 'plate_no')})، "
            f"وأنا بكامل أهليتي المعتبرة شرعاً ونظاماً، باطلاعي وموافقتي واقتناعي التام بنسبة الخطأ المقررة عليّ وقدرها ({_val(m, 'fault_ratio')}) "
            f"في الحادث المروري رقم ({_val(m, 'incident_no')}) الواقع مع الطرف الآخر ({_val(m, 'other_party')}) نتيجة ({_sel(m, 'fault_cause')})، "
            f"والمبنية على المعاينة الميدانية للآثار المادية وأحكام نظام المرور ولائحته التنفيذية، مع احتفاظ الأطراف بحقوقهم التأمينية والنظامية."
        ),
    },

    "decl_hit_run": {
        "title": "نموذج بلاغ وإقرار صدم وهروب",
        "icon": "🚨",
        "subtitle": "رصد أوصاف المركبة الهاربة واتجاهها والكاميرات المحيطة بالموقع للتعميم والبحث",
        "category": "إقرار",
        "allow_absence": False,
        "require_image": False,
        "fields": [
            {"key": "incident_no", "label": "رقم البلاغ / الحادث", "type": "text", "sample": "460983104"},
            {"key": "party_name", "label": "اسم المبلّغ المتضرر الرباعي", "type": "text", "sample": "سلطان بن فهد بن ناصر الحربي"},
            {"key": "party_id", "label": "رقم الهوية / الإقامة", "type": "text", "sample": "1092233445"},
            {"key": "party_phone", "label": "رقم الجوال", "type": "text", "sample": "0543322110"},
            {"key": "plate_no", "label": "مركبة المبلّغ ولوحتها وموضع الإصابة", "type": "text", "sample": "فورد تورس (د ص ق 7740) - صدم بالرفرف الخلفي الأيسر"},
            {"key": "flee_desc", "label": "أوصاف المركبة الهاربة وأرقام اللوحة المرصودة", "type": "text", "sample": "هايلوكس غمارتين أبيض - لوحة تبدأ بـ (34) بدون غطاء صندوق"},
            {"key": "flee_dir", "label": "اتجاه الهروب وموضع التلف المتوقع بالمركبة الهاربة", "type": "text", "sample": "اتجهت شمالاً نحو الطريق العام - يتوقع كسر بالركن الأمامي الأيمن"},
            {"key": "cctv_info", "label": "رصد الكاميرات المحيطة بالموقع", "type": "select", "options": [
                "توجد كاميرات محلات تجارية مقابلة لموقع الاصطدام مباشرة",
                "توجد كاميرات أمنية على التقاطع الرئيسي",
                "يوجد توثيق بكاميرا المركبة (داش كام)",
                "لا توجد كاميرات مراقبة ظاهرة في محيط الموقع",
                OTHER_OPTION,
            ], "sample": "توجد كاميرات محلات تجارية مقابلة لموقع الاصطدام مباشرة",
             "a4_compose": {"fmt": "{value}", "append_if": "cctv_info_other", "append_fmt": " — {extra}"}},
            _other_field("cctv_info", "اكتب تفاصيل الكاميرات يدوياً"),
        ],
        "legal_fn": lambda m: (
            f"أقر أنا المبلّغ ({_val(m, 'party_name')})، حامل الهوية رقم ({_val(m, 'party_id')})، بصحة كافة البيانات والأوصاف المدونة أعلاه "
            f"بشأن تعرض مركبتي ({_val(m, 'plate_no')}) لحادث صدم وهروب في البلاغ رقم ({_val(m, 'incident_no')}) من قِبل المركبة الموصوفة بـ ({_val(m, 'flee_desc')}) "
            f"والتي غادرت الموقع باتجاه ({_val(m, 'flee_dir')})، وحالة الكاميرات بالمحيط: ({_sel(m, 'cctv_info')}). "
            f"وأقر بعدم وجود خلاف سابق أو شبهة جنائية خارج نطاق الحادث المروري، وأتحمل المسؤولية النظامية الكاملة في حال ثبوت كيدية البلاغ أو خلاف ما ذُكر."
        ),
    },

    "decl_statement": {
        "title": "نموذج أقوال سريعة في موقع الحادث",
        "icon": "🗣️",
        "subtitle": "تدوين الإفادة الأولية الفورية للأطراف أو الشهود لحظة مباشرة الحادث في الميدان",
        "category": "إقرار",
        "allow_absence": False,
        "require_image": False,
        "fields": [
            {"key": "incident_no", "label": "رقم الحادث المرجعي", "type": "text", "sample": "460983990"},
            {"key": "speaker_role", "label": "صفة المدلي بالأقوال", "type": "select", "options": [
                "طرف أول (قائد مركبة)",
                "طرف ثاني (قائد مركبة)",
                "طرف ثالث",
                "راكب / مرافق",
                "عابر طريق - مشاة",
                "مالك مركبة متوقفة / عين متضررة",
                "شاهد عيان حاضر بالموقع",
            ], "sample": "طرف أول (قائد مركبة)"},
            {"key": "party_name", "label": "الاسم الرباعي للمدلي بالأقوال", "type": "text", "sample": "ياسر بن إبراهيم بن حمد الشهري"},
            {"key": "party_id", "label": "رقم الهوية / الإقامة", "type": "text", "sample": "1078899001"},
            {"key": "party_phone", "label": "رقم الجوال", "type": "text", "sample": "0567788990"},
            {"key": "plate_no", "label": "المركبة ورقم اللوحة (إن وجدت)", "type": "text", "sample": "كيا K5 رصاصي - ع م ن 2039"},
            {"key": "lane_speed", "label": "المسار والاتجاه والسرعة التقديرية قبل الحادث (اختياري للشاهد)", "type": "text", "sample": "المسار الأيمن متجهاً شرقاً بسرعة تقارب 70 كم/س"},
            {"key": "statement_text", "label": "نص الإفادة الميدانية الفورية", "type": "textarea", "sample": "أثناء سيري النظامي في مساري فوجئت بدخول المركبة الأخرى من الفتحة الجانبية دون توقف أو إعطاء أفضلية، وحاولت التهدئة وتلافيها إلا أن ضيق المسافة أدى لوقوع الاصطدام."},
        ],
        "legal_fn": lambda m: _statement_legal(m),
    },

    "decl_settlement": {
        "title": "إقرار صلح وتنازل بين طرفين أو أكثر",
        "icon": "🤝",
        "subtitle": "صلح ميداني متعدد الأطراف وإسقاط الحق الخاص أمام قسم مرور العارضة",
        "category": "إقرار",
        "allow_absence": False,
        "require_image": False,
        "fields": _settlement_fields(),
        "legal_fn": _settlement_legal,
    },

    "decl_flee_waiver": {
        "title": "إقرار تنازل في واقعة صدم وهروب",
        "icon": "🔄",
        "subtitle": "تنازل المبلّغ عن الحق الخاص دون الإخلال بإجراءات الحق العام في الهروب",
        "category": "إقرار",
        "allow_absence": False,
        "require_image": False,
        "fields": [
            {"key": "incident_no", "label": "رقم بلاغ الصدم والهروب الأصلي وتاريخه", "type": "text", "sample": "460983104 - 1448/06/10 هـ", "a4_keep_pair": True},
            {"key": "incident_loc", "label": "موقع الواقعة", "type": "text", "sample": "الطريق العام جنوب العارضة باتجاه أحد المسارحة", "a4_keep_pair": True},
            {"key": "waiver_status", "label": "حالة التنازل في البلاغ", "type": "select", "options": [
                "تنازل عن الحق الخاص بعد معرفة/حضور الطرف المتسبب والتصالح معه",
                "تنازل المُبلّغ وطلب حفظ وإقفال بلاغ الصدم والهروب",
            ], "sample": "تنازل عن الحق الخاص بعد معرفة/حضور الطرف المتسبب والتصالح معه"},
            {"key": "party_name", "label": "الاسم الرباعي للمُبلّغ المتضرر", "type": "text", "sample": "سلطان بن فهد بن ناصر الحربي", "a4_keep_pair": True,
             "a4_label": "المُبلّغ المتنازل",
             "a4_compose": {"keys": ["party_id"], "fmt": "{value} — هوية: {party_id}"}},
            {"key": "party_id", "label": "رقم الهوية / الإقامة", "type": "text", "sample": "1092233445", "a4_hidden": True},
            {"key": "party_phone", "label": "رقم الجوال", "type": "text", "sample": "0543322110", "a4_keep_pair": True},
            {"key": "plate_no", "label": "نوع المركبة المتضررة ورقم لوحتها", "type": "text", "sample": "فورد تورس (د ص ق 7740) - صدم بالرفرف الخلفي الأيسر", "a4_keep_pair": True},
            {"key": "signer_capacity", "label": "صفة المتنازل", "type": "select", "options": [
                "أصالة عن نفسه",
                "وكيل شرعي مخول بالتنازل",
            ], "sample": "أصالة عن نفسه", "a4_keep_pair": True},
            {"key": "wakala_no", "label": "رقم الوكالة الشرعية المخولة بالتنازل", "type": "text", "sample": "461829405", "a4_keep_pair": True,
             "visible_if": {"key": "signer_capacity", "contains_any": ["وكيل"]},
             "a4_label": "الوكالة الشرعية",
             "a4_compose": {"keys": ["wakala_date"], "fmt": "رقم {value} بتاريخ {wakala_date}"}},
            {"key": "wakala_date", "label": "تاريخ الوكالة", "type": "text", "sample": "1448/04/15 هـ", "a4_hidden": True,
             "visible_if": {"key": "signer_capacity", "contains_any": ["وكيل"]}},
            {"key": "agent_present", "label": "اسم وهوية الوكيل الحاضر", "type": "text", "sample": "فهد بن سعيد القحطاني — هوية 1099887766", "a4_keep_pair": True,
             "visible_if": {"key": "signer_capacity", "contains_any": ["وكيل"]}},
            {"key": "cause_name", "label": "الاسم الرباعي للطرف المتسبب", "type": "text", "sample": "ماجد بن حسن العتيبي", "a4_keep_pair": True,
             "visible_if": {"key": "waiver_status", "contains_any": ["حضور"]},
             "a4_label": "الطرف المتسبب",
             "a4_compose": {"keys": ["cause_id"], "fmt": "{value} — هوية: {cause_id}"}},
            {"key": "cause_id", "label": "رقم هوية / إقامة الطرف المتسبب", "type": "text", "sample": "1109876543", "a4_hidden": True,
             "visible_if": {"key": "waiver_status", "contains_any": ["حضور"]}},
            {"key": "cause_phone", "label": "رقم جوال الطرف المتسبب", "type": "text", "sample": "0501122334", "a4_keep_pair": True,
             "visible_if": {"key": "waiver_status", "contains_any": ["حضور"]}},
            {"key": "cause_vehicle", "label": "نوع المركبة المتسببة ورقم لوحتها", "type": "text", "sample": "هايلوكس غمارتين أبيض - ر س ل 5500", "a4_keep_pair": True,
             "visible_if": {"key": "waiver_status", "contains_any": ["حضور"]}},
            {"key": "settlement_detail", "label": "تفاصيل التسوية أو العوض المستلم", "type": "textarea",
             "sample": "تصالح الطرفان على إصلاح التلفيات ودفع مبلغ (800) ريال، وتم التنازل عن الحق الخاص.",
             "visible_if": {"key": "waiver_status", "contains_any": ["حضور"]}},
            {"key": "close_reason", "label": "سبب طلب إقفال البلاغ والتنازل", "type": "textarea",
             "sample": "أضرار سطحية لا يرغب بمتابعتها",
             "visible_if": {"key": "waiver_status", "contains_any": ["إقفال"]}},
        ],
        "legal_fn": _flee_waiver_legal,
    },

    "decl_animal_hit": {
        "title": "نموذج وإقرار صدم حيوان",
        "icon": "🐪",
        "subtitle": "توثيق صدم حيوان سائب أو مملوك مع الصلح الميداني أو إثبات الواقعة وإذن الإصلاح",
        "category": "إقرار",
        "allow_absence": False,
        "require_image": False,
        "fields": [
            {"key": "incident_no", "label": "رقم الحادث / البلاغ", "type": "text", "sample": "460991250",
             "a4_keep_pair": True, "a4_label": "رقم الحادث / البلاغ وتاريخه",
             "a4_compose": {"keys": ["incident_datetime"], "fmt": "{value} — {incident_datetime}"}},
            {"key": "incident_datetime", "label": "تاريخ ووقت الحادث / البلاغ", "type": "text",
             "sample": "2026/11/20 - 19:30", "prefill_now": True, "a4_hidden": True},
            {"key": "incident_loc", "label": "موقع الحادث واسم الطريق", "type": "text",
             "sample": "الطريق العام جنوب العارضة باتجاه أحد المسارحة", "prefill_shift_gps": True, "a4_keep_pair": True,
             "placeholder": "اكتب اسم الطريق وموقع الحادث"},
            {"key": "road_condition", "label": "وقت الحادث وحالة الطريق", "type": "select", "options": [
                "ليلي - طريق عام خارج النطاق العمراني",
                "نهاري - طريق عام خارج النطاق العمراني",
                "ليلي - داخل النطاق العمراني",
                "نهاري - داخل النطاق العمراني",
            ], "sample": "ليلي - طريق عام خارج النطاق العمراني", "a4_keep_pair": True},
            {"key": "animal_type", "label": "نوع الحيوان", "type": "select", "options": [
                "إبل (جمل / ناقة)",
                "حمار",
                "بقرة",
                "أغنام (ضأن / ماعز)",
                "خيل / فرس",
                "كلب",
                "قط",
                "حيوان بري / قردة",
                "أخرى (تحديد يدوي)",
            ], "sample": "إبل (جمل / ناقة)", "a4_keep_pair": True,
             "a4_compose": {"fmt": "{value}", "append_if": "animal_type_other", "append_fmt": " — {extra}"}},
            {"key": "animal_type_other", "label": "اكتب نوع الحيوان", "type": "text",
             "sample": "ظبي بري", "placeholder": "اكتب نوع الحيوان بدقة",
             "visible_if": {"key": "animal_type", "contains_any": ["أخرى"]}, "a4_hidden": True},
            {"key": "animal_count", "label": "عدد الحيوانات المصطدمة", "type": "text", "sample": "1",
             "prefill_sample": True, "a4_keep_pair": True},
            {"key": "animal_state", "label": "حالة الحيوان بعد الصدم", "type": "select", "options": [
                "نفوق في الموقع",
                "مصاب في الموقع",
                "هروب الحيوان بعد الصدم",
            ], "sample": "نفوق في الموقع", "a4_keep_pair": True},
            {"key": "tag_status", "label": "حالة الوسم أو الشريحة الإلكترونية", "type": "select", "options": [
                "لا يوجد وسم ولا شريحة (مجهول المالك)",
                "يوجد وسم / شريحة (موضح بالبيان)",
                "حيوان غير مملوك بطبيعته (كلب / قط / بري)",
            ], "sample": "لا يوجد وسم ولا شريحة (مجهول المالك)", "a4_keep_pair": True},
            {"key": "legal_mode", "label": "الوضع النظامي للإقرار", "type": "select", "options": [
                "حيوان سائب مجهول المالك — طلب إذن إصلاح وإنهاء إجراء",
                "حضور مالك الحيوان — صلح وتنازل ميداني عن الحق الخاص",
                "حضور مالك الحيوان — إثبات واقعة مع بقاء المطالبة بالحق الخاص",
            ], "sample": "حيوان سائب مجهول المالك — طلب إذن إصلاح وإنهاء إجراء", "a4_keep_pair": True},
            {"key": "party_name", "label": "اسم السائق المقر الرباعي", "type": "text",
             "sample": "فهد بن سعيد بن علي القحطاني", "a4_keep_pair": True,
             "a4_label": "السائق المقر",
             "a4_compose": {"keys": ["party_id"], "fmt": "{value} — هوية: {party_id}"}},
            {"key": "party_id", "label": "رقم الهوية / الإقامة للسائق", "type": "text",
             "sample": "1099887766", "a4_hidden": True},
            {"key": "party_phone", "label": "رقم جوال السائق", "type": "text",
             "sample": "0551122334", "a4_keep_pair": True},
            {"key": "party_nationality", "label": "جنسية السائق", "type": "text",
             "sample": "سعودي", "prefill_sample": True, "a4_keep_pair": True},
            {"key": "vehicle_desc", "label": "نوع المركبة وطرازها ولونها", "type": "text",
             "sample": "تويوتا لاندكروزر 2022 - أبيض", "a4_keep_pair": True},
            {"key": "plate_no", "label": "رقم اللوحة", "type": "text",
             "sample": "أ ب ج 1234", "a4_keep_pair": True},
            {"key": "vehicle_damage", "label": "الأضرار الظاهرة بالمركبة", "type": "textarea",
             "sample": "كسر بالصدام الأمامي وتشوه بغطاء المحرك دون تسرب سوائل ظاهر"},
            {"key": "health_status", "label": "الحالة الصحية للسائق والركاب", "type": "text",
             "sample": "سليم ولله الحمد ولا توجد إصابات", "prefill_sample": True, "a4_keep_pair": True},
            {"key": "owner_name", "label": "اسم مالك الحيوان الرباعي", "type": "text",
             "sample": "سعيد بن محمد بن أحمد المالكي",
             "visible_if": {"key": "legal_mode", "contains_any": ["حضور مالك"]},
             "a4_keep_pair": True, "a4_label": "مالك الحيوان",
             "a4_compose": {"keys": ["owner_id"], "fmt": "{value} — هوية: {owner_id}"}},
            {"key": "owner_id", "label": "رقم هوية / إقامة مالك الحيوان", "type": "text",
             "sample": "1044556677",
             "visible_if": {"key": "legal_mode", "contains_any": ["حضور مالك"]}, "a4_hidden": True},
            {"key": "owner_phone", "label": "رقم جوال مالك الحيوان", "type": "text",
             "sample": "0509988776",
             "visible_if": {"key": "legal_mode", "contains_any": ["حضور مالك"]}, "a4_keep_pair": True},
            {"key": "tag_detail", "label": "وصف الوسم / الشريحة الإلكترونية", "type": "text",
             "sample": "وسم أذن أيمن برقم عارضة-4821",
             "visible_if": {"key": "legal_mode", "contains_any": ["حضور مالك"]}, "a4_keep_pair": True},
            {"key": "settlement_detail", "label": "تفاصيل الصلح أو المطالبة بالحق الخاص", "type": "textarea",
             "sample": "تصالح الطرفان على تحمل كل طرف تلفياته دون مطالبة مالية إضافية.",
             "visible_if": {"key": "legal_mode", "contains_any": ["حضور مالك"]}},
        ],
        "legal_fn": _animal_hit_legal,
    },

    # ==================== ثانياً: قائمة المحاضر الرسمية (5 محاضر نظامية) ====================
    "min_inspection": {
        "title": "محضر تفتيش مركبة وجرد مقتنيات",
        "icon": "🔍",
        "subtitle": "توثيق حالة المركبة وجرد الأمانات الشخصية قبل الرفع للحجز أو عند نقل السائق للمستشفى",
        "category": "محضر",
        "allow_absence": True,
        "require_image": False,
        "fields": [
            {"key": "incident_no", "label": "رقم الحادث / المعاملة", "type": "text", "sample": "460984120"},
            {"key": "legal_reason", "label": "المسوغ النظامي للتفتيش والجرد", "type": "select", "options": [
                "نقل قائد المركبة للمستشفى بالهلال الأحمر إثر حادث مروري",
                "جرد وقائي إلزامي قبل سحب المركبة لساحة الحجز",
                "مركبة متروكة في موقع يعيق الحركة المرورية",
                "تفتيش احترازي لوجود شبهة مرورية أو أمنية بالموقع",
                "وفاة قائد المركبة في الحادث",
                OTHER_OPTION,
            ], "sample": "نقل قائد المركبة للمستشفى بالهلال الأحمر إثر حادث مروري",
             "a4_compose": {"fmt": "{value}", "append_if": "legal_reason_other", "append_fmt": " — {extra}"}},
            _other_field("legal_reason", "اكتب المسوغ يدوياً"),
            {"key": "plate_no", "label": "بيانات المركبة ورقم اللوحة", "type": "text", "sample": "جيب لكزس أبيض - ر س ل 5500"},
            {"key": "party_name", "label": "اسم القائد / المالك (أو الشاهد الحاضر)", "type": "text", "sample": "نايف بن عبدالله القحطاني"},
            {"key": "party_id", "label": "رقم الهوية / الإقامة", "type": "text", "sample": "1054433221"},
            {"key": "body_state", "label": "حالة الهيكل الخارجي والزجاج", "type": "text", "sample": "تلفيات بالمقدمة وتهشم الزجاج الأمامي وسلامة المقصورة الخلفية"},
            {"key": "inventory_list", "label": "جرد المقتنيات الشخصية والأمانات المرصودة", "type": "textarea", "sample": "محفظة شخصية بداخلها الهوية الوطنية ومبلغ (450) ريال + جوال آيفون أسود + الإطار الاحتياطي وعدة المركبة."},
            {"key": "items_action", "label": "التصرف النظامي بالمقتنيات", "type": "select", "options": [
                "حُفظت المقتنيات الثمينة بصندوق أمانات القسم بموجب سند رسمي",
                "سُلمت المقتنيات الشخصية كاملة للمالك أو ذويه في الموقع",
                "سُلمت لجهة الاختصاص بموجب محضر رسمي",
                "لا توجد مقتنيات ثمينة وبقيت التجهيزات العادية داخل المركبة المقفلة",
                OTHER_OPTION,
            ], "sample": "حُفظت المقتنيات الثمينة بصندوق أمانات القسم بموجب سند رسمي",
             "a4_compose": {"fmt": "{value}", "append_if": "items_action_other", "append_fmt": " — {extra}"}},
            _other_field("items_action", "اكتب التصرف يدوياً"),
            {"key": "scene_officer", "label": "رتبة واسم مباشر الواقعة / الدورية الميدانية (اختياري)", "type": "text",
             "sample": "", "placeholder": "يُذكر عند اختلافه عن مستلم الخفر المناوب"},
        ],
        "legal_fn": lambda m: (
            f"إنه في الزمان والمكان المثبتين آلياً بترويسة هذا المحضر، واستناداً للمسوغ النظامي ({_sel(m, 'legal_reason')}) في المعاملة رقم ({_val(m, 'incident_no')})، "
            f"جرى بمعرفتنا تفتيش المركبة ({_val(m, 'plate_no')}) العائدة لـ ({_val(m, 'party_name')} - هوية: {_val(m, 'party_id')})، وحالتها الخارجية: ({_val(m, 'body_state')})، "
            f"وأسفر الجرد الفعلي لمحتوياتها عن وجود: ({_val(m, 'inventory_list')})، وقد جرى اتخاذ الإجراء التالي حيالها: ({_sel(m, 'items_action')}). "
            + (f" ومباشر الواقعة الميدانية: ({_val(m, 'scene_officer')}). " if str(m.get('scene_officer') or '').strip() else "")
            + "حُرر هذا المحضر الرسمي إثباتاً للحالة وصوناً للأمانات ومنعاً لأي ادعاء لاحق."
        ),
    },

    "min_seizure": {
        "title": "محضر ضبط وحجز مركبة مخالفة",
        "icon": "🚓",
        "subtitle": "ضبط المركبات المرتكبة لمخالفات موجبة للحجز وتوثيق تسليمها لسطحة الحجز المعتمدة",
        "category": "محضر",
        "allow_absence": True,
        "require_image": False,
        "fields": [
            {"key": "incident_no", "label": "رقم محضر الضبط", "type": "text", "sample": "99012458"},
            {"key": "seize_reason", "label": "المخالفة الموجبة للضبط والحجز النظامي", "type": "select", "options": [
                "طمس أو إخفاء معالم لوحات المركبة بقصد التمويه",
                "السير بالمركبة بدون لوحات نهائياً على الطريق العام",
                "ارتكاب مخالفة التفحيط أو الاستعراض الخطر",
                "تعديلات جوهرية في المحرك أو الهيكل تخل بالسلامة والسكينة",
                "مركبة مطلوبة بتعميم قبض أو حجز مروري ساري المفعول",
                "القيادة بدون رخصة",
                "الاشتباه بحالة غير طبيعية",
                "الحجز على ذمة حادث جسيم أو هروب",
                "عكس السير أو قطع الإشارة",
                "مركبة مهملة/معطلة تعيق الطريق",
                "السائق هارب / غير متواجد",
                OTHER_OPTION,
            ], "sample": "طمس أو إخفاء معالم لوحات المركبة بقصد التمويه",
             "a4_compose": {"fmt": "{value}", "append_if": "seize_reason_other", "append_fmt": " — {extra}"}},
            _other_field("seize_reason", "اكتب سبب الضبط يدوياً"),
            {"key": "plate_no", "label": "نوع المركبة ورقم اللوحة / الهيكل", "type": "text", "sample": "شيفروليه كابرس أسود - ك هـ ي 9012"},
            {"key": "party_name", "label": "اسم قائد المركبة عند الضبط", "type": "text", "sample": "تركي بن منصور الدوسري"},
            {"key": "party_id", "label": "رقم الهوية / الإقامة", "type": "text", "sample": "1109876543"},
            {"key": "tow_truck", "label": "بيانات سطحة السحب واسم السائق", "type": "text", "sample": "سطحة الحجز المعتمدة رقم (14) - السائق: رفيق أحمد"},
            {"key": "impound_loc", "label": "ساحة الحجز المودعة بها المركبة", "type": "text", "sample": "ساحة حجز المرور بالعارضة"},
            {"key": "pre_tow_state", "label": "حالة الهيكل الخارجي قبل الرفع على السطحة", "type": "text", "sample": "خدوش سابقة بالصدام الخلفي والزجاج سليم والأبواب مقفلة"},
            {"key": "scene_officer", "label": "رتبة واسم مباشر الواقعة / الدورية الميدانية (اختياري)", "type": "text",
             "sample": "", "placeholder": "يُذكر عند اختلافه عن مستلم الخفر المناوب"},
        ],
        "legal_fn": lambda m: (
            f"بناءً على الصلاحيات النظامية المخولة لرجال المرور بموجب نظام المرور ولائحته التنفيذية، جرى في الزمان والمكان الموضحين بترويسة المحضر رقم ({_val(m, 'incident_no')}) "
            f"ضبط المركبة ({_val(m, 'plate_no')}) بقيادة ({_val(m, 'party_name')} - هوية: {_val(m, 'party_id')}) لارتكاب مخالفة ({_sel(m, 'seize_reason')}). "
            f"وبمعاينة المركبة قبل الرفع تبين ({_val(m, 'pre_tow_state')})، وسُلمت ميدانياً إلى ({_val(m, 'tow_truck')}) لإيداعها في ({_val(m, 'impound_loc')}) لاستكمال المقتضى النظامي."
            + (f" ومباشر الواقعة الميدانية: ({_val(m, 'scene_officer')})." if str(m.get('scene_officer') or '').strip() else "")
        ),
    },

    "min_wrong_viol": {
        "title": "محضر مخالفة مرصودة بالخطأ",
        "icon": "📋",
        "subtitle": "محضر إيضاحي محوكم مرفق بصورة الإشعار للعرض على الهيئة المرورية لإلغاء المخالفة",
        "category": "محضر",
        "allow_absence": True,
        "require_image": True,
        "fields": [
            {"key": "incident_no", "label": "رقم المخالفة المقيدة بالخطأ", "type": "text", "sample": "31009876542"},
            {"key": "viol_datetime", "label": "تاريخ ووقت تسجيل المخالفة", "type": "text", "sample": "1448/05/28 هـ - 09:15 صباحاً"},
            {"key": "plate_no", "label": "رقم اللوحة المسجلة بالخطأ", "type": "text", "sample": "أ ب ج 1234"},
            {"key": "party_name", "label": "اسم المستفيد المتضرر / اللوحة الصحيحة", "type": "text", "sample": "عمر بن صالح المالكي (اللوحة الصحيحة للمخالف: أ ب ح 1234)"},
            {"key": "party_id", "label": "رقم هوية المتضرر أو السجل المرجعي", "type": "text", "sample": "1045678912"},
            {"key": "error_reason", "label": "سبب الخطأ (حوكمة العرض على الهيئة المرورية)", "type": "select", "options": [
                "خطأ مطبعي غير مقصود في أحرف أو أرقام اللوحة أثناء الرصد الميداني",
                "تشابه مركبتين في ذات الموقع لحظة تحرير المخالفة",
                "اختيار بند أو وصف مخالفة غير مطابق للواقعة بالخطأ",
                "تكرار تقني مزدوج لذات المخالفة في وقت واحد بجهاز الرصد",
                OTHER_OPTION,
            ], "sample": "خطأ مطبعي غير مقصود في أحرف أو أرقام اللوحة أثناء الرصد الميداني",
             "a4_compose": {"fmt": "{value}", "append_if": "error_reason_other", "append_fmt": " — {extra}"}},
            _other_field("error_reason", "اكتب سبب الخطأ يدوياً"),
            {"key": "observer_name", "label": "رتبة واسم راصد المخالفة", "type": "text",
             "sample": "العريف سعيد بن محمد العسيري", "prefill_sample": True},
            {"key": "officer_note", "label": "إفادة راصد المخالفة التفصيلية", "type": "textarea", "sample": "أثناء مباشرة تنظيم الحركة المرورية جرى إدخال حرف (ج) بدلاً من (ح) بالخطأ للوحة المركبة المخالفة الفعلية، والمركبة المسجل عليها الإشعار لم تكن بالموقع."},
            {"key": "scene_officer", "label": "رتبة واسم مباشر الواقعة / الدورية الميدانية (اختياري)", "type": "text",
             "sample": "", "placeholder": "يُذكر عند اختلافه عن مستلم الخفر المناوب"},
        ],
        "legal_fn": lambda m: (
            f"نرفع هذا المحضر الرسمي بشأن المخالفة المرورية رقم ({_val(m, 'incident_no')}) المقيدة بتاريخ ({_val(m, 'viol_datetime')}) على اللوحة ({_val(m, 'plate_no')})، "
            f"حيث تبين بعد المراجعة والتدقيق وقوع خطأ في الرصد ناتج عن ({_sel(m, 'error_reason')})، والبيانات المرجعية هي ({_val(m, 'party_name')} - {_val(m, 'party_id')}). "
            f"وراصد المخالفة: ({_val(m, 'observer_name')}). وإيضاح الراصد الميداني كالآتي: ({_val(m, 'officer_note')}). "
            f"وعليه حُرر هذا المحضر مرفقاً به صورة المخالفة ومعتمداً للعرض على الهيئة المرورية لإلغاء المخالفة نظاماً."
        ),
    },

    "min_incident": {
        "title": "محضر إثبات واقعة ميدانية",
        "icon": "🛡️",
        "subtitle": "توثيق الوقائع الميدانية العارضة أو تلف الممتلكات العامة أو الامتناع عن إبراز الهوية",
        "category": "محضر",
        "allow_absence": True,
        "require_image": False,
        "fields": [
            {"key": "incident_no", "label": "الرقم المرجعي للواقعة", "type": "text", "sample": "460985007"},
            {"key": "incident_kind", "label": "تصنيف الواقعة الميدانية", "type": "select", "options": [
                "تلف ممتلكات عامة (عمود إنارة / لوحة إرشادية / سياج) جراء حادث",
                "امتناع قائد مركبة عن إبراز الهوية أو التجاوب مع الفرقة",
                "وجود عائق مروري خطر أو انسكاب مواد على الطريق العام",
                "خلاف ميداني بين أطراف حادث مروري والسيطرة عليه بالموقع",
                "واقعة ميدانية مرورية عارضة تستوجب التوثيق الرسمي",
                OTHER_OPTION,
            ], "sample": "تلف ممتلكات عامة (عمود إنارة / لوحة إرشادية / سياج) جراء حادث",
             "a4_compose": {"fmt": "{value}", "append_if": "incident_kind_other", "append_fmt": " — {extra}"}},
            _other_field("incident_kind", "اكتب تصنيف الواقعة يدوياً"),
            {"key": "party_name", "label": "اسم الطرف ذي العلاقة (إن وجد)", "type": "text", "sample": "فيصل بن راشد الغامدي"},
            {"key": "party_id", "label": "رقم الهوية / الإقامة", "type": "text", "sample": "1081122334"},
            {"key": "plate_no", "label": "بيانات المركبة / العين المتضررة بالموقع", "type": "text", "sample": "جمس سييرا (ط ك ل 6610) - عمود إنارة رقم 48"},
            {"key": "facts_detail", "label": "تفاصيل الوقائع المشاهدة عياناً بالموقع", "type": "textarea", "sample": "عند مباشرة الموقع تبين ارتطام المركبة المذكورة بعمود الإنارة رقم (48) بالجزيرة الوسطية مما أدى لميلان العمود وانكشاف الكيبل الأرضي دون إصابات بشرية."},
            {"key": "taken_measure", "label": "الإجراء الفوري المتخذ في الموقع", "type": "textarea", "sample": "تأمين الموقع بالدورية التحذيرية وإشعار طوارئ البلدية والكهرباء لمباشرة العمود واستكمال إجراءات الحادث."},
            {"key": "scene_officer", "label": "رتبة واسم مباشر الواقعة / الدورية الميدانية (اختياري)", "type": "text",
             "sample": "", "placeholder": "يُذكر عند اختلافه عن مستلم الخفر المناوب"},
        ],
        "legal_fn": lambda m: (
            f"إنه في الزمان والمكان المثبتين آلياً بترويسة المحضر رقم ({_val(m, 'incident_no')})، وأثناء قيامنا بمهام العمل الميداني باشرنا واقعة ({_sel(m, 'incident_kind')}) "
            f"المرتبطة بـ ({_val(m, 'party_name')} - هوية: {_val(m, 'party_id')}) والمركبة / الموقع ({_val(m, 'plate_no')}). "
            f"وقد ثبت لنا بالمعاينة المباشرة الآتي: ({_val(m, 'facts_detail')})، وجرى اتخاذ الإجراء الفوري التالي: ({_val(m, 'taken_measure')}). "
            + (f" ومباشر الواقعة الميدانية: ({_val(m, 'scene_officer')}). " if str(m.get('scene_officer') or '').strip() else "")
            + "وعليه حُرر هذا المحضر الرسمي إثباتاً للواقعة على الطبيعة ورفعه لمستلم الخفر المناوب لاستكمال اللازم نظاماً."
        ),
    },

    # ==================== ثالثاً: النماذج الطبية والجنائية (3) ====================
    "med_injury": {
        "title": "نموذج معالجة مصاب / مصابين",
        "icon": "🚑",
        "subtitle": "إحالة مصاب أو عدة مصابين في حادث مروري للمستشفى وطلب التقرير الطبي وتحديد وضع التحفظ",
        "category": "إحالة طبية",
        "allow_absence": True,
        "require_image": False,
        "fields": [
            {"key": "incident_no", "label": "رقم الحادث وتاريخه", "type": "text", "sample": "460986112 - 1448/06/08 هـ"},
            {"key": "hospital_name", "label": "المستشفى / الجهة الصحية الموجه لها", "type": "text", "sample": "مستشفى العارضة العام - قسم الطوارئ"},
            {"key": "cases_mode", "label": "تصنيف الإحالة والعدد", "type": "select", "options": [
                "مصاب واحد في حادث مروري",
                "عدة مصابين في حادث مروري (مرفق بيانهم)"
            ], "sample": "مصاب واحد في حادث مروري"},
            {"key": "party_name", "label": "اسم المصاب الرباعي", "type": "text", "sample": "موسى بن يحيى بن أحمد خبراني"},
            {"key": "party_id", "label": "رقم الهوية / الإقامة والجنسية", "type": "text", "sample": "1098877665 - سعودي"},
            {"key": "plate_no", "label": "بيانات المركبة وصفته بالحادث", "type": "text", "sample": "تويوتا هايلوكس (ب ر د 3318) - قائد المركبة"},
            {"key": "transport_way", "label": "وسيلة الوصول للمستشفى والحالة الأولية", "type": "select", "options": [
                "نُقل بواسطة فرقة الهلال الأحمر السعودي من موقع الحادث",
                "راجع الطوارئ عن طريق ذويه / نقل خاص إثر الحادث",
                "حضر برفقة الدورية المرورية المباشرة للموقع",
                OTHER_OPTION,
            ], "sample": "نُقل بواسطة فرقة الهلال الأحمر السعودي من موقع الحادث",
             "a4_compose": {"fmt": "{value}", "append_if": "transport_way_other", "append_fmt": " — {extra}"}},
            _other_field("transport_way", "اكتب وسيلة النقل يدوياً"),
            {"key": "security_hold", "label": "التوجيه الأمني بعد تلقي العلاج", "type": "select", "options": [
                "يُطلق سراحه بعد تلقي العلاج اللازم ما لم يكن مطلوباً لجهة أخرى",
                "يُتحفظ عليه أمنياً ويُشعر قسم مرور العارضة قبل خروجه لاستكمال التحقيق",
                "يبقى تحت الملاحظة الطبية مع تزويدنا بالتقرير الطبي العاجل",
                OTHER_OPTION,
            ], "sample": "يُطلق سراحه بعد تلقي العلاج اللازم ما لم يكن مطلوباً لجهة أخرى",
             "a4_compose": {"fmt": "{value}", "append_if": "security_hold_other", "append_fmt": " — {extra}"}},
            _other_field("security_hold", "اكتب التوجيه الأمني يدوياً"),
            {"key": "other_injured", "label": "بيان المصابين الإضافيين (الاسم، الهوية، الصفة، الإصابة الظاهرة)", "type": "textarea",
             "sample": "2- ريان بن موسى خبراني | هوية: 1123344556 | مرافق | إصابة متوسطة بالكتف الأيمن.\n3- عادل محمد علي | إقامة: 2456677889 | قائد الطرف الثاني | رضوض وكدمات متفرقة.",
             "visible_if": {"key": "cases_mode", "contains_any": ["عدة مصابين"]}},
        ],
        "legal_fn": _med_injury_legal,
    },

    "med_morgue": {
        "title": "نموذج إيداع جثمان / جثامين",
        "icon": "🏥",
        "subtitle": "إيداع جثمان متوفى أو عدة جثامين بثلاجة الموتى إثر حادث مروري وطلب تقرير الوفاة وعدم التسليم إلا بفسح",
        "category": "إحالة طبية",
        "allow_absence": True,
        "require_image": False,
        "fields": [
            {"key": "incident_no", "label": "رقم الحادث الجسيم وموقعه", "type": "text", "sample": "460986450 - الطريق العام"},
            {"key": "hospital_name", "label": "المستشفى / ثلاجة الموتى المودع بها", "type": "text", "sample": "ثلاجة الموتى بمستشفى العارضة العام"},
            {"key": "deceased_count", "label": "تصنيف حالة الإيداع والعدد", "type": "select", "options": [
                "جثمان واحد (متوفى واحد)",
                "عدة جثامين (أكثر من متوفى في الحادث)"
            ], "sample": "جثمان واحد (متوفى واحد)"},
            {"key": "party_name", "label": "اسم المتوفى الأول (أو مجهول الهوية مع أوصافه)", "type": "text", "sample": "عبدالله بن حسن بن علي"},
            {"key": "party_id", "label": "رقم الهوية / الإقامة والجنسية والعمر", "type": "text", "sample": "1043322110 - سعودي - 38 عاماً"},
            {"key": "plate_no", "label": "المركبة ورقم اللوحة وصفة المتوفى بالحادث", "type": "text", "sample": "صالون لاندكروزر (ب ح ط 9879) - قائد المركبة"},
            {"key": "transport_death", "label": "جهة إعلان الوفاة ووسيلة نقل الجثمان", "type": "select", "options": [
                "وفاة في موقع الحادث ونُقل الجثمان عبر النقل المجهز (الشرشورة) بعد المعاينة",
                "توفي في قسم الطوارئ بالمستشفى متأثراً بإصاباته البالغة بالحادث",
                "نُقل بواسطة إسعاف الهلال الأحمر وتأكدت الوفاة طبياً عند الوصول",
                OTHER_OPTION,
            ], "sample": "وفاة في موقع الحادث ونُقل الجثمان عبر النقل المجهز (الشرشورة) بعد المعاينة",
             "a4_compose": {"fmt": "{value}", "append_if": "transport_death_other", "append_fmt": " — {extra}"}},
            _other_field("transport_death", "اكتب وسيلة النقل يدوياً"),
            {"key": "forensic_order", "label": "التوجيه النظامي حيال التحفظ والكشف الطبي", "type": "select", "options": [
                "إيداع الجثمان بالثلاجة والتحفظ عليه وعدم تسليمه إلا بخطاب فسح رسمي من قسم مرور العارضة",
                "إجراء الكشف الطبي الظاهري وتزويدنا بتقرير الوفاة الرسمي وأسبابها المباشرة",
                "إبقاء الجثمان رهن الفحص الطبي الشرعي بناءً على توجيه النيابة العامة",
                OTHER_OPTION,
            ], "sample": "إيداع الجثمان بالثلاجة والتحفظ عليه وعدم تسليمه إلا بخطاب فسح رسمي من قسم مرور العارضة",
             "a4_compose": {"fmt": "{value}", "append_if": "forensic_order_other", "append_fmt": " — {extra}"}},
            _other_field("forensic_order", "اكتب التوجيه يدوياً"),
            {"key": "other_deceased", "label": "بيانات الجثامين الإضافية عند تعدد الوفيات (الاسم، الهوية، الصفة)", "type": "textarea",
             "sample": "2- ...",
             "visible_if": {"key": "deceased_count", "contains_any": ["عدة جثامين"]}},
        ],
        "legal_fn": _med_morgue_legal,
    },

    "med_toxicology": {
        "title": "نموذج إحالة وطلب تحليل سموم",
        "icon": "🧪",
        "subtitle": "طلب سحب عينات حيوية وفحص مخبري للسموم والمسكرات والمؤثرات العقلية وتوثيق سلسلة الحيازة",
        "category": "إحالة طبية",
        "allow_absence": True,
        "require_image": False,
        "fields": [
            {"key": "incident_no", "label": "رقم الحادث / المحضر المرجعي", "type": "text", "sample": "460986890",
             "a4_keep_pair": True},
            {"key": "awtar_no", "label": "رقم طلب (أوتار)", "type": "text", "sample": "AWT-2026-88412",
             "placeholder": "أدخل رقم الطلب في منصة أوتار", "normalize_digits": True,
             "a4_label": "رقم (أوتار)", "a4_keep_pair": True},
            {"key": "lab_dest", "label": "الجهة المحال إليها (المستشفى / مركز مراقبة السموم)", "type": "text", "sample": "قسم الطوارئ والمختبر / مركز مراقبة السموم والكيمياء الشرعية"},
            {"key": "party_name", "label": "اسم الشخص المحال للفحص رباعياً", "type": "text", "sample": "ماجد بن سالم بن عوض القحطاني"},
            {"key": "party_id", "label": "رقم الهوية / الإقامة والجنسية", "type": "text", "sample": "1089911223 - سعودي"},
            {"key": "plate_no", "label": "بيانات المركبة وصفته بالواقعة", "type": "text", "sample": "هيونداي إلنترا (ط س ع 6120) - قائد المركبة الطرف الأول"},
            {"key": "suspicion_signs", "label": "المسوغ النظامي والقرائن الميدانية لطلب التحليل", "type": "select", "options": [
                "الاشتباه بالقيادة تحت تأثير مسكر أو مخدر أو مؤثر عقلي لقرائن المعاينة الميدانية",
                "حادث مروري جسيم نتج عنه وفيات أو إصابات بالغة يستوجب الفحص النظامي الشامل",
                "ظهور علامات غير طبيعية واضطراب في التوازن والنطق أو العثور على مواد يشتبه بها",
                "سحب عينة حيوية احترازية لحالة منومة أو متوفاة لتحديد المسببات السمية",
                OTHER_OPTION,
            ], "sample": "الاشتباه بالقيادة تحت تأثير مسكر أو مخدر أو مؤثر عقلي لقرائن المعاينة الميدانية",
             "a4_compose": {"fmt": "{value}", "append_if": "suspicion_signs_other", "append_fmt": " — {extra}"}},
            _other_field("suspicion_signs", "اكتب المسوغ يدوياً"),
            {"key": "sample_type", "label": "نوع العينات والفحص المخبري المطلوب", "type": "select", "options": [
                "سحب عينتي دم وبول للكشف الكمي والنوعي عن الكحول والمخدرات والمؤثرات العقلية",
                "سحب عينة دم وريدية عاجلة لقياس نسبة الكحول والسموم (حالة طوارئ / منوم)",
                "فحص سموم جنائي شامل للعينات الحيوية مع تحريزها بأختام رسمية",
                OTHER_OPTION,
            ], "sample": "سحب عينتي دم وبول للكشف الكمي والنوعي عن الكحول والمخدرات والمؤثرات العقلية",
             "a4_compose": {"fmt": "{value}", "append_if": "sample_type_other", "append_fmt": " — {extra}"}},
            _other_field("sample_type", "اكتب نوع العينات يدوياً"),
            {"key": "escort_info", "label": "بيانات المرافق الأمني وإجراء التسليم والتحريز", "type": "textarea", "sample": "مبعوث برفقة الدورية المرورية المستلمة — يُسحب الفحص تحت الإشراف المباشر مع توثيق سلسلة الحيازة وإعادة المذكور برفقة المرافق الأمني فور الانتهاء."},
        ],
        "legal_fn": _toxicology_legal,
    },
}

# المحضر الخامس داخل قائمة المحاضر الرسمية — البيانات من ABU_ARISH_IMPOUND_TEMPLATE
TRAFFIC_FORMS[ABU_ARISH_IMPOUND_TEMPLATE["id"]] = _minutes_form_from_template(ABU_ARISH_IMPOUND_TEMPLATE)
TRAFFIC_FORMS.update(TAKMEEL_FORMS)


# =====================================================================
# 3. محرك البصمة الصوري ورمز التحقق QR
# =====================================================================
def generate_fingerprint_png_b64(seed_text: str, ink_rgb=(13, 71, 161)) -> str:
    w, h = 240, 290
    img = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    rng = random.Random(hashlib.sha256(seed_text.encode("utf-8")).hexdigest())

    cx, cy = w // 2, h // 2 + 4
    for i in range(1, 23):
        rx = int(i * 4.3)
        ry = int(i * 5.5)
        bbox = [cx - rx, cy - ry, cx + rx, cy + ry]
        angle = -165 + rng.randint(0, 20)
        while angle < 165:
            sweep = rng.randint(24, 62)
            end_a = min(angle + sweep, 168)
            alpha = rng.randint(180, 245)
            draw.arc(bbox, start=angle, end=end_a, fill=(*ink_rgb, alpha), width=2)
            angle += sweep + rng.randint(6, 15)

    draw.arc([cx - 10, cy - 18, cx + 10, cy + 22], start=190, end=350, fill=(*ink_rgb, 235), width=2)
    draw.rounded_rectangle([6, 6, w - 6, h - 6], radius=14, outline=(*ink_rgb, 95), width=2)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    buf.close()
    del img
    return b64


def generate_qr_png_b64(data_text: str) -> str:
    buf = io.BytesIO()
    try:
        if HAS_QRCODE:
            qr = qrcode.QRCode(version=2, box_size=5, border=1)
            qr.add_data(data_text)
            qr.make(fit=True)
            img = qr.make_image(fill_color="#0f3d2e", back_color="white")
            if hasattr(img, "get_image"):
                img.get_image().save(buf, format="PNG")
            else:
                img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        pass

    img = Image.new("RGB", (130, 130), "white")
    draw = ImageDraw.Draw(img)
    rng = random.Random(data_text)
    for r in range(13):
        for c in range(13):
            if (r < 3 and c < 3) or (r < 3 and c > 9) or (r > 9 and c < 3) or rng.choice([True, False]):
                draw.rectangle([c * 10, r * 10, c * 10 + 8, r * 10 + 8], fill="#0f3d2e")
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# =====================================================================
# 4. قاعدة البيانات المحلية SQLite
# =====================================================================
DB_PATH = "khafar_system.db"


BLANK_SHIFT = {
    "dept_name": "قسم مرور العارضة",
    "officer_rank": "مستلم الخفر المناوب",
    "officer_name": "",
    "duty_rank": "وحدة الحوادث",
    "duty_name": "",
    "default_gps": "بانتظار رصد الموقع",
}
# مفتاح صورة توقيع مستلم الخفر المناوب — يُحفظ في SQLite وlocalStorage فقط (ليس في الكوكيز)
DUTY_SIG_KEY = "duty_sig_b64"
DUTY_SIG_LS_KEY = "khafar_duty_sig"
MANAGER_SIG_BACKUP = "manager_sig_backup.json"
MANAGER_SIG_PNG = "manager_signature.png"
MANAGER_AUTH_MODE = "توقيع مدير وحدة الحوادث المعتمد مركزياً"
DEFAULT_MANAGER_TITLE = "مدير وحدة الحوادث بقسم مرور العارضة"
DEVICE_COOKIE = "khafar_device_uid"
SHIFT_COOKIE = "khafar_shift"
_SHIFT_TEXT_KEYS = ("dept_name", "officer_rank", "officer_name", "duty_rank", "duty_name", "default_gps")
_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _manager_pin() -> str:
    try:
        pin = st.secrets.get("MANAGER_PIN", "4411")
    except Exception:
        pin = "4411"
    return str(pin or "4411").strip() or "4411"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS shift_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            dept_name TEXT,
            officer_rank TEXT,
            officer_name TEXT,
            duty_rank TEXT,
            duty_name TEXT,
            default_gps TEXT
        )
    """)
    if c.execute("SELECT COUNT(*) FROM shift_settings").fetchone()[0] == 0:
        c.execute("""
            INSERT INTO shift_settings (id, dept_name, officer_rank, officer_name, duty_rank, duty_name, default_gps)
            VALUES (1, 'قسم مرور العارضة', 'مستلم الخفر المناوب', '', 'وحدة الحوادث', '', 'بانتظار رصد الموقع')
        """)
    # السجل العام لم يعد مصدراً للبيانات الشخصية: تُمسح الأسماء والإحداثيات منه دائماً.
    c.execute("""
        UPDATE shift_settings
        SET dept_name=?, officer_rank=?, officer_name='', duty_rank=?, duty_name='', default_gps=?
        WHERE id=1
    """, ("قسم مرور العارضة", "مستلم الخفر المناوب", "وحدة الحوادث", "بانتظار رصد الموقع"))
    c.execute("""
        CREATE TABLE IF NOT EXISTS device_shifts (
            device_hash TEXT PRIMARY KEY,
            dept_name TEXT,
            officer_rank TEXT,
            officer_name TEXT,
            duty_rank TEXT,
            duty_name TEXT,
            default_gps TEXT
        )
    """)
    device_shift_cols = {row[1] for row in c.execute("PRAGMA table_info(device_shifts)").fetchall()}
    if "duty_sig_b64" not in device_shift_cols:
        c.execute("ALTER TABLE device_shifts ADD COLUMN duty_sig_b64 TEXT")

    c.execute("""
        CREATE TABLE IF NOT EXISTS manager_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            manager_name TEXT,
            manager_title TEXT,
            manager_sig_b64 TEXT,
            auto_insert INTEGER DEFAULT 1,
            updated_at TEXT
        )
    """)
    if c.execute("SELECT COUNT(*) FROM manager_settings").fetchone()[0] == 0:
        c.execute(
            """
            INSERT INTO manager_settings (id, manager_name, manager_title, manager_sig_b64, auto_insert, updated_at)
            VALUES (1, ?, ?, '', 1, ?)
            """,
            ("", DEFAULT_MANAGER_TITLE, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )

    c.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_no TEXT,
            form_id TEXT,
            form_title TEXT,
            category TEXT,
            party_name TEXT,
            party_id TEXT,
            plate_no TEXT,
            gps_coords TEXT,
            created_at TEXT,
            fields_json TEXT,
            legal_text TEXT,
            citizen_stamp_b64 TEXT,
            citizen_auth_mode TEXT,
            officer_stamp_b64 TEXT,
            attachment_b64 TEXT,
            officer_full TEXT,
            duty_full TEXT,
            dept_name TEXT,
            verify_hash TEXT,
            officer_auth_mode TEXT,
            duty_auth_mode TEXT,
            duty_stamp_b64 TEXT
        )
    """)
    existing_cols = {row[1] for row in c.execute("PRAGMA table_info(records)").fetchall()}
    for col_name, col_type in (
        ("officer_auth_mode", "TEXT"),
        ("duty_auth_mode", "TEXT"),
        ("duty_stamp_b64", "TEXT"),
        ("receiver_name", "TEXT"),
        ("receiver_role", "TEXT"),
        ("device_hash", "TEXT"),
    ):
        if col_name not in existing_cols:
            c.execute(f"ALTER TABLE records ADD COLUMN {col_name} {col_type}")
    conn.commit()
    conn.close()


RECEIVER_ROLE_OPTIONS = [
    "المختص المناوب بالطوارئ",
    "الطبيب المناوب",
    "المسعف المستلم",
    "مأمور ثلاجة الموتى",
    "أخصائي المختبر المناوب",
]


def _blank_shift() -> dict:
    blank = dict(BLANK_SHIFT)
    blank[DUTY_SIG_KEY] = ""
    return blank


def _clean_shift(data: dict | None) -> dict:
    cleaned = _blank_shift()
    if not isinstance(data, dict):
        return cleaned
    for key in _SHIFT_TEXT_KEYS:
        if data.get(key) is None:
            continue
        cleaned[key] = str(data.get(key) or "")[:180]
    cleaned["dept_name"] = "قسم مرور العارضة"
    if not cleaned["officer_rank"].strip():
        cleaned["officer_rank"] = "مستلم الخفر المناوب"
    if not cleaned["duty_rank"].strip():
        cleaned["duty_rank"] = "وحدة الحوادث"
    if not cleaned["default_gps"].strip():
        cleaned["default_gps"] = "بانتظار رصد الموقع"
    # صورة التوقيع قد تكون كبيرة — لا تُقطع بحد 180 ولا تُمرَّر للكوكيز
    raw_sig = str(data.get(DUTY_SIG_KEY) or "").strip()
    if raw_sig.startswith("data:"):
        raw_sig = raw_sig.split(",", 1)[-1].strip()
    cleaned[DUTY_SIG_KEY] = raw_sig[:250000] if raw_sig else ""
    return cleaned


def shift_light_payload(data: dict | None) -> dict:
    """بيانات المناوبة النصية الخفيفة فقط (بدون Base64 التوقيع) للكوكيز."""
    cleaned = _clean_shift(data)
    return {key: cleaned.get(key, "") for key in _SHIFT_TEXT_KEYS}


def make_ink_transparent_b64(raw_b64: str, max_w: int = 520, max_h: int = 180) -> str:
    """توقيع حبري رسمي: خلفية بيضاء ناصعة + حبر أزرق قلم (15,45,130) بدون أي كحلي/أسود."""
    payload = str(raw_b64 or "").strip()
    if not payload:
        return ""
    if payload.startswith("data:"):
        payload = payload.split(",", 1)[-1]
    try:
        ink = (15, 45, 130)
        img = Image.open(io.BytesIO(base64.b64decode(payload)))
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        w, h = img.size
        src = img.load()

        # تقدير لون الخلفية من الزوايا والحواف (يشمل الخلفيات الكحلية الشفافة/المعتمة)
        samples = []
        for (sx, sy) in (
            (0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
            (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2),
        ):
            r, g, b, a = src[sx, sy]
            if a < 40:
                samples.append((13, 40, 55))  # خلفية واجهة داكنة شائعة خلف الشفافية
            else:
                samples.append((r, g, b))
        bg_r = sum(c[0] for c in samples) / len(samples)
        bg_g = sum(c[1] for c in samples) / len(samples)
        bg_b = sum(c[2] for c in samples) / len(samples)
        bg_bright = (bg_r + bg_g + bg_b) / 3.0

        strength = [[0.0] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                r, g, b, a = src[x, y]
                if a < 40:
                    strength[y][x] = 0.0
                    continue
                if r > 200 and g > 200 and b > 200:
                    strength[y][x] = 0.0
                    continue
                dist = abs(r - bg_r) + abs(g - bg_g) + abs(b - bg_b)
                brightness = (r + g + b) / 3.0
                if bg_bright < 140:
                    # خلفية داكنة/كحلية: الحبر هو ما يختلف عنها أو يكون أفتح/أزرق أوضح
                    if dist < 55 and brightness < 150:
                        strength[y][x] = 0.0
                    else:
                        strength[y][x] = max(0.0, min(1.0, dist / 220.0))
                else:
                    # خلفية فاتحة: الحبر هو البكسل الأغمق
                    strength[y][x] = max(0.0, min(1.0, (235.0 - brightness) / 180.0))

        out = Image.new("RGBA", (w, h), (255, 255, 255, 255))
        out_px = out.load()
        for y in range(h):
            for x in range(w):
                s = strength[y][x]
                if 0 < x < w - 1 and 0 < y < h - 1:
                    s = (
                        s * 0.5
                        + strength[y][x - 1] * 0.125
                        + strength[y][x + 1] * 0.125
                        + strength[y - 1][x] * 0.125
                        + strength[y + 1][x] * 0.125
                    )
                if s < 0.10:
                    out_px[x, y] = (255, 255, 255, 255)
                else:
                    t = max(0.18, min(1.0, s))
                    out_px[x, y] = (
                        int(255 + (ink[0] - 255) * t),
                        int(255 + (ink[1] - 255) * t),
                        int(255 + (ink[2] - 255) * t),
                        255,
                    )
        buf = io.BytesIO()
        out.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return payload[:250000]


def compress_signature_b64(raw_b64: str) -> str:
    """ضغط توقيع مستلم الخفر المناوب إلى PNG شفاف صغير مناسب للطباعة A4."""
    return make_ink_transparent_b64(raw_b64, max_w=480, max_h=160)


def _default_manager_settings() -> dict:
    return {
        "manager_name": "",
        "manager_title": DEFAULT_MANAGER_TITLE,
        "manager_sig_b64": "",
        "auto_insert": True,
        "updated_at": "",
        "display_name": DEFAULT_MANAGER_TITLE,
    }


def _manager_sig_from_secrets() -> dict:
    """نسخة دائمة من secrets لا تُمسح عند إعادة تشغيل Streamlit Cloud."""
    out = {}
    try:
        b64 = str(st.secrets.get("MANAGER_SIGNATURE_B64", "") or "").strip()
    except Exception:
        b64 = ""
    if b64:
        if b64.startswith("data:"):
            b64 = b64.split(",", 1)[-1]
        out["manager_sig_b64"] = b64
    try:
        name = str(st.secrets.get("MANAGER_NAME", "") or "").strip()
    except Exception:
        name = ""
    try:
        title = str(st.secrets.get("MANAGER_TITLE", "") or "").strip()
    except Exception:
        title = ""
    if name:
        out["manager_name"] = name
    if title:
        out["manager_title"] = title
    return out


def _read_manager_sig_png_file() -> str:
    try:
        if not os.path.exists(MANAGER_SIG_PNG):
            return ""
        with open(MANAGER_SIG_PNG, "rb") as fh:
            raw = fh.read()
        if not raw:
            return ""
        return base64.b64encode(raw).decode("utf-8")
    except Exception:
        return ""


def get_manager_signature_settings() -> dict:
    """اقرأ توقيع المدير: SQLite → ملف JSON/PNG → st.secrets (دائم)."""
    out = _default_manager_settings()
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT manager_name, manager_title, manager_sig_b64, auto_insert, updated_at "
            "FROM manager_settings WHERE id=1"
        ).fetchone()
        conn.close()
        if row:
            out["manager_name"] = str(row[0] or "")
            out["manager_title"] = str(row[1] or DEFAULT_MANAGER_TITLE) or DEFAULT_MANAGER_TITLE
            out["manager_sig_b64"] = str(row[2] or "")
            out["auto_insert"] = bool(int(row[3] if row[3] is not None else 1))
            out["updated_at"] = str(row[4] or "")
    except Exception:
        pass

    if not out["manager_sig_b64"]:
        try:
            if os.path.exists(MANAGER_SIG_BACKUP):
                with open(MANAGER_SIG_BACKUP, "r", encoding="utf-8") as fh:
                    backup = json.load(fh)
                if isinstance(backup, dict) and backup.get("manager_sig_b64"):
                    out["manager_name"] = str(backup.get("manager_name") or out["manager_name"])
                    out["manager_title"] = str(backup.get("manager_title") or out["manager_title"]) or DEFAULT_MANAGER_TITLE
                    out["manager_sig_b64"] = str(backup.get("manager_sig_b64") or "")
                    out["auto_insert"] = bool(backup.get("auto_insert", out["auto_insert"]))
                    out["updated_at"] = str(backup.get("updated_at") or out["updated_at"])
                    save_manager_signature_settings(
                        out["manager_name"],
                        out["manager_title"],
                        out["manager_sig_b64"],
                        out["auto_insert"],
                        write_backup=False,
                    )
        except Exception:
            pass

    if not out["manager_sig_b64"]:
        png_b64 = _read_manager_sig_png_file()
        if png_b64:
            out["manager_sig_b64"] = png_b64
            try:
                save_manager_signature_settings(
                    out["manager_name"],
                    out["manager_title"],
                    png_b64,
                    out["auto_insert"],
                    write_backup=True,
                )
            except Exception:
                pass

    if not out["manager_sig_b64"]:
        secrets_data = _manager_sig_from_secrets()
        if secrets_data.get("manager_sig_b64"):
            out["manager_name"] = str(secrets_data.get("manager_name") or out["manager_name"])
            out["manager_title"] = str(secrets_data.get("manager_title") or out["manager_title"]) or DEFAULT_MANAGER_TITLE
            out["manager_sig_b64"] = str(secrets_data.get("manager_sig_b64") or "")
            out["updated_at"] = out.get("updated_at") or "from secrets"
            try:
                save_manager_signature_settings(
                    out["manager_name"],
                    out["manager_title"],
                    out["manager_sig_b64"],
                    out["auto_insert"],
                    write_backup=True,
                )
            except Exception:
                pass
    else:
        # املأ الاسم/المسمى من secrets إن كانا فارغين محلياً
        secrets_data = _manager_sig_from_secrets()
        if not out["manager_name"] and secrets_data.get("manager_name"):
            out["manager_name"] = secrets_data["manager_name"]
        if (not out["manager_title"] or out["manager_title"] == DEFAULT_MANAGER_TITLE) and secrets_data.get("manager_title"):
            out["manager_title"] = secrets_data["manager_title"]

    # نظّف التوقيع المحفوظ فوراً (خلفية بيضاء + حبر أزرق) دون إلزام بإعادة التوقيع
    raw_sig = str(out.get("manager_sig_b64") or "").strip()
    if raw_sig:
        cleaned_now = make_ink_transparent_b64(raw_sig, max_w=520, max_h=200) or raw_sig
        out["manager_sig_b64"] = cleaned_now
        if _signature_has_dark_or_teal_bg(raw_sig):
            try:
                save_manager_signature_settings(
                    out.get("manager_name", ""),
                    out.get("manager_title", DEFAULT_MANAGER_TITLE),
                    cleaned_now,
                    bool(out.get("auto_insert", True)),
                    write_backup=True,
                )
            except Exception:
                pass

    name = (out["manager_name"] or "").strip()
    title = (out["manager_title"] or DEFAULT_MANAGER_TITLE).strip()
    out["display_name"] = f"{name} — {title}".strip(" —") if name else title
    return out


def _signature_has_dark_or_teal_bg(raw_b64: str) -> bool:
    """يكشف الخلفية الكحلية/الداكنة في التوقيع المحفوظ سابقاً لإعادة تنظيفه مرة واحدة."""
    payload = str(raw_b64 or "").strip()
    if not payload:
        return False
    if payload.startswith("data:"):
        payload = payload.split(",", 1)[-1]
    try:
        img = Image.open(io.BytesIO(base64.b64decode(payload))).convert("RGBA")
        img.thumbnail((160, 80), Image.Resampling.NEAREST)
        pixels = list(img.getdata())
        if not pixels:
            return False
        darkish = 0
        for r, g, b, a in pixels:
            if a < 40:
                # شفافية فوق واجهة داكنة تظهر كحليّة في المعاينة
                darkish += 1
                continue
            if r < 90 and g < 120 and b < 160:
                darkish += 1
            elif r < 60 and g < 90 and b > 80:
                darkish += 1
        return (darkish / max(len(pixels), 1)) > 0.12
    except Exception:
        return True


def _write_manager_sig_backup(data: dict) -> None:
    payload = {
        "manager_name": str(data.get("manager_name") or ""),
        "manager_title": str(data.get("manager_title") or DEFAULT_MANAGER_TITLE),
        "manager_sig_b64": str(data.get("manager_sig_b64") or ""),
        "auto_insert": bool(data.get("auto_insert", True)),
        "updated_at": str(data.get("updated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    }
    with open(MANAGER_SIG_BACKUP, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    # ملف PNG ثابت على السيرفر لاستعادة سريعة
    try:
        raw_b64 = str(payload.get("manager_sig_b64") or "").strip()
        if raw_b64:
            if raw_b64.startswith("data:"):
                raw_b64 = raw_b64.split(",", 1)[-1]
            with open(MANAGER_SIG_PNG, "wb") as fh:
                fh.write(base64.b64decode(raw_b64))
        elif os.path.exists(MANAGER_SIG_PNG):
            os.remove(MANAGER_SIG_PNG)
    except Exception:
        pass


def save_manager_signature_settings(
    manager_name: str,
    manager_title: str,
    manager_sig_b64: str,
    auto_insert: bool = True,
    write_backup: bool = True,
) -> dict:
    cleaned_sig = make_ink_transparent_b64(manager_sig_b64, max_w=520, max_h=200) if manager_sig_b64 else ""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    name = str(manager_name or "")[:180]
    title = str(manager_title or DEFAULT_MANAGER_TITLE)[:180] or DEFAULT_MANAGER_TITLE
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO manager_settings (id, manager_name, manager_title, manager_sig_b64, auto_insert, updated_at)
        VALUES (1, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            manager_name=excluded.manager_name,
            manager_title=excluded.manager_title,
            manager_sig_b64=excluded.manager_sig_b64,
            auto_insert=excluded.auto_insert,
            updated_at=excluded.updated_at
        """,
        (name, title, cleaned_sig[:350000], 1 if auto_insert else 0, now),
    )
    conn.commit()
    conn.close()
    data = {
        "manager_name": name,
        "manager_title": title,
        "manager_sig_b64": cleaned_sig,
        "auto_insert": bool(auto_insert),
        "updated_at": now,
    }
    if write_backup:
        try:
            _write_manager_sig_backup(data)
        except Exception:
            pass
    data["display_name"] = f"{name} — {title}".strip(" —") if name.strip() else title
    return data


def ingest_manager_signature_bytes(
    raw_bytes: bytes,
    manager_name: str,
    manager_title: str,
    auto_insert: bool = True,
) -> dict:
    """اعتماد توقيع من ملف مرفوع مباشرة إلى SQLite + الملفات الثابتة."""
    if not raw_bytes:
        raise ValueError("ملف التوقيع فارغ")
    b64 = base64.b64encode(raw_bytes).decode("utf-8")
    return save_manager_signature_settings(
        manager_name,
        manager_title or DEFAULT_MANAGER_TITLE,
        b64,
        auto_insert=auto_insert,
    )


def manager_secrets_snippet(data: dict | None = None) -> str:
    cfg = data or get_manager_signature_settings()
    b64 = str(cfg.get("manager_sig_b64") or "").strip()
    name = str(cfg.get("manager_name") or "").replace('"', '\\"')
    title = str(cfg.get("manager_title") or DEFAULT_MANAGER_TITLE).replace('"', '\\"')
    return (
        "# ألصق هذا في Streamlit Secrets مرة واحدة للأبد\n"
        f'MANAGER_PIN = "{_manager_pin()}"\n'
        f'MANAGER_NAME = "{name}"\n'
        f'MANAGER_TITLE = "{title}"\n'
        f'MANAGER_SIGNATURE_B64 = """{b64}"""\n'
    )


def clear_manager_signature_settings(keep_meta: bool = True) -> dict:
    current = get_manager_signature_settings()
    name = current.get("manager_name", "") if keep_meta else ""
    title = current.get("manager_title", DEFAULT_MANAGER_TITLE) if keep_meta else DEFAULT_MANAGER_TITLE
    auto = current.get("auto_insert", True) if keep_meta else True
    return save_manager_signature_settings(name, title, "", auto_insert=auto)


def export_manager_signature_backup_bytes() -> bytes:
    data = get_manager_signature_settings()
    payload = {
        "manager_name": data.get("manager_name", ""),
        "manager_title": data.get("manager_title", DEFAULT_MANAGER_TITLE),
        "manager_sig_b64": data.get("manager_sig_b64", ""),
        "auto_insert": bool(data.get("auto_insert", True)),
        "updated_at": data.get("updated_at", ""),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def import_manager_signature_backup(raw: bytes | str) -> dict:
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="ignore")
    else:
        text = str(raw or "")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("ملف النسخة الاحتياطية غير صالح")
    return save_manager_signature_settings(
        str(data.get("manager_name") or ""),
        str(data.get("manager_title") or DEFAULT_MANAGER_TITLE),
        str(data.get("manager_sig_b64") or ""),
        bool(data.get("auto_insert", True)),
    )


def manager_auto_signature_active() -> tuple[bool, dict]:
    mgr = get_manager_signature_settings()
    active = bool(mgr.get("auto_insert")) and bool(str(mgr.get("manager_sig_b64") or "").strip())
    return active, mgr


def device_hash_for(uid: str) -> str:
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()


def read_request_cookie(name: str) -> str:
    try:
        cookies = st.context.cookies
    except Exception:
        return ""
    if not cookies:
        return ""
    try:
        value = cookies.get(name, "")
    except Exception:
        return ""
    return str(value or "").strip().strip('"')


def read_device_uid() -> str:
    uid = read_request_cookie(DEVICE_COOKIE)
    return uid if _UUID4_RE.match(uid) else ""


def ensure_device_identity() -> tuple[str, str]:
    """ يضمن وجود معرّف جهاز فوري: كوكي المتصفح أولاً، ثم ?duid=، ثم معرّف الجلسة الاحتياطي."""
    cookie_uid = read_device_uid()
    if cookie_uid:
        st.session_state["device_uid"] = cookie_uid
        st.session_state.pop("device_uid_pending", None)
        hashed = device_hash_for(cookie_uid)
        st.session_state["device_hash"] = hashed
        return cookie_uid, hashed

    # مسار مساند للآيفون عندما تكون الكوكيز فارغة داخل iframe / ITP
    try:
        q_uid = str(st.query_params.get("duid") or "").strip()
    except Exception:
        q_uid = ""
    if q_uid and _UUID4_RE.match(q_uid):
        st.session_state["device_uid"] = q_uid
        st.session_state["device_uid_pending"] = q_uid
        hashed = device_hash_for(q_uid)
        st.session_state["device_hash"] = hashed
        return q_uid, hashed

    pending = str(
        st.session_state.get("device_uid_pending")
        or st.session_state.get("device_uid")
        or ""
    ).strip()
    if not pending or not _UUID4_RE.match(pending):
        pending = str(uuid.uuid4())
        st.session_state["device_uid_pending"] = pending
    st.session_state["device_uid"] = pending
    hashed = device_hash_for(pending)
    st.session_state["device_hash"] = hashed
    return pending, hashed


def get_device_shift(device_hash: str) -> dict:
    if not device_hash:
        return _blank_shift()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT dept_name, officer_rank, officer_name, duty_rank, duty_name, default_gps, duty_sig_b64 "
        "FROM device_shifts WHERE device_hash=?",
        (device_hash,),
    ).fetchone()
    conn.close()
    if not row:
        return _blank_shift()
    return _clean_shift(dict(row))


def device_shift_exists(device_hash: str) -> bool:
    if not device_hash:
        return False
    conn = sqlite3.connect(DB_PATH)
    found = conn.execute("SELECT 1 FROM device_shifts WHERE device_hash=?", (device_hash,)).fetchone()
    conn.close()
    return bool(found)


def save_device_shift(device_hash: str, data: dict) -> dict:
    cleaned = _clean_shift(data)
    if not device_hash:
        return cleaned
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO device_shifts (
            device_hash, dept_name, officer_rank, officer_name, duty_rank, duty_name, default_gps, duty_sig_b64
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_hash) DO UPDATE SET
            dept_name=excluded.dept_name,
            officer_rank=excluded.officer_rank,
            officer_name=excluded.officer_name,
            duty_rank=excluded.duty_rank,
            duty_name=excluded.duty_name,
            default_gps=excluded.default_gps,
            duty_sig_b64=excluded.duty_sig_b64
    """, (
        device_hash, cleaned["dept_name"], cleaned["officer_rank"], cleaned["officer_name"],
        cleaned["duty_rank"], cleaned["duty_name"], cleaned["default_gps"], cleaned.get(DUTY_SIG_KEY, ""),
    ))
    conn.commit()
    conn.close()
    return cleaned


def clear_device_shift(device_hash: str) -> None:
    if not device_hash:
        return
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM device_shifts WHERE device_hash=?", (device_hash,))
    conn.commit()
    conn.close()


def shift_from_cookie() -> dict | None:
    raw = read_request_cookie(SHIFT_COOKIE)
    if not raw:
        return None
    parsed = None
    try:
        parsed = json.loads(raw)
    except Exception:
        try:
            from urllib.parse import unquote
            parsed = json.loads(unquote(raw))
        except Exception:
            return None
    return _clean_shift(parsed) if isinstance(parsed, dict) else None


_LIVE_GPS_PAIR = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_DISPLAY_GPS = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*°\s*([NSns])\s*,\s*(\d+(?:\.\d+)?)\s*°\s*([EWew])\s*$"
)


def format_live_gps(lat: float, lng: float) -> str:
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        raise ValueError("gps out of range")
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lng >= 0 else "W"
    return f"{abs(lat):.5f}° {ns}, {abs(lng):.5f}° {ew}"


def signed_gps_pair(text: str) -> tuple[float, float] | None:
    raw = str(text or "").strip()
    live = _LIVE_GPS_PAIR.match(raw)
    if live:
        lat, lng = float(live.group(1)), float(live.group(2))
    else:
        shown = _DISPLAY_GPS.match(raw)
        if not shown:
            return None
        lat = float(shown.group(1)) * (1 if shown.group(2).upper() == "N" else -1)
        lng = float(shown.group(3)) * (1 if shown.group(4).upper() == "E" else -1)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        return None
    return lat, lng


def google_maps_url(text: str) -> str:
    pair = signed_gps_pair(text)
    if not pair:
        return ""
    lat, lng = pair
    return f"https://www.google.com/maps?q={lat:.5f},{lng:.5f}"


def update_default_gps(device_hash: str, gps: str) -> None:
    current = get_device_shift(device_hash)
    current["default_gps"] = gps
    save_device_shift(device_hash, current)


def parse_gps_paste(text: str) -> tuple[float, float] | None:
    """يستخرج الإحداثيات من نص خام أو رابط Google Maps / واتساب."""
    raw = str(text or "").strip()
    if not raw:
        return None
    direct = signed_gps_pair(raw)
    if direct:
        return direct
    patterns = (
        r"[?&]q=(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)",
        r"@(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)",
        r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)",
        r"destination=(-?\d+(?:\.\d+)?)%2C(-?\d+(?:\.\d+)?)",
        r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)",
    )
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            lat, lng = float(match.group(1)), float(match.group(2))
        except ValueError:
            continue
        if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
            return lat, lng
    return None


def _query_gps_pair() -> tuple[float, float] | None:
    lat_raw = str(st.query_params.get("gps_lat") or "").strip()
    lon_raw = str(st.query_params.get("gps_lon") or "").strip()
    if lat_raw and lon_raw:
        try:
            lat, lng = float(lat_raw), float(lon_raw)
            if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
                return lat, lng
        except ValueError:
            pass
    legacy = str(st.query_params.get("live_gps") or "").strip()
    if legacy:
        return signed_gps_pair(legacy)
    return None


def consume_live_gps_query(device_hash: str) -> None:
    pair = _query_gps_pair()
    hash_now = device_hash or str(st.session_state.get("device_hash") or "").strip()
    if pair:
        formatted = format_live_gps(*pair)
        st.session_state["gps_live_ok"] = True
        st.session_state["gps_live_value"] = formatted
        if hash_now:
            update_default_gps(hash_now, formatted)
            st.session_state.pop("pending_live_gps", None)
        else:
            st.session_state["pending_live_gps"] = formatted
        st.session_state["gps_toast"] = formatted
    elif any(k in st.query_params for k in ("gps_lat", "gps_lon", "live_gps")):
        st.session_state["gps_toast_err"] = "تعذر قراءة إحداثي الموقع."
    for key in ("gps_lat", "gps_lon", "gps_ts", "live_gps"):
        st.query_params.pop(key, None)


def gps_header_line(coords: str) -> str:
    safe = html.escape(str(coords or "—"))
    maps = google_maps_url(coords)
    if not maps:
        return f"<p>إحداثيات الموقع: {safe}</p>"
    href = html.escape(maps, quote=True)
    return (
        f"<p>إحداثيات الموقع: {safe} "
        f"<a class='no-print' href='{href}' target='_blank' rel='noopener noreferrer' "
        f"style='font-size:11px; font-weight:800; color:#000000; margin-right:6px;'>خرائط</a></p>"
    )


def doc_exists_in_archive(doc_no: str, device_hash: str) -> bool:
    """هل الرقم المرجعي محفوظ مسبقاً في أرشيف هذا الجهاز؟"""
    ref = str(doc_no or "").strip()
    if not ref or not device_hash:
        return False
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT 1 FROM records WHERE device_hash=? AND doc_no=? LIMIT 1",
        (device_hash, ref),
    ).fetchone()
    conn.close()
    return bool(row)


def save_record_to_db(rec: dict, device_hash: str) -> bool:
    if not device_hash:
        return False
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO records (
            doc_no, form_id, form_title, category, party_name, party_id, plate_no,
            gps_coords, created_at, fields_json, legal_text, citizen_stamp_b64,
            citizen_auth_mode, officer_stamp_b64, attachment_b64, officer_full,
            duty_full, dept_name, verify_hash, officer_auth_mode, duty_auth_mode,
            duty_stamp_b64, receiver_name, receiver_role, device_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        rec["doc_no"], rec["form_id"], rec["form_title"], rec["category"],
        rec["party_name"], rec["party_id"], rec["plate_no"], rec["gps_coords"],
        rec["created_at"], json.dumps(rec["fields"], ensure_ascii=False),
        rec["legal_text"], rec["citizen_stamp_b64"], rec["citizen_auth_mode"],
        rec["officer_stamp_b64"], rec["attachment_b64"], rec["officer_full"],
        rec["duty_full"], rec["dept_name"], rec["verify_hash"],
        rec.get("officer_auth_mode", ""), rec.get("duty_auth_mode", ""),
        rec.get("duty_stamp_b64", ""),
        rec.get("receiver_name", ""), rec.get("receiver_role", ""),
        device_hash,
    ))
    conn.commit()
    conn.close()
    return True





# === KHAFAR_MANUAL_ARCHIVE_START ===
_KHAFAR_ORIG_FUNCS = {}
_KHAFAR_ALLOW_WRITE = False
_KHAFAR_LINE_TO_SITE = {8910: 8910}
_KHAFAR_USED_RETURN_SITES = {8910}
_KHAFAR_READER_FN_NAMES = ['get_traffic_logo_b64']

def _khafar_clear_archive_caches():
    import streamlit as _st
    for _rname in _KHAFAR_READER_FN_NAMES:
        _rfn = globals().get(_rname)
        if _rfn is not None and hasattr(_rfn, "clear"):
            try:
                _rfn.clear()
            except Exception:
                pass
    # مسح أي بصمة منع تكرار داخلية حتى يسمح بالحفظ والتحديث في كل ضغطة زر
    for _k in list(_st.session_state.keys()):
        _kl = str(_k).lower()
        if not _kl.startswith("_khafar_") and any(_w in _kl for _w in ("last_arch", "arch_hash", "arch_sig", "auto_arch", "arch_fp", "saved_sig", "saved_hash")):
            _st.session_state.pop(_k, None)

def _khafar_arm_manual_save():
    import streamlit as _st
    _st.session_state["_khafar_save_requested"] = True

def _khafar_dry_run_call(_orig_fn, *args, **kwargs):
    import builtins as _bi, copy as _copy, io as _io, os as _os, pathlib as _pl, sqlite3 as _sq3, streamlit as _st
    _before_keys = set(_st.session_state.keys())
    _before_vals = {}
    for _k in _before_keys:
        if str(_k).startswith("_khafar_"):
            continue
        try:
            _before_vals[_k] = _copy.deepcopy(_st.session_state[_k])
        except Exception:
            pass

    _orig_wt = _pl.Path.write_text
    _orig_wb = _pl.Path.write_bytes
    _orig_popen = _pl.Path.open
    _orig_preplace = _pl.Path.replace
    _orig_os_replace = _os.replace
    _orig_bi_open = _bi.open
    _orig_io_open = _io.open
    _orig_connect = _sq3.connect

    def _noop(*_a, **_kw):
        return 0

    def _guarded_open(file, mode="r", *a, **kw):
        if any(m in str(mode) for m in ("w", "a", "+", "x")):
            return _io.StringIO() if "b" not in str(mode) else _io.BytesIO()
        return _orig_bi_open(file, mode, *a, **kw)

    def _guarded_popen(self_p, mode="r", *a, **kw):
        if any(m in str(mode) for m in ("w", "a", "+", "x")):
            return _io.StringIO() if "b" not in str(mode) else _io.BytesIO()
        return _orig_popen(self_p, mode, *a, **kw)

    class _ReadOnlyConnProxy:
        def __init__(self, real_conn):
            self._c = real_conn
        def execute(self, sql, *a, **kw):
            s_up = str(sql).lstrip().upper()
            if s_up.startswith(("INSERT", "REPLACE", "UPDATE", "DELETE")):
                class _DummyCur:
                    lastrowid = 0
                    rowcount = 0
                    def fetchone(self): return None
                    def fetchall(self): return []
                return _DummyCur()
            return self._c.execute(sql, *a, **kw)
        def commit(self):
            return None
        def __getattr__(self, name):
            return getattr(self._c, name)
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            try:
                self._c.close()
            except Exception:
                pass
            return False

    try:
        _pl.Path.write_text = _noop
        _pl.Path.write_bytes = _noop
        _pl.Path.open = _guarded_popen
        _pl.Path.replace = _noop
        _os.replace = _noop
        _bi.open = _guarded_open
        _io.open = _guarded_open
        _sq3.connect = lambda *a, **kw: _ReadOnlyConnProxy(_orig_connect(*a, **kw))
        return _orig_fn(*args, **kwargs)
    finally:
        _pl.Path.write_text = _orig_wt
        _pl.Path.write_bytes = _orig_wb
        _pl.Path.open = _orig_popen
        _pl.Path.replace = _orig_preplace
        _os.replace = _orig_os_replace
        _bi.open = _orig_bi_open
        _io.open = _orig_io_open
        _sq3.connect = _orig_connect
        for _k in list(_st.session_state.keys()):
            if not str(_k).startswith("_khafar_") and _k not in _before_keys:
                _st.session_state.pop(_k, None)
        for _k, _v in _before_vals.items():
            try:
                if _st.session_state.get(_k) != _v:
                    _st.session_state[_k] = _v
            except Exception:
                pass

def _khafar_wrap_manual_archive(_orig_fn, _fn_name=""):
    import sys as _sys
    _KHAFAR_ORIG_FUNCS[_fn_name] = _orig_fn

    def _wrapped(*args, **kwargs):
        global _KHAFAR_ALLOW_WRITE
        import streamlit as _st

        if _KHAFAR_ALLOW_WRITE:
            return _orig_fn(*args, **kwargs)

        try:
            _caller_line = _sys._getframe(1).f_lineno
        except Exception:
            _caller_line = -1

        _site_id = _KHAFAR_LINE_TO_SITE.get(_caller_line)
        if _site_id is None:
            return _orig_fn(*args, **kwargs)

        # تنفيذ الحفظ الفعلي بأحدث المدخلات فور ضغط الزر ثم تحديث عداد الأرشيف بالأعلى
        if _st.session_state.pop("_khafar_save_requested", False):
            _KHAFAR_ALLOW_WRITE = True
            try:
                _khafar_clear_archive_caches()
                _res_saved = _orig_fn(*args, **kwargs)
                _khafar_clear_archive_caches()
                _st.session_state["_khafar_manual_save_flash"] = True
                _st.session_state.pop("_khafar_manual_save_err", None)
            except Exception as _exc:
                _st.session_state["_khafar_manual_save_err"] = str(_exc)
                _res_saved = None
            finally:
                _KHAFAR_ALLOW_WRITE = False
            try:
                _st.rerun(scope="app")
            except TypeError:
                _st.rerun()
            return _res_saved

        # حفظ نسخة احتياطية من المعاملات وعرض الزر الرسمي
        _st.session_state["_khafar_last_op"] = (_fn_name, args, kwargs)
        try:
            _st.markdown(
                '<div style="background:linear-gradient(135deg,#0d3b2e 0%,#07231b 100%);'
                'border:1.5px solid #d4a853;border-radius:10px;padding:8px 14px;margin:8px 0 6px 0;'
                'direction:rtl;text-align:right;color:#fef3c7;font-size:13px;font-weight:700;">'
                ' <b>حفظ الوثيقة في الأرشيف:</b> تم إيقاف الحفظ التلقائي للمسودات  اضغط الزر أدناه لاعتماد وحفظ الوثيقة في الأرشيف.'
                '</div>',
                unsafe_allow_html=True,
            )
            _st.button(
                " حفظ واعتماد الوثيقة في الأرشيف الرسمي",
                key="_khafar_manual_arch_btn_main",
                type="primary",
                use_container_width=True,
                on_click=_khafar_arm_manual_save,
            )
            if _st.session_state.pop("_khafar_manual_save_flash", False):
                _st.success(" تم حفظ واعتماد الوثيقة في الأرشيف الرسمي بنجاح!")
                try:
                    _st.toast(" تم الحفظ في الأرشيف الرسمي بنجاح!", icon="")
                except Exception:
                    pass
            _err = _st.session_state.pop("_khafar_manual_save_err", None)
            if _err:
                _st.error(f" تعذر الحفظ في الأرشيف: {_err}")
        except Exception:
            pass

        if _site_id in _KHAFAR_USED_RETURN_SITES:
            return _khafar_dry_run_call(_orig_fn, *args, **kwargs)
        return None

    return _wrapped

def _khafar_flush_fallback_save():
    global _KHAFAR_ALLOW_WRITE
    import streamlit as _st
    if _st.session_state.pop("_khafar_save_requested", False):
        _op = _st.session_state.get("_khafar_last_op")
        if _op:
            _fn_name, _a, _kw = _op
            _real_fn = _KHAFAR_ORIG_FUNCS.get(_fn_name)
            if _real_fn is not None:
                _KHAFAR_ALLOW_WRITE = True
                try:
                    _khafar_clear_archive_caches()
                    _real_fn(*_a, **_kw)
                    _khafar_clear_archive_caches()
                    _st.session_state["_khafar_manual_save_flash"] = True
                finally:
                    _KHAFAR_ALLOW_WRITE = False
                try:
                    _st.rerun(scope="app")
                except TypeError:
                    _st.rerun()
# === KHAFAR_MANUAL_ARCHIVE_END ===

def auto_save_to_archive(rec: dict, device_hash: str) -> bool:
    """حفظ تلقائي مرة واحدة لكل رقم مرجعي قبل عرض زر الطباعة."""
    ref = str((rec or {}).get("doc_no") or "").strip()
    if not ref or not device_hash:
        return False
    archived = st.session_state.setdefault("auto_archived_refs", set())
    if not isinstance(archived, set):
        archived = set(archived or [])
        st.session_state.auto_archived_refs = archived
    if ref in archived or doc_exists_in_archive(ref, device_hash):
        archived.add(ref)
        return False
    ok = save_record_to_db(rec, device_hash)
    if ok:
        archived.add(ref)
        st.session_state.auto_archived_refs = archived
        st.session_state.last_auto_archive_ref = ref
    return ok
auto_save_to_archive = _khafar_wrap_manual_archive(auto_save_to_archive, 'auto_save_to_archive')
auto_save_to_archive = _khafar_wrap_manual_archive(auto_save_to_archive, 'auto_save_to_archive')


def search_records_db(q: str = "", device_hash: str = "", *, all_devices: bool = False) -> list:
    """جلب السجلات. عند all_devices=True تُعرض كل سجلات القسم دون فلتر device_hash (مهم للآيفون)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    q = (q or "").strip()
    if all_devices or not device_hash:
        if not all_devices and not device_hash:
            conn.close()
            return []
        if not q:
            rows = conn.execute("SELECT * FROM records ORDER BY id DESC").fetchall()
        else:
            like = f"%{q}%"
            rows = conn.execute(
                """
                SELECT * FROM records
                WHERE party_id LIKE ? OR plate_no LIKE ? OR party_name LIKE ? OR doc_no LIKE ? OR form_title LIKE ?
                ORDER BY id DESC
                """,
                (like, like, like, like, like),
            ).fetchall()
    else:
        if not q:
            rows = conn.execute(
                "SELECT * FROM records WHERE device_hash=? ORDER BY id DESC",
                (device_hash,),
            ).fetchall()
        else:
            like = f"%{q}%"
            rows = conn.execute(
                """
                SELECT * FROM records
                WHERE device_hash=? AND (
                    party_id LIKE ? OR plate_no LIKE ? OR party_name LIKE ? OR doc_no LIKE ? OR form_title LIKE ?
                )
                ORDER BY id DESC
                """,
                (device_hash, like, like, like, like, like),
            ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_record_db(rec_id: int, device_hash: str = "", *, force: bool = False):
    conn = sqlite3.connect(DB_PATH)
    if force or not device_hash:
        conn.execute("DELETE FROM records WHERE id=?", (rec_id,))
    else:
        conn.execute("DELETE FROM records WHERE id=? AND device_hash=?", (rec_id, device_hash))
    conn.commit()
    conn.close()


def render_device_bootstrap(
    server_has_uid: bool,
    shift_payload: dict | None,
    wipe: bool,
    duty_sig_b64: str = "",
    preferred_uid: str = "",
) -> None:
    """يبقي معرّف الجهاز في الكوكيز والتخزين المحلي دون إضافته إلى الرابط.
    التوقيع (duty_sig_b64) يُحفظ في localStorage فقط — وليس في الكوكيز — لتفادي حد 4KB.
    preferred_uid: معرّف الجلسة الاحتياطي يُعتمد فوراً إن لم يوجد معرّف في المتصفح.
    """
    light = shift_light_payload(shift_payload) if shift_payload else None
    shift_js = json.dumps(light, ensure_ascii=True) if light else "null"
    sig_js = json.dumps(str(duty_sig_b64 or ""), ensure_ascii=True)
    preferred_js = json.dumps(str(preferred_uid or ""), ensure_ascii=True)
    st.html(
        f"""
<script>
(function () {{
  var uidKey = "khafar_device_uid";
  var shiftKey = "khafar_shift";
  var dutySigKey = "{DUTY_SIG_LS_KEY}";
  var serverHasUid = {"true" if server_has_uid else "false"};
  var wipe = {"true" if wipe else "false"};
  var officialShift = {shift_js};
  var officialDutySig = {sig_js};
  var preferredUid = {preferred_js};
  function readCookie(name) {{
    var parts = (document.cookie || "").split("; ");
    for (var i = 0; i < parts.length; i++) {{
      var pair = parts[i].split("=");
      if (pair[0] === name) return decodeURIComponent(pair.slice(1).join("=") || "");
    }}
    return "";
  }}
  function writeCookie(name, value, maxAge) {{
    document.cookie = name + "=" + encodeURIComponent(value) + "; max-age=" + maxAge + "; path=/; SameSite=Lax";
  }}
  function uuid4() {{
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    var bytes = new Uint8Array(16);
    if (window.crypto && crypto.getRandomValues) crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    var hex = [];
    for (var i = 0; i < 16; i++) hex.push(bytes[i].toString(16).padStart(2, "0"));
    return hex.slice(0, 4).join("") + "-" + hex.slice(4, 6).join("") + "-" + hex.slice(6, 8).join("") + "-" + hex.slice(8, 10).join("") + "-" + hex.slice(10).join("");
  }}
  function isUuid(v) {{
    return /^[0-9a-f]{{8}}-[0-9a-f]{{4}}-4[0-9a-f]{{3}}-[89ab][0-9a-f]{{3}}-[0-9a-f]{{12}}$/i.test(String(v || ""));
  }}
  function isIOS() {{
    try {{
      return /iPad|iPhone|iPod/i.test(navigator.userAgent || "")
        || (navigator.platform === "MacIntel" && (navigator.maxTouchPoints || 0) > 1);
    }} catch (e) {{ return false; }}
  }}
  function readQuery(name) {{
    try {{ return new URLSearchParams(window.location.search || "").get(name) || ""; }} catch (e) {{ return ""; }}
  }}
  function softReload() {{
    // تجنّب حلقات إعادة التحميل على iOS Safari / WebView
    if (isIOS()) return;
    try {{
      window.location.replace(window.location.pathname + window.location.search + window.location.hash);
    }} catch (e) {{}}
  }}
  var uid = "";
  try {{ uid = localStorage.getItem(uidKey) || ""; }} catch (e) {{}}
  if (!uid) uid = readCookie(uidKey);
  var qUid = readQuery("duid");
  if (!isUuid(uid) && isUuid(qUid)) uid = qUid;
  if (!isUuid(uid) && isUuid(preferredUid)) uid = preferredUid;
  if (!isUuid(uid)) uid = uuid4();
  try {{ localStorage.setItem(uidKey, uid); }} catch (e) {{}}
  writeCookie(uidKey, uid, 31536000);
  if (wipe) {{
    try {{ localStorage.removeItem(shiftKey); }} catch (e) {{}}
    try {{ localStorage.removeItem(dutySigKey); }} catch (e) {{}}
    writeCookie(shiftKey, "", 0);
    try {{
      if (!sessionStorage.getItem("khafar_wiped")) {{
        sessionStorage.setItem("khafar_wiped", "1");
        softReload();
        return;
      }}
      sessionStorage.removeItem("khafar_wiped");
    }} catch (e) {{}}
  }} else if (officialShift) {{
    var packed = JSON.stringify(officialShift);
    try {{ localStorage.setItem(shiftKey, packed); }} catch (e) {{}}
    writeCookie(shiftKey, packed, 31536000);
    if (officialDutySig) {{
      try {{ localStorage.setItem(dutySigKey, officialDutySig); }} catch (e) {{}}
    }}
  }} else {{
    var localShift = "";
    try {{ localShift = localStorage.getItem(shiftKey) || ""; }} catch (e) {{}}
    try {{
      if (localShift && !readCookie(shiftKey) && !sessionStorage.getItem("khafar_shift_sync")) {{
        sessionStorage.setItem("khafar_shift_sync", "1");
        try {{
          var parsed = JSON.parse(localShift);
          if (parsed && typeof parsed === "object") {{
            delete parsed.duty_sig_b64;
            localShift = JSON.stringify(parsed);
            try {{ localStorage.setItem(shiftKey, localShift); }} catch (e3) {{}}
          }}
        }} catch (e2) {{}}
        writeCookie(shiftKey, localShift, 31536000);
        softReload();
        return;
      }}
      sessionStorage.removeItem("khafar_shift_sync");
    }} catch (e) {{}}
  }}
  try {{
    if (!serverHasUid && !sessionStorage.getItem("khafar_uid_boot")) {{
      sessionStorage.setItem("khafar_uid_boot", "1");
      softReload();
    }}
  }} catch (e) {{}}
}})();
</script>
""",
        unsafe_allow_javascript=True,
    )
    # إخفاء شارات Streamlit Cloud (التاج / GitHub) من الغلاف الخارجي دون فراغ في الواجهة
    render_hide_st_cloud_badges()


def render_hide_st_cloud_badges() -> None:
    """يزرع CSS مرة واحدة في parent/top لإخفاء شارات Streamlit Cloud فقط (بدون Observer/Interval)."""
    components.html(
        """<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>html,body{margin:0;padding:0;width:0;height:0;overflow:hidden;}</style>
</head><body>
<script>
(function () {
  var STYLE_ID = "hide-st-cloud-badges";
  var CSS_TEXT = [
    '[class*="viewerBadge"], [class*="_viewerBadge"], [class*="_link_gzau3"],',
    '[class*="profileContainer"], [class*="_profileContainer"],',
    '[class*="profilePreview"], [class*="_profilePreview"],',
    'a[href*="streamlit.io"], a[href*="share.streamlit.io/user"],',
    'img[src*="avatars.githubusercontent.com"],',
    '[data-testid="manage-app-button"], [data-testid="stToolbar"],',
    'header[data-testid="stHeader"], footer',
    '{ display: none !important; visibility: hidden !important; opacity: 0 !important;',
    '  pointer-events: none !important; width: 0 !important; height: 0 !important; }',
    'iframe[height="0"]{height:0px!important;margin:-1rem 0 0 0!important;display:block!important;border:none!important;}'
  ].join("\\n");

  function plant(doc) {
    try {
      if (!doc || !doc.head) return;
      var style = doc.getElementById(STYLE_ID);
      if (!style) {
        style = doc.createElement("style");
        style.id = STYLE_ID;
        doc.head.appendChild(style);
      }
      style.textContent = CSS_TEXT;
    } catch (e) {}
  }

  try { plant(window.parent && window.parent.document); } catch (e) {}
  try { plant(window.top && window.top.document); } catch (e) {}
})();
</script>
</body></html>""",
        height=0,
        scrolling=False,
    )


# =====================================================================
# 5. قالب الطباعة الرسمي مقاس A4 بالترويسة الخماسية المعتمدة وشعار المرور
# =====================================================================
def _sig_slot_img(b64: str, slot_id: str) -> str:
    slot_style = (
        "max-height:50px; height:auto; max-width:98%; width:auto; object-fit:contain; "
        "display:inline-block; background:#ffffff !important; mix-blend-mode:multiply; "
        "border:none !important; box-shadow:none !important;"
    )
    if b64:
        return (
            f"<img id='{slot_id}' class='sig-slot-img' "
            f"src='data:image/png;base64,{b64}' "
            f"style='{slot_style}' />"
        )
    return (
        f"<img id='{slot_id}' class='sig-slot-img' src='' alt='' "
        f"style='{slot_style} display:none;' />"
    )


def _stable_form_session_key() -> str:
    """مفتاح جلسة ثابت لا يتغير عند إدخال الرقم المرجعي اليدوي (doc_no)."""
    return str(st.session_state.get("auto_doc_no") or st.session_state.get("doc_no") or "doc")


def _receiver_widget_keys(form_id: str) -> tuple[str, str]:
    stable = _stable_form_session_key()
    return f"receiver_name_{form_id}_{stable}", f"receiver_role_{form_id}_{stable}"


def _resolve_stamp_b64(*candidates) -> str:
    for item in candidates:
        text = str(item or "").strip()
        if text:
            return text
    return ""


def _live_pad_card(pad_id: str, title: str, subtitle: str) -> str:
    return f"""
    <div class="live-pad-card" data-pad="{pad_id}">
        <div class="live-pad-title">{title}</div>
        <div class="live-pad-sub">{subtitle}</div>
        <canvas id="pad_{pad_id}" class="live-pad-canvas" width="900" height="220"
            style="touch-action:none; user-select:none; -webkit-user-select:none; -webkit-touch-callout:none; cursor:crosshair;"></canvas>
        <div class="live-pad-actions no-print">
            <button type="button" class="clear-sig-btn" onclick="clearLivePad('{pad_id}')">مسح التوقيع</button>
        </div>
    </div>
    """


def render_officer_sig_pad_html() -> str:
    """لوحة توقيع حي لمستلم الخفر المناوب في الإعدادات — تنقل الناتج إلى جسر Streamlit عبر postMessage."""
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<style>
  body{{margin:0;padding:8px;background:#0d1316;font-family:Cairo,Tahoma,sans-serif;color:#e2e8f0}}
  .wrap{{background:#101820;border:1px solid #1e6b50;border-radius:12px;padding:10px}}
  .title{{font-weight:800;color:#f3cc7a;font-size:13px;margin-bottom:6px;text-align:center}}
  canvas{{width:100%;height:180px;border:1.5px dashed #0d47a1;border-radius:8px;background:#fff;touch-action:none;user-select:none;-webkit-user-select:none;cursor:crosshair;display:block}}
  .actions{{display:flex;gap:8px;justify-content:center;margin-top:8px;flex-wrap:wrap}}
  button{{border:1px solid #d4a853;background:#112924;color:#fff;border-radius:8px;padding:7px 12px;font-weight:800;cursor:pointer}}
  .ok{{color:#34d399;font-size:12px;font-weight:700;text-align:center;margin-top:6px;min-height:18px}}
</style></head><body>
<div class="wrap">
  <div class="title">ارسم توقيع مستلم الخفر المناوب هنا (خط أسود حاد للطباعة)</div>
  <canvas id="pad_officer_settings" width="900" height="220" tabindex="-1"></canvas>
  <div class="actions">
    <button type="button" id="btnClear">مسح اللوحة</button>
    <button type="button" id="btnAdopt">✅ اعتماد التوقيع في الجلسة</button>
  </div>
  <div class="ok" id="padStatus"></div>
</div>
<script>
(function(){{
  var canvas = document.getElementById('pad_officer_settings');
  var ctx = canvas.getContext('2d');
  var drawing = false;
  function pos(e){{
    var r = canvas.getBoundingClientRect();
    var src = (e.touches && e.touches[0]) ? e.touches[0] : e;
    return {{ x: (src.clientX - r.left) * (canvas.width / r.width), y: (src.clientY - r.top) * (canvas.height / r.height) }};
  }}
  function start(e){{ if (e.cancelable) e.preventDefault(); e.stopPropagation(); drawing = true; var p = pos(e); ctx.beginPath(); ctx.moveTo(p.x, p.y); }}
  function move(e){{
    if (!drawing) return; if (e.cancelable) e.preventDefault(); e.stopPropagation();
    var p = pos(e);
    ctx.lineWidth = 3.2; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.strokeStyle = '#000000'; ctx.lineTo(p.x, p.y); ctx.stroke();
  }}
  function end(e){{ if (e && e.cancelable) e.preventDefault(); drawing = false; }}
  canvas.addEventListener('pointerdown', start, {{passive:false}});
  canvas.addEventListener('pointermove', move, {{passive:false}});
  canvas.addEventListener('pointerup', end, {{passive:false}});
  canvas.addEventListener('mousedown', start); canvas.addEventListener('mousemove', move);
  canvas.addEventListener('mouseup', end); canvas.addEventListener('mouseleave', end);
  canvas.addEventListener('touchstart', start, {{passive:false}});
  canvas.addEventListener('touchmove', move, {{passive:false}});
  canvas.addEventListener('touchend', end, {{passive:false}});
  document.getElementById('btnClear').onclick = function(){{
    ctx.clearRect(0,0,canvas.width,canvas.height);
    document.getElementById('padStatus').textContent = '';
  }};
  document.getElementById('btnAdopt').onclick = function(){{
    var blank = document.createElement('canvas');
    blank.width = canvas.width; blank.height = canvas.height;
    if (canvas.toDataURL() === blank.toDataURL()) {{
      document.getElementById('padStatus').textContent = 'ارسم التوقيع أولاً';
      return;
    }}
    var dataUrl = canvas.toDataURL('image/png');
    var b64 = dataUrl.split(',')[1] || '';
    try {{ localStorage.setItem('{DUTY_SIG_LS_KEY}', b64); }} catch (e) {{}}
    try {{
      parent.postMessage({{ type: 'khafar_duty_sig', b64: b64 }}, '*');
    }} catch (e) {{}}
    document.getElementById('padStatus').textContent = 'تم اعتماد التوقيع — اضغط حفظ التوقيع بالأسفل إن لزم';
  }};
}})();
</script>
</body></html>"""


def render_manager_sig_pad_html() -> str:
    """لوحة توقيع المدير: تنزيل PNG شفاف + نسخ Base64 — بدون جسر نصي وبدون كيبورد."""
    return """<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<style>
  body{margin:0;padding:8px;background:#0d1316;font-family:Cairo,Tahoma,sans-serif;color:#e2e8f0}
  .wrap{background:#101820;border:1px solid #c9a227;border-radius:12px;padding:10px}
  .title{font-weight:800;color:#f3cc7a;font-size:13px;margin-bottom:6px;text-align:center}
  .hint{color:#94a3b8;font-size:11px;text-align:center;margin:4px 0 8px;line-height:1.45}
  canvas{width:100%;height:180px;border:1.5px dashed #c9a227;border-radius:8px;background:#ffffff;touch-action:none;user-select:none;-webkit-user-select:none;cursor:crosshair;display:block}
  .actions{display:flex;gap:8px;justify-content:center;margin-top:8px;flex-wrap:wrap}
  button{border:1px solid #d4a853;background:#112924;color:#fff;border-radius:8px;padding:8px 12px;font-weight:800;cursor:pointer;font-size:12px}
  button.primary{background:#145a48;border-color:#34d399}
  .ok{color:#34d399;font-size:12px;font-weight:700;text-align:center;margin-top:8px;min-height:34px;line-height:1.4}
</style></head><body>
<div class="wrap">
  <div class="title">توقيع مدير وحدة الحوادث (إصبع أو قلم)</div>
  <div class="hint">بعد الرسم اضغط «تجهيز وتنزيل» ثم ارفع الملف بالزر أسفل اللوحة لاعتماده فوراً لجميع الأفراد — بدون كيبورد.</div>
  <canvas id="pad_manager_settings" width="900" height="220" tabindex="-1"></canvas>
  <div class="actions">
    <button type="button" id="btnMgrClear">مسح اللوحة</button>
    <button type="button" class="primary" id="btnMgrExport">✅ تجهيز وتنزيل ملف التوقيع الشفاف</button>
  </div>
  <div class="ok" id="mgrPadStatus"></div>
</div>
<script>
(function(){
  var canvas = document.getElementById('pad_manager_settings');
  var ctx = canvas.getContext('2d');
  var drawing = false;
  function pos(e){
    var r = canvas.getBoundingClientRect();
    var src = (e.touches && e.touches[0]) ? e.touches[0] : e;
    return { x: (src.clientX - r.left) * (canvas.width / r.width), y: (src.clientY - r.top) * (canvas.height / r.height) };
  }
  function start(e){ if (e.cancelable) e.preventDefault(); e.stopPropagation(); drawing = true; var p = pos(e); ctx.beginPath(); ctx.moveTo(p.x, p.y); }
  function move(e){
    if (!drawing) return; if (e.cancelable) e.preventDefault(); e.stopPropagation();
    var p = pos(e);
    ctx.lineWidth = 3.2; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.strokeStyle = '#0d47a1'; ctx.lineTo(p.x, p.y); ctx.stroke();
  }
  function end(e){ if (e && e.cancelable) e.preventDefault(); drawing = false; }
  canvas.addEventListener('pointerdown', start, {passive:false});
  canvas.addEventListener('pointermove', move, {passive:false});
  canvas.addEventListener('pointerup', end, {passive:false});
  canvas.addEventListener('mousedown', start); canvas.addEventListener('mousemove', move);
  canvas.addEventListener('mouseup', end); canvas.addEventListener('mouseleave', end);
  canvas.addEventListener('touchstart', start, {passive:false});
  canvas.addEventListener('touchmove', move, {passive:false});
  canvas.addEventListener('touchend', end, {passive:false});

  function isBlank(){
    var blank = document.createElement('canvas');
    blank.width = canvas.width; blank.height = canvas.height;
    return canvas.toDataURL() === blank.toDataURL();
  }

  function toTransparentPng(srcCanvas, maxW){
    var w = srcCanvas.width, h = srcCanvas.height;
    var tmp = document.createElement('canvas');
    tmp.width = w; tmp.height = h;
    var tctx = tmp.getContext('2d');
    // خلفية بيضاء صافية ثم الحبر الأزرق الرسمي
    tctx.fillStyle = '#ffffff';
    tctx.fillRect(0, 0, w, h);
    tctx.drawImage(srcCanvas, 0, 0);
    var img = tctx.getImageData(0, 0, w, h);
    var d = img.data;
    var inkR = 15, inkG = 45, inkB = 130;
    for (var i = 0; i < d.length; i += 4) {
      var r = d[i], g = d[i+1], b = d[i+2], a = d[i+3];
      if (a < 40 || (r > 200 && g > 200 && b > 200)) {
        d[i] = 255; d[i+1] = 255; d[i+2] = 255; d[i+3] = 255;
        continue;
      }
      var br = (r + g + b) / 3;
      var t = Math.max(0.15, Math.min(1, (235 - br) / 180));
      d[i] = Math.round(255 + (inkR - 255) * t);
      d[i+1] = Math.round(255 + (inkG - 255) * t);
      d[i+2] = Math.round(255 + (inkB - 255) * t);
      d[i+3] = 255;
    }
    tctx.putImageData(img, 0, 0);
    if (maxW && w > maxW) {
      var scale = maxW / w;
      var out = document.createElement('canvas');
      out.width = Math.round(w * scale);
      out.height = Math.round(h * scale);
      var octx = out.getContext('2d');
      octx.fillStyle = '#ffffff';
      octx.fillRect(0, 0, out.width, out.height);
      octx.drawImage(tmp, 0, 0, out.width, out.height);
      return out.toDataURL('image/png');
    }
    return tmp.toDataURL('image/png');
  }

  document.getElementById('btnMgrClear').onclick = function(){
    ctx.clearRect(0,0,canvas.width,canvas.height);
    document.getElementById('mgrPadStatus').textContent = '';
  };

  document.getElementById('btnMgrExport').onclick = function(){
    if (isBlank()) {
      document.getElementById('mgrPadStatus').textContent = 'ارسم التوقيع أولاً على اللوحة.';
      return;
    }
    var dataUrl = toTransparentPng(canvas, 260);
    var b64 = (dataUrl.split(',')[1] || '');
    try {
      var a = document.createElement('a');
      a.href = dataUrl;
      a.download = 'manager_signature.png';
      document.body.appendChild(a);
      a.click();
      setTimeout(function(){ a.remove(); }, 200);
    } catch (e) {}
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(b64).catch(function(){});
      }
    } catch (e) {}
    document.getElementById('mgrPadStatus').textContent =
      'تم تجهيز manager_signature.png وتنزيله. ارفعه الآن من الزر أسفل اللوحة لاعتماده فوراً لجميع الأفراد.';
  };
})();
</script>
</body></html>"""


def _harden_bridge_textarea_js(placeholder_token: str) -> str:
    """يمنع كيبورد الجوال على حقول الجسر المخفية: readonly + inputmode=none بدون أي focus."""
    return f"""
  function hardenBridgeFields() {{
    var nodes = document.querySelectorAll('textarea');
    for (var i = 0; i < nodes.length; i++) {{
      var ph = (nodes[i].getAttribute('placeholder') || '');
      if (ph.indexOf({json.dumps(placeholder_token)}) === -1) continue;
      try {{
        nodes[i].setAttribute('readonly', 'readonly');
        nodes[i].setAttribute('inputmode', 'none');
        nodes[i].setAttribute('autocomplete', 'off');
        nodes[i].setAttribute('tabindex', '-1');
        nodes[i].style.caretColor = 'transparent';
      }} catch (e) {{}}
    }}
  }}
  hardenBridgeFields();
  setTimeout(hardenBridgeFields, 120);
  setTimeout(hardenBridgeFields, 600);
"""


def render_manager_sig_bridge_listener() -> None:
    """مُلغى: اعتماد المدير يتم عبر تنزيل PNG ثم st.file_uploader مباشرة."""
    return


def render_live_sig_bridge_listener() -> None:
    """مُعطّل عمداً: التواقيع الحية تُزامن محلياً داخل إطار A4 بدون جسر Streamlit."""
    return


def _consume_live_sig_bridge() -> None:
    """مُعطّل عمداً — لا rerun من لوحات التوقيع الحي."""
    if "live_sig_bridge" in st.session_state:
        try:
            st.session_state.live_sig_bridge = ""
        except Exception:
            pass
    return


def _signer_id_for_pad(form_id: str, pad: str, values: dict) -> str:
    values = values or {}
    if form_id == "decl_flee_waiver" and pad == "p2":
        return str(values.get("cause_id") or "").strip()
    if form_id == "decl_animal_hit" and pad == "p2":
        return str(values.get("owner_id") or "").strip()
    if pad.startswith("p") and pad[1:].isdigit():
        return str(values.get(f"{pad}_id") or values.get("party_id") or "").strip()
    return str(
        values.get("agent_id")
        or values.get("party_id")
        or values.get("p1_id")
        or values.get("observer_name")
        or ""
    ).strip()


def render_officer_sig_bridge_listener(*, allow_ls_restore: bool = False) -> None:
    """يستقبل توقيع لوحة الإعدادات عند اعتماد صريح فقط — بدون focus وبدون كيبورد جوال."""
    restore_flag = "true" if allow_ls_restore else "false"
    st.html(
        f"""
<style>
textarea[placeholder*="DUTY_SIG_BRIDGE"],
div[data-testid="stTextArea"]:has(textarea[placeholder*="DUTY_SIG_BRIDGE"]) {{
  height: 0 !important; min-height: 0 !important; max-height: 0 !important;
  padding: 0 !important; margin: 0 !important; border: none !important;
  opacity: 0 !important; overflow: hidden !important; pointer-events: none !important;
}}
</style>
<script>
(function(){{
  var LS_KEY = {json.dumps(DUTY_SIG_LS_KEY)};
  var ALLOW_RESTORE = {restore_flag};
{_harden_bridge_textarea_js("DUTY_SIG_BRIDGE")}
  function fillBridge(b64) {{
    if (!b64) return false;
    hardenBridgeFields();
    var nodes = document.querySelectorAll('textarea');
    for (var i = 0; i < nodes.length; i++) {{
      var ph = (nodes[i].getAttribute('placeholder') || '');
      if (ph.indexOf('DUTY_SIG_BRIDGE') === -1) continue;
      var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(nodes[i], String(b64));
      nodes[i].dispatchEvent(new Event('input', {{ bubbles: true }}));
      nodes[i].dispatchEvent(new Event('change', {{ bubbles: true }}));
      return true;
    }}
    return false;
  }}
  if (!window.__khafarDutySigBridge) {{
    window.__khafarDutySigBridge = true;
    window.addEventListener('message', function(ev){{
      try {{
        var data = ev.data || {{}};
        if (!data || data.type !== 'khafar_duty_sig' || !data.b64) return;
        fillBridge(data.b64);
      }} catch (e) {{}}
    }});
  }}
  if (ALLOW_RESTORE) {{
    try {{
      if (!sessionStorage.getItem('khafar_duty_sig_restored')) {{
        var saved = localStorage.getItem(LS_KEY) || '';
        if (saved) {{
          sessionStorage.setItem('khafar_duty_sig_restored', '1');
          setTimeout(function(){{ fillBridge(saved); }}, 80);
        }}
      }}
    }} catch (e) {{}}
  }}
}})();
</script>
""",
        unsafe_allow_javascript=True,
    )


_WIDE_FIELD_KEYS = {
    "exterior_damages",
    "interior_inventory",
    "tow_truck_info",
    "legal_article",
    "release_condition",
    "impound_reason_cat",
}


def _field_is_wide(field: dict, value: str) -> bool:
    if field.get("a4_keep_pair"):
        return False
    if field.get("type") == "textarea":
        return True
    if field.get("key") in _WIDE_FIELD_KEYS:
        return True
    label = str(field.get("label") or "")
    if len(label) > 56 or len(value) > 96:
        return True
    return False


def _settlement_party_merged_cells(index: int, fields_map: dict) -> str:
    ordinal = _PARTY_ORDINALS[index]
    prefix = f"p{index}_"
    name = str(fields_map.get(f"{prefix}name") or "-").strip() or "-"
    nid = str(fields_map.get(f"{prefix}id") or "-").strip() or "-"
    phone = str(fields_map.get(f"{prefix}phone") or "-").strip() or "-"
    vehicle = str(fields_map.get(f"{prefix}vehicle") or "-").strip() or "-"
    role = str(fields_map.get(f"{prefix}role") or "-").strip() or "-"
    capacity = str(fields_map.get(f"{prefix}capacity") or "").strip()
    agent = str(fields_map.get(f"{prefix}agent") or "").strip()
    wakala_no = str(fields_map.get(f"{prefix}wakala_no") or "").strip()
    wakala_date = str(fields_map.get(f"{prefix}wakala_date") or "").strip()
    amount = str(fields_map.get(f"{prefix}amount") or "").strip()
    identity = f"{name} | هوية: {nid} | جوال: {phone}"
    capacity_bits = [capacity] if capacity else []
    if capacity and "وكيل" in capacity:
        if agent:
            capacity_bits.append(agent)
        if wakala_no:
            wakala_line = f"وكالة {wakala_no}"
            if wakala_date:
                wakala_line += f" بتاريخ {wakala_date}"
            capacity_bits.append(wakala_line)
    capacity_text = " — ".join(part for part in capacity_bits if part)
    role_line = role
    if amount and "مبلغ مالي" in role:
        role_line = f"{role} وقدره: {amount}"
    if capacity_text:
        vehicle_line = f"{vehicle} — {role_line} ({capacity_text})"
    else:
        vehicle_line = f"{vehicle} — {role_line}"
    return (
        f"<td class='lbl half'>{html.escape(f'بيانات الطرف {ordinal}')}</td>"
        f"<td class='val half'>{html.escape(identity)}</td>"
        f"<td class='lbl half'>{html.escape('المركبة والصفة')}</td>"
        f"<td class='val half'>{html.escape(vehicle_line)}</td>"
    )


def _data_table_rows(form_def: dict | None, fields_map: dict, dense: bool, form_id: str = "") -> str:
    def pair_cells(label: str, value: str, wide: bool, *, isolate: bool = False) -> str:
        safe_label = html.escape(label)
        if isolate:
            safe_value = (
                '<span class="rtl-iso" dir="rtl" style="unicode-bidi:isolate; white-space:normal; '
                'display:inline; max-width:100%; overflow-wrap:anywhere; word-break:break-word;">'
                + html.escape(value)
                + "</span>"
            )
        else:
            safe_value = html.escape(value)
        val_cls = "val plate-val" if isolate else "val"
        if wide:
            return f"<td class='lbl'>{safe_label}</td><td class='{val_cls} span3' colspan='3'>{safe_value}</td>"
        return f"<td class='lbl half'>{safe_label}</td><td class='{val_cls} half'>{safe_value}</td>"

    if not form_def:
        rows = []
        for key, value in fields_map.items():
            shown = str(value or "-")
            rows.append(f"<tr>{pair_cells(str(key), shown, True)}</tr>")
        return "".join(rows)

    compact_settlement = form_id == "decl_settlement"
    party_count = _count_parties(fields_map) if compact_settlement else 0
    skip_keys = set()
    if compact_settlement:
        for index in range(1, party_count + 1):
            for suffix in (
                "name", "id", "phone", "vehicle", "role", "amount",
                "capacity", "wakala_no", "wakala_date", "agent",
            ):
                skip_keys.add(f"p{index}_{suffix}")
        skip_keys.update({"settlement_basis", "compensation", "injury_statement"})

    rows = []
    pending = None
    parties_emitted = False
    for field in form_def["fields"]:
        key = str(field.get("key") or "")
        if key in skip_keys:
            continue
        if not _include_field_on_a4(field, fields_map):
            continue
        shown = _resolve_select_display(fields_map, key, str(fields_map.get(key, "-") or "-"))
        label = str(field.get("a4_label") or field["label"])
        # تسميات المفرد/الجمع في جدول A4 (مثل: اسم المصاب بدل المصاب الأول)
        if form_id in {"med_injury", "med_morgue"}:
            label = _field_display_label(form_id, {**field, "label": label}, fields_map)
        if key in _REF_FIELD_KEYS or any(tok in label for tok in _REF_LABEL_TOKENS):
            manual_shown = normalize_western_digits(str(fields_map.get("manual_ref_no") or "").strip())
            raw_shown = normalize_western_digits(str(fields_map.get(key, "") or "").strip())
            shown = manual_shown or raw_shown
            label = "رقم مرجعي" if (manual_shown or raw_shown) else label
            # لا تُعرض نقاط وهمية إن تُرك الرقم فارغاً
            if not shown:
                shown = ""
        sibling_key = field.get("a4_with")
        if sibling_key:
            sibling = str(fields_map.get(sibling_key, "") or "").strip()
            if sibling:
                shown = f"{shown} — {sibling}" if shown else sibling
        compose = field.get("a4_compose") or {}
        if isinstance(compose, dict) and compose.get("fmt"):
            mapping = {"value": shown}
            for compose_key in compose.get("keys") or []:
                mapping[compose_key] = str(fields_map.get(compose_key, "") or "").strip() or "-"
            shown = compose["fmt"].format_map(mapping)
            extra_key = compose.get("append_if")
            extra = str(fields_map.get(extra_key, "") or "").strip() if extra_key else ""
            if extra and compose.get("append_fmt"):
                if "أخرى" in str(fields_map.get(key, "") or ""):
                    shown = extra
                else:
                    shown += str(compose["append_fmt"]).replace("{extra}", extra)
        field = {**field, "label": label}
        isolate = (
            key in {"plate_no", "party_id", "awtar_no"} or key in _REF_FIELD_KEYS
            or "لوحة" in label or "plate" in key.lower() or label == "رقم مرجعي"
        )
        wide = dense and _field_is_wide(field, shown)
        if not dense or wide:
            if pending:
                rows.append(f"<tr>{pair_cells(pending[0], pending[1], True, isolate=pending[2])}</tr>")
                pending = None
            if dense and wide:
                rows.append(f"<tr>{pair_cells(field['label'], shown, True, isolate=isolate)}</tr>")
            else:
                rows.append(f"<tr>{pair_cells(field['label'], shown, True, isolate=isolate)}</tr>")
        elif pending is None:
            pending = (field["label"], shown, isolate)
        else:
            rows.append(
                "<tr>"
                + pair_cells(pending[0], pending[1], False, isolate=pending[2])
                + pair_cells(field["label"], shown, False, isolate=isolate)
                + "</tr>"
            )
            pending = None
        if compact_settlement and key == "party_count" and not parties_emitted:
            if pending:
                rows.append(f"<tr>{pair_cells(pending[0], pending[1], True, isolate=pending[2])}</tr>")
                pending = None
            for index in range(1, party_count + 1):
                rows.append(f"<tr>{_settlement_party_merged_cells(index, fields_map)}</tr>")
            basis = str(fields_map.get("settlement_basis") or "-").strip() or "-"
            injury = str(fields_map.get("injury_statement") or "-").strip() or "-"
            compensation = str(fields_map.get("compensation") or "").strip()
            summary = f"{basis} | {injury}"
            if compensation:
                summary += f" | العوض: {compensation}"
            rows.append(
                f"<tr>{pair_cells('أساس الصلح والإقرار المروري', summary, True)}</tr>"
            )
            parties_emitted = True
    if pending:
        rows.append(f"<tr>{pair_cells(pending[0], pending[1], True, isolate=pending[2])}</tr>")
    return "".join(rows)


def _distinct_role(name: str, role: str) -> str:
    name = (name or "").strip()
    role = (role or "").strip()
    if not role or role == name:
        return ""
    return role


def build_official_a4_html(rec: dict, form_def: dict | None, logo_b64: str, interactive_sig: bool = False) -> str:
    fields_map = rec["fields"] if isinstance(rec.get("fields"), dict) else json.loads(rec["fields_json"])
    if form_def:
        field_count = sum(1 for field in form_def["fields"] if _include_field_on_a4(field, fields_map))
    else:
        field_count = len(fields_map)
    dense = True
    rows_html = _data_table_rows(form_def, fields_map, dense, str(rec.get("form_id") or ""))
    data_tbl_cls = "data-tbl cols-4"

    qr_payload = f"DOC:{rec['doc_no']}|ID:{rec['party_id']}|PLATE:{rec['plate_no']}|SEAL:{rec['verify_hash']}"
    awtar_qr = normalize_western_digits(str(fields_map.get("awtar_no") or "").strip())
    if awtar_qr:
        qr_payload += f"|AWTAR:{awtar_qr}"
    qr_b64 = generate_qr_png_b64(qr_payload)

    _logo = (logo_b64 or "").strip() or get_traffic_logo_b64()
    center_logo_html = (
        f"<img class='hdr-logo' src='data:image/png;base64,{_logo}' "
        f"style='width:88px!important;height:88px!important;max-width:88px!important;"
        f"max-height:88px!important;object-fit:contain!important;display:block;"
        f"margin:0 auto;padding:0;border:none;background:transparent;"
        f"-webkit-print-color-adjust:exact;print-color-adjust:exact;' "
        f"alt='شعار المرور' />"
        if _logo
        else "<div style='font-size:14px;font-weight:800;color:#000000;'>الإدارة العامة للمرور</div>"
    )

    is_medical = rec.get("category") == "إحالة طبية"
    is_letter = bool(form_def and form_def.get("is_official_letter"))
    citizen_mode = rec.get("citizen_auth_mode", "") or ""
    officer_mode = rec.get("officer_auth_mode", "") or ""
    duty_mode = rec.get("duty_auth_mode", "") or ""
    receiver_name = (rec.get("receiver_name") or "").strip()
    receiver_role = (rec.get("receiver_role") or "").strip()

    # فصل اسم المصاب/الحالة عن اسم المناوب المستلم في الإحالات الطبية
    if is_letter:
        recipient_title = (form_def or {}).get("recipient_role_title") or "المختص المستلم بحجز مرور أبو عريش"
        col1_header = "المختص المستلم (حجز مرور أبو عريش)"
        col1_top_name = receiver_name
        col1_role_line = _distinct_role(receiver_name, receiver_role)
        if col1_role_line == recipient_title or "حجز مرور أبو عريش" in col1_role_line:
            col1_role_line = ""
        citizen_pad_title = "لوحة توقيع: المختص المستلم بحجز مرور أبو عريش"
        citizen_pad_sub = " — ".join([x for x in (receiver_name, receiver_role) if x and x != recipient_title]) or recipient_title
    elif is_medical:
        col1_header = "جهة الاستلام (المستشفى / المختبر)"
        col1_top_name = receiver_name
        col1_role_line = _distinct_role(receiver_name or col1_header, receiver_role)
        citizen_pad_title = "لوحة توقيع: المختص المناوب المستلم"
        citizen_pad_sub = " — ".join([x for x in (receiver_name, receiver_role) if x]) or "جهة الاستلام"
    else:
        handover_agent = rec.get("form_id") == "decl_handover" and _is_agent_role(fields_map.get("receiver_role"))
        if handover_agent:
            col1_header = "توقيع المستلم (الوكيل الشرعي)"
            col1_top_name = str(fields_map.get("agent_name") or "").strip()
            agent_id = str(fields_map.get("agent_id") or "").strip()
            col1_role_line = f"هوية رقم: {agent_id}" if agent_id else ""
            citizen_pad_title = "لوحة توقيع: الوكيل الشرعي"
            citizen_pad_sub = " — ".join(part for part in (col1_top_name, col1_role_line) if part) or "الوكيل الشرعي"
        elif rec.get("form_id") == "min_wrong_viol":
            col1_header = "راصد المخالفة (محرر الإشعار)"
            col1_top_name = str(fields_map.get("observer_name") or "").strip() or (rec.get("party_name") or "").strip()
            if col1_top_name in {"", "غير محدد", "-"}:
                col1_top_name = ""
            col1_role_line = ""
            citizen_pad_title = "لوحة توقيع: راصد المخالفة"
            citizen_pad_sub = col1_top_name or "راصد المخالفة"
        else:
            col1_header = "الطرف المعني"
            col1_top_name = (rec.get("party_name") or "").strip()
            if col1_top_name in {"", "غير محدد", "-"}:
                col1_top_name = ""
            col1_role_line = ""
            citizen_pad_title = "لوحة توقيع: المواطن / المقر / الطرف المعني"
            citizen_pad_sub = col1_top_name or "الطرف المعني"

    col1_name_html = (
        f'<div class="sig-person">{html.escape(col1_top_name)}</div>'
        if col1_top_name else ""
    )
    col1_role_html = (
        f'<div class="sig-role">{html.escape(col1_role_line)}</div>'
        if col1_role_line else ""
    )

    live_pads_early = rec.get("live_sig_pads") or {}
    if not isinstance(live_pads_early, dict):
        live_pads_early = {}
    fields_early = rec.get("fields") if isinstance(rec.get("fields"), dict) else {}
    citizen_stamp_now = _resolve_stamp_b64(
        rec.get("citizen_stamp_b64"),
        live_pads_early.get("citizen"),
        fields_early.get("__sig_citizen"),
    )
    officer_stamp_now = _resolve_stamp_b64(
        rec.get("officer_stamp_b64"),
        live_pads_early.get("officer"),
        fields_early.get("__sig_officer"),
    )
    duty_stamp_now = _resolve_stamp_b64(
        rec.get("duty_stamp_b64"),
        live_pads_early.get("duty"),
        fields_early.get("__sig_duty"),
    )

    # توقيع مدير وحدة الحوادث المعتمد مركزياً يُدرج تلقائياً لجميع الأفراد (غير قابل للتعديل بدون الرمز السري)
    manager_auto, manager_cfg = manager_auto_signature_active()
    manager_duty_full = ""
    if manager_auto:
        duty_stamp_now = str(manager_cfg.get("manager_sig_b64") or "").strip()
        manager_duty_full = str(manager_cfg.get("display_name") or DEFAULT_MANAGER_TITLE)
        duty_mode = MANAGER_AUTH_MODE

    # تبقى لوحة التوقيع ظاهرة أثناء وضع التوقيع الحي حتى لا يُفقد الرسم عند التحديث
    needs_citizen_pad = interactive_sig and ("توقيع حي" in citizen_mode)
    needs_officer_pad = interactive_sig and ("توقيع حي" in officer_mode)
    # لا تُعرض لوحة توقيع وحدة الحوادث للأفراد عند تفعيل التوقيع المركزي للمدير
    needs_duty_pad = (not manager_auto) and interactive_sig and ("توقيع حي" in duty_mode)

    # إرشاد التوقيع يبقى في لوحة الرسم فوق الورقة، لا داخل خلايا المحضر
    guide_hint = ""

    # --- Citizen / receiver cell ---
    if citizen_stamp_now:
        citizen_box_inner = _sig_slot_img(citizen_stamp_now, "slot_citizen")
    elif needs_citizen_pad:
        citizen_box_inner = (
            "<div class='sig-guide'>"
            + _sig_slot_img("", "slot_citizen")
            + guide_hint
            + "</div>"
        )
    elif is_medical and "ختم وتوقيع" in citizen_mode:
        citizen_box_inner = """
        <div class='sig-guide sig-guide-print-clean' style='border:1px dashed #000000; border-radius:6px; padding:8px 6px; margin:3px 4px; font-size:11px; color:#000000; font-weight:700; line-height:1.6;'>
            التوقيع والختم الرسمي لجهة الاستلام
        </div>
        """
    elif "غياب" in citizen_mode or "امتناع" in citizen_mode:
        citizen_box_inner = "<div style='padding:16px 0; font-weight:700; color:#7f1d1d; font-size:11px;'>غياب الطرف / امتناع مثبت بالمحضر</div>"
    else:
        citizen_box_inner = _sig_slot_img("", "slot_citizen")

    # --- Officer cell ---
    if officer_stamp_now:
        officer_box_inner = _sig_slot_img(officer_stamp_now, "slot_officer")
    elif needs_officer_pad:
        officer_box_inner = (
            "<div class='sig-guide'>"
            + _sig_slot_img("", "slot_officer")
            + guide_hint
            + "</div>"
        )
    else:
        officer_box_inner = _sig_slot_img("", "slot_officer")

    form_id_now = str(rec.get("form_id") or "")
    form_title_now = str(rec.get("form_title") or "") + " " + str((form_def or {}).get("title") or "")
    is_toxicology = form_id_now == "med_toxicology" or "تحليل سموم" in form_title_now

    # --- Duty cell ---
    if is_toxicology:
        # خطاب تحليل السموم فقط: ختم إدارة مرور منطقة جازان + توثيق نصي لمستلم الخفر المناوب بدون خانة توقيع
        tox_officer_name = str(rec.get("officer_full") or "").strip()
        for _pfx in ("مستلم الخفر المناوب /", "مستلم الخفر المناوب/", "مستلم الخفر المناوب -", "مستلم الخفر المناوب-"):
            if tox_officer_name.startswith(_pfx):
                tox_officer_name = tox_officer_name[len(_pfx):].strip()
                break
        tox_officer_line = (
            '<div style="margin-top:8px;font-size:12px;font-weight:800;color:#000000 !important;'
            'line-height:1.45;text-align:center;">'
            f"توثيق مستلم الخفر المناوب: {html.escape(tox_officer_name or '—')}"
            "</div>"
        )
        if duty_stamp_now:
            duty_box_inner = _sig_slot_img(duty_stamp_now, "slot_duty") + tox_officer_line
        elif needs_duty_pad:
            duty_box_inner = (
                "<div class='sig-guide'>"
                + _sig_slot_img("", "slot_duty")
                + guide_hint
                + "</div>"
                + tox_officer_line
            )
        elif "ختم" in duty_mode or not duty_mode:
            duty_box_inner = (
                '<div style="display:inline-block; border:1.5px solid #000000; color:#000000; '
                'padding:6px 12px; border-radius:5px; font-size:12px; font-weight:800; '
                'line-height:1.45; max-width:96%;">'
                "ختم المصادقة النظامي لإدارة مرور منطقة جازان"
                "</div>"
                + tox_officer_line
            )
        else:
            duty_box_inner = _sig_slot_img("", "slot_duty") + tox_officer_line
        # لا تُعرض لوحة/خانة توقيع لمستلم الخفر المناوب في هذا الخطاب
        needs_officer_pad = False
        officer_box_inner = ""
    elif duty_stamp_now:
        duty_box_inner = _sig_slot_img(duty_stamp_now, "slot_duty")
        if manager_auto:
            duty_box_inner += (
                '<div style="margin-top:4px;display:inline-block;border:1.2px solid #000;'
                'padding:2px 8px;border-radius:4px;font-size:10.5px;font-weight:800;">'
                "مُصادق ومُعتمد نظاماً"
                "</div>"
            )
    elif needs_duty_pad:
        duty_box_inner = (
            "<div class='sig-guide'>"
            + _sig_slot_img("", "slot_duty")
            + guide_hint
            + "</div>"
        )
    elif "ختم" in duty_mode or not duty_mode:
        duty_box_inner = """
            <div style="display:inline-block; border:1.5px solid #000000; color:#000000; padding:3px 10px; border-radius:5px; font-size:11.5px; font-weight:800;">
                مُصادق ومُعتمد نظاماً
            </div>
        """
    else:
        duty_box_inner = _sig_slot_img("", "slot_duty")

    # جدول التوقيعات ثابت بـ 3 أعمدة للنماذج العادية، وشبكة مضغوطة لنماذج التنازل متعددة الأطراف
    # (تحليل السموم: عمودان فقط — جهة الاستلام + مصادقة إدارة مرور منطقة جازان)
    col_width = "50%" if is_toxicology else "33.3%"
    party_signers = _waiver_signers(form_id_now, fields_map)
    multi_sig = bool(party_signers)
    needs_party_live = multi_sig and interactive_sig and ("توقيع حي" in citizen_mode)

    def _sig_cell(header: str, name: str, role: str, inner: str) -> str:
        name_html = f'<div class="sig-person">{html.escape(name)}</div>' if name else ""
        role_html = f'<div class="sig-role">{html.escape(role)}</div>' if role else ""
        return (
            '<div class="sig-cell">'
            f'<div class="sig-head">{html.escape(header)}</div>'
            f"{name_html}{role_html}{inner}"
            "</div>"
        )

    if multi_sig:
        def _sig_td(header: str, name: str, role: str, inner: str, colspan: int = 1) -> str:
            span = f" colspan='{colspan}'" if colspan > 1 else ""
            name_html = f'<div class="sig-person">{html.escape(name)}</div>' if name else ""
            role_html = f'<div class="sig-role">{html.escape(role)}</div>' if role else ""
            return (
                f"<td class='sig-cell'{span}>"
                f"<div class='sig-head'>{html.escape(header)}</div>"
                f"{name_html}{role_html}{inner}"
                "</td>"
            )

        party_stamps = rec.get("party_stamps") or {}
        if not isinstance(party_stamps, dict):
            party_stamps = {}
        if not party_stamps and isinstance(fields_map.get("__party_stamps"), dict):
            party_stamps = fields_map.get("__party_stamps") or {}
        live_pads = rec.get("live_sig_pads") or fields_map.get("__live_sig_pads") or {}
        if not isinstance(live_pads, dict):
            live_pads = {}
        sig_slots = []
        for signer in party_signers:
            pad = signer["pad"]
            pad_b64 = (
                str(party_stamps.get(pad) or "").strip()
                or str(live_pads.get(pad) or "").strip()
                or str(fields_map.get(f"__sig_{pad}") or "").strip()
            )
            if needs_party_live and not pad_b64:
                inner = "<div class='sig-guide'>" + _sig_slot_img("", f"slot_{pad}") + "</div>"
            elif pad_b64:
                inner = _sig_slot_img(pad_b64, f"slot_{pad}")
            elif rec.get("citizen_stamp_b64") and len(party_signers) == 1:
                inner = _sig_slot_img(rec["citizen_stamp_b64"], f"slot_{pad}")
            else:
                inner = _sig_slot_img("", f"slot_{pad}")
            sig_slots.append((signer["header"], signer["name"], signer["role"], inner))
        duty_name_now = manager_duty_full or str(rec.get("duty_full") or "")
        if not is_toxicology:
            sig_slots.append(("مستلم الخفر المناوب", str(rec.get("officer_full") or ""), "", officer_box_inner))
            sig_slots.append(("وحدة الحوادث", duty_name_now, "", duty_box_inner))
        else:
            tox_duty_header = "وحدة الحوادث" if manager_auto else "مصادقة إدارة مرور منطقة جازان"
            sig_slots.append((tox_duty_header, duty_name_now if manager_auto else "", "", duty_box_inner))
        grid_cols = 3 if len(sig_slots) <= 3 else 4
        sig_rows = []
        for start in range(0, len(sig_slots), grid_cols):
            chunk = sig_slots[start:start + grid_cols]
            last_span = (grid_cols - len(chunk) + 1) if len(chunk) < grid_cols else 1
            sig_rows.append(
                "<tr>"
                + "".join(
                    _sig_td(*slot, last_span if index == len(chunk) - 1 else 1)
                    for index, slot in enumerate(chunk)
                )
                + "</tr>"
            )
        colgroup = ""
        multi_cls = "sig-tbl sig-multi"
        if grid_cols == 4:
            multi_cls += " cols-4"
            colgroup = "<colgroup>" + "<col style='width:25%'>" * 4 + "</colgroup>"
        sig_table_html = (
            f"<table class='{multi_cls}'>{colgroup}<tbody>"
            + "".join(sig_rows)
            + "</tbody></table>"
        )
    else:
        duty_name_display = manager_duty_full or str(rec.get("duty_full") or "")
        duty_name_html = (
            f'<div class="sig-person">{html.escape(duty_name_display)}</div>'
            if duty_name_display else ""
        )
        if is_toxicology:
            tox_right_header = "وحدة الحوادث" if manager_auto else "مصادقة إدارة مرور منطقة جازان"
            sig_table_html = f"""
                <table class="sig-tbl">
                    <thead>
                        <tr>
                            <th style="width:50%;">{html.escape(col1_header)}</th>
                            <th style="width:50%;">{html.escape(tox_right_header)}</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td style="width:50%;">
                                {col1_name_html}
                                {col1_role_html}
                                {citizen_box_inner}
                            </td>
                            <td style="width:50%;">
                                {duty_name_html if manager_auto else ""}
                                {duty_box_inner}
                            </td>
                        </tr>
                    </tbody>
                </table>
            """
        else:
            sig_table_html = f"""
                <table class="sig-tbl">
                    <thead>
                        <tr>
                            <th>{html.escape(col1_header)}</th>
                            <th>مستلم الخفر المناوب</th>
                            <th>وحدة الحوادث</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td style="width:{col_width};">
                                {col1_name_html}
                                {col1_role_html}
                                {citizen_box_inner}
                            </td>
                            <td style="width:{col_width};">
                                <div class="sig-person">{html.escape(str(rec['officer_full']))}</div>
                                {officer_box_inner}
                            </td>
                            <td style="width:{col_width};">
                                {duty_name_html}
                                {duty_box_inner}
                            </td>
                        </tr>
                    </tbody>
                </table>
            """

    live_pad_ids = []
    dock_cards = []
    _live_pads_map = rec.get("live_sig_pads") or fields_map.get("__live_sig_pads") or {}
    if not isinstance(_live_pads_map, dict):
        _live_pads_map = {}
    _party_stamps_map = rec.get("party_stamps") or fields_map.get("__party_stamps") or {}
    if not isinstance(_party_stamps_map, dict):
        _party_stamps_map = {}
    if needs_party_live:
        for signer in party_signers:
            live_pad_ids.append(signer["pad"])
            dock_cards.append(_live_pad_card(signer["pad"], signer["pad_title"], signer["sub"]))
    elif needs_citizen_pad:
        live_pad_ids.append("citizen")
        dock_cards.append(_live_pad_card("citizen", citizen_pad_title, citizen_pad_sub))
    if needs_officer_pad and not is_toxicology:
        live_pad_ids.append("officer")
        dock_cards.append(_live_pad_card("officer", "لوحة توقيع: مستلم الخفر المناوب", rec.get("officer_full", "")))
    if needs_duty_pad:
        live_pad_ids.append("duty")
        duty_pad_title = (
            "لوحة توقيع: مصادقة إدارة مرور منطقة جازان"
            if is_toxicology
            else "لوحة توقيع: مصادقة وحدة الحوادث"
        )
        duty_pad_sub = (
            "إدارة مرور منطقة جازان"
            if is_toxicology
            else rec.get("duty_full", "")
        )
        dock_cards.append(_live_pad_card("duty", duty_pad_title, duty_pad_sub))

    preloaded_live_sigs = {}
    for pad_id in live_pad_ids:
        b64 = (
            str(_live_pads_map.get(pad_id) or "").strip()
            or str(_party_stamps_map.get(pad_id) or "").strip()
            or str(fields_map.get(f"__sig_{pad_id}") or "").strip()
        )
        if not b64 and pad_id == "citizen":
            b64 = citizen_stamp_now
        elif not b64 and pad_id == "officer":
            b64 = officer_stamp_now
        elif not b64 and pad_id == "duty":
            b64 = duty_stamp_now
        if b64:
            preloaded_live_sigs[pad_id] = b64

    live_dock_html = ""
    if dock_cards:
        live_dock_html = (
            '<div class="live-sig-dock no-print">'
            '<div class="live-sig-dock-head">✍️ لوحات التوقيع الحي بالإصبع (ارسم هنا — يُنسخ فوراً إلى خانات A4 محلياً بدون تحديث الصفحة)</div>'
            '<div class="live-sig-dock-grid">'
            + "".join(dock_cards)
            + "</div></div>"
        )

    attachment_block = ""
    image_count = 0
    show_atts = rec.get("show_attachments_in_print", True)
    att_items = parse_attachments(rec.get("attachment_b64"))
    if show_atts and att_items:
        cards = []
        for att in att_items:
            kind = (att.get("kind") or "image").lower()
            if kind == "pdf":
                cards.append(
                    '<div class="att-card att-pdf-card">'
                    '<div class="att-pdf-icon">📄</div>'
                    '<div class="att-pdf-note">مرفق PDF</div>'
                    "</div>"
                )
            else:
                image_count += 1
                mime = html.escape(str(att.get("mime") or "image/png"))
                b64 = att.get("b64") or ""
                cards.append(
                    f'<div class="att-card">'
                    f'<img src="data:{mime};base64,{b64}" alt="" />'
                    f"</div>"
                )
        att_grid_cls = "attachment-grid atts-single" if image_count <= 1 else "attachment-grid atts-multi"
        attachment_block = f"""
        <div class="attachment-section">
            <div class="attachment-title">📎 المرفقات المصورة المعتمدة في التقرير</div>
            <div class="{att_grid_cls}">{"".join(cards)}</div>
        </div>
        """

    if is_letter:
        legal_box_title = "صيغة الخطاب الرسمي الموجه لحجز مرور محافظة أبو عريش:"
    elif is_medical:
        legal_box_title = "نص الخطاب والتوجيه الرسمي المعتمد:"
    else:
        legal_box_title = f"الصيغة النظامية المعتمدة ({rec['category']}):"
    cleaned_legal_text = normalize_official_legal_text(rec.get("legal_text") or "")
    banner_title = (form_def or {}).get("official_title") or rec["form_title"]
    text_len = len(re.sub(r"<[^>]+>", "", cleaned_legal_text or ""))
    rows_cnt = rows_html.count("<tr")
    sigs_cnt = len(party_signers) + (1 if is_toxicology else 2)
    form_id_now = str(rec.get("form_id") or "")
    # الصور المضغوطة لا تفرض dense إذا كان النص والجدول قصيرين
    images_force_dense = image_count > 0 and not (rows_cnt <= 5 and text_len <= 480)
    if (
        form_id_now == "decl_settlement"
        or sigs_cnt >= 4
        or rows_cnt >= 8
        or text_len > 620
        or images_force_dense
    ):
        tier = "dense"
    elif rows_cnt <= 5 and text_len <= 420:
        tier = "spacious"
    else:
        tier = "balanced"
    sheet_cls = f"a4-sheet a4-paper a4-page print-area a4-tier-{tier}"
    if tier == "dense":
        sheet_cls += " a4-dense-print"
    gps_line_html = gps_header_line(str(rec.get("gps_coords") or ""))

    return f"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="format-detection" content="telephone=no">
<title>{rec['doc_no']} - {banner_title}</title>
<style>
    @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@600;700;800;900&family=Tajawal:wght@700;800;900&display=swap');
    *, *::before, *::after {{ box-sizing: border-box; font-family: "Cairo", "Tajawal", Tahoma, Arial, sans-serif !important; }}
    /* ورقة A4 معزولة داخل iframe: نص أسود عريض فوق خلفية بيضاء */
    html, body {{ color-scheme: light; direction: rtl; }}
    body {{ margin: 0; padding: 14px; background: #0d1316; direction: rtl; text-align: right; color: #e2e8f0; }}
    .a4-sheet, .a4-paper,
    .a4-paper table, .a4-sheet table, .a4-paper thead, .a4-paper tbody, .a4-paper tr,
    .a4-sheet thead, .a4-sheet tbody, .a4-sheet tr,
    .a4-paper .hdr, .a4-sheet .hdr,
    .a4-paper .sig-footer, .a4-sheet .sig-footer,
    .a4-paper .sig-tbl, .a4-sheet .sig-tbl,
    .a4-paper .sig-grid, .a4-sheet .sig-grid,
    .a4-paper .footer-qr, .a4-sheet .footer-qr {{
        direction: rtl !important;
    }}
    .a4-paper th, .a4-paper td, .a4-sheet th, .a4-sheet td {{
        text-align: right !important;
    }}
    .a4-paper .sig-tbl th, .a4-paper .sig-tbl td, .a4-sheet .sig-tbl th, .a4-sheet .sig-tbl td,
    .a4-paper .sig-cell, .a4-sheet .sig-cell, .a4-paper .sig-head, .a4-sheet .sig-head {{
        text-align: center !important;
    }}
    .toolbar {{
        max-width: 210mm; margin: 0 auto 8px auto; display: block;
        background: #0f3d2e; border: 1px solid #d4a853; padding: 10px; border-radius: 10px;
        box-sizing: border-box;
    }}
    .print-btn {{
        width: 100% !important; max-width: none !important; display: block; box-sizing: border-box;
        background: linear-gradient(135deg, #d4a853 0%, #a37a2c 100%); color: #fff; border: none;
        padding: 12px 18px; font-size: 15px; font-weight: 800; border-radius: 8px; cursor: pointer;
        text-align: center;
    }}
    .live-sig-dock {{
        max-width: 794px; margin: 0 auto 14px auto; background: #101820; border: 1px solid #1e6b50;
        border-radius: 12px; padding: 12px 14px 16px 14px;
    }}
    .live-sig-dock-head {{
        color: #f3cc7a; font-weight: 800; font-size: 13px; margin-bottom: 10px; text-align: center;
    }}
    .live-sig-dock-grid {{
        display:flex; flex-direction:column; gap:12px;
    }}
    .live-pad-card {{
        background: #0b1218; border: 1px solid #243041; border-radius: 10px; padding: 10px;
    }}
    .live-pad-title {{ color: #e2e8f0; font-weight: 800; font-size: 12.5px; margin-bottom: 2px; }}
    .live-pad-sub {{ color: #94a3b8; font-size: 11px; margin-bottom: 8px; }}
    .live-pad-canvas {{
        width: 100%; height: 220px; border: 1.5px dashed #0d47a1; border-radius: 8px;
        background: #f8fafc; display: block;
        touch-action: none !important;
        user-select: none !important;
        -webkit-user-select: none !important;
        -webkit-touch-callout: none !important;
        -ms-touch-action: none !important;
    }}
    .live-pad-actions {{ margin-top: 6px; text-align: center; }}
    .clear-sig-btn {{
        font-size: 11px; padding: 4px 12px; cursor: pointer; border-radius: 6px;
        border: 1px solid #475569; background: #1e293b; color: #e2e8f0;
    }}
    .sig-guide {{ border: 1px dashed #94a3b8; border-radius: 6px; padding: 4px; min-height: 48px; }}
    .sig-guide-hint, .sig-mode-note {{ display: none !important; }}
    .sig-person {{ font-size: 10.5px; font-weight: 800; margin-bottom: 2px; }}
    .sig-role {{ font-size: 10.5px; font-weight: 700; color: #000000 !important; margin-bottom: 3px; }}
    .sig-grid {{
        display: grid; margin-top: 10px; border: 1.4px solid #000000;
        page-break-inside: avoid; break-inside: avoid;
    }}
    .sig-cell {{
        border: 1.4px solid #000000 !important; text-align: center; padding: 12px 10px !important; min-height: 95px; line-height: 1.65 !important; color: #000000 !important;
    }}
    .sig-head {{
        background: #f1f5f3; color: #000000 !important; font-size: 13px; font-weight: 800; padding: 9px !important; line-height: 1.65 !important; border: 1.4px solid #000000 !important;
    }}
    .sig-grid .sig-person {{ font-size: 9px; }}
    .sig-grid .sig-role {{ font-size: 8.5px; }}
    .sig-grid .sig-slot-img, .sig-multi .sig-slot-img, .sig-tbl .sig-slot-img,
    img.sig-slot-img, #slot_duty, #slot_officer, #slot_citizen {{
        max-height: 50px !important; height: auto !important; max-width: 98% !important;
        width: auto !important; object-fit: contain !important; display: inline-block !important;
        background: #ffffff !important; mix-blend-mode: multiply !important;
        border: none !important; box-shadow: none !important; visibility: visible !important;
    }}
    td.sig-cell img.sig-slot-img, .sig-cell img.sig-slot-img {{
        background: #ffffff !important; mix-blend-mode: multiply !important;
    }}
    .sig-guide {{ background: #ffffff !important; }}
    .ios-print-hint {{
        display: none; margin: 8px auto; max-width: 210mm; padding: 10px 12px;
        background: #fef2f2; border: 1px solid #f87171; border-radius: 8px;
        color: #b91c1c; font-size: 13px; font-weight: 700; text-align: center;
    }}
    @media print {{
        .sig-tbl .sig-slot-img, .sig-grid .sig-slot-img, .sig-multi .sig-slot-img, img.sig-slot-img {{
            display: inline-block !important; visibility: visible !important; opacity: 1 !important;
            max-height: 50px !important; height: auto !important;
            background: #ffffff !important; mix-blend-mode: multiply !important;
            border: none !important; box-shadow: none !important;
            -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important;
        }}
    }}
    @media screen {{
        body {{ padding: 8px !important; overflow-x: hidden; }}
        .toolbar {{ width: 100%; padding: 8px; }}
        .print-btn {{ width: 100% !important; max-width: none !important; font-size: 14px; padding: 12px 14px; }}
        .a4-preview-viewport {{
            direction: rtl !important;
            width: 100% !important;
            overflow: auto !important;
            display: block !important;
            padding: 0 !important;
            margin: 0 !important;
            height: auto;
        }}
        .a4-page-frame {{
            direction: rtl !important;
            width: 210mm !important;
            height: 297mm !important;
            padding: 6mm 7mm !important;
            box-sizing: border-box !important;
            margin: 0 auto !important;
            overflow: hidden !important;
            background: #ffffff !important;
            position: relative !important;
            box-shadow: 0 12px 32px rgba(0,0,0,0.45);
            transform-origin: top center !important;
        }}
        .a4-sheet, .a4-paper {{
            direction: rtl !important;
            width: 100% !important;
            height: 285mm !important;
            min-height: 285mm !important;
            max-height: 285mm !important;
            box-sizing: border-box !important;
            margin: 0 auto !important;
            background: #ffffff !important;
            color: #000000 !important;
            padding: 0 !important;
            border: 1.8px solid #0f3d2e !important;
            border-radius: 4px !important;
            overflow: hidden !important;
            display: table !important;
            table-layout: fixed !important;
            box-shadow: none !important;
            transform-origin: top center !important;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
            color-adjust: exact !important;
        }}
        .a4-row {{ display: table-row !important; }}
        .a4-cell {{ display: table-cell !important; width: 100% !important; }}
        .a4-row-mid {{ height: 100% !important; }}
        .legal-wrap-cell {{ vertical-align: top !important; padding: 4px 0 !important; }}
        .sig-bottom-cell {{ vertical-align: bottom !important; padding: 0 !important; }}
        .a4-fit {{ display: contents !important; }}
        .a4-sheet, .a4-sheet p, .a4-sheet td, .a4-sheet th, .a4-sheet div, .a4-sheet span,
        .a4-paper, .a4-paper p, .a4-paper td, .a4-paper th, .a4-paper div, .a4-paper span {{
            color: #000000 !important;
            opacity: 1 !important;
        }}
        .a4-sheet .doc-banner, .a4-paper .doc-banner,
        .a4-sheet .doc-banner *, .a4-paper .doc-banner * {{
            color: #ffffff !important;
            background-color: #0f3d2e !important;
        }}
    }}
    @media only screen and (max-width: 820px) {{
        .a4-preview-viewport {{
            direction: rtl !important;
            width: 100% !important;
            overflow: auto !important;
            display: block !important;
            padding: 0 !important;
        }}
        .a4-page-frame {{
            width: 210mm !important;
            max-width: none !important;
            margin: 0 auto !important;
            transform-origin: top center !important;
        }}
        .a4-sheet, .a4-paper {{
            width: 100% !important;
            max-width: none !important;
            direction: rtl !important;
            margin: 0 auto !important;
            transform-origin: top center !important;
        }}
    }}
    .a4-fit {{ display: contents !important; }}
    .hdr, .header, .report-header {{
        display: flex !important;
        justify-content: space-between !important;
        align-items: center !important;
        width: 100% !important;
        gap: 0 !important;
        padding: 2px 0 8px 0 !important;
        margin-bottom: 8px !important;
        border-bottom: 2px solid #0f5132;
        box-sizing: border-box !important;
    }}
    .hdr > div:first-child,
    .hdr > div:last-child,
    .header > div:first-child,
    .header > div:last-child {{
        width: 38% !important;
        max-width: 38% !important;
        box-sizing: border-box !important;
    }}
    .hdr-right {{
        text-align: center !important; line-height: 1.38 !important;
        margin: 0 !important; padding: 0 8px 0 0 !important;
        width: 38% !important; max-width: 38% !important;
    }}
    .hdr-right p {{
        margin: 0 !important; padding: 0 !important;
        font-size: 12.5px !important; font-weight: 800 !important;
        line-height: 1.38 !important; color: #000000 !important;
        text-align: center !important;
    }}
    .hdr-center {{
        text-align: center; display: flex; justify-content: center; align-items: center;
        width: 24% !important; max-width: 24% !important;
        height: 80px; min-width: 80px; min-height: 80px;
        flex: 0 0 24% !important; margin: 0 auto; padding: 0 6px !important;
        background: transparent !important; border: none !important; border-radius: 0 !important; box-shadow: none !important;
    }}
    .hdr-center img, .hdr-logo {{
        width: 80px !important; height: 80px !important;
        max-width: 80px !important; max-height: 80px !important;
        object-fit: contain !important; display: block;
        margin: 0 auto; padding: 0 !important; border: none !important;
        background: transparent !important;
        -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important;
    }}
    .hdr-left, .hdr > div:last-child, .header > div:last-child {{
        direction: rtl !important;
        text-align: left !important;
        padding-right: 10px !important;
        padding-left: 6px !important;
        margin: 0 !important;
        line-height: 1.32 !important;
        width: 38% !important; max-width: 38% !important;
        box-sizing: border-box !important;
    }}
    .hdr-left p {{
        margin: 0 !important; padding: 0 !important;
        font-size: 11.5px !important; font-weight: 700 !important;
        line-height: 1.32 !important; color: #000000 !important;
        text-align: left !important;
        overflow-wrap: anywhere !important; word-break: break-word !important;
        white-space: normal !important;
    }}
    .hdr-left p.hdr-nowrap {{
        white-space: normal !important;
    }}
    .doc-banner {{
        background: #0f3d2e; color: #ffffff !important; text-align: center;
        padding: 10px 16px !important; border-radius: 6px; font-size: 16px !important; font-weight: 800;
        margin: 0 0 18px 0 !important;
        -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important;
    }}
    table.data-tbl td.lbl, table.sig-tbl th, .sig-head {{
        -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important;
    }}
    table.data-tbl {{
        width: 100% !important; border-collapse: collapse !important;
        table-layout: fixed !important; margin-bottom: 20px !important;
    }}
    .a4-paper, .a4-paper * {{
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
        color-adjust: exact !important;
    }}
    table.data-tbl th, table.data-tbl td {{
        border: 1px solid #1e293b !important; padding: 5px 8px !important;
        font-size: 12px !important; line-height: 1.45 !important; vertical-align: top;
        direction: rtl; text-align: right; color: #000000 !important; font-weight: 700 !important;
        white-space: normal !important; word-wrap: break-word !important;
        overflow-wrap: anywhere !important; word-break: break-word !important;
        overflow: hidden !important;
    }}
    table.data-tbl td.lbl {{ width: 20%; background: #f3f6f5 !important; font-weight: 800 !important; color: #000000 !important; }}
    table.data-tbl td.val {{
        width: 30%; background: #ffffff !important; color: #000000 !important; font-weight: 700 !important;
        white-space: normal !important; font-size: 12px !important;
        overflow-wrap: anywhere !important; word-break: break-word !important; overflow: hidden !important;
    }}
    table.data-tbl td.val.plate-val, table.data-tbl td.plate-val {{
        white-space: normal !important; overflow: hidden !important;
        word-break: break-word !important; overflow-wrap: anywhere !important;
    }}
    table.data-tbl .rtl-iso {{
        unicode-bidi: isolate; white-space: normal !important; display: inline !important;
        overflow-wrap: anywhere !important; word-break: break-word !important;
    }}
    table.data-tbl td span, table.data-tbl td b, table.data-tbl td strong,
    table.sig-tbl td span, table.sig-tbl td b, table.sig-tbl td strong {{
        white-space: normal !important; display: inline !important;
        overflow-wrap: anywhere !important; word-break: break-word !important;
    }}
    table.data-tbl.cols-4 td.lbl.half {{ width: 20%; }}
    table.data-tbl.cols-4 td.val.half {{ width: 30%; }}
    table.data-tbl.cols-4 td.lbl {{ width: 20%; }}
    table.data-tbl.cols-4 td.val.span3 {{ width: auto; }}
    .legal-box {{
        background: #ffffff !important; border: 1px solid #94a3b8; border-right: 4px solid #0f3d2e !important;
        border-radius: 4px; padding: 10px 12px !important; margin-bottom: 12px !important;
        font-size: 12.5px !important; line-height: 1.75 !important;
        text-align: justify !important; text-justify: inter-word !important; text-align-last: right !important;
        direction: rtl !important; width: 100% !important; max-width: 100% !important; box-sizing: border-box !important;
        overflow-wrap: break-word !important; word-break: normal !important; white-space: normal !important;
        word-spacing: normal !important; color: #000000 !important; font-weight: 700 !important;
    }}
    .legal-box > div:first-child {{ margin-bottom: 8px !important; font-weight: 800 !important; text-align: right !important; }}
    .legal-box div {{
        font-size: 12.5px !important; line-height: 1.75 !important; color: #000000 !important; font-weight: 700 !important;
        text-align: justify !important; text-justify: inter-word !important; text-align-last: right !important;
        direction: rtl !important; overflow-wrap: break-word !important; word-break: normal !important;
        white-space: normal !important; word-spacing: normal !important;
    }}
    .legal-box > div:first-child {{ text-align: right !important; }}
    table.sig-tbl {{
        table-layout: fixed !important; width: 100% !important;
        border-collapse: collapse; margin-top: 10px; text-align: center;
        page-break-inside: avoid; break-inside: avoid;
    }}
    table.sig-multi.cols-4 > tbody > tr:first-child > td {{ width: 25% !important; }}
    table.sig-multi .sig-person, table.sig-multi .sig-head, table.sig-multi .sig-role {{
        word-break: normal !important; overflow-wrap: break-word; white-space: normal;
    }}
    table.sig-tbl th {{ background: #f1f5f3; border: 1px solid #1e293b !important; padding: 8px !important; font-size: 12px; line-height: 1.45 !important; color: #000000 !important; font-weight: 800 !important; }}
    table.sig-tbl td {{ border: 1px solid #1e293b !important; padding: 8px 6px !important; width: {col_width}; vertical-align: middle; height: auto; min-height: 76px; line-height: 1.45 !important; color: #000000 !important; font-weight: 700 !important; }}
    .sig-person {{ color: #000000 !important; font-weight: 800 !important; }}
    .sig-role {{ color: #000000 !important; font-weight: 700 !important; }}
    .sig-head {{ color: #000000 !important; font-weight: 800 !important; border: 1.4px solid #000000 !important; }}
    .sig-cell {{ border: 1.4px solid #000000 !important; color: #000000 !important; }}
    .sig-footer {{
        display: flex; flex-direction: column; flex: 1 1 auto;
        page-break-inside: avoid; break-inside: avoid;
    }}
    .footer-qr {{
        margin-top: 8px !important;
        background: #f4f7f6; border: 1.4px solid #000000; border-radius: 6px;
        padding: 5px 8px !important; display: flex; flex-direction: row; justify-content: space-between; align-items: center;
        direction: rtl !important;
        width: 100% !important; max-width: 100% !important;
        box-sizing: border-box !important;
        page-break-inside: avoid; break-inside: avoid;
        color: #000000 !important; font-weight: 700 !important;
        overflow: hidden !important;
    }}
    .footer-qr > div:first-child {{
        flex: 1 1 auto; min-width: 0; text-align: right !important; padding-left: 8px !important;
    }}
    .footer-qr img {{
        flex: 0 0 auto; width: 42px !important; height: 42px !important;
        max-width: 42px !important; max-height: 42px !important;
        display: block !important;
    }}
    .attachment-section {{
        margin-top: 4px; border: 1px dashed #000000; border-radius: 6px; padding: 3px 6px;
        background: #f8fafc; page-break-inside: avoid; break-inside: avoid;
    }}
    .attachment-title {{
        font-size: 12px; font-weight: 800; color: #000000; margin-bottom: 2px; text-align: right;
    }}
    .attachment-grid {{
        display: flex; flex-wrap: nowrap; gap: 6px; align-items: center; overflow: hidden;
    }}
    .att-card {{ flex: 1 1 0; text-align: center; min-width: 0; }}
    .att-card img {{
        max-width: 100%; width: auto; height: auto; object-fit: contain;
        border: 1.4px solid #000000; border-radius: 4px; background: #fff; display: block; margin: 0 auto;
    }}
    .attachment-grid.atts-single .att-card img,
    .attachment-grid.atts-multi .att-card img {{
        max-height: 80px !important; height: auto !important;
    }}
    /* صور المرفقات ثابتة مضغوطة — لا تُكبَّر أبداً عبر expandLegal */
    .att-caption, .att-pdf-name {{ display: none !important; }}
    .att-pdf-card {{
        border: 1.4px solid #000000; border-radius: 4px; padding: 2px 6px; background: #fff;
        max-height: 75px; display: flex; align-items: center; justify-content: center; gap: 4px;
    }}
    .att-pdf-icon {{ font-size: 16px; line-height: 1; }}
    .att-pdf-note {{ font-size: 10px; color: #000000; font-weight: 700; }}
    .a4-sheet table a, .a4-sheet .legal-box a, a[href^="tel"] {{
        color: #000000 !important; text-decoration: none !important; pointer-events: none !important;
    }}
    /* a4-dense-print / a4-compact: لا تلمس padding الورقة — الإطار الفيزيائي يتحكم */
    .a4-compact, .a4-dense-print {{ padding: 0 !important; }}

    /* ===== إطار A4 فيزيائي ثابت + مستويات كثافة بايثون ===== */
    .a4-page-frame {{
        width: 210mm;
        height: 297mm;
        padding: 6mm 7mm;
        box-sizing: border-box;
        overflow: hidden;
        page-break-after: avoid !important;
        page-break-inside: avoid !important;
        break-after: avoid !important;
        break-inside: avoid !important;
        position: relative;
        background: #ffffff;
        margin: 0 auto;
    }}
    .a4-sheet, .a4-paper, .a4-page, .print-area {{
        width: 100% !important;
        height: 285mm !important;
        min-height: 285mm !important;
        max-height: 285mm !important;
        box-sizing: border-box !important;
        display: table !important;
        table-layout: fixed !important;
        border: 1.8px solid #0f3d2e !important;
        border-radius: 4px !important;
        background: #ffffff !important;
        margin: 0 auto !important;
        padding: 0 !important;
        overflow: hidden !important;
        page-break-after: avoid !important;
        page-break-inside: avoid !important;
    }}
    .a4-row {{ display: table-row !important; }}
    .a4-cell {{ display: table-cell !important; width: 100% !important; }}
    .a4-row-top {{ height: auto !important; }}
    .a4-row-mid {{ height: 100% !important; }}
    .a4-row-bot {{ height: auto !important; }}
    .a4-top-cell {{ vertical-align: top !important; padding: 3mm 3.5mm 0 3.5mm !important; }}
    .legal-wrap-cell {{
        vertical-align: top !important;
        padding: 2mm 3.5mm !important;
    }}
    .sig-bottom-cell {{
        vertical-align: bottom !important;
        padding: 0 3.5mm 3mm 3.5mm !important;
    }}
    .sig-footer {{ width: 100% !important; }}

    /* spacious */
    .a4-tier-spacious .hdr-center, .a4-tier-spacious .hdr-center img, .a4-tier-spacious .hdr-logo {{
        width: 86px !important; height: 86px !important; max-width: 86px !important; max-height: 86px !important;
        min-width: 86px !important; min-height: 86px !important;
    }}
    .a4-tier-spacious .hdr-right p {{ font-size: 13px !important; line-height: 1.42 !important; }}
    .a4-tier-spacious .hdr-left p {{ font-size: 12.5px !important; line-height: 1.4 !important; }}
    .a4-tier-spacious .doc-banner {{
        font-size: 16px !important; padding: 9px 14px !important; margin: 10px 0 14px !important;
    }}
    .a4-tier-spacious table.data-tbl {{ margin-bottom: 12px !important; }}
    .a4-tier-spacious table.data-tbl th, .a4-tier-spacious table.data-tbl td {{
        font-size: 13.5px !important; line-height: 1.65 !important; padding: 10px 12px !important;
    }}
    .a4-tier-spacious .legal-box, .a4-tier-spacious .legal-box .legal-body, .a4-tier-spacious .legal-box .legal-title {{
        font-size: 15px !important; line-height: 2.1 !important;
    }}
    .a4-tier-spacious .legal-box {{
        padding: 18px !important; margin: 4px 0 10px !important;
    }}
    .a4-tier-spacious .legal-title {{ margin-bottom: 10px !important; }}
    .a4-tier-spacious table.sig-tbl td, .a4-tier-spacious .sig-cell {{
        height: 105px !important; min-height: 105px !important; padding: 10px 8px !important; font-size: 13px !important;
    }}
    .a4-tier-spacious table.sig-tbl th, .a4-tier-spacious .sig-head {{
        padding: 8px !important; font-size: 13px !important;
    }}
    .a4-tier-spacious img.sig-slot-img {{ max-height: 56px !important; }}
    .a4-tier-spacious .footer-qr {{ padding: 8px 10px !important; margin-top: 8px !important; }}

    /* balanced */
    .a4-tier-balanced .hdr-center, .a4-tier-balanced .hdr-center img, .a4-tier-balanced .hdr-logo {{
        width: 76px !important; height: 76px !important; max-width: 76px !important; max-height: 76px !important;
        min-width: 76px !important; min-height: 76px !important;
    }}
    .a4-tier-balanced .hdr-right p {{ font-size: 12.5px !important; }}
    .a4-tier-balanced .doc-banner {{
        font-size: 14.5px !important; padding: 7px 12px !important; margin: 8px 0 10px !important;
    }}
    .a4-tier-balanced table.data-tbl {{ margin-bottom: 8px !important; }}
    .a4-tier-balanced table.data-tbl th, .a4-tier-balanced table.data-tbl td {{
        font-size: 12.5px !important; line-height: 1.5 !important; padding: 6px 9px !important;
    }}
    .a4-tier-balanced .legal-box, .a4-tier-balanced .legal-box .legal-body, .a4-tier-balanced .legal-box .legal-title {{
        font-size: 13px !important; line-height: 1.75 !important;
    }}
    .a4-tier-balanced .legal-box {{
        padding: 12px 14px !important; margin: 4px 0 8px !important;
    }}
    .a4-tier-balanced table.sig-tbl td, .a4-tier-balanced .sig-cell {{
        height: 78px !important; min-height: 78px !important; padding: 7px 6px !important; font-size: 12px !important;
    }}
    .a4-tier-balanced img.sig-slot-img {{ max-height: 48px !important; }}
    .a4-tier-balanced .footer-qr {{ padding: 6px 8px !important; margin-top: 6px !important; }}

    /* dense */
    .a4-tier-dense .hdr-center, .a4-tier-dense .hdr-center img, .a4-tier-dense .hdr-logo,
    .a4-dense-print .hdr-center, .a4-dense-print .hdr-center img, .a4-dense-print .hdr-logo {{
        width: 66px !important; height: 66px !important; max-width: 66px !important; max-height: 66px !important;
        min-width: 66px !important; min-height: 66px !important;
    }}
    .a4-tier-dense .hdr-right p, .a4-dense-print .hdr-right p {{ font-size: 11.5px !important; }}
    .a4-tier-dense .doc-banner, .a4-dense-print .doc-banner {{
        font-size: 13px !important; padding: 5px 10px !important; margin: 4px 0 6px !important;
    }}
    .a4-tier-dense table.data-tbl, .a4-dense-print table.data-tbl {{ margin-bottom: 5px !important; }}
    .a4-tier-dense table.data-tbl th, .a4-tier-dense table.data-tbl td,
    .a4-dense-print table.data-tbl th, .a4-dense-print table.data-tbl td {{
        font-size: 11px !important; line-height: 1.35 !important; padding: 3.5px 6px !important;
    }}
    .a4-tier-dense .legal-box, .a4-tier-dense .legal-box .legal-body, .a4-tier-dense .legal-box .legal-title,
    .a4-dense-print .legal-box, .a4-dense-print .legal-box .legal-body, .a4-dense-print .legal-box .legal-title {{
        font-size: 11.5px !important; line-height: 1.45 !important;
    }}
    .a4-tier-dense .legal-box, .a4-dense-print .legal-box {{
        padding: 7px 10px !important; margin: 2px 0 5px !important;
    }}
    .a4-tier-dense table.sig-tbl td, .a4-tier-dense .sig-cell,
    .a4-dense-print table.sig-tbl td, .a4-dense-print .sig-cell {{
        height: 54px !important; min-height: 54px !important; padding: 4px 5px !important; font-size: 11px !important;
    }}
    .a4-tier-dense img.sig-slot-img, .a4-dense-print img.sig-slot-img {{ max-height: 40px !important; }}
    .a4-tier-dense .footer-qr, .a4-dense-print .footer-qr {{
        padding: 4px 7px !important; margin-top: 4px !important;
    }}
    .a4-tier-dense .a4-top-cell {{ padding: 2mm 2.5mm 0 2.5mm !important; }}
    .a4-tier-dense .legal-wrap-cell {{ padding: 1mm 2.5mm !important; }}
    .a4-tier-dense .sig-bottom-cell {{ padding: 0 2.5mm 2mm 2.5mm !important; }}

    @media print {{
        /* لا تثبت 297mm: US Letter على الآيفون = 279.4mm فقط مع هوامش AirPrint */
        @page {{ margin: 5mm 6mm !important; }}
        html, body {{
            width: 100% !important;
            height: auto !important;
            margin: 0 !important;
            padding: 0 !important;
            overflow: hidden !important;
            background: #ffffff !important;
            direction: rtl !important;
            text-align: right !important;
            transform: none !important;
        }}
        .a4-preview-viewport, .a4-preview-wrapper {{
            margin: 0 !important; padding: 0 !important; width: 100% !important; height: auto !important;
            overflow: hidden !important; background: #ffffff !important; direction: rtl !important;
        }}
        .toolbar, .no-print, .zoom-bar, .live-sig-dock, .clear-sig-btn, .sig-guide-hint, .sig-mode-note,
        .live-pad-actions, .live-sig-dock-head, .ios-print-hint {{ display: none !important; }}
        .sig-guide, .sig-guide-print-clean {{
            border: none !important; padding: 0 !important; margin: 0 !important; background: transparent !important;
        }}
        .live-pad-canvas {{ display: none !important; border: none !important; }}

        /* قاعدة آمنة افتراضية = سقف الآيفون (US Letter) */
        .a4-page-frame {{
            width: 100% !important;
            max-width: 100% !important;
            height: 254mm !important;
            max-height: 254mm !important;
            min-height: 0 !important;
            padding: 4mm 5mm !important;
            box-sizing: border-box !important;
            overflow: hidden !important;
            margin: 0 auto !important;
            position: relative !important;
            background: #ffffff !important;
            page-break-after: avoid !important;
            page-break-inside: avoid !important;
            break-after: avoid !important;
            break-inside: avoid !important;
            box-shadow: none !important;
        }}
        html.a4-print-desktop .a4-page-frame, body.a4-print-desktop .a4-page-frame {{
            height: 276mm !important;
            max-height: 276mm !important;
        }}
        .a4-sheet, .a4-paper, .a4-page, .print-area, .report-container {{
            direction: rtl !important;
            transform: none !important;
            width: 100% !important;
            max-width: 100% !important;
            height: 945px !important;
            min-height: 0 !important;
            max-height: 945px !important;
            margin: 0 auto !important;
            display: table !important;
            table-layout: fixed !important;
            box-sizing: border-box !important;
            page-break-after: avoid !important;
            break-after: avoid !important;
            page-break-inside: avoid !important;
            break-inside: avoid !important;
            box-shadow: none !important;
            border: 1.8px solid #0f3d2e !important;
            border-radius: 4px !important;
            overflow: hidden !important;
            background: #ffffff !important;
            padding: 0 !important;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
            color-adjust: exact !important;
        }}
        html.a4-print-desktop .a4-sheet, html.a4-print-desktop .a4-paper,
        body.a4-print-desktop .a4-sheet, body.a4-print-desktop .a4-paper {{
            height: 1035px !important;
            max-height: 1035px !important;
        }}
        .a4-row {{ display: table-row !important; }}
        .a4-cell {{ display: table-cell !important; width: 100% !important; }}
        .a4-row-mid {{ height: 100% !important; }}
        .legal-wrap-cell {{ vertical-align: top !important; }}
        .sig-bottom-cell {{ vertical-align: bottom !important; }}
        .a4-paper, .a4-paper *, .a4-sheet, .a4-sheet * {{
            color: #000000 !important; opacity: 1 !important;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
            color-adjust: exact !important;
        }}
        .a4-paper .doc-banner, .a4-paper .doc-banner *,
        .a4-sheet .doc-banner, .a4-sheet .doc-banner * {{
            color: #ffffff !important;
            background-color: #0f3d2e !important;
        }}
        .a4-paper table.data-tbl, .a4-sheet table.data-tbl,
        .a4-paper table.sig-tbl, .a4-sheet table.sig-tbl {{
            width: 100% !important; border-collapse: collapse !important; table-layout: fixed !important;
        }}
        .a4-paper table.data-tbl th, .a4-paper table.data-tbl td,
        .a4-sheet table.data-tbl th, .a4-sheet table.data-tbl td,
        .a4-paper table.sig-tbl th, .a4-paper table.sig-tbl td,
        .a4-sheet table.sig-tbl th, .a4-sheet table.sig-tbl td {{
            border: 1px solid #1e293b !important;
            white-space: normal !important;
            overflow-wrap: anywhere !important;
            word-break: break-word !important;
        }}
        .a4-paper table.data-tbl td.lbl, .a4-sheet table.data-tbl td.lbl {{
            width: 20% !important; background: #f3f6f5 !important;
        }}
        .a4-paper table.data-tbl td.val, .a4-sheet table.data-tbl td.val {{
            width: 30% !important; background: #ffffff !important;
        }}
        .a4-paper .legal-box, .a4-sheet .legal-box {{
            background: #ffffff !important;
            border: 1px solid #94a3b8 !important;
            border-right: 4px solid #0f3d2e !important;
            text-align: justify !important; text-align-last: right !important;
            direction: rtl !important; white-space: normal !important;
        }}
        .a4-paper .hdr, .a4-sheet .hdr {{
            display: flex !important; justify-content: space-between !important; align-items: center !important;
            width: 100% !important; border-bottom: 2px solid #0f5132 !important;
            page-break-inside: avoid !important;
        }}
        .a4-paper .hdr-left, .a4-sheet .hdr-left {{
            width: 38% !important; max-width: 38% !important;
            direction: rtl !important; text-align: left !important;
            padding-right: 10px !important; padding-left: 6px !important;
            box-sizing: border-box !important;
        }}
        .signatures, .sig-footer, table.sig-tbl, .sig-grid, .footer-qr, .attachment-section {{
            page-break-inside: avoid !important; break-inside: avoid !important;
        }}
        .a4-paper .footer-qr, .a4-sheet .footer-qr, .footer-qr {{
            width: 100% !important; max-width: 100% !important;
            box-sizing: border-box !important; overflow: hidden !important;
        }}
        a, a[href^="tel"] {{
            color: #000000 !important; text-decoration: none !important; pointer-events: none !important;
        }}
    }}
</style>
</head>
<body>
    <div id="iosPrintHint" class="ios-print-hint no-print">
        للطباعة أو حفظ PDF على الآيفون: افتح الرابط في متصفح Safari عبر أيقونة البوصلة بالأسفل
    </div>
    <div class="toolbar no-print">
        <button class="print-btn" type="button" id="printOfficialBtn">🖨️ طباعة الوثيقة الرسمية / حفظ ومشاركة A4 PDF</button>
    </div>

    {live_dock_html}

    <div class="a4-preview-viewport" id="a4PreviewViewport">
    <div id="a4PageFrame" class="a4-page-frame" data-a4-tier="{tier}">
    <div class="{sheet_cls}" id="a4Sheet" data-print-root="1" data-a4-tier="{tier}">
        <div class="a4-row a4-row-top">
            <div class="a4-cell a4-top-cell">
                <div class="hdr">
                    <div class="hdr-right">
                        <p>المملكة العربية السعودية</p>
                        <p>وزارة الداخلية</p>
                        <p>الأمن العام - الإدارة العامة للمرور</p>
                        <p>إدارة مرور منطقة جازان</p>
                        <p>قسم مرور العارضة</p>
                    </div>
                    <div class="hdr-center">
                        {center_logo_html}
                    </div>
                    <div class="hdr-left">
                        <p class="hdr-nowrap">الرقم المرجعي: {html.escape(str(rec.get('doc_no') or '').strip())}</p>
                        <p class="hdr-nowrap">التاريخ والوقت: {rec['created_at']}</p>
                        {gps_line_html}
                    </div>
                </div>
                <div class="doc-banner">{banner_title}</div>
                <table class="{data_tbl_cls}">{rows_html}</table>
            </div>
        </div>
        <div class="a4-row a4-row-mid">
            <div class="a4-cell legal-wrap-cell">
                <div class="legal-box" dir="rtl">
                    <div class="legal-title" dir="rtl">{legal_box_title}</div>
                    <div class="legal-body" dir="rtl">&#8207;{cleaned_legal_text}</div>
                </div>
                {attachment_block}
            </div>
        </div>
        <div class="a4-row a4-row-bot">
            <div class="a4-cell sig-bottom-cell">
                <div class="sig-footer">
                    {sig_table_html}
                    <div class="footer-qr">
                        <div>
                            <div style="font-size:10.5px; font-weight:800; color:#000000;">
                                وثيقة رسمية مقفلة إلكترونياً ضد الكشط أو التعديل اليدوي — قسم مرور العارضة.
                            </div>
                            <div style="font-size:10px; font-weight:700; color:#000000;">ختم التحقق الرقمي (SHA-256 Seal): {rec['verify_hash']}</div>
                        </div>
                        <img src="data:image/png;base64,{qr_b64}" style="width:42px; height:42px;" />
                    </div>
                </div>
            </div>
        </div>
    </div>
    </div>
</div>
<script>
    const PEN_COLOR = '#0d47a1';
    const LIVE_PADS = {json.dumps(live_pad_ids, ensure_ascii=False)};
    const PRELOADED_SIGS = {json.dumps(preloaded_live_sigs, ensure_ascii=False)};
    const DOC_SIG_KEY = {json.dumps(
        f"{rec.get('form_id') or 'form'}_{rec.get('auto_doc_no') or rec.get('doc_no') or 'doc'}",
        ensure_ascii=False,
    )};
    window.__memPads = window.__memPads || {{}};

    function padStorageKey(padId) {{
        return 'khafar_pad_' + DOC_SIG_KEY + '_' + padId;
    }}
    function padStoreGet(key) {{
        try {{
            var v = localStorage.getItem(key);
            if (v) return v;
        }} catch (e) {{}}
        try {{
            var s = sessionStorage.getItem(key);
            if (s) return s;
        }} catch (e2) {{}}
        return window.__memPads[key] || '';
    }}
    function padStoreSet(key, val) {{
        window.__memPads[key] = val || '';
        try {{ localStorage.setItem(key, val || ''); }} catch (e) {{}}
        try {{ sessionStorage.setItem(key, val || ''); }} catch (e2) {{}}
    }}
    function padStoreDel(key) {{
        try {{ delete window.__memPads[key]; }} catch (e) {{}}
        try {{ localStorage.removeItem(key); }} catch (e2) {{}}
        try {{ sessionStorage.removeItem(key); }} catch (e3) {{}}
    }}

    // مزامنة محلية فقط داخل نفس إطار HTML — بدون postMessage / بدون Streamlit rerun / بدون كيبورد
    function syncPadToSlot(padId) {{
        const canvas = document.getElementById('pad_' + padId);
        let slot = document.getElementById('slot_' + padId);
        if (!canvas) return;
        if (!slot) {{
            try {{ slot = document.querySelector('img.sig-slot-img#slot_' + padId) || document.querySelector('#slot_' + padId); }} catch (e) {{}}
        }}
        if (!slot) return;
        const blank = document.createElement('canvas');
        blank.width = canvas.width; blank.height = canvas.height;
        const empty = canvas.toDataURL() === blank.toDataURL();
        if (empty) {{
            slot.removeAttribute('src');
            slot.style.display = 'none';
            padStoreDel(padStorageKey(padId));
            return;
        }}
        // خلفية بيضاء صافية + حبر أزرق داكن واضح عند التصدير للطباعة
        const out = document.createElement('canvas');
        out.width = canvas.width;
        out.height = canvas.height;
        const octx = out.getContext('2d');
        octx.fillStyle = '#ffffff';
        octx.fillRect(0, 0, out.width, out.height);
        octx.drawImage(canvas, 0, 0);
        const dataUrl = out.toDataURL('image/png');
        slot.src = dataUrl;
        slot.style.display = 'inline-block';
        slot.style.background = '#ffffff';
        try {{
          const b64 = (dataUrl.split(',')[1] || '');
          if (b64) padStoreSet(padStorageKey(padId), b64);
        }} catch (e) {{}}
    }}

    function wireLivePad(padId) {{
        const canvas = document.getElementById('pad_' + padId);
        if (!canvas) return;
        try {{
            canvas.style.touchAction = 'none';
            canvas.style.userSelect = 'none';
            canvas.style.webkitUserSelect = 'none';
            canvas.setAttribute('tabindex', '-1');
        }} catch (e) {{}}
        const ctx = canvas.getContext('2d');
        const dpr = Math.max(window.devicePixelRatio || 1, 1);
        if (!canvas.dataset.dprReady) {{
            const rect = canvas.getBoundingClientRect();
            const displayW = Math.max(rect.width || canvas.width || 900, 1);
            const displayH = Math.max(rect.height || canvas.height || 220, 1);
            canvas.width = Math.round(displayW * dpr);
            canvas.height = Math.round(displayH * dpr);
            canvas.style.width = displayW + 'px';
            canvas.style.height = displayH + 'px';
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            canvas.dataset.dprReady = '1';
        }}
        ctx.strokeStyle = PEN_COLOR;
        ctx.lineWidth = 2.8;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        let drawing = false;
        const getPt = (e) => {{
            const r = canvas.getBoundingClientRect();
            let src = e;
            if (e.touches && e.touches.length) src = e.touches[0];
            else if (e.changedTouches && e.changedTouches.length) src = e.changedTouches[0];
            else if (typeof e.clientX === 'number') src = e;
            // إحداثيات CSS ثابتة مع setTransform(dpr)
            return {{
                x: (src.clientX - r.left),
                y: (src.clientY - r.top)
            }};
        }};
        const startDraw = (e) => {{
            if (e.cancelable) e.preventDefault();
            e.stopPropagation();
            drawing = true;
            const p = getPt(e);
            ctx.beginPath();
            ctx.moveTo(p.x, p.y);
            ctx.lineTo(p.x + 0.1, p.y + 0.1);
            ctx.stroke();
        }};
        const moveDraw = (e) => {{
            if (!drawing) return;
            if (e.cancelable) e.preventDefault();
            e.stopPropagation();
            const p = getPt(e);
            ctx.lineTo(p.x, p.y);
            ctx.stroke();
        }};
        const endDraw = (e) => {{
            if (e && e.cancelable) e.preventDefault();
            if (!drawing) {{
                syncPadToSlot(padId);
                return;
            }}
            drawing = false;
            syncPadToSlot(padId);
        }};
        canvas.addEventListener('pointerdown', startDraw, {{ passive: false }});
        canvas.addEventListener('pointermove', moveDraw, {{ passive: false }});
        canvas.addEventListener('pointerup', endDraw, {{ passive: false }});
        canvas.addEventListener('pointercancel', endDraw, {{ passive: false }});
        canvas.addEventListener('mousedown', startDraw);
        canvas.addEventListener('mousemove', moveDraw);
        window.addEventListener('mouseup', endDraw);
        canvas.addEventListener('touchstart', startDraw, {{ passive: false }});
        canvas.addEventListener('touchmove', moveDraw, {{ passive: false }});
        canvas.addEventListener('touchend', endDraw, {{ passive: false }});
        canvas.addEventListener('touchcancel', endDraw, {{ passive: false }});
        canvas.addEventListener('pointerdown', function(ev) {{
            try {{ if (canvas.setPointerCapture) canvas.setPointerCapture(ev.pointerId); }} catch (e) {{}}
        }}, {{ passive: false }});
    }}

    function clearLivePad(padId) {{
        const canvas = document.getElementById('pad_' + padId);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        ctx.save();
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.restore();
        syncPadToSlot(padId);
    }}

    LIVE_PADS.forEach(wireLivePad);

    function restoreLivePad(padId, b64) {{
        if (!padId || !b64) return;
        const canvas = document.getElementById('pad_' + padId);
        if (!canvas) return;
        const img = new Image();
        img.onload = function() {{
            try {{
                const ctx = canvas.getContext('2d');
                const dpr = Math.max(window.devicePixelRatio || 1, 1);
                ctx.save();
                ctx.setTransform(1, 0, 0, 1, 0, 0);
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.restore();
                ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
                const w = canvas.width / dpr;
                const h = canvas.height / dpr;
                ctx.drawImage(img, 0, 0, w, h);
                syncPadToSlot(padId);
            }} catch (e) {{}}
        }};
        img.src = 'data:image/png;base64,' + b64;
    }}
    (LIVE_PADS || []).forEach(function(padId) {{
        var b64 = padStoreGet(padStorageKey(padId));
        if (!b64 && PRELOADED_SIGS && PRELOADED_SIGS[padId]) b64 = PRELOADED_SIGS[padId];
        if (b64) restoreLivePad(padId, b64);
    }});

    const IS_IOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
        || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    try {{ window.__khafarIsIOS = IS_IOS; }} catch (eIOS) {{}}

    function getPrintHeightTargets(win) {{
        const w = win || window;
        let ios = false;
        try {{
            ios = !!(w.__khafarIsIOS)
                || /iPad|iPhone|iPod/.test(w.navigator.userAgent)
                || (w.navigator.platform === "MacIntel" && w.navigator.maxTouchPoints > 1);
        }} catch (e) {{
            ios = IS_IOS;
        }}
        // TARGET_H_PX: سقف محتوى الورقة الداخلي (الجدول الخارجي)
        // FRAME: الغلاف الفيزيائي الآمن لـ US Letter / A4
        return {{
            isIOS: ios,
            TARGET_H_PX: ios ? 945 : 1035,
            FRAME_H_PX: ios ? 960 : 1040,
            FRAME_H_MM: ios ? "254mm" : "276mm"
        }};
    }}

    function applyPrintPhysicalSize(rootDoc, forPrint) {{
        const doc = rootDoc || document;
        const win = doc.defaultView || window;
        const t = getPrintHeightTargets(win);
        const frame = doc.getElementById("a4PageFrame") || doc.querySelector(".a4-page-frame");
        const sheet = doc.getElementById("a4Sheet")
            || doc.querySelector(".a4-sheet")
            || doc.querySelector(".a4-paper");
        try {{
            const rootEl = doc.documentElement;
            const bodyEl = doc.body;
            if (t.isIOS) {{
                if (rootEl) rootEl.classList.remove("a4-print-desktop");
                if (bodyEl) bodyEl.classList.remove("a4-print-desktop");
                if (rootEl) rootEl.classList.add("a4-print-ios");
                if (bodyEl) bodyEl.classList.add("a4-print-ios");
            }} else {{
                if (rootEl) rootEl.classList.remove("a4-print-ios");
                if (bodyEl) bodyEl.classList.remove("a4-print-ios");
                if (rootEl) rootEl.classList.add("a4-print-desktop");
                if (bodyEl) bodyEl.classList.add("a4-print-desktop");
            }}
        }} catch (eCls) {{}}
        if (frame) {{
            try {{
                frame.style.setProperty("width", "100%", "important");
                frame.style.setProperty("max-width", "100%", "important");
                frame.style.setProperty("height", (forPrint ? t.FRAME_H_MM : t.FRAME_H_PX + "px"), "important");
                frame.style.setProperty("max-height", (forPrint ? t.FRAME_H_MM : t.FRAME_H_PX + "px"), "important");
                frame.style.setProperty("min-height", "0", "important");
                frame.style.setProperty("overflow", "hidden", "important");
                frame.style.setProperty("page-break-after", "avoid", "important");
                frame.style.setProperty("page-break-inside", "avoid", "important");
                frame.style.setProperty("box-sizing", "border-box", "important");
                frame.style.setProperty("margin", "0 auto", "important");
            }} catch (eF) {{}}
        }}
        if (sheet) {{
            try {{
                sheet.style.setProperty("width", "100%", "important");
                sheet.style.setProperty("max-width", "100%", "important");
                sheet.style.setProperty("height", t.TARGET_H_PX + "px", "important");
                sheet.style.setProperty("min-height", "0", "important");
                sheet.style.setProperty("max-height", t.TARGET_H_PX + "px", "important");
                sheet.style.setProperty("overflow", "hidden", "important");
                sheet.style.setProperty("margin-left", "auto", "important");
                sheet.style.setProperty("margin-right", "auto", "important");
                sheet.style.setProperty("box-sizing", "border-box", "important");
                sheet.style.setProperty("page-break-after", "avoid", "important");
                sheet.style.setProperty("page-break-inside", "avoid", "important");
            }} catch (eS) {{}}
        }}
        return t;
    }}

    function stepDownFitA4(rootDoc) {{
        const doc = rootDoc || document;
        const frame = doc.getElementById("a4PageFrame") || doc.querySelector(".a4-page-frame");
        const sheet = doc.getElementById("a4Sheet")
            || doc.querySelector(".a4-sheet")
            || doc.querySelector(".a4-paper");
        if (!sheet) return 0;
        const t = getPrintHeightTargets(doc.defaultView || window);
        const TARGET_H_PX = t.TARGET_H_PX;

        try {{
            sheet.style.removeProperty("zoom");
            sheet.style.setProperty("transform", "none", "important");
            sheet.style.setProperty("width", "100%", "important");
            sheet.style.setProperty("max-width", "100%", "important");
            sheet.style.setProperty("margin-left", "auto", "important");
            sheet.style.setProperty("margin-right", "auto", "important");
            sheet.style.setProperty("box-sizing", "border-box", "important");
        }} catch (e) {{}}

        // قياس الارتفاع الطبيعي بدون قصّ
        try {{
            sheet.style.setProperty("height", "auto", "important");
            sheet.style.setProperty("min-height", "0", "important");
            sheet.style.setProperty("max-height", "none", "important");
            sheet.style.setProperty("overflow", "visible", "important");
        }} catch (e2) {{}}

        function bumpDown(node, fontDelta, padDelta) {{
            if (!node || !node.style) return;
            try {{
                const cs = (doc.defaultView || window).getComputedStyle(node);
                const fs = parseFloat(cs.fontSize) || 0;
                if (fs > 8.5) {{
                    node.style.setProperty("font-size", Math.max(8.5, fs - fontDelta).toFixed(2) + "px", "important");
                }}
                const pt = parseFloat(cs.paddingTop) || 0;
                const pb = parseFloat(cs.paddingBottom) || 0;
                if (pt > 1 || pb > 1) {{
                    node.style.setProperty("padding-top", Math.max(1, pt - padDelta).toFixed(2) + "px", "important");
                    node.style.setProperty("padding-bottom", Math.max(1, pb - padDelta).toFixed(2) + "px", "important");
                }}
                const mt = parseFloat(cs.marginTop) || 0;
                const mb = parseFloat(cs.marginBottom) || 0;
                if (mt > 1) node.style.setProperty("margin-top", Math.max(0, mt - Math.min(padDelta, 0.6)).toFixed(2) + "px", "important");
                if (mb > 1) node.style.setProperty("margin-bottom", Math.max(0, mb - Math.min(padDelta, 0.6)).toFixed(2) + "px", "important");
                const lh = parseFloat(cs.lineHeight);
                if (!isNaN(lh) && lh > 12) {{
                    node.style.setProperty("line-height", Math.max(11, lh - fontDelta * 0.8).toFixed(2) + "px", "important");
                }}
            }} catch (e4) {{}}
        }}

        function shrinkOnce() {{
            const targets = sheet.querySelectorAll(
                ".legal-box, .legal-box .legal-body, .legal-box .legal-title, .legal-box div,"
                + "table.data-tbl th, table.data-tbl td,"
                + "table.sig-tbl th, table.sig-tbl td, .sig-cell, .sig-head, .sig-person, .sig-role,"
                + ".doc-banner, .footer-qr, .footer-qr div, .hdr-right p, .hdr-left p,"
                + ".a4-top-cell, .legal-wrap-cell, .sig-bottom-cell, .attachment-section, .attachment-title"
            );
            targets.forEach(function(el) {{ bumpDown(el, 0.4, 1); }});
            try {{
                const logos = sheet.querySelectorAll(".hdr-center img, .hdr-logo, img.sig-slot-img");
                logos.forEach(function(img) {{
                    const cs = (doc.defaultView || window).getComputedStyle(img);
                    const h = parseFloat(cs.height) || parseFloat(img.style.maxHeight) || 0;
                    if (h > 28) {{
                        const nh = Math.max(28, h - 2);
                        img.style.setProperty("height", nh + "px", "important");
                        img.style.setProperty("width", nh + "px", "important");
                        img.style.setProperty("max-height", nh + "px", "important");
                        img.style.setProperty("max-width", nh + "px", "important");
                    }}
                }});
            }} catch (e5) {{}}
        }}

        let step = 0;
        void sheet.offsetHeight;
        while ((sheet.scrollHeight > TARGET_H_PX) && step < 10) {{
            shrinkOnce();
            void sheet.offsetHeight;
            step += 1;
        }}

        // أقفل على السقف الدقيق للجهاز
        applyPrintPhysicalSize(doc, true);
        if (frame) {{
            try {{ frame.style.setProperty("overflow", "hidden", "important"); }} catch (e6) {{}}
        }}
        return step;
    }}

    function expandLegalToFillSpace(rootDoc) {{
        const doc = rootDoc || document;
        const sheet = doc.getElementById("a4Sheet")
            || doc.querySelector(".a4-sheet")
            || doc.querySelector(".a4-paper");
        if (!sheet) return 0;
        const legal = sheet.querySelector(".legal-box");
        if (!legal) return 0;
        const win = doc.defaultView || window;
        const t = getPrintHeightTargets(win);
        const TARGET_H_PX = t.TARGET_H_PX;

        // امسح أي قيود سطرية على حجم الخط / تباعد الأسطر من الصندوق ونصه
        try {{
            [legal].concat(Array.from(legal.querySelectorAll(".legal-title, .legal-body, div"))).forEach(function(el) {{
                try {{
                    el.style.removeProperty("font-size");
                    el.style.removeProperty("line-height");
                    el.style.removeProperty("padding");
                    el.style.removeProperty("margin");
                }} catch (clr) {{}}
            }});
        }} catch (eClr) {{}}

        function blockH(el) {{
            if (!el) return 0;
            try {{
                const cs = win.getComputedStyle(el);
                const mt = parseFloat(cs.marginTop) || 0;
                const mb = parseFloat(cs.marginBottom) || 0;
                return (el.offsetHeight || el.getBoundingClientRect().height || 0) + mt + mb;
            }} catch (e) {{
                return el.offsetHeight || 0;
            }}
        }}

        function measureUsedH() {{
            // مجموع ارتفاعات الكتل الفعلية فقط (بدون الاعتماد على scrollHeight للحاوية الثابتة)
            let sum = 0;
            const topCell = sheet.querySelector(".a4-top-cell");
            if (topCell) {{
                sum += blockH(topCell);
            }} else {{
                sum += blockH(sheet.querySelector(".hdr"));
                sum += blockH(sheet.querySelector(".doc-banner"));
                sum += blockH(sheet.querySelector("table.data-tbl"));
            }}
            sum += blockH(legal);
            sum += blockH(sheet.querySelector(".attachment-section"));
            const sig = sheet.querySelector(".sig-footer") || sheet.querySelector(".sig-bottom-cell");
            sum += blockH(sig);
            return sum;
        }}

        function freeSpace() {{
            return TARGET_H_PX - measureUsedH();
        }}

        function currentLegalMetrics() {{
            const cs = win.getComputedStyle(legal);
            const fs = parseFloat(cs.fontSize) || 12;
            let lhRatio = NaN;
            const lhRaw = cs.lineHeight;
            if (lhRaw && lhRaw !== "normal") {{
                const lhPx = parseFloat(lhRaw);
                if (!isNaN(lhPx) && fs > 0) lhRatio = lhPx / fs;
            }}
            if (isNaN(lhRatio) || lhRatio < 1.05) lhRatio = 1.6;
            return {{
                fs: fs,
                lh: lhRatio,
                pt: parseFloat(cs.paddingTop) || 0,
                pr: parseFloat(cs.paddingRight) || 0,
                pb: parseFloat(cs.paddingBottom) || 0,
                pl: parseFloat(cs.paddingLeft) || 0,
                mt: parseFloat(cs.marginTop) || 0,
                mb: parseFloat(cs.marginBottom) || 0
            }};
        }}

        function applyLegalMetrics(m) {{
            const padY = Math.min(20, Math.max(m.pt, m.pb));
            const padX = Math.min(22, Math.max(m.pr, m.pl));
            const marY = Math.min(14, Math.max(m.mt, m.mb, 0));
            legal.style.setProperty("font-size", m.fs.toFixed(2) + "px", "important");
            legal.style.setProperty("line-height", m.lh.toFixed(3), "important");
            legal.style.setProperty("padding", padY.toFixed(2) + "px " + padX.toFixed(2) + "px", "important");
            legal.style.setProperty("margin", marY.toFixed(2) + "px 0", "important");
            legal.querySelectorAll(".legal-body, .legal-title, div").forEach(function(el) {{
                el.style.setProperty("font-size", m.fs.toFixed(2) + "px", "important");
                el.style.setProperty("line-height", m.lh.toFixed(3), "important");
            }});
        }}

        function applyDataTblBump(fs, padY, padX) {{
            sheet.querySelectorAll("table.data-tbl th, table.data-tbl td").forEach(function(el) {{
                el.style.setProperty("font-size", fs.toFixed(2) + "px", "important");
                el.style.setProperty("padding", padY.toFixed(2) + "px " + padX.toFixed(2) + "px", "important");
            }});
        }}

        function atCap(m) {{
            return m.fs >= 16.5 - 0.01 && m.lh >= 2.25 - 0.01
                && Math.max(m.pt, m.pb) >= 20 - 0.01
                && Math.max(m.pr, m.pl) >= 22 - 0.01
                && Math.max(m.mt, m.mb) >= 14 - 0.01;
        }}

        // تأكد من قفل ارتفاع الورقة ثم قِس الفراغ الحقيقي من مجموع الكتل
        applyPrintPhysicalSize(doc, true);
        void sheet.offsetHeight;
        let free = freeSpace();
        if (free <= 85) return 0;

        let steps = 0;
        let dataFs = 12.5;
        let dataPadY = 5;
        let dataPadX = 8;
        try {{
            const sample = sheet.querySelector("table.data-tbl td");
            if (sample) {{
                const cs = win.getComputedStyle(sample);
                dataFs = parseFloat(cs.fontSize) || dataFs;
                dataPadY = parseFloat(cs.paddingTop) || dataPadY;
                dataPadX = parseFloat(cs.paddingLeft) || dataPadX;
            }}
        }} catch (e0) {{}}

        while (free > 85 && steps < 28) {{
            const before = currentLegalMetrics();
            const beforeData = {{ fs: dataFs, padY: dataPadY, padX: dataPadX }};
            if (atCap(before) && dataFs >= 13.5 - 0.01) break;

            const next = {{
                fs: Math.min(16.5, before.fs + 0.35),
                lh: Math.min(2.25, before.lh + 0.05),
                pt: Math.min(20, before.pt + 0.65),
                pr: Math.min(22, before.pr + 0.65),
                pb: Math.min(20, before.pb + 0.65),
                pl: Math.min(22, before.pl + 0.65),
                mt: Math.min(14, Math.max(before.mt, 4) + 0.5),
                mb: Math.min(14, Math.max(before.mb, 4) + 0.5)
            }};
            applyLegalMetrics(next);
            dataFs = Math.min(13.5, dataFs + 0.2);
            dataPadY = Math.min(8, dataPadY + 0.25);
            dataPadX = Math.min(10, dataPadX + 0.25);
            applyDataTblBump(dataFs, dataPadY, dataPadX);
            void sheet.offsetHeight;

            const newFree = freeSpace();
            // توقف قبل التواقيع بهامش أمان 22px، ولا تتجاوز صفحة واحدة
            if (newFree < 22 || measureUsedH() > TARGET_H_PX - 22) {{
                applyLegalMetrics(before);
                applyDataTblBump(beforeData.fs, beforeData.padY, beforeData.padX);
                void sheet.offsetHeight;
                break;
            }}
            free = newFree;
            steps += 1;
            if (atCap(next) && dataFs >= 13.5 - 0.01) break;
        }}
        applyPrintPhysicalSize(doc, true);
        return steps;
    }}

    function balanceA4Page(rootDoc) {{
        const doc = rootDoc || document;
        applyPrintPhysicalSize(doc, true);
        const down = stepDownFitA4(doc);
        const up = expandLegalToFillSpace(doc);
        applyPrintPhysicalSize(doc, true);
        return {{ down: down, up: up }};
    }}
    try {{ window.getPrintHeightTargets = getPrintHeightTargets; }} catch (e) {{}}
    try {{ window.applyPrintPhysicalSize = applyPrintPhysicalSize; }} catch (e) {{}}
    try {{ window.stepDownFitA4 = stepDownFitA4; }} catch (e) {{}}
    try {{ window.expandLegalToFillSpace = expandLegalToFillSpace; }} catch (e) {{}}
    try {{ window.balanceA4Page = balanceA4Page; }} catch (e) {{}}
    try {{ window.autoBalanceA4 = balanceA4Page; }} catch (e) {{}}
    try {{ window.fitSinglePageForPrint = balanceA4Page; }} catch (e) {{}}

    function fitA4Preview() {{
        if (window.matchMedia && window.matchMedia("print").matches) return;
        const viewport = document.getElementById("a4PreviewViewport");
        const frame = document.getElementById("a4PageFrame");
        const paper = document.getElementById("a4Sheet");
        if (!viewport || !frame) return;
        // المعاينة على الشاشة تبقى بمظهر A4 الكامل؛ الطباعة تضبط السقف الآمن لاحقاً
        try {{
            frame.style.width = "210mm";
            frame.style.height = "297mm";
            frame.style.maxHeight = "297mm";
            frame.style.margin = "0 auto";
            frame.style.direction = "rtl";
            frame.style.transformOrigin = "top center";
            frame.style.transform = "";
            frame.style.zoom = "";
            if (paper) {{
                paper.style.width = "100%";
                paper.style.height = "285mm";
                paper.style.minHeight = "285mm";
                paper.style.maxHeight = "285mm";
                paper.style.margin = "0 auto";
                paper.style.zoom = "";
                paper.style.transform = "none";
            }}
        }} catch (e) {{}}
        try {{
            // للمعاينة: استخدم سقف الجهاز حتى يظهر نفس توازن الطباعة
            balanceA4Page(document);
        }} catch (eBal) {{}}
        const avail = Math.max(viewport.clientWidth || window.innerWidth || 794, 1);
        const natural = frame.offsetWidth || Math.round(210 * 96 / 25.4) || 794;
        const fitZoom = Math.max(0.15, Math.min(1, avail / Math.max(natural, 1)));
        frame.style.zoom = String(fitZoom);
        viewport.style.overflow = "hidden";
        viewport.style.height = "auto";
        try {{
            if (window.frameElement) {{
                const dock = document.querySelector(".live-sig-dock");
                const dockH = dock ? dock.offsetHeight + 18 : 0;
                const toolbar = document.querySelector(".toolbar");
                const tH = toolbar ? toolbar.offsetHeight + 12 : 0;
                const viewH = viewport.scrollHeight || (frame.offsetHeight * fitZoom);
                window.frameElement.style.height = Math.ceil(viewH + 120 + dockH + tH) + "px";
            }}
        }} catch (e2) {{}}
    }}

    function syncAllLivePads() {{
        try {{
            (LIVE_PADS || []).forEach(function(padId) {{ syncPadToSlot(padId); }});
        }} catch (e) {{}}
    }}
    try {{ window.syncAllLivePads = syncAllLivePads; }} catch (e) {{}}

    function prepareA4Print() {{
        syncAllLivePads();
        const viewport = document.getElementById("a4PreviewViewport");
        const frame = document.getElementById("a4PageFrame");
        const paper = document.getElementById("a4Sheet");
        if (viewport) {{
            viewport.style.height = "auto";
            viewport.style.overflow = "visible";
            viewport.style.zoom = "";
        }}
        if (frame) {{
            frame.style.zoom = "";
            frame.style.transform = "none";
            frame.style.width = "100%";
            frame.style.overflow = "hidden";
            frame.style.margin = "0 auto";
        }}
        if (paper) {{
            paper.style.zoom = "";
            paper.style.transform = "none";
            paper.style.width = "100%";
            paper.style.margin = "0 auto";
        }}
        const t = getPrintHeightTargets(window);
        const TARGET_H_PX = t.TARGET_H_PX;
        applyPrintPhysicalSize(document, true);
        if (paper) {{
            try {{
                paper.style.setProperty("height", TARGET_H_PX + "px", "important");
                paper.style.setProperty("max-height", TARGET_H_PX + "px", "important");
            }} catch (eH) {{}}
        }}
        balanceA4Page(document);
    }}
    try {{ window.prepareA4Print = prepareA4Print; }} catch (e) {{}}

    function restoreA4Preview() {{
        const viewport = document.getElementById("a4PreviewViewport");
        const frame = document.getElementById("a4PageFrame");
        const paper = document.getElementById("a4Sheet");
        if (viewport) {{
            viewport.style.height = "";
            viewport.style.overflow = "hidden";
        }}
        if (frame) {{
            frame.style.zoom = "";
            frame.style.removeProperty("transform");
            frame.style.removeProperty("width");
            frame.style.removeProperty("height");
            frame.style.removeProperty("margin");
            frame.style.removeProperty("overflow");
        }}
        if (paper) {{
            paper.style.zoom = "";
            paper.style.removeProperty("transform");
            paper.style.removeProperty("width");
            paper.style.removeProperty("height");
            paper.style.removeProperty("min-height");
            paper.style.removeProperty("max-height");
            paper.style.removeProperty("overflow");
            paper.style.removeProperty("margin");
            // امسح تصغير step-down من العناصر الداخلية بإعادة تحميل الأنماط عبر إزالة inline typography
            try {{
                paper.querySelectorAll("[style]").forEach(function(el) {{
                    if (!el.classList.contains("hdr-logo") && el.tagName !== "IMG") {{
                        ["font-size","padding-top","padding-bottom","margin-top","margin-bottom","line-height","height","width","max-height","max-width"]
                            .forEach(function(prop) {{
                                try {{
                                    if (el.style.getPropertyPriority(prop) === "important") {{
                                        el.style.removeProperty(prop);
                                    }}
                                }} catch (ie) {{}}
                            }});
                    }}
                }});
            }} catch (e3) {{}}
        }}
        scheduleA4Fit();
    }}

    function collectPrintStyles() {{
        try {{
            return Array.from(document.querySelectorAll("style"))
                .map(function(node) {{ return node.outerHTML; }})
                .join("\\n");
        }} catch (e) {{
            return "";
        }}
    }}

    function buildCleanPrintHtml(frameHtml) {{
        var styles = collectPrintStyles();
        var topBar = ''
            + '<div class="no-print" style="position:sticky;top:0;z-index:9999;background:#14532d;color:#fff;'
            + 'padding:10px 12px;display:flex;justify-content:space-between;align-items:center;gap:8px;'
            + 'font-family:Cairo,Tahoma,sans-serif;direction:rtl;margin-bottom:10px;">'
            + '<button type="button" onclick="window.print()" style="background:#eab308;color:#000;border:none;'
            + 'padding:8px 14px;border-radius:6px;font-weight:800;font-size:14px;cursor:pointer;">'
            + '🖨️ اضغط للطباعة أو الحفظ PDF عبر مشاركة سفاري (⬆️)</button>'
            + '<button type="button" onclick="window.close()" style="background:#dc2626;color:#fff;border:none;'
            + 'padding:8px 14px;border-radius:6px;font-weight:800;font-size:14px;cursor:pointer;">✕ إغلاق</button>'
            + '</div>';
        return '<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8">'
            + '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
            + '<meta name="format-detection" content="telephone=no">'
            + '<title>وثيقة رسمية - قسم مرور العارضة</title>'
            + '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cairo:wght@600;700;800;900&family=Tajawal:wght@700;800;900&display=swap">'
            + styles
            + '<style>@page{{margin:5mm 6mm !important;}}'
            + 'html,body{{width:100% !important;height:auto !important;margin:0 !important;padding:0 !important;'
            + 'overflow:hidden !important;background:#fff !important;direction:rtl !important;}}'
            + '.a4-page-frame{{width:100% !important;max-width:100% !important;height:254mm !important;max-height:254mm !important;'
            + 'padding:4mm 5mm !important;box-sizing:border-box !important;overflow:hidden !important;margin:0 auto !important;'
            + 'background:#fff !important;page-break-after:avoid !important;page-break-inside:avoid !important;position:relative !important;}}'
            + 'html.a4-print-desktop .a4-page-frame,body.a4-print-desktop .a4-page-frame{{height:276mm !important;max-height:276mm !important;}}'
            + '.a4-sheet,.a4-paper{{width:100% !important;height:945px !important;min-height:0 !important;'
            + 'max-height:945px !important;display:table !important;table-layout:fixed !important;'
            + 'box-sizing:border-box !important;overflow:hidden !important;margin:0 auto !important;'
            + 'border:1.8px solid #0f3d2e !important;border-radius:4px !important;background:#fff !important;'
            + 'page-break-after:avoid !important;page-break-inside:avoid !important;}}'
            + 'html.a4-print-desktop .a4-sheet,html.a4-print-desktop .a4-paper,'
            + 'body.a4-print-desktop .a4-sheet,body.a4-print-desktop .a4-paper{{height:1035px !important;max-height:1035px !important;}}'
            + '.a4-row{{display:table-row !important;}}.a4-cell{{display:table-cell !important;width:100% !important;}}'
            + '.a4-row-mid{{height:100% !important;}}.legal-wrap-cell{{vertical-align:top !important;}}'
            + '.sig-bottom-cell{{vertical-align:bottom !important;}}'
            + '@media screen{{'
            + 'html,body{{margin:0 !important;padding:12px !important;background:#0f172a !important;'
            + 'display:flex !important;flex-direction:column !important;align-items:center !important;'
            + 'direction:rtl !important;width:100% !important;height:auto !important;overflow:auto !important;}}'
            + '.no-print{{width:100% !important;max-width:720px !important;box-sizing:border-box !important;}}'
            + '.a4-page-frame{{width:min(100%,210mm) !important;max-width:100% !important;height:auto !important;'
            + 'max-height:none !important;margin:0 auto 16px auto !important;transform-origin:top center !important;'
            + 'box-shadow:0 10px 28px rgba(0,0,0,0.45) !important;}}'
            + '.a4-sheet,.a4-paper{{width:100% !important;height:auto !important;min-height:0 !important;'
            + 'max-height:none !important;margin:0 auto !important;}}'
            + '}}'
            + '@media print{{.no-print{{display:none !important;}}'
            + 'html,body{{width:100% !important;height:auto !important;margin:0 !important;padding:0 !important;overflow:hidden !important;}}'
            + '.a4-page-frame{{width:100% !important;height:254mm !important;max-height:254mm !important;overflow:hidden !important;'
            + 'page-break-after:avoid !important;page-break-inside:avoid !important;}}'
            + 'html.a4-print-desktop .a4-page-frame,body.a4-print-desktop .a4-page-frame{{height:276mm !important;max-height:276mm !important;}}'
            + '.a4-sheet,.a4-paper{{height:945px !important;max-height:945px !important;overflow:hidden !important;width:100% !important;margin:0 auto !important;}}'
            + 'html.a4-print-desktop .a4-sheet,html.a4-print-desktop .a4-paper,'
            + 'body.a4-print-desktop .a4-sheet,body.a4-print-desktop .a4-paper{{height:1035px !important;max-height:1035px !important;}}}}'
            + '</style></head><body style="margin:0;padding:12px;background:#0f172a;direction:rtl;width:100%;height:auto;overflow:auto;display:flex;flex-direction:column;align-items:center;">'
            + topBar + frameHtml
            + '<script>(function(){{'
            + 'window.__khafarPrintWin=true;document.__khafarPrintWin=true;'
            + 'var IS_IOS=/iPad|iPhone|iPod/.test(navigator.userAgent)||(navigator.platform==="MacIntel"&&navigator.maxTouchPoints>1);'
            + 'window.__khafarIsIOS=IS_IOS;'
            + 'function getPrintHeightTargets(){{var ios=IS_IOS;return {{isIOS:ios,TARGET_H_PX:ios?945:1035,FRAME_H_PX:ios?960:1040,FRAME_H_MM:ios?"254mm":"276mm"}};}}'
            + 'function applyPrintPhysicalSize(doc){{doc=doc||document;var t=getPrintHeightTargets();'
            + 'try{{var root=doc.documentElement,body=doc.body;'
            + 'if(t.isIOS){{if(root){{root.classList.remove("a4-print-desktop");root.classList.add("a4-print-ios");}}'
            + 'if(body){{body.classList.remove("a4-print-desktop");body.classList.add("a4-print-ios");}}'
            + '}}else{{if(root){{root.classList.remove("a4-print-ios");root.classList.add("a4-print-desktop");}}'
            + 'if(body){{body.classList.remove("a4-print-ios");body.classList.add("a4-print-desktop");}}}}catch(e){{}}'
            + 'var frame=doc.getElementById("a4PageFrame")||doc.querySelector(".a4-page-frame");'
            + 'var sheet=doc.getElementById("a4Sheet")||doc.querySelector(".a4-sheet")||doc.querySelector(".a4-paper");'
            + 'if(frame){{try{{frame.style.setProperty("width","100%","important");frame.style.setProperty("height",t.FRAME_H_MM,"important");'
            + 'frame.style.setProperty("max-height",t.FRAME_H_MM,"important");frame.style.setProperty("overflow","hidden","important");'
            + 'frame.style.setProperty("page-break-after","avoid","important");frame.style.setProperty("page-break-inside","avoid","important");'
            + 'frame.style.setProperty("margin","0 auto","important");}}catch(e2){{}}}}'
            + 'if(sheet){{try{{sheet.style.setProperty("width","100%","important");'
            + 'sheet.style.setProperty("height",t.TARGET_H_PX+"px","important");'
            + 'sheet.style.setProperty("max-height",t.TARGET_H_PX+"px","important");'
            + 'sheet.style.setProperty("min-height","0","important");sheet.style.setProperty("overflow","hidden","important");'
            + 'sheet.style.setProperty("margin-left","auto","important");sheet.style.setProperty("margin-right","auto","important");'
            + 'sheet.style.setProperty("page-break-after","avoid","important");sheet.style.setProperty("page-break-inside","avoid","important");'
            + '}}catch(e3){{}}}}return t;}}'
            + 'function stepDownFitA4(rootDoc){{'
            + 'var doc=rootDoc||document;var t=getPrintHeightTargets();var TARGET_H_PX=t.TARGET_H_PX;'
            + 'var frame=doc.getElementById("a4PageFrame")||doc.querySelector(".a4-page-frame");'
            + 'var sheet=doc.getElementById("a4Sheet")||doc.querySelector(".a4-sheet")||doc.querySelector(".a4-paper");'
            + 'if(!sheet)return 0;'
            + 'try{{sheet.style.removeProperty("zoom");sheet.style.setProperty("transform","none","important");'
            + 'sheet.style.setProperty("width","100%","important");sheet.style.setProperty("max-width","100%","important");'
            + 'sheet.style.setProperty("margin-left","auto","important");sheet.style.setProperty("margin-right","auto","important");'
            + 'sheet.style.setProperty("box-sizing","border-box","important");}}catch(e){{}}'
            + 'try{{sheet.style.setProperty("height","auto","important");sheet.style.setProperty("min-height","0","important");'
            + 'sheet.style.setProperty("max-height","none","important");sheet.style.setProperty("overflow","visible","important");}}catch(e2){{}}'
            + 'function bumpDown(node,fontDelta,padDelta){{if(!node||!node.style)return;try{{'
            + 'var cs=(doc.defaultView||window).getComputedStyle(node);var fs=parseFloat(cs.fontSize)||0;'
            + 'if(fs>8.5)node.style.setProperty("font-size",Math.max(8.5,fs-fontDelta).toFixed(2)+"px","important");'
            + 'var pt=parseFloat(cs.paddingTop)||0;var pb=parseFloat(cs.paddingBottom)||0;'
            + 'if(pt>1||pb>1){{node.style.setProperty("padding-top",Math.max(1,pt-padDelta).toFixed(2)+"px","important");'
            + 'node.style.setProperty("padding-bottom",Math.max(1,pb-padDelta).toFixed(2)+"px","important");}}'
            + '}}catch(e4){{}}}}'
            + 'function shrinkOnce(){{'
            + 'var targets=sheet.querySelectorAll(".legal-box,.legal-box .legal-body,.legal-box .legal-title,.legal-box div,'
            + 'table.data-tbl th,table.data-tbl td,table.sig-tbl th,table.sig-tbl td,.sig-cell,.sig-head,.sig-person,.sig-role,'
            + '.doc-banner,.footer-qr,.footer-qr div,.hdr-right p,.hdr-left p,.a4-top-cell,.legal-wrap-cell,.sig-bottom-cell");'
            + 'targets.forEach(function(el){{bumpDown(el,0.4,1);}});'
            + 'try{{sheet.querySelectorAll(".hdr-center img,.hdr-logo,img.sig-slot-img").forEach(function(img){{'
            + 'var cs=(doc.defaultView||window).getComputedStyle(img);var h=parseFloat(cs.height)||0;'
            + 'if(h>28){{var nh=Math.max(28,h-2);img.style.setProperty("height",nh+"px","important");'
            + 'img.style.setProperty("width",nh+"px","important");img.style.setProperty("max-height",nh+"px","important");'
            + 'img.style.setProperty("max-width",nh+"px","important");}}}});}}catch(e5){{}}}}'
            + 'var step=0;void sheet.offsetHeight;'
            + 'while((sheet.scrollHeight>TARGET_H_PX)&&step<10){{shrinkOnce();void sheet.offsetHeight;step+=1;}}'
            + 'applyPrintPhysicalSize(doc);'
            + 'if(frame){{try{{frame.style.setProperty("overflow","hidden","important");}}catch(e6){{}}}}'
            + 'return step;}}'
            + 'function expandLegalToFillSpace(rootDoc){{'
            + 'var doc=rootDoc||document;var t=getPrintHeightTargets();var TARGET_H_PX=t.TARGET_H_PX;'
            + 'var sheet=doc.getElementById("a4Sheet")||doc.querySelector(".a4-sheet")||doc.querySelector(".a4-paper");'
            + 'if(!sheet)return 0;var legal=sheet.querySelector(".legal-box");if(!legal)return 0;'
            + 'var win=doc.defaultView||window;'
            + 'try{{[legal].concat(Array.from(legal.querySelectorAll(".legal-title,.legal-body,div"))).forEach(function(el){{'
            + 'try{{el.style.removeProperty("font-size");el.style.removeProperty("line-height");'
            + 'el.style.removeProperty("padding");el.style.removeProperty("margin");}}catch(clr){{}}}});}}catch(eClr){{}}'
            + 'function blockH(el){{if(!el)return 0;try{{var cs=win.getComputedStyle(el);'
            + 'return (el.offsetHeight||0)+(parseFloat(cs.marginTop)||0)+(parseFloat(cs.marginBottom)||0);}}catch(e){{return el.offsetHeight||0;}}}}'
            + 'function measureUsedH(){{var sum=0;var topCell=sheet.querySelector(".a4-top-cell");'
            + 'if(topCell){{sum+=blockH(topCell);}}else{{sum+=blockH(sheet.querySelector(".hdr"));'
            + 'sum+=blockH(sheet.querySelector(".doc-banner"));sum+=blockH(sheet.querySelector("table.data-tbl"));}}'
            + 'sum+=blockH(legal);sum+=blockH(sheet.querySelector(".attachment-section"));'
            + 'sum+=blockH(sheet.querySelector(".sig-footer")||sheet.querySelector(".sig-bottom-cell"));return sum;}}'
            + 'function freeSpace(){{return TARGET_H_PX-measureUsedH();}}'
            + 'function currentLegalMetrics(){{var cs=win.getComputedStyle(legal);var fs=parseFloat(cs.fontSize)||12;var lhRatio=NaN;'
            + 'var lhRaw=cs.lineHeight;if(lhRaw&&lhRaw!=="normal"){{var lhPx=parseFloat(lhRaw);if(!isNaN(lhPx)&&fs>0)lhRatio=lhPx/fs;}}'
            + 'if(isNaN(lhRatio)||lhRatio<1.05)lhRatio=1.6;return {{fs:fs,lh:lhRatio,pt:parseFloat(cs.paddingTop)||0,'
            + 'pr:parseFloat(cs.paddingRight)||0,pb:parseFloat(cs.paddingBottom)||0,pl:parseFloat(cs.paddingLeft)||0,'
            + 'mt:parseFloat(cs.marginTop)||0,mb:parseFloat(cs.marginBottom)||0}};}}'
            + 'function applyLegalMetrics(m){{var padY=Math.min(20,Math.max(m.pt,m.pb));var padX=Math.min(22,Math.max(m.pr,m.pl));'
            + 'var marY=Math.min(14,Math.max(m.mt,m.mb,0));'
            + 'legal.style.setProperty("font-size",m.fs.toFixed(2)+"px","important");'
            + 'legal.style.setProperty("line-height",m.lh.toFixed(3),"important");'
            + 'legal.style.setProperty("padding",padY.toFixed(2)+"px "+padX.toFixed(2)+"px","important");'
            + 'legal.style.setProperty("margin",marY.toFixed(2)+"px 0","important");'
            + 'legal.querySelectorAll(".legal-body,.legal-title,div").forEach(function(el){{'
            + 'el.style.setProperty("font-size",m.fs.toFixed(2)+"px","important");'
            + 'el.style.setProperty("line-height",m.lh.toFixed(3),"important");}});}}'
            + 'function applyDataTblBump(fs,padY,padX){{sheet.querySelectorAll("table.data-tbl th,table.data-tbl td").forEach(function(el){{'
            + 'el.style.setProperty("font-size",fs.toFixed(2)+"px","important");'
            + 'el.style.setProperty("padding",padY.toFixed(2)+"px "+padX.toFixed(2)+"px","important");}});}}'
            + 'function atCap(m){{return m.fs>=16.49&&m.lh>=2.24&&Math.max(m.pt,m.pb)>=19.99&&Math.max(m.pr,m.pl)>=21.99&&Math.max(m.mt,m.mb)>=13.99;}}'
            + 'applyPrintPhysicalSize(doc);void sheet.offsetHeight;var free=freeSpace();if(free<=85)return 0;'
            + 'var steps=0;var dataFs=12.5;var dataPadY=5;var dataPadX=8;'
            + 'try{{var sample=sheet.querySelector("table.data-tbl td");if(sample){{var cs0=win.getComputedStyle(sample);'
            + 'dataFs=parseFloat(cs0.fontSize)||dataFs;dataPadY=parseFloat(cs0.paddingTop)||dataPadY;'
            + 'dataPadX=parseFloat(cs0.paddingLeft)||dataPadX;}}}}catch(e0){{}}'
            + 'while(free>85&&steps<28){{var before=currentLegalMetrics();var beforeData={{fs:dataFs,padY:dataPadY,padX:dataPadX}};'
            + 'if(atCap(before)&&dataFs>=13.49)break;'
            + 'var next={{fs:Math.min(16.5,before.fs+0.35),lh:Math.min(2.25,before.lh+0.05),'
            + 'pt:Math.min(20,before.pt+0.65),pr:Math.min(22,before.pr+0.65),'
            + 'pb:Math.min(20,before.pb+0.65),pl:Math.min(22,before.pl+0.65),'
            + 'mt:Math.min(14,Math.max(before.mt,4)+0.5),mb:Math.min(14,Math.max(before.mb,4)+0.5)}};'
            + 'applyLegalMetrics(next);dataFs=Math.min(13.5,dataFs+0.2);dataPadY=Math.min(8,dataPadY+0.25);'
            + 'dataPadX=Math.min(10,dataPadX+0.25);applyDataTblBump(dataFs,dataPadY,dataPadX);void sheet.offsetHeight;'
            + 'var newFree=freeSpace();'
            + 'if(newFree<22||measureUsedH()>TARGET_H_PX-22){{applyLegalMetrics(before);'
            + 'applyDataTblBump(beforeData.fs,beforeData.padY,beforeData.padX);void sheet.offsetHeight;break;}}'
            + 'free=newFree;steps+=1;if(atCap(next)&&dataFs>=13.49)break;}}'
            + 'applyPrintPhysicalSize(doc);return steps;}}'
            + 'function balanceA4Page(rootDoc){{var doc=rootDoc||document;applyPrintPhysicalSize(doc);'
            + 'stepDownFitA4(doc);expandLegalToFillSpace(doc);applyPrintPhysicalSize(doc);}}'
            + 'window.stepDownFitA4=stepDownFitA4;window.expandLegalToFillSpace=expandLegalToFillSpace;window.balanceA4Page=balanceA4Page;'
            + 'function go(){{try{{balanceA4Page(document);}}catch(e){{}}try{{window.focus();}}catch(e2){{}}try{{window.print();}}catch(e3){{}}}}'
            + 'if(document.fonts&&document.fonts.ready){{document.fonts.ready.then(function(){{setTimeout(go,450);}});}}'
            + 'else{{setTimeout(go,450);}}'
            + 'window.addEventListener("load",function(){{setTimeout(go,700);}});'
            + 'window.addEventListener("beforeprint",function(){{try{{balanceA4Page(document);}}catch(e){{}}}});'
            + '}}());<\\/script>'
            + '</body></html>';
    }}

    function openOfficialPrintWindow() {{
        // مسار متزامن 100%: مزامنة التواقيع ثم window.open داخل نفس ضغطة المستخدم
        try {{ syncAllLivePads(); }} catch (e) {{}}
        try {{ prepareA4Print(); }} catch (e2) {{}}
        var frame = document.getElementById("a4PageFrame")
            || document.querySelector(".a4-page-frame");
        var sheet = document.getElementById("a4Sheet")
            || document.querySelector(".a4-page")
            || document.querySelector(".a4-paper");
        if (!frame && !sheet) {{
            alert("لم يتم العثور على ورقة A4");
            return;
        }}
        var printWin = window.open("", "_blank");
        if (!printWin || printWin.closed || typeof printWin.closed === "undefined") {{
            var hint = document.getElementById("iosPrintHint");
            if (hint) hint.style.display = "block";
            try {{ prepareA4Print(); }} catch (e3) {{}}
            try {{ window.print(); }} catch (e4) {{}}
            return;
        }}
        var hintHide = document.getElementById("iosPrintHint");
        if (hintHide) hintHide.style.display = "none";
        var cleanHtml = buildCleanPrintHtml((frame || sheet).outerHTML);
        try {{
            printWin.document.open();
            printWin.document.write(cleanHtml);
            printWin.document.close();
        }} catch (e5) {{
            try {{ prepareA4Print(); window.print(); }} catch (e6) {{}}
        }}
        setTimeout(function() {{ try {{ restoreA4Preview(); }} catch (e7) {{}} }}, 1200);
    }}
    try {{ window.openOfficialPrintWindow = openOfficialPrintWindow; }} catch (e) {{}}

    var printBtn = document.getElementById("printOfficialBtn");
    if (printBtn) {{
        printBtn.addEventListener("click", function(ev) {{
            ev.preventDefault();
            openOfficialPrintWindow();
        }});
    }}

    window.onbeforeprint = prepareA4Print;
    window.addEventListener("beforeprint", prepareA4Print);
    window.addEventListener("afterprint", restoreA4Preview);
    function scheduleA4Fit() {{
        fitA4Preview();
    }}
    window.addEventListener("load", scheduleA4Fit);
    window.addEventListener("resize", scheduleA4Fit);
    if (window.ResizeObserver) {{
        const previewBox = document.getElementById("a4PreviewViewport");
        if (previewBox) new ResizeObserver(scheduleA4Fit).observe(previewBox);
    }}
    if (document.fonts && document.fonts.ready) {{
        document.fonts.ready.then(scheduleA4Fit);
    }}
    setTimeout(scheduleA4Fit, 150);
    setTimeout(scheduleA4Fit, 600);
</script>




<style id="khafar-final-a4-fix">
  .legal-box {{
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
    flex: 1 1 auto !important;
    background: #f8fafc !important;
    border: 1.4px solid #cbd5e1 !important;
    border-right: 5px solid #0f3d2e !important;
    border-radius: 6px !important;
    width: 100% !important;
    box-sizing: border-box !important;
  }}
  .legal-box .legal-box-title {{
    font-weight: 800 !important;
    color: #000000 !important;
    text-align: right !important;
    margin-bottom: 6px !important;
  }}
  .legal-box .legal-box-body {{
    direction: rtl !important;
    unicode-bidi: embed !important;
    text-align: justify !important;
    text-justify: inter-word !important;
    text-align-last: right !important;
    color: #000000 !important;
    font-weight: 700 !important;
    overflow-wrap: break-word !important;
    white-space: normal !important;
  }}
  img.sig-slot-img {{
    background: #ffffff !important;
    mix-blend-mode: normal !important;
    max-height: 50px !important;
    width: auto !important;
    max-width: 95% !important;
    object-fit: contain !important;
    margin: 2px auto !important;
  }}
  #khafarIosShareTray {{
    display: none;
    flex-direction: column;
    gap: 8px;
    width: 100%;
    max-width: 760px;
    margin: 8px auto 12px auto;
    padding: 12px 14px;
    background: linear-gradient(135deg, #0d3b2e 0%, #07231b 100%);
    border: 2px solid #d4a853;
    border-radius: 12px;
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.35);
    direction: rtl;
    box-sizing: border-box;
    font-family: 'Cairo', Tahoma, sans-serif;
  }}
  #khafarIosShareTray .ios-ready-main-btn {{
    width: 100%;
    background: linear-gradient(135deg, #eab308 0%, #ca8a04 100%);
    color: #0b1512;
    border: none;
    border-radius: 9px;
    padding: 12px 14px;
    font-family: 'Cairo', Tahoma, sans-serif;
    font-size: 14.5px;
    font-weight: 900;
    cursor: pointer;
    text-align: center;
  }}
  #khafarIosShareTray .ios-ready-sub-row {{
    display: flex;
    gap: 8px;
    justify-content: center;
    flex-wrap: wrap;
  }}
  #khafarIosShareTray .ios-ready-sec-btn {{
    flex: 1 1 auto;
    background: rgba(255, 255, 255, 0.12);
    color: #ffffff;
    border: 1px solid rgba(212, 168, 83, 0.55);
    border-radius: 8px;
    padding: 8px 12px;
    font-family: 'Cairo', Tahoma, sans-serif;
    font-size: 12.5px;
    font-weight: 800;
    cursor: pointer;
    text-align: center;
    text-decoration: none;
  }}
  @media screen {{
    #zoomBar, .zoom-bar {{
      display: flex !important;
      flex-wrap: nowrap !important;
      justify-content: center !important;
      align-items: center !important;
      gap: 5px !important;
      width: fit-content !important;
      max-width: 99% !important;
      margin: 8px auto 10px auto !important;
      padding: 5px 8px !important;
      background: linear-gradient(135deg, #0d3b2e 0%, #07231b 100%) !important;
      border: 1.5px solid #d4a853 !important;
      border-radius: 999px !important;
      box-shadow: 0 5px 14px rgba(0, 0, 0, 0.28) !important;
      direction: rtl !important;
      white-space: nowrap !important;
    }}
    #zoomBar .khafar-z-btn {{
      background: rgba(255, 255, 255, 0.10) !important;
      color: #ffffff !important;
      border: 1px solid rgba(212, 168, 83, 0.45) !important;
      border-radius: 999px !important;
      padding: 4px 10px !important;
      font-family: 'Cairo', Tahoma, sans-serif !important;
      font-size: 12px !important;
      font-weight: 800 !important;
      cursor: pointer !important;
      line-height: 1.3 !important;
      margin: 0 !important;
      white-space: nowrap !important;
    }}
    #zoomBar .khafar-z-btn:active, #zoomBar .khafar-z-btn:hover {{
      background: #15805c !important;
      border-color: #fde68a !important;
    }}
    #zoomBar .khafar-z-fit {{
      background: linear-gradient(135deg, #d4a853 0%, #b08532 100%) !important;
      color: #0b1512 !important;
      border: none !important;
      font-weight: 900 !important;
    }}
    #zoomBar #zoomPctLabel {{
      background: #ffffff !important;
      color: #092c20 !important;
      border-radius: 999px !important;
      padding: 3px 10px !important;
      font-size: 12px !important;
      font-weight: 900 !important;
      min-width: 48px !important;
      text-align: center !important;
      cursor: pointer !important;
    }}
    #khafarZoomViewport {{
      width: 100% !important;
      overflow-x: auto !important;
      overflow-y: hidden !important;
      direction: rtl !important;
      padding-bottom: 6px !important;
      -webkit-overflow-scrolling: touch !important;
    }}
    #khafarZoomSizer {{
      margin: 0 auto !important;
      position: relative !important;
      overflow: hidden !important;
    }}
    #khafarZoomCanvas {{
      width: 794px !important;
      min-width: 794px !important;
      max-width: 794px !important;
      position: absolute !important;
      top: 0 !important;
      right: 0 !important;
      transform-origin: top right !important;
    }}
    #khafarZoomCanvas > #a4Sheet {{
      width: 794px !important;
      min-width: 794px !important;
      max-width: 794px !important;
      zoom: 1 !important;
      transform: none !important;
      margin: 0 !important;
    }}
  }}
  @media print {{
    @page {{ size: A4 portrait; margin: 4.5mm 6mm !important; }}
    html, body {{
      margin: 0 !important;
      padding: 0 !important;
      background: #ffffff !important;
      width: 100% !important;
      height: auto !important;
      overflow: visible !important;
    }}
    .no-print, .toolbar, #zoomBar, .zoom-bar, .live-sig-dock, #printOfficialBtn, .print-btn, #khafarIosShareTray {{
      display: none !important;
    }}
    #khafarZoomViewport, #khafarZoomSizer, #khafarZoomCanvas {{
      position: static !important;
      width: 100% !important;
      min-width: 0 !important;
      max-width: none !important;
      height: auto !important;
      overflow: visible !important;
      transform: none !important;
    }}
    #a4Sheet {{
      display: flex !important;
      flex-direction: column !important;
      justify-content: space-between !important;
      width: 100% !important;
      min-width: 0 !important;
      max-width: none !important;
      margin: 0 auto !important;
      box-sizing: border-box !important;
      border: 1.8px solid #0f3d2e !important;
      border-radius: 4px !important;
      padding: 4mm 5.5mm !important;
      background: #ffffff !important;
      page-break-after: avoid !important;
      page-break-inside: avoid !important;
      break-inside: avoid !important;
    }}
  }}
</style>
<script src="https://cdn.jsdelivr.net/npm/modern-screenshot@4.6.0/dist/index.js"></script>
<script src="https://cdn.jsdelivr.net/npm/jspdf@2.5.1/dist/jspdf.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>
<script id="khafar-final-js-fix">
(function() {{
  window.__padInk = window.__padInk || {{}};
  window.__cachedIosPdfAb = null;
  window.__cachedIosPdfName = 'Maroor_AlArdah_Official.pdf';

  // =========================================================
  // 1) مزامنة التوقيع الحي بالإصبع 100%
  // =========================================================
  function canvasHasVisibleInk(canvas) {{
    try {{
      var ctx = canvas.getContext('2d');
      var data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      for (var i = 3; i < data.length; i += 16) {{
        if (data[i] > 18) return true;
      }}
    }} catch (e) {{}}
    return false;
  }}

  function bindInkTracker(padId) {{
    var c = document.getElementById('pad_' + padId);
    if (!c || c.dataset.inkBound === '1') return;
    c.dataset.inkBound = '1';
    var mark = function() {{
      c.dataset.hasInk = '1';
      window.__padInk[padId] = true;
      window.__cachedIosPdfAb = null;
    }};
    var syncSoon = function() {{
      setTimeout(function() {{ window.syncPadToSlot(padId); }}, 25);
    }};
    c.addEventListener('pointerdown', mark, {{ passive: true }});
    c.addEventListener('touchstart', mark, {{ passive: true }});
    c.addEventListener('mousedown', mark);
    c.addEventListener('pointerup', syncSoon, {{ passive: true }});
    c.addEventListener('touchend', syncSoon, {{ passive: true }});
    c.addEventListener('mouseup', syncSoon);
  }}

  if (typeof LIVE_PADS !== 'undefined' && Array.isArray(LIVE_PADS)) {{
    LIVE_PADS.forEach(bindInkTracker);
  }}

  window.clearLivePad = function(padId) {{
    window.__cachedIosPdfAb = null;
    var c = document.getElementById('pad_' + padId);
    if (c) {{
      delete c.dataset.hasInk;
      window.__padInk[padId] = false;
      c.getContext('2d').clearRect(0, 0, c.width, c.height);
    }}
    var s = document.getElementById('slot_' + padId);
    if (s) {{
      s.removeAttribute('src');
      s.style.setProperty('display', 'none', 'important');
    }}
    try {{
      if (typeof padStorageKey === 'function') localStorage.removeItem(padStorageKey(padId));
    }} catch (e) {{}}
  }};

  window.syncPadToSlot = function(padId) {{
    var canvas = document.getElementById('pad_' + padId);
    var slot = document.getElementById('slot_' + padId);
    if (!canvas || !slot) return;
    var hasInk = (canvas.dataset.hasInk === '1') || !!window.__padInk[padId] || canvasHasVisibleInk(canvas);
    if (!hasInk) {{
      var saved = '';
      try {{
        if (typeof padStorageKey === 'function') saved = localStorage.getItem(padStorageKey(padId)) || '';
      }} catch (e) {{}}
      if (!saved) return;
    }}
    var out = document.createElement('canvas');
    out.width = canvas.width;
    out.height = canvas.height;
    var octx = out.getContext('2d');
    octx.fillStyle = '#ffffff';
    octx.fillRect(0, 0, out.width, out.height);
    octx.drawImage(canvas, 0, 0);
    var dataUrl = out.toDataURL('image/png');
    slot.setAttribute('src', dataUrl);
    slot.setAttribute('style', 'display:block !important; visibility:visible !important; opacity:1 !important; max-height:48px !important; width:auto !important; max-width:95% !important; margin:3px auto 0 auto !important; object-fit:contain !important; background:#ffffff !important; mix-blend-mode:normal !important; border:none !important;');
    try {{
      var b64 = (dataUrl.split(',')[1] || '');
      if (b64 && typeof padStorageKey === 'function') localStorage.setItem(padStorageKey(padId), b64);
    }} catch (e) {{}}
  }};

  window.syncAllLivePads = function() {{
    if (typeof LIVE_PADS !== 'undefined' && Array.isArray(LIVE_PADS)) {{
      LIVE_PADS.forEach(function(p) {{ window.syncPadToSlot(p); }});
    }}
  }};

  // =========================================================
  // 2) تخصيص نموذج تحليل السموم بـ 3 خانات توقيع صحيحة الملكية:
  //    [يمين: جهة الاستلام] | [منتصف: ضابط الخفر] | [يسار: مدير إدارة مرور منطقة جازان + العقيد محمد آل هادي + توقيع رئيس الحوادث وتوقيعه المحفوظ]
  // =========================================================
  function applyToxicologyDirectorBlock(docRoot) {{
    var sheet = (docRoot.getElementById ? docRoot.getElementById('a4Sheet') : null)
      || (docRoot.querySelector ? docRoot.querySelector('#a4Sheet') : null);
    if (!sheet) return;

    var bannerEl = sheet.querySelector('.doc-banner');
    var bannerTxt = bannerEl ? (bannerEl.textContent || '') : '';
    var sheetTxt = sheet.textContent || '';
    var isTox = (bannerTxt.indexOf('سموم') !== -1)
      || (sheetTxt.indexOf('تحليل سموم') !== -1)
      || (sheetTxt.indexOf('تحليل السموم') !== -1)
      || (sheetTxt.indexOf('مراقبة السموم') !== -1);

    if (!isTox) return;

    if (docRoot === document) {{
      docRoot.querySelectorAll('div, span, label, strong, b').forEach(function(el) {{
        if (el.children.length === 0 && !sheet.contains(el)) {{
          var t = el.textContent || '';
          if (t.indexOf('مستلم الخفر المناوب') !== -1) {{
            el.textContent = t.replace(/مستلم الخفر المناوب/g, 'ضابط الخفر المناوب');
          }}
        }}
      }});
    }}

    if (sheet.dataset.toxThreeColFixed === '1') return;

    var ownerDoc = sheet.ownerDocument || document;
    var hdrEl = null;
    var candidates = sheet.querySelectorAll('th, td, div, span');
    for (var i = 0; i < candidates.length; i++) {{
      var c = candidates[i];
      if (c.children.length === 0) {{
        var ct = (c.textContent || '').trim();
        if (ct === 'وحدة الحوادث' || ct === 'رئيس وحدة الحوادث' || ct === 'مدير إدارة مرور منطقة جازان') {{
          hdrEl = c;
          break;
        }}
      }}
    }}

    var bodyCell = null;
    var bodyCandidates = sheet.querySelectorAll('td, div');
    for (var j = 0; j < bodyCandidates.length; j++) {{
      var bc = bodyCandidates[j];
      if (bc.querySelector('table') || bc.querySelector('tr')) continue;
      var bt = (bc.textContent || '').trim();
      if ((bt.indexOf('فهد بن أحمد') !== -1 || bt.indexOf('مجرشي') !== -1 || bt.indexOf('رئيس وحدة الحوادث') !== -1 || bt.indexOf('محمد بن عبدالله آل هادي') !== -1) && bt.length < 260) {{
        if (bc.tagName === 'TD') {{
          bodyCell = bc;
          break;
        }} else if (!bodyCell) {{
          bodyCell = bc.closest('td') || bc;
        }}
      }}
    }}

    if (hdrEl) {{
      hdrEl.textContent = 'مدير إدارة مرور منطقة جازان';
      if (!bodyCell) {{
        var hCellLookup = hdrEl.closest('th, td');
        var hRowLookup = hCellLookup ? hCellLookup.parentElement : null;
        var tblLookup = hCellLookup ? hCellLookup.closest('table') : null;
        if (tblLookup && hRowLookup && tblLookup.rows && tblLookup.rows[hRowLookup.rowIndex + 1]) {{
          bodyCell = tblLookup.rows[hRowLookup.rowIndex + 1].cells[hCellLookup.cellIndex] || null;
        }}
      }}
    }}

    if (!bodyCell) return;

    var bRow = bodyCell.parentElement;
    var rightHospCell = (bRow && bRow.cells && bRow.cells.length > 0 && bRow.cells[0] !== bodyCell) ? bRow.cells[0] : null;

    var unitHeadSigs = [];
    bodyCell.querySelectorAll('img, svg').forEach(function(sigNode) {{
      if (sigNode.tagName === 'IMG') {{
        var sVal = (sigNode.getAttribute('src') || '').trim();
        if (sVal) {{
          sigNode.setAttribute('style', 'display:block !important; visibility:visible !important; opacity:1 !important; max-height:48px !important; width:auto !important; max-width:92% !important; margin:3px auto 0 auto !important; object-fit:contain !important; background:#ffffff !important; mix-blend-mode:normal !important; border:none !important;');
        }}
      }}
      unitHeadSigs.push(sigNode);
    }});

    var dutySlotImg = null;
    var customDutyName = '';

    sheet.querySelectorAll('tr, div').forEach(function(el) {{
      if (el.querySelector('table')) return;
      if (bodyCell.contains(el) || el.contains(bodyCell)) return;
      var rawT = (el.textContent || '').replace(/\s+/g, ' ').trim();
      if (rawT.length > 0 && rawT.length < 180 && (rawT.indexOf('توثيق مستلم الخفر') === 0 || rawT.indexOf('توثيق ضابط الخفر') === 0)) {{
        var stripImgs = el.querySelectorAll('img');
        for (var k = 0; k < stripImgs.length; k++) {{
          if (unitHeadSigs.indexOf(stripImgs[k]) === -1) {{
            dutySlotImg = stripImgs[k];
            break;
          }}
        }}
        var colonPos = rawT.indexOf(':');
        if (colonPos !== -1) {{
          var extracted = rawT.slice(colonPos + 1).trim();
          if (extracted && extracted !== 'مستلم الخفر المناوب' && extracted !== 'ضابط الخفر' && extracted !== 'ضابط الخفر المناوب' && extracted !== '-') {{
            customDutyName = extracted;
          }}
        }}
        if (dutySlotImg && el.contains(dutySlotImg) && dutySlotImg.parentNode) {{
          dutySlotImg.parentNode.removeChild(dutySlotImg);
        }}
        var parentRow = el.closest('tr');
        if (parentRow && parentRow.cells && parentRow.cells.length === 1) {{
          if (dutySlotImg && parentRow.contains(dutySlotImg) && dutySlotImg.parentNode) {{
            dutySlotImg.parentNode.removeChild(dutySlotImg);
          }}
          parentRow.remove();
        }} else {{
          el.remove();
        }}
      }}
    }});

    if (!dutySlotImg) {{
      var otherSlots = sheet.querySelectorAll('img[id^="slot_"]');
      for (var sIdx = 0; sIdx < otherSlots.length; sIdx++) {{
        var cand = otherSlots[sIdx];
        if (bodyCell.contains(cand)) continue;
        if (rightHospCell && rightHospCell.contains(cand)) continue;
        if (unitHeadSigs.indexOf(cand) !== -1) continue;
        var sid = (cand.id || '').toLowerCase();
        if (sid.indexOf('hosp') === -1 && sid.indexOf('lab') === -1 && sid.indexOf('cit') === -1 && sid.indexOf('party') === -1) {{
          dutySlotImg = cand;
          break;
        }}
      }}
    }}

    if (!dutySlotImg) {{
      dutySlotImg = ownerDoc.createElement('img');
      dutySlotImg.id = 'slot_khafar_duty_tox';
      dutySlotImg.className = 'sig-slot-img';
      dutySlotImg.style.display = 'none';
      dutySlotImg.alt = '';
    }}

    function buildMiddleDutyBox() {{
      var dutyWrap = ownerDoc.createElement('div');
      dutyWrap.style.cssText = 'display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:4px 6px;gap:3px;min-height:68px;';
      var dutySub = ownerDoc.createElement('div');
      dutySub.style.cssText = 'font-weight:800;font-size:12px;color:#0f3d2e;line-height:1.45;';
      dutySub.textContent = customDutyName ? customDutyName : 'توقيع ضابط الخفر المناوب';
      dutyWrap.appendChild(dutySub);
      dutyWrap.appendChild(dutySlotImg);
      return dutyWrap;
    }}

    var hCell = hdrEl ? hdrEl.closest('th, td') : null;
    var hRow = hCell ? hCell.parentElement : null;
    var sigTable = bodyCell.closest('table');

    if (sigTable && hRow && bRow && hCell !== bodyCell) {{
      var midTh = ownerDoc.createElement(hCell.tagName);
      midTh.className = hCell.className || '';
      midTh.style.cssText = hCell.style.cssText || '';
      midTh.textContent = 'ضابط الخفر';
      hRow.insertBefore(midTh, hCell);

      var midTd = ownerDoc.createElement(bodyCell.tagName);
      midTd.className = bodyCell.className || '';
      midTd.style.cssText = bodyCell.style.cssText || '';
      midTd.appendChild(buildMiddleDutyBox());
      bRow.insertBefore(midTd, bodyCell);

      var cols = sigTable.querySelectorAll('colgroup col');
      if (cols && cols.length === 2) {{
        var extraCol = cols[1].cloneNode(true);
        cols[1].parentNode.insertBefore(extraCol, cols[1]);
        cols = sigTable.querySelectorAll('colgroup col');
      }}
      if (cols && cols.length === 3) {{
        cols.forEach(function(cl) {{ cl.style.width = '33.33%'; }});
      }}
      Array.prototype.forEach.call(hRow.cells, function(cell) {{
        cell.removeAttribute('width');
        cell.style.setProperty('width', '33.33%', 'important');
      }});
      Array.prototype.forEach.call(bRow.cells, function(cell) {{
        cell.removeAttribute('width');
        cell.style.setProperty('width', '33.33%', 'important');
      }});
      Array.prototype.forEach.call(sigTable.rows, function(r) {{
        if (r !== hRow && r !== bRow && r.cells.length === 1 && r.cells[0].colSpan === 2) {{
          r.cells[0].colSpan = 3;
        }}
      }});
    }} else if (bRow) {{
      var midCombined = bodyCell.cloneNode(false);
      if (hdrEl && bodyCell.contains(hdrEl)) {{
        var hdrTop = hdrEl;
        while (hdrTop.parentElement && hdrTop.parentElement !== bodyCell) {{
          hdrTop = hdrTop.parentElement;
        }}
        var midHdrClone = hdrTop.cloneNode(true);
        midHdrClone.textContent = 'ضابط الخفر';
        midCombined.appendChild(midHdrClone);
      }}
      midCombined.appendChild(buildMiddleDutyBox());
      bRow.insertBefore(midCombined, bodyCell);
      if (bRow.children) {{
        Array.prototype.forEach.call(bRow.children, function(ch) {{
          ch.style.setProperty('width', '33.33%', 'important');
        }});
      }}
    }}

    var hdrInsideBody = hdrEl && bodyCell.contains(hdrEl) && bodyCell !== hdrEl;
    if (hdrInsideBody) {{
      var keepHdr = hdrEl;
      while (keepHdr.parentElement && keepHdr.parentElement !== bodyCell) {{
        keepHdr = keepHdr.parentElement;
      }}
      while (keepHdr.nextSibling) {{
        bodyCell.removeChild(keepHdr.nextSibling);
      }}
    }} else {{
      bodyCell.innerHTML = '';
    }}

    var leftWrap = ownerDoc.createElement('div');
    leftWrap.style.cssText = 'display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:4px 6px;gap:3px;min-height:68px;';

    var colName = ownerDoc.createElement('div');
    colName.style.cssText = 'font-weight:900;font-size:13px;color:#000000;line-height:1.45;';
    colName.textContent = 'العقيد / محمد بن عبدالله آل هادي';

    var accHeadLine = ownerDoc.createElement('div');
    accHeadLine.style.cssText = 'font-weight:800;font-size:11.5px;color:#0f3d2e;line-height:1.4;';
    accHeadLine.textContent = 'توقيع رئيس الحوادث بمرور العارضة';

    leftWrap.appendChild(colName);
    leftWrap.appendChild(accHeadLine);
    unitHeadSigs.forEach(function(sigEl) {{
      leftWrap.appendChild(sigEl);
    }});

    bodyCell.appendChild(leftWrap);
    sheet.dataset.toxThreeColFixed = '1';
  }}

  // =========================================================
  // 3) موازنة الخطوط والمسافات وقفل صفحة 1/1 بدون قص سفلي
  // =========================================================
  function balanceSheetElement(sheet, targetH, isPrintMode, isIOSMode, skipCssZoom) {{
    if (!sheet) return;
    sheet.style.setProperty('display', 'flex', 'important');
    sheet.style.setProperty('flex-direction', 'column', 'important');
    sheet.style.setProperty('justify-content', 'space-between', 'important');
    sheet.style.setProperty('box-sizing', 'border-box', 'important');
    sheet.style.setProperty('zoom', '1', 'important');

    if (isIOSMode && isPrintMode && !skipCssZoom) {{
      sheet.style.setProperty('width', '645px', 'important');
      sheet.style.setProperty('padding', '3mm 4.5mm', 'important');
    }}

    sheet.style.setProperty('height', 'auto', 'important');
    sheet.style.setProperty('min-height', targetH + 'px', 'important');
    sheet.style.setProperty('max-height', 'none', 'important');
    sheet.style.setProperty('overflow', 'visible', 'important');

    var hdr = sheet.querySelector('.hdr');
    var logo = sheet.querySelector('.hdr-logo') || sheet.querySelector('.hdr-center img');
    var hdrCenter = sheet.querySelector('.hdr-center');
    var banner = sheet.querySelector('.doc-banner');
    var dataTbl = sheet.querySelector('table.data-tbl');
    var legal = sheet.querySelector('.legal-box');
    var legalBody = sheet.querySelector('.legal-box-body') || (legal && legal.lastElementChild);
    var legalTitle = sheet.querySelector('.legal-box-title') || (legal && legal.firstElementChild);
    var tblCells = sheet.querySelectorAll('table.data-tbl td');
    var sigHeads = sheet.querySelectorAll('table.sig-tbl th, .sig-head');
    var sigCells = sheet.querySelectorAll('table.sig-tbl td, .sig-cell');
    var sigImgs = sheet.querySelectorAll('img.sig-slot-img');
    var attImgs = sheet.querySelectorAll('.att-card img');
    var attSec = sheet.querySelector('.attachment-section');
    var footerQr = sheet.querySelector('.footer-qr');

    var rowsCnt = sheet.querySelectorAll('table.data-tbl tr').length;
    var textLen = legalBody ? (legalBody.textContent || '').trim().length : 0;
    var hasAtts = attImgs && attImgs.length > 0;

    if (rowsCnt <= 6 && textLen <= 560 && sigCells.length <= 3) {{
      tblCells.forEach(function(td) {{
        td.style.setProperty('font-size', isIOSMode ? '12.5px' : '13.5px', 'important');
        td.style.setProperty('padding', isIOSMode ? '6px 8px' : '9px 11px', 'important');
        td.style.setProperty('line-height', isIOSMode ? '1.45' : '1.6', 'important');
      }});
      if (legal) {{
        legal.style.setProperty('padding', isIOSMode ? '12px 14px' : '18px 20px', 'important');
        legal.style.setProperty('margin', isIOSMode ? '5px 0 8px 0' : '8px 0 12px 0', 'important');
      }}
      if (legalTitle) legalTitle.style.setProperty('font-size', isIOSMode ? '14px' : '15.5px', 'important');
      if (legalBody) {{
        legalBody.style.setProperty('font-size', isIOSMode ? (hasAtts ? '13px' : '14.2px') : (hasAtts ? '15px' : '16.5px'), 'important');
        legalBody.style.setProperty('line-height', isIOSMode ? (hasAtts ? '1.65' : '1.85') : (hasAtts ? '2.0' : '2.25'), 'important');
      }}
      sigCells.forEach(function(td) {{
        td.style.setProperty('height', isIOSMode ? (hasAtts ? '64px' : '74px') : (hasAtts ? '88px' : '102px'), 'important');
        td.style.setProperty('padding', isIOSMode ? '5px' : '8px', 'important');
      }});
    }} else if (rowsCnt <= 8 && textLen <= 750 && sigCells.length <= 4) {{
      tblCells.forEach(function(td) {{
        td.style.setProperty('font-size', isIOSMode ? '11.5px' : '12px', 'important');
        td.style.setProperty('padding', isIOSMode ? '4px 6px' : '5px 8px', 'important');
      }});
      if (legal) legal.style.setProperty('padding', isIOSMode ? '8px 10px' : '12px 14px', 'important');
      if (legalBody) {{
        legalBody.style.setProperty('font-size', isIOSMode ? '12.5px' : '13.5px', 'important');
        legalBody.style.setProperty('line-height', isIOSMode ? '1.6' : '1.8', 'important');
      }}
    }}

    var fs = parseFloat((legalBody && legalBody.style.fontSize) || '11.5') || 11.5;
    var lh = parseFloat((legalBody && legalBody.style.lineHeight) || '1.45') || 1.45;
    var tfs = 11.0;
    var maxSteps = isIOSMode ? 18 : 14;
    var step = 0;

    while (sheet.scrollHeight > targetH && step < maxSteps) {{
      fs = Math.max(8.8, fs - 0.35);
      lh = Math.max(1.18, lh - 0.05);
      tfs = Math.max(8.8, tfs - 0.25);

      if (hdr) {{
        hdr.style.setProperty('padding', '0 0 3px 0', 'important');
        hdr.style.setProperty('margin-bottom', '4px', 'important');
      }}
      if (logo) {{
        logo.style.setProperty('width', '54px', 'important');
        logo.style.setProperty('height', '54px', 'important');
        logo.style.setProperty('max-width', '54px', 'important');
        logo.style.setProperty('max-height', '54px', 'important');
      }}
      if (hdrCenter) {{
        hdrCenter.style.setProperty('width', '54px', 'important');
        hdrCenter.style.setProperty('height', '54px', 'important');
        hdrCenter.style.setProperty('min-height', '54px', 'important');
      }}
      if (banner) {{
        banner.style.setProperty('padding', '3px 8px', 'important');
        banner.style.setProperty('margin', '0 0 4px 0', 'important');
        banner.style.setProperty('font-size', '12px', 'important');
      }}
      if (dataTbl) dataTbl.style.setProperty('margin-bottom', '4px', 'important');
      if (legal) {{
        legal.style.setProperty('flex', '0 1 auto', 'important');
        legal.style.setProperty('padding', '4px 7px', 'important');
        legal.style.setProperty('margin', '2px 0 4px 0', 'important');
      }}
      if (legalTitle) {{
        legalTitle.style.setProperty('font-size', (fs + 0.5) + 'px', 'important');
        legalTitle.style.setProperty('margin-bottom', '2px', 'important');
      }}
      if (legalBody) {{
        legalBody.style.setProperty('font-size', fs + 'px', 'important');
        legalBody.style.setProperty('line-height', String(lh), 'important');
      }}
      tblCells.forEach(function(td) {{
        td.style.setProperty('font-size', tfs + 'px', 'important');
        td.style.setProperty('padding', '2px 4px', 'important');
        td.style.setProperty('line-height', '1.2', 'important');
      }});
      if (attSec) {{
        attSec.style.setProperty('margin', '2px 0', 'important');
        attSec.style.setProperty('padding', '2px 5px', 'important');
      }}
      attImgs.forEach(function(im) {{
        im.style.setProperty('max-height', (step > 5 ? '44px' : '54px'), 'important');
      }});
      sigHeads.forEach(function(th) {{
        th.style.setProperty('font-size', '9.2px', 'important');
        th.style.setProperty('padding', '2px 4px', 'important');
        th.style.setProperty('line-height', '1.18', 'important');
      }});
      sigCells.forEach(function(td) {{
        td.style.setProperty('height', 'auto', 'important');
        td.style.setProperty('min-height', '34px', 'important');
        td.style.setProperty('padding', '2px 4px', 'important');
        td.style.setProperty('line-height', '1.18', 'important');
      }});
      sigImgs.forEach(function(im) {{
        im.style.setProperty('max-height', '32px', 'important');
      }});
      if (footerQr) {{
        footerQr.style.setProperty('margin-top', '3px', 'important');
        footerQr.style.setProperty('padding', '3px 6px', 'important');
      }}
      step++;
    }}

    var naturalH = sheet.scrollHeight;
    if (isIOSMode && isPrintMode && !skipCssZoom) {{
      sheet.style.setProperty('width', '100%', 'important');
    }}

    if (skipCssZoom) {{
      return;
    }}

    if (isPrintMode && naturalH > targetH) {{
      var z = Math.max(0.72, Math.floor((targetH / naturalH) * 1000) / 1000);
      sheet.style.setProperty('min-height', '0', 'important');
      sheet.style.setProperty('zoom', String(z), 'important');
      sheet.style.setProperty('margin', '0 auto', 'important');
    }} else if (isPrintMode) {{
      sheet.style.setProperty('height', targetH + 'px', 'important');
    }}
  }}

  function balanceSheetTypography(docRoot, targetH, isPrintMode, isIOSMode) {{
    applyToxicologyDirectorBlock(docRoot);
    var sheet = (docRoot.getElementById ? docRoot.getElementById('a4Sheet') : null)
      || (docRoot.querySelector ? docRoot.querySelector('#a4Sheet') : null);
    balanceSheetElement(sheet, targetH, isPrintMode, isIOSMode, false);
  }}

  applyToxicologyDirectorBlock(document);
  window.syncAllLivePads();
  balanceSheetTypography(document, 1045, false, false);

  // =========================================================
  // 4) شريط التكبير والتصغير السلس (5% إلى 200%)
  // =========================================================
  (function() {{
    window.addEventListener('resize', function(ev) {{
      ev.stopImmediatePropagation();
    }}, true);

    var sheetEl = document.getElementById('a4Sheet');
    if (!sheetEl) return;

    document.querySelectorAll('#zoomBar, .zoom-bar, #khafarPreviewZoomBar').forEach(function(b) {{ b.remove(); }});

    var bar = document.createElement('div');
    bar.id = 'zoomBar';
    bar.className = 'zoom-bar no-print';
    bar.innerHTML = ''
      + '<button type="button" class="khafar-z-btn" data-kz="-"> تصغير</button>'
      + '<span id="zoomPctLabel" data-kz="1" title="اضغط للعودة إلى 100%">100%</span>'
      + '<button type="button" class="khafar-z-btn" data-kz="+"> تكبير</button>'
      + '<button type="button" class="khafar-z-btn khafar-z-fit" data-kz="fit"> ملاءمة</button>';

    var viewport = document.getElementById('khafarZoomViewport');
    var sizer = document.getElementById('khafarZoomSizer');
    var canvasWrap = document.getElementById('khafarZoomCanvas');

    if (!viewport) {{
      viewport = document.createElement('div');
      viewport.id = 'khafarZoomViewport';
      sizer = document.createElement('div');
      sizer.id = 'khafarZoomSizer';
      canvasWrap = document.createElement('div');
      canvasWrap.id = 'khafarZoomCanvas';

      var parent = sheetEl.parentNode;
      parent.insertBefore(bar, sheetEl);
      parent.insertBefore(viewport, sheetEl);
      canvasWrap.appendChild(sheetEl);
      sizer.appendChild(canvasWrap);
      viewport.appendChild(sizer);
    }}

    balanceSheetTypography(document, 1045, false, false);

    var curScale = 1;
    var lastWinW = window.innerWidth || 0;

    window.__syncKhafarFrameHeight = function() {{
      try {{
        if (window.frameElement) {{
          var rect = viewport.getBoundingClientRect();
          var totalH = Math.ceil((window.pageYOffset || document.documentElement.scrollTop || 0) + rect.top + sizer.offsetHeight + 36);
          if (totalH > 350) {{
            window.frameElement.style.height = totalH + 'px';
          }}
        }}
      }} catch (e) {{}}
    }};

    window.__applyPreviewScale = function(val) {{
      curScale = Math.max(0.05, Math.min(2.0, Math.round(val * 100) / 100));
      sheetEl.style.setProperty('zoom', '1', 'important');
      sheetEl.style.setProperty('transform', 'none', 'important');

      var natW = 794;
      var natH = Math.max(sheetEl.offsetHeight || 0, sheetEl.scrollHeight || 0, 1045);

      canvasWrap.style.setProperty('transform', 'scale(' + curScale + ')', 'important');
      sizer.style.setProperty('width', Math.ceil(natW * curScale) + 'px', 'important');
      sizer.style.setProperty('height', Math.ceil(natH * curScale + 6) + 'px', 'important');

      var lbl = document.getElementById('zoomPctLabel');
      if (lbl) lbl.textContent = Math.round(curScale * 100) + '%';

      setTimeout(window.__syncKhafarFrameHeight, 40);
    }};

    function fitStageToScreen() {{
      var availW = (viewport.clientWidth || document.documentElement.clientWidth || window.innerWidth || 794) - 8;
      var ratio = Math.min(1.0, availW / 794);
      window.__applyPreviewScale(ratio);
    }}

    bar.querySelectorAll('[data-kz]').forEach(function(btn) {{
      btn.addEventListener('click', function(ev) {{
        ev.preventDefault();
        ev.stopPropagation();
        var act = btn.getAttribute('data-kz');
        if (act === '+') window.__applyPreviewScale(curScale + 0.10);
        else if (act === '-') window.__applyPreviewScale(curScale - 0.05);
        else if (act === 'fit') fitStageToScreen();
        else window.__applyPreviewScale(parseFloat(act) || 1);
      }});
    }});

    if ((window.innerWidth || 900) < 820) {{
      setTimeout(fitStageToScreen, 80);
    }} else {{
      setTimeout(function() {{ window.__applyPreviewScale(1.0); }}, 80);
    }}

    window.addEventListener('orientationchange', function() {{
      setTimeout(function() {{
        if (Math.abs((window.innerWidth || 0) - lastWinW) > 40) {{
          lastWinW = window.innerWidth || 0;
          if (lastWinW < 820) fitStageToScreen();
        }}
      }}, 220);
    }});
  }})();

  // =========================================================
  // 5) محرك توليد ومشاركة ملف PDF الحقيقي للآيفون (يعمل في وضع التطبيق المثبت Standalone)
  // =========================================================
  function loadExternalScript(url) {{
    return new Promise(function(resolve) {{
      var s = document.createElement('script');
      s.src = url;
      s.onload = function() {{ resolve(true); }};
      s.onerror = function() {{ resolve(false); }};
      document.head.appendChild(s);
    }});
  }}

  function ensurePdfLibraries() {{
    var tasks = [];
    if (!(window.jspdf && window.jspdf.jsPDF) && !window.jsPDF) {{
      tasks.push(loadExternalScript('https://cdn.jsdelivr.net/npm/jspdf@2.5.1/dist/jspdf.umd.min.js'));
    }}
    if (!(window.modernScreenshot && window.modernScreenshot.domToJpeg) && !window.html2canvas) {{
      tasks.push(loadExternalScript('https://cdn.jsdelivr.net/npm/modern-screenshot@4.6.0/dist/index.js'));
      tasks.push(loadExternalScript('https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js'));
    }}
    return Promise.all(tasks);
  }}

  function getShareCapableWindow() {{
    var wins = [];
    try {{
      if (window.top && window.top.navigator && typeof window.top.navigator.share === 'function') wins.push(window.top);
    }} catch (e) {{}}
    try {{
      if (window.parent && window.parent !== window.top && window.parent.navigator && typeof window.parent.navigator.share === 'function') wins.push(window.parent);
    }} catch (e) {{}}
    if (window.navigator && typeof window.navigator.share === 'function') wins.push(window);

    for (var i = 0; i < wins.length; i++) {{
      var w = wins[i];
      try {{
        var b = new w.Blob(['%PDF-1.4'], {{ type: 'application/pdf' }});
        var f = new w.File([b], 'test.pdf', {{ type: 'application/pdf' }});
        if (!w.navigator.canShare || w.navigator.canShare({{ files: [f] }})) {{
          return w;
        }}
      }} catch (e) {{}}
    }}
    return wins[0] || null;
  }}

  function extractCleanPdfFileName() {{
    var numMatch = (document.getElementById('a4Sheet') ? document.getElementById('a4Sheet').textContent : '').match(/\b(4\d{{7,11}}|KHF-[A-Z0-9]+|\d{{6,10}})\b/);
    var suffix = numMatch ? numMatch[1] : String(Date.now()).slice(-6);
    return 'Maroor_AlArdah_' + suffix + '.pdf';
  }}

  function buildOfficialPdfArrayBuffer() {{
    applyToxicologyDirectorBlock(document);
    window.syncAllLivePads();

    return ensurePdfLibraries().then(function() {{
      var origSheet = document.getElementById('a4Sheet');
      var stage = document.createElement('div');
      stage.style.cssText = 'position:fixed;top:0;right:0;width:794px;background:#ffffff;z-index:-9999;opacity:1;pointer-events:none;margin:0;padding:0;direction:rtl;';

      var clone = origSheet.cloneNode(true);
      clone.id = 'a4SheetPdfCapture';
      clone.style.cssText += ';width:794px !important;min-width:794px !important;max-width:794px !important;zoom:1 !important;transform:none !important;margin:0 !important;background:#ffffff !important;direction:rtl !important;font-family:Cairo,-apple-system,Tahoma,Arial,sans-serif !important;';

      origSheet.querySelectorAll('img[id^="slot_"]').forEach(function(liveSlot) {{
        var cSlot = clone.querySelector('#' + liveSlot.id);
        if (liveSlot && cSlot && liveSlot.getAttribute('src')) {{
          cSlot.setAttribute('src', liveSlot.getAttribute('src'));
          cSlot.setAttribute('style', liveSlot.getAttribute('style') || 'display:block !important; max-height:48px !important;');
        }}
      }});

      // حذف أي عنصر صورة فارغ أو مخفي حتى لا يتأخر محرك الرسم في iOS WebKit
      clone.querySelectorAll('img').forEach(function(im) {{
        var s = (im.getAttribute('src') || '').trim();
        var disp = (im.style && im.style.display) || '';
        if (!s || s.length < 12 || disp === 'none') {{
          im.remove();
        }}
      }});

      stage.appendChild(clone);
      document.body.appendChild(stage);
      balanceSheetElement(clone, 1085, true, false, true);

      return new Promise(function(resolve) {{ setTimeout(resolve, 70); }}).then(function() {{
        var capturePromise;
        if (window.modernScreenshot && window.modernScreenshot.domToJpeg) {{
          capturePromise = window.modernScreenshot.domToJpeg(clone, {{ scale: 0.5, quality: 0.5, backgroundColor: '#ffffff' }})
            .catch(function() {{ return null; }})
            .then(function() {{
              return window.modernScreenshot.domToJpeg(clone, {{ scale: 2.2, quality: 0.92, backgroundColor: '#ffffff' }});
            }});
        }} else {{
          capturePromise = Promise.reject(new Error('modernScreenshot unavailable'));
        }}

        return capturePromise.catch(function() {{
          if (!window.html2canvas) throw new Error('PDF capture library unavailable');
          var lb = clone.querySelector('.legal-box-body');
          if (lb) {{
            lb.style.setProperty('text-align', 'right', 'important');
            lb.style.setProperty('letter-spacing', '0px', 'important');
          }}
          return window.html2canvas(clone, {{
            scale: 2,
            useCORS: true,
            backgroundColor: '#ffffff',
            logging: false
          }}).then(function(cv) {{
            return cv.toDataURL('image/jpeg', 0.92);
          }});
        }}).then(function(imgDataUrl) {{
          var cW = clone.offsetWidth || 794;
          var cH = Math.max(clone.offsetHeight || 0, clone.scrollHeight || 0, 1085);
          stage.remove();

          var JsPdfCtor = (window.jspdf && window.jspdf.jsPDF) || window.jsPDF;
          var pdf = new JsPdfCtor({{ orientation: 'portrait', unit: 'mm', format: 'a4', compress: true }});
          var pageW = 210, pageH = 297, margin = 4.5;
          var maxW = pageW - margin * 2;
          var maxH = pageH - margin * 2;
          var ratio = cW / cH;
          var drawW = maxW;
          var drawH = drawW / ratio;
          if (drawH > maxH) {{
            drawH = maxH;
            drawW = drawH * ratio;
          }}
          var x = (pageW - drawW) / 2;
          var y = margin;
          pdf.addImage(imgDataUrl, 'JPEG', x, y, drawW, drawH, undefined, 'FAST');
          return pdf.output('arraybuffer');
        }}).catch(function(err) {{
          try {{ stage.remove(); }} catch (e) {{}}
          throw err;
        }});
      }});
    }});
  }}

  // استدعاء متزامن فوري (0ms) لقائمة مشاركة الآيفون بدون أي تأخير
  function triggerIosNativeShareSync(ab, fileName) {{
    var shareWin = getShareCapableWindow();
    if (!shareWin) return Promise.reject(new Error('WebShareUnavailable'));
    var blob = new shareWin.Blob([ab], {{ type: 'application/pdf' }});
    var file = new shareWin.File([blob], fileName, {{ type: 'application/pdf', lastModified: Date.now() }});
    return shareWin.navigator.share({{ files: [file] }});
  }}

  // طباعة مباشرة عبر النافذة العليا عند الحاجة داخل وضع التطبيق المثبت
  function triggerIosTopWindowPrint() {{
    try {{
      applyToxicologyDirectorBlock(document);
      window.syncAllLivePads();
      var topDoc = (window.top && window.top.document) ? window.top.document : null;
      if (topDoc) {{
        var oldRoot = topDoc.getElementById('khafarTopIosPrintHost');
        if (oldRoot) oldRoot.remove();
        var host = topDoc.createElement('div');
        host.id = 'khafarTopIosPrintHost';

        var styles = '';
        document.querySelectorAll('style, link[rel="stylesheet"]').forEach(function(n) {{ styles += n.outerHTML; }});

        var clone = document.getElementById('a4Sheet').cloneNode(true);
        document.querySelectorAll('#a4Sheet img[id^="slot_"]').forEach(function(ls) {{
          var cs = clone.querySelector('#' + ls.id);
          if (ls && cs && ls.getAttribute('src')) {{
            cs.setAttribute('src', ls.getAttribute('src'));
            cs.setAttribute('style', ls.getAttribute('style') || 'display:block !important; max-height:48px !important;');
          }}
        }});

        host.innerHTML = styles
          + '<style id="khafarTopMaskStyle">@media screen{{#khafarTopIosPrintHost{{display:none !important;}}}}@media print{{body>*:not(#khafarTopIosPrintHost){{display:none !important;}}#khafarTopIosPrintHost{{display:block !important;width:100% !important;background:#fff !important;}}}}</style>'
          + clone.outerHTML;
        topDoc.body.appendChild(host);
        balanceSheetElement(host.querySelector('#a4Sheet'), 795, true, true, false);
        window.top.focus();
        window.top.print();
        setTimeout(function() {{ try {{ host.remove(); }} catch (e) {{}} }}, 1500);
        return;
      }}
    }} catch (e) {{}}
    window.print();
  }}

  function showIosShareReadyTray(anchorBtn) {{
    var tray = document.getElementById('khafarIosShareTray');
    if (!tray) {{
      tray = document.createElement('div');
      tray.id = 'khafarIosShareTray';
      tray.className = 'no-print';

      var safariHref = '';
      try {{
        var topUrl = (window.top && window.top.location && window.top.location.href) ? window.top.location.href : window.location.href;
        if (topUrl.indexOf('https://') === 0) {{
          safariHref = 'x-safari-' + topUrl;
        }}
      }} catch (e) {{}}

      tray.innerHTML = ''
        + '<button type="button" class="ios-ready-main-btn" id="khafarIosShareNowBtn"> اضغط هنا لإرسال ومشاركة ملف الـ PDF الجاهز (واتساب / حفظ)</button>'
        + '<div class="ios-ready-sub-row">'
        + '<button type="button" class="ios-ready-sec-btn" id="khafarIosDirectPrintBtn"> طباعة مباشرة (AirPrint)</button>'
        + (safariHref ? '<a class="ios-ready-sec-btn" href="' + safariHref + '" target="_top"> فتح في Safari</a>' : '')
        + '</div>';

      anchorBtn.parentNode.insertBefore(tray, anchorBtn.nextSibling);

      document.getElementById('khafarIosShareNowBtn').addEventListener('click', function(e) {{
        e.preventDefault();
        e.stopPropagation();
        if (!window.__cachedIosPdfAb) return;
        triggerIosNativeShareSync(window.__cachedIosPdfAb, window.__cachedIosPdfName).catch(function(err) {{
          if (err && err.name === 'AbortError') return;
          triggerIosTopWindowPrint();
        }});
      }});

      document.getElementById('khafarIosDirectPrintBtn').addEventListener('click', function(e) {{
        e.preventDefault();
        e.stopPropagation();
        triggerIosTopWindowPrint();
      }});
    }}
    tray.style.display = 'flex';
    if (typeof window.__syncKhafarFrameHeight === 'function') {{
      setTimeout(window.__syncKhafarFrameHeight, 50);
    }}
  }}

  // =========================================================
  // 6) زر الطباعة والمشاركة الرئيسي (الأندرويد والكمبيوتر كما هما والآيفون عبر ملف PDF الحقيقي)
  // =========================================================
  var oldBtn = document.querySelector('#printOfficialBtn') || document.querySelector('.print-btn');
  if (oldBtn) {{
    var newBtn = oldBtn.cloneNode(true);
    oldBtn.parentNode.replaceChild(newBtn, oldBtn);
    var origBtnHtml = newBtn.innerHTML;

    newBtn.addEventListener('click', function(ev) {{
      ev.preventDefault();
      ev.stopPropagation();

      applyToxicologyDirectorBlock(document);
      window.syncAllLivePads();

      var isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

      // على الآيفون (سواء تطبيق مثبت على الشاشة الرئيسية أو متصفح): مشاركة ملف PDF حقيقي بصفحة 1/1
      if (isIOS) {{
        // إذا كان الملف مجهزا مسبقا ولم يتغير التوقيع افتح قائمة مشاركة الآيفون فورا في 0ms!
        if (window.__cachedIosPdfAb) {{
          triggerIosNativeShareSync(window.__cachedIosPdfAb, window.__cachedIosPdfName).catch(function(err) {{
            if (err && err.name === 'AbortError') return;
            showIosShareReadyTray(newBtn);
          }});
          return;
        }}

        newBtn.disabled = true;
        newBtn.innerHTML = ' جاري تجهيز ملف PDF الرسمي (صفحة 1/1)...';

        var pdfName = extractCleanPdfFileName();
        buildOfficialPdfArrayBuffer().then(function(ab) {{
          window.__cachedIosPdfAb = ab;
          window.__cachedIosPdfName = pdfName;
          newBtn.disabled = false;
          newBtn.innerHTML = origBtnHtml;

          // محاولة فتح قائمة مشاركة الآيفون تلقائيا فور الجاهزية
          triggerIosNativeShareSync(ab, pdfName).catch(function(err) {{
            if (err && err.name === 'AbortError') return;
            // في حال انتهت مهلة النقرة في iOS أظهر زر الإرسال الفوري الجاهز أمام الفرد
            showIosShareReadyTray(newBtn);
          }});
        }}).catch(function() {{
          newBtn.disabled = false;
          newBtn.innerHTML = origBtnHtml;
          triggerIosTopWindowPrint();
        }});
        return;
      }}

      // على الأندرويد والكمبيوتر: المسار السريع المخفي كما هو بدون أي تغيير
      var targetH = 1042;
      var sheetClone = document.getElementById('a4Sheet').cloneNode(true);
      sheetClone.style.zoom = '1';
      sheetClone.style.transform = 'none';
      sheetClone.style.width = '100%';

      document.querySelectorAll('#a4Sheet img[id^="slot_"]').forEach(function(liveSlot) {{
        var cloneSlot = sheetClone.querySelector('#' + liveSlot.id);
        if (liveSlot && cloneSlot && liveSlot.getAttribute('src')) {{
          cloneSlot.setAttribute('src', liveSlot.getAttribute('src'));
          cloneSlot.setAttribute('style', liveSlot.getAttribute('style') || 'display:block !important; max-height:48px !important;');
        }}
      }});

      var stylesHtml = '';
      document.querySelectorAll('style, link[rel="stylesheet"]').forEach(function(node) {{
        stylesHtml += node.outerHTML;
      }});

      var printDocHtml = '<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8">'
        + '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        + '<title>وثيقة رسمية - قسم مرور العارضة</title>'
        + stylesHtml
        + '</head><body>'
        + sheetClone.outerHTML
        + '</body></html>';

      var ifr = document.getElementById('khafarHiddenPrintFrame');
      if (ifr) ifr.remove();
      ifr = document.createElement('iframe');
      ifr.id = 'khafarHiddenPrintFrame';
      ifr.style.cssText = 'position:fixed;right:0;bottom:0;width:748px;height:1123px;opacity:0;pointer-events:none;border:0;z-index:-9999;';
      document.body.appendChild(ifr);
      var idoc = ifr.contentWindow.document;
      idoc.open();
      idoc.write(printDocHtml);
      idoc.close();
      setTimeout(function() {{
        try {{ balanceSheetTypography(idoc, targetH, true, false); }} catch (e) {{}}
        ifr.contentWindow.focus();
        ifr.contentWindow.print();
      }}, 420);
    }});
  }}
}})();
</script>
</body>
</html>
"""


# =====================================================================
# 6. إدارة حالة الجلسة والتنقل
# =====================================================================
init_db()
init_takmeel_db()
_device_uid, DEVICE_HASH = ensure_device_identity()
_cookie_uid_ready = bool(read_device_uid())
_wipe_shift = bool(st.session_state.get("wipe_device_shift"))
if DEVICE_HASH and not _wipe_shift and not device_shift_exists(DEVICE_HASH):
    _cookie_shift = shift_from_cookie()
    if _cookie_shift:
        save_device_shift(DEVICE_HASH, _cookie_shift)
consume_live_gps_query(DEVICE_HASH)
if DEVICE_HASH and st.session_state.get("pending_live_gps"):
    update_default_gps(DEVICE_HASH, str(st.session_state.pop("pending_live_gps")))
    st.session_state["gps_live_ok"] = True
shift = get_device_shift(DEVICE_HASH)
if shift.get(DUTY_SIG_KEY):
    st.session_state[DUTY_SIG_KEY] = shift.get(DUTY_SIG_KEY) or ""
elif DUTY_SIG_KEY not in st.session_state:
    st.session_state[DUTY_SIG_KEY] = ""
_mirror_shift = shift if (DEVICE_HASH and device_shift_exists(DEVICE_HASH) and not _wipe_shift) else None
render_device_bootstrap(
    _cookie_uid_ready,
    _mirror_shift,
    _wipe_shift,
    duty_sig_b64=str(shift.get(DUTY_SIG_KEY) or ""),
    preferred_uid=_device_uid,
)
if _wipe_shift:
    st.session_state.pop("wipe_device_shift", None)
    st.session_state[DUTY_SIG_KEY] = ""
logo_b64_global = get_traffic_logo_b64()
now_ksa = datetime.now(KSA_TZ)

unit_display = format_entity(shift["officer_rank"], shift["officer_name"])
duty_display = format_entity(shift["duty_rank"], shift["duty_name"])
saved_officer_sig = str(shift.get(DUTY_SIG_KEY) or st.session_state.get(DUTY_SIG_KEY) or "").strip()

VALID_NAV_TABS = ["النماذج الميدانية", "الأرشيف المحلي", "الإعدادات والبصمة"]
NAV_ALIASES = {
    "مناوبة الخفر": "الإعدادات والبصمة",
    "بصمة الشحن OTG": "الإعدادات والبصمة",
}
_DECL_FORM_COUNT = sum(1 for _f in TRAFFIC_FORMS.values() if _f.get("category") == "إقرار")
_DECL_TAB_LABEL = f"✍️ الإقرارات الميدانية ({_DECL_FORM_COUNT})"
CATEGORY_TAB_MAP = {
    _DECL_TAB_LABEL: "إقرار",
    "🚓 المحاضر النظامية (5)": "محضر",
    "🚑 الطبية والجنائية (3)": "إحالة طبية",
    "📊 التكميل (4)": "تكميل",
}
CATEGORY_TAB_ALIASES = {
    "✍️ الإقرارات الميدانية (6)": _DECL_TAB_LABEL,
    "✍️ الإقرارات الميدانية (7)": _DECL_TAB_LABEL,
}

if "nav_tab" not in st.session_state:
    st.session_state.nav_tab = "النماذج الميدانية"
# ترحيل التبويبات القديمة إلى الشريط الأفقي المدمج
if st.session_state.nav_tab in NAV_ALIASES:
    st.session_state.nav_tab = NAV_ALIASES[st.session_state.nav_tab]
if st.session_state.nav_tab not in VALID_NAV_TABS:
    st.session_state.nav_tab = "النماذج الميدانية"
# توافق عنوان تبويب الإقرارات بعد زيادة العدد من (6) إلى (7)
if st.session_state.get("forms_category_tab") in CATEGORY_TAB_ALIASES:
    st.session_state.forms_category_tab = CATEGORY_TAB_ALIASES[st.session_state.forms_category_tab]
if st.session_state.get("active_category_tab") in CATEGORY_TAB_ALIASES:
    st.session_state.active_category_tab = CATEGORY_TAB_ALIASES[st.session_state.active_category_tab]
if "opened_form_id" not in st.session_state:
    st.session_state.opened_form_id = None
# إزالة فلتر «جميع النماذج» القديم إن وُجد في الجلسة
if "catalog_filter" in st.session_state:
    del st.session_state["catalog_filter"]
if "doc_no" not in st.session_state:
    st.session_state.doc_no = f"KH-{now_ksa.strftime('%y%m%d-%H%M%S')}"
if "auto_doc_no" not in st.session_state:
    st.session_state.auto_doc_no = st.session_state.doc_no
if "manual_ref_no" not in st.session_state:
    st.session_state.manual_ref_no = ""
# إن وُجد رقم يدوي محفوظ سابقاً فلا يُستبدل بالتلقائي عند إعادة التشغيل
if str(st.session_state.get("manual_ref_no") or "").strip():
    st.session_state.doc_no = normalize_western_digits(str(st.session_state.manual_ref_no).strip())
if "doc_time" not in st.session_state:
    st.session_state.doc_time = now_ksa.strftime("%Y/%m/%d - %H:%M")
if "citizen_locked" not in st.session_state:
    st.session_state.citizen_locked = False
if "citizen_stamp_b64" not in st.session_state:
    st.session_state.citizen_stamp_b64 = ""
if "citizen_auth_mode" not in st.session_state:
    st.session_state.citizen_auth_mode = ""
if "party_stamps" not in st.session_state:
    st.session_state.party_stamps = {}
if "live_sig_pads" not in st.session_state:
    st.session_state.live_sig_pads = {}
# استهلاك جسر التوقيع الحي مبكراً قبل بناء السجل/أزرار الحفظ والتنزيل
_consume_live_sig_bridge()
if "officer_approved" not in st.session_state:
    st.session_state.officer_approved = False
if "officer_stamp_b64" not in st.session_state:
    st.session_state.officer_stamp_b64 = ""
if "officer_auth_mode" not in st.session_state:
    st.session_state.officer_auth_mode = "توقيع حي على الشاشة بالإصبع (لمستلم الخفر المناوب)"
if "duty_auth_mode" not in st.session_state:
    st.session_state.duty_auth_mode = "ختم المصادقة النظامي لوحدة الحوادث"
if "duty_stamp_b64" not in st.session_state:
    st.session_state.duty_stamp_b64 = ""
if "receiver_name" not in st.session_state:
    st.session_state.receiver_name = ""
if "receiver_role" not in st.session_state:
    st.session_state.receiver_role = RECEIVER_ROLE_OPTIONS[0]
if "officer_full_override" not in st.session_state:
    st.session_state.officer_full_override = ""
if "attachment_b64" not in st.session_state:
    st.session_state.attachment_b64 = ""
if "attachments" not in st.session_state:
    st.session_state.attachments = parse_attachments(st.session_state.attachment_b64)
elif st.session_state.attachment_b64 and not st.session_state.attachments:
    st.session_state.attachments = parse_attachments(st.session_state.attachment_b64)
if "show_attachments_in_print" not in st.session_state:
    st.session_state.show_attachments_in_print = True
if "scanner_model" not in st.session_state:
    st.session_state.scanner_model = "وضع المحاكاة متصل (معزول العتاد)"


def sync_attachments_to_session():
    """مزامنة قائمة المرفقات مع حقل Base64 المحفوظ في الجلسة وقاعدة البيانات."""
    items = st.session_state.get("attachments") or []
    st.session_state.attachments = items
    st.session_state.attachment_b64 = serialize_attachments(items)


def reset_doc_state():
    t_now = datetime.now(KSA_TZ)
    auto_no = f"KH-{t_now.strftime('%y%m%d-%H%M%S')}"
    st.session_state.auto_doc_no = auto_no
    st.session_state.manual_ref_no = ""
    st.session_state.doc_no = auto_no
    st.session_state.doc_time = t_now.strftime("%Y/%m/%d - %H:%M")
    st.session_state.citizen_locked = False
    st.session_state.citizen_stamp_b64 = ""
    st.session_state.citizen_auth_mode = ""
    st.session_state.party_stamps = {}
    st.session_state.live_sig_pads = {}
    st.session_state.officer_approved = False
    st.session_state.officer_stamp_b64 = ""
    st.session_state.officer_auth_mode = "توقيع حي على الشاشة بالإصبع (لمستلم الخفر المناوب)"
    st.session_state.duty_auth_mode = "ختم المصادقة النظامي لوحدة الحوادث"
    st.session_state.duty_stamp_b64 = ""
    st.session_state.receiver_name = ""
    st.session_state.receiver_role = RECEIVER_ROLE_OPTIONS[0]
    st.session_state.officer_full_override = ""
    st.session_state.attachments = []
    st.session_state.attachment_b64 = ""
    st.session_state.show_attachments_in_print = True
    st.session_state.att_upload_nonce = int(st.session_state.get("att_upload_nonce") or 0) + 1
    if "live_sig_bridge" in st.session_state:
        st.session_state.live_sig_bridge = ""
    # مسح مفاتيح إدخال الرقم المرجعي اليدوي المرتبطة بالنماذج
    for state_key in list(st.session_state.keys()):
        if str(state_key).startswith("manual_ref_inp_"):
            del st.session_state[state_key]


all_archived = search_records_db("", DEVICE_HASH, all_devices=True)
archive_count = len(all_archived)

header_logo_widget = (
    f"<div class='logo-frame'><img src='data:image/png;base64,{logo_b64_global}' alt='شعار المرور' /></div>"
    if logo_b64_global
    else "<div class='logo-frame' style='font-size:22px;'>🛡️</div>"
)

scanner_short = (st.session_state.scanner_model or "محاكاة").replace("وضع المحاكاة متصل (معزول العتاد)", "محاكاة")
if len(scanner_short) > 28:
    scanner_short = scanner_short[:26] + "…"


def form_short_hint(subtitle: str, max_words: int = 3) -> str:
    words = [w for w in (subtitle or "").split() if w]
    return " ".join(words[:max_words]) if words else ""


def open_form_from_catalog(fid: str):
    st.session_state.opened_form_id = fid
    reset_doc_state()
    safe_rerun()


def render_compact_form_buttons(category: str, primary: bool = False):
    """بطاقات نماذج مدمجة: أيقونة + اسم + وصف مختصر + سهم — تفتح بضغطة واحدة."""
    keys = [k for k, v in TRAFFIC_FORMS.items() if v["category"] == category]
    for fid in keys:
        f_item = TRAFFIC_FORMS[fid]
        hint = form_short_hint(f_item.get("subtitle", ""), 3)
        label = f"{f_item['icon']}  {f_item['title']}"
        if hint:
            label = f"{label}  ·  {hint}  ←"
        else:
            label = f"{label}  ←"
        if st.button(
            label,
            key=f"open_{fid}",
            type="primary" if primary else "secondary",
            use_container_width=True,
        ):
            open_form_from_catalog(fid)


# =====================================================================
# 7. الترويسة المدمجة + شريط الحالة الأفقي
# =====================================================================
gps_now = str(shift["default_gps"])
if st.session_state.get("gps_live_value") and not signed_gps_pair(gps_now):
    gps_now = str(st.session_state.get("gps_live_value"))
gps_is_live = bool(signed_gps_pair(gps_now)) or bool(st.session_state.get("gps_live_ok"))
gps_chip_text = (
    f"✅ موقع فعلي معتمد {gps_now}"
    if gps_is_live
    else f"GPS {gps_now}"
)
gps_maps = google_maps_url(gps_now)
gps_maps_html = (
    f"<a class='gps-map-link' href='{html.escape(gps_maps, quote=True)}' target='_blank' rel='noopener noreferrer'>خرائط</a>"
    if gps_maps else ""
)
st.markdown(f"""
<div class="khafar-top-header">
    <div class="header-brand-row">
        <div class="header-brand-inline">
            {header_logo_widget}
            <div class="official-5lines-compact">
                <div>المملكة العربية السعودية · وزارة الداخلية</div>
                <div>الأمن العام - الإدارة العامة للمرور</div>
                <div class="dept-line">إدارة مرور جازان · قسم مرور العارضة</div>
            </div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)
st.html(
    f"""
<div class="compact-status-bar">
    <span class="status-chip">🟢 محلي جاهز</span>
    <span class="status-chip gold">🧬 {html.escape(scanner_short)}</span>
    <span class="status-chip gps" id="khafar-gps-chip">{html.escape(gps_chip_text)}</span>
    {gps_maps_html}
    <button type="button" class="gps-locate-btn" id="khafar-gps-btn">📍 تحديد موقعي الفعلي</button>
    <span class="status-chip time">{now_ksa.strftime('%Y/%m/%d %H:%M')}</span>
</div>
<script>
(function () {{
  var root = window.top || window.parent || window;
  var doc = (root && root.document) ? root.document : document;
  function geoApi() {{
    return (root && root.navigator && root.navigator.geolocation)
      || (window.parent && window.parent.navigator && window.parent.navigator.geolocation)
      || navigator.geolocation;
  }}
  function applyCoords(lat, lon) {{
    try {{
      var u = new URL(root.location.href);
      u.searchParams.set("gps_lat", String(lat));
      u.searchParams.set("gps_lon", String(lon));
      u.searchParams.set("gps_ts", String(Date.now()));
      root.location.assign(u.toString());
    }} catch (err) {{
      var u2 = new URL(window.location.href);
      u2.searchParams.set("gps_lat", String(lat));
      u2.searchParams.set("gps_lon", String(lon));
      u2.searchParams.set("gps_ts", String(Date.now()));
      window.location.assign(u2.toString());
    }}
  }}
  function locate(btn) {{
    var geo = geoApi();
    var secure = false;
    try {{ secure = !!(root.isSecureContext || window.isSecureContext); }} catch (e) {{ secure = !!window.isSecureContext; }}
    if (!secure) {{
      btn.textContent = "يلزم HTTPS أو localhost لرصد الموقع";
      return;
    }}
    if (!geo) {{
      btn.textContent = "المتصفح لا يدعم تحديد الموقع";
      return;
    }}
    btn.disabled = true;
    btn.textContent = "⏳ جارِ رصد الموقع...";
    var onOk = function (pos) {{
      var lat = Number(pos.coords.latitude).toFixed(5);
      var lon = Number(pos.coords.longitude).toFixed(5);
      applyCoords(lat, lon);
    }};
    var onFailNetwork = function () {{
      btn.disabled = false;
      btn.textContent = "📍 تعذر الرصد — الصق رابط الخرائط من الإعدادات";
    }};
    var onFailFirst = function (err) {{
      var code = err && err.code;
      if (code === 2 || code === 3) {{
        btn.textContent = "⏳ محاولة ثانية عبر الشبكة...";
        geo.getCurrentPosition(onOk, onFailNetwork, {{
          enableHighAccuracy: false, timeout: 8000, maximumAge: 60000
        }});
        return;
      }}
      btn.disabled = false;
      btn.textContent = "📍 تعذر الرصد — اسمح بالموقع أو الصق رابط الخرائط";
    }};
    geo.getCurrentPosition(onOk, onFailFirst, {{
      enableHighAccuracy: true, timeout: 6000, maximumAge: 0
    }});
  }}
  function bind(btn) {{
    if (!btn || btn.dataset.khafarGpsBound === "1") return;
    btn.dataset.khafarGpsBound = "1";
    btn.addEventListener("click", function (ev) {{
      if (ev && ev.preventDefault) ev.preventDefault();
      locate(btn);
    }});
  }}
  function scan() {{
    bind(doc.getElementById("khafar-gps-btn"));
    try {{ bind(document.getElementById("khafar-gps-btn")); }} catch (e) {{}}
  }}
  scan();
  if (!root.__khafarGpsObserver) {{
    try {{
      root.__khafarGpsObserver = new MutationObserver(function () {{ scan(); }});
      root.__khafarGpsObserver.observe(doc.documentElement || doc.body, {{ childList: true, subtree: true }});
    }} catch (e) {{}}
  }}
  setTimeout(scan, 300);
  setTimeout(scan, 1200);
}})();
</script>
""",
    unsafe_allow_javascript=True,
)
if st.session_state.pop("gps_toast", None):
    st.toast("تم حفظ موقعك الفعلي في الشريط والتقرير.", icon="📍")
if st.session_state.pop("gps_toast_err", None):
    st.toast("تعذر قراءة إحداثي الموقع.", icon="⚠️")

nav_cols = st.columns(3)
nav_items = [
    ("النماذج الميدانية", "📋 النماذج"),
    ("الأرشيف المحلي", f"📁 الأرشيف ({archive_count})"),
    ("الإعدادات والبصمة", "⚙️ الإعدادات والبصمة"),
]
for idx, (tab_key, tab_label) in enumerate(nav_items):
    with nav_cols[idx]:
        is_active = st.session_state.nav_tab == tab_key
        if st.button(
            tab_label,
            key=f"nav_btn_{tab_key}",
            type="primary" if is_active else "secondary",
            use_container_width=True,
        ):
            st.session_state.nav_tab = tab_key
            if tab_key != "النماذج الميدانية":
                st.session_state.opened_form_id = None
            safe_rerun()

# =====================================================================
# القسم الأول: النماذج الميدانية (18 نموذجاً)
# =====================================================================
if st.session_state.nav_tab == "النماذج الميدانية":

    if st.session_state.opened_form_id is None:
        tab_decl, tab_min, tab_med, tab_tak = st.tabs(list(CATEGORY_TAB_MAP.keys()))
        with tab_decl:
            render_compact_form_buttons("إقرار", primary=False)
        with tab_min:
            render_compact_form_buttons("محضر", primary=False)
        with tab_med:
            render_compact_form_buttons("إحالة طبية", primary=False)
        with tab_tak:
            render_compact_form_buttons("تكميل", primary=False)

    else:
        fid = st.session_state.opened_form_id
        form_def = TRAFFIC_FORMS[fid]
        if form_def.get("category") == "تكميل":
            top_bar1, top_bar2 = st.columns([1.2, 2.8])
            with top_bar1:
                if st.button("↩️ العودة للنماذج", use_container_width=True, key="tak_back"):
                    st.session_state.opened_form_id = None
                    safe_rerun()
            with top_bar2:
                st.markdown(
                    f"<div class='badge-tak' style='display:inline-block;margin-top:8px'>"
                    f"📊 التكميل · {html.escape(form_def['title'])}</div>",
                    unsafe_allow_html=True,
                )
            render_takmeel_form(fid, logo_b64_global, shift)
        else:
            pending_prefill = st.session_state.pop("pending_form_prefill", None)
            if pending_prefill and pending_prefill.get("form_id") == fid:
                prefix = f"inp_{fid}_"
                for state_key in list(st.session_state.keys()):
                    if str(state_key).startswith(prefix):
                        del st.session_state[state_key]
                for key, value in (pending_prefill.get("values") or {}).items():
                    if value:
                        st.session_state[f"inp_{fid}_{key}"] = value
                pref_ref = normalize_western_digits(
                    str((pending_prefill.get("values") or {}).get("incident_no") or "").strip()
                )
                if pref_ref and form_uses_reference_number(form_def):
                    st.session_state[f"manual_ref_inp_{fid}"] = pref_ref
                    st.session_state.manual_ref_no = pref_ref
                    st.session_state.doc_no = pref_ref
            cat_badge_cls = {"إقرار": "green", "محضر": "gold", "إحالة طبية": "med", "تكميل": "tak"}.get(form_def["category"], "green")

            top_bar1, top_bar2, top_bar3 = st.columns([1.3, 1.3, 1.4])
            with top_bar1:
                if st.button("↩️ العودة للنماذج", use_container_width=True):
                    st.session_state.opened_form_id = None
                    safe_rerun()
            with top_bar2:
                if st.button("⚡ تعبئة بيانات تجريبية فورية", type="primary", use_container_width=True, disabled=st.session_state.citizen_locked):
                    for fld in form_def["fields"]:
                        st.session_state[f"inp_{fid}_{fld['key']}"] = fld["sample"]
                    if form_uses_reference_number(form_def):
                        primary_ref = form_primary_ref_field_key(form_def)
                        sample_ref = ""
                        for fld in form_def["fields"]:
                            if fld.get("key") == primary_ref:
                                sample_ref = str(fld.get("sample") or "")
                                break
                        sample_ref = normalize_western_digits(sample_ref.strip())
                        st.session_state[f"manual_ref_inp_{fid}"] = sample_ref
                        st.session_state.manual_ref_no = sample_ref
                        if sample_ref:
                            st.session_state.doc_no = sample_ref
                    safe_rerun()
            with top_bar3:
                if st.button("🆕 تفريغ وبدء سجل جديد", use_container_width=True):
                    for fld in form_def["fields"]:
                        wkey = f"inp_{fid}_{fld['key']}"
                        if wkey in st.session_state:
                            del st.session_state[wkey]
                    reset_doc_state()
                    safe_rerun()

            # مزامنة الرقم المرجعي اليدوي قبل عرض الترويسة
            if form_uses_reference_number(form_def):
                _ref_widget_key = f"manual_ref_inp_{fid}"
                if _ref_widget_key not in st.session_state:
                    st.session_state[_ref_widget_key] = str(st.session_state.get("manual_ref_no") or "")
                _raw_ref = str(st.session_state.get(_ref_widget_key) or "")
                _norm_ref = normalize_western_digits(_raw_ref.strip())
                if _raw_ref.strip() and _raw_ref != _norm_ref:
                    st.session_state[_ref_widget_key] = _norm_ref
                sync_doc_no_with_manual_ref(_norm_ref)

            st.markdown(f"""
            <div class="hero-shift-card" style="padding:16px 20px; margin-top:8px;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;">
                    <div>
                        <span class="badge-{cat_badge_cls}">قسم مرور العارضة</span>
                        <h3 style="margin:6px 0 2px 0; color:#ffffff; font-size:20px;">{form_def['icon']} {_form_display_title(form_def, {k: st.session_state.get(f'inp_{fid}_{k}', '') for k in ('cases_mode', 'deceased_count', 'party_count')}, fid)}</h3>
                        <div style="font-size:13px; color:#f3cc7a; font-weight:700;">{form_def.get('official_title', '')}</div>
                    </div>
                    <div style="font-size:12.5px; color:#d4a853; font-weight:700;">
                        الرقم المرجعي: {st.session_state.doc_no}  |  {st.session_state.doc_time}
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            if form_uses_reference_number(form_def):
                st.text_input(
                    "رقم مرجعي (إدخال يدوي)",
                    key=f"manual_ref_inp_{fid}",
                    placeholder="أدخل الرقم المرجعي الخاص بك",
                    disabled=st.session_state.citizen_locked,
                    help="يُعتمد هذا الرقم في ترويسة الوثيقة والخطاب والمعاينة والطباعة والأرشيف. تُحوَّل الأرقام العربية تلقائياً إلى إنجليزية.",
                )
                _typed_raw = str(st.session_state.get(f"manual_ref_inp_{fid}") or "")
                _typed_ref = normalize_western_digits(_typed_raw.strip())
                if _typed_raw.strip() and _typed_raw != _typed_ref:
                    # تطبيع الأرقام العربية بعد الإدخال ثم إعادة العرض
                    st.session_state[f"manual_ref_inp_{fid}"] = _typed_ref
                    sync_doc_no_with_manual_ref(_typed_ref)
                    safe_rerun()
                sync_doc_no_with_manual_ref(_typed_ref)
                st.caption("اتركه فارغاً للإبقاء على الرقم التلقائي للجلسة، أو اكتب رقمك ليُعتمد فوراً في الوثيقة.")

            if st.session_state.citizen_locked:
                lk1, lk2 = st.columns([3.8, 1.2])
                with lk1:
                    st.markdown("""
                    <div class="lock-emerald-banner">
                        🔒 تم قفل جميع الحقول النصية نهائياً لمنع أي تعديل لاحق على الوثيقة الرسمية.
                    </div>
                    """, unsafe_allow_html=True)
                with lk2:
                    if st.button("🔓 فك القفل (يمسح البصمة)", use_container_width=True):
                        st.session_state.citizen_locked = False
                        st.session_state.citizen_stamp_b64 = ""
                        st.session_state.party_stamps = {}
                        st.session_state.live_sig_pads = {}
                        st.session_state.officer_approved = False
                        st.session_state.officer_stamp_b64 = ""
                        st.session_state.officer_auth_mode = "توقيع حي على الشاشة بالإصبع (لمستلم الخفر المناوب)"
                        st.session_state.duty_auth_mode = "ختم المصادقة النظامي لوحدة الحوادث"
                        st.session_state.duty_stamp_b64 = ""
                        safe_rerun()

            current_values = {}

            def _label_values_snapshot() -> dict:
                snap = dict(current_values)
                for peek_key in (
                    "cases_mode", "deceased_count", "party_count",
                    "waiver_status", "legal_mode", "other_injured", "other_deceased",
                ):
                    wpeek = f"inp_{fid}_{peek_key}"
                    if peek_key not in snap and wpeek in st.session_state:
                        snap[peek_key] = st.session_state[wpeek]
                return snap

            def render_field(fld):
                wkey = f"inp_{fid}_{fld['key']}"
                locked = st.session_state.citizen_locked
                if fld.get("prefill_sample") and wkey not in st.session_state:
                    st.session_state[wkey] = fld.get("sample", "")
                if fld.get("prefill_now") and wkey not in st.session_state:
                    st.session_state[wkey] = now_ksa.strftime("%Y/%m/%d - %H:%M")
                if fld.get("prefill_shift_gps") and wkey not in st.session_state:
                    gps_seed = str((shift or {}).get("default_gps") or "").strip()
                    waiting = gps_seed in ("", "بانتظار رصد الموقع") or "بانتظار" in gps_seed
                    if gps_seed and not waiting and signed_gps_pair(gps_seed):
                        st.session_state[wkey] = gps_seed
                label_now = _field_display_label(fid, fld, _label_values_snapshot())
                if fld["type"] == "select":
                    opts = fld["options"]
                    default_idx = opts.index(st.session_state[wkey]) if (wkey in st.session_state and st.session_state[wkey] in opts) else 0
                    return st.selectbox(label_now, options=opts, index=default_idx, key=wkey, disabled=locked)
                if fld["type"] == "textarea":
                    return st.text_area(label_now, key=wkey, height=88, disabled=locked)
                ph = fld.get("placeholder") or ""
                if fld.get("prefill_shift_gps") and not ph:
                    ph = "اكتب اسم الطريق وموقع الحادث"
                return st.text_input(
                    label_now,
                    key=wkey,
                    disabled=locked,
                    placeholder=ph,
                )

            _primary_ref_key = form_primary_ref_field_key(form_def) if form_uses_reference_number(form_def) else ""

            def _is_unified_ref_field(fld: dict) -> bool:
                """تخطّي حقل الرقم المرجعي القديم لصالح مربع الإدخال اليدوي الموحّد."""
                if not _primary_ref_key:
                    return False
                return str(fld.get("key") or "") == _primary_ref_key

            def render_field_grid(fields):
                visible_fields = [fld for fld in (fields or []) if not _is_unified_ref_field(fld)]
                if not visible_fields:
                    return
                columns = st.columns(2)
                for idx, fld in enumerate(visible_fields):
                    target = st.container() if fld["type"] == "textarea" else columns[idx % 2]
                    with target:
                        current_values[fld["key"]] = render_field(fld)
            if fid == "decl_handover":
                by_key = {fld["key"]: fld for fld in form_def["fields"]}
                current_values["receiver_role"] = render_field(by_key["receiver_role"])
                if _is_agent_role(current_values.get("receiver_role")):
                    for pair in (
                        ("agent_name", "agent_id"),
                        ("principal_name", "principal_id"),
                        ("wakala_no", "wakala_date"),
                    ):
                        pair_cols = st.columns(2)
                        for col, key in zip(pair_cols, pair):
                            with col:
                                current_values[key] = render_field(by_key[key])
                else:
                    render_field_grid([by_key["party_name"], by_key["party_id"]])
                render_field_grid([by_key[key] for key in ("party_phone", "vehicle_desc", "plate_no", "vehicle_state")])
            elif fid in {"decl_settlement", "decl_flee_waiver", "decl_animal_hit"}:
                pair_slot = 0
                pair_cols = None
                for fld in form_def["fields"]:
                    if _is_unified_ref_field(fld):
                        continue
                    if not _field_is_visible(fld, current_values):
                        continue
                    party_match = fld["key"][:2] if fld["key"].startswith("p") else ""
                    if fid == "decl_settlement" and fld["key"].endswith("_name") and party_match[1:2].isdigit():
                        ordinal = _PARTY_ORDINALS[int(fld["key"][1])]
                        st.markdown(f"**الطرف {ordinal}**")
                        pair_slot = 0
                    if fid == "decl_animal_hit" and fld["key"] == "owner_name":
                        st.markdown("**بيانات مالك الحيوان والتسوية**")
                        pair_slot = 0
                    if fld["type"] == "textarea" or fld.get("stack_under"):
                        current_values[fld["key"]] = render_field(fld)
                        pair_slot = 0
                        continue
                    if pair_slot % 2 == 0:
                        pair_cols = st.columns(2)
                    with pair_cols[pair_slot % 2]:
                        current_values[fld["key"]] = render_field(fld)
                    pair_slot += 1
                if fid == "decl_settlement":
                    st.caption("بعد اعتماد الوثيقة تظهر لوحة توقيع حي مستقلة لكل طرف مشمول، مع مستلم الخفر المناوب ووحدة الحوادث، داخل صفحة A4 واحدة.")
                elif fid == "decl_animal_hit":
                    st.caption("مجهول المالك: 3 خانات توقيع (السائق + مستلم الخفر المناوب + وحدة الحوادث). حضور المالك: 4 خانات بإضافة مالك الحيوان ولوحة توقيع حي.")
                else:
                    st.caption("بعد الاعتماد تُفتح لوحة توقيع المُبلّغ المتنازل، ولوحة الطرف المتسبب عند حضوره، بجانب مستلم الخفر المناوب ووحدة الحوادث.")
            else:
                pair_slot = 0
                pair_cols = None
                for fld in form_def["fields"]:
                    if _is_unified_ref_field(fld):
                        continue
                    if not _field_is_visible(fld, current_values):
                        continue
                    if fld["type"] == "textarea" or fld.get("stack_under"):
                        current_values[fld["key"]] = render_field(fld)
                        pair_slot = 0
                        continue
                    if pair_slot % 2 == 0:
                        pair_cols = st.columns(2)
                    with pair_cols[pair_slot % 2]:
                        current_values[fld["key"]] = render_field(fld)
                    pair_slot += 1

            for fld in form_def["fields"]:
                key = fld.get("key")
                if key and key in current_values and _should_normalize_digits(fld):
                    current_values[key] = normalize_western_digits(current_values.get(key) or "")

            # اعتماد الرقم المرجعي اليدوي في قيم النموذج والخطاب والترويسة
            _manual_now = normalize_western_digits(str(st.session_state.get("manual_ref_no") or "").strip())
            if form_uses_reference_number(form_def):
                sync_doc_no_with_manual_ref(_manual_now)
                current_values = apply_manual_reference(current_values, _manual_now, form_def)
                # إن وُجدت قيمة قديمة في session لحقل incident_no بدون إدخال يدوي، أبقِها كافتراضي
                if not _manual_now and _primary_ref_key:
                    legacy = st.session_state.get(f"inp_{fid}_{_primary_ref_key}")
                    if legacy and not current_values.get(_primary_ref_key):
                        current_values[_primary_ref_key] = normalize_western_digits(str(legacy).strip())
                        if _primary_ref_key != "incident_no":
                            current_values["incident_no"] = current_values[_primary_ref_key]

            if fid == "decl_hit_run":
                if st.button("🔄 الانتقال لإقرار تنازل عن بلاغ صدم وهروب", use_container_width=True):
                    st.session_state.pending_form_prefill = {
                        "form_id": "decl_flee_waiver",
                        "values": {
                            key: current_values.get(key) or ""
                            for key in ("incident_no", "party_name", "party_id", "party_phone", "plate_no")
                        },
                    }
                    open_form_from_catalog("decl_flee_waiver")

            att_label = (
                "📸 إرفاق صورة إشعار المخالفة (مطلوب لحوكمة الإلغاء بالهيئة المرورية)"
                if form_def["require_image"]
                else "📎 إرفاق صورة الهوية / التقرير الأولي أو مرفق داعم (اختياري)"
            )
            if "att_upload_nonce" not in st.session_state:
                st.session_state.att_upload_nonce = 0
            # خارج أي st.form حتى تظهر المعاينة فوراً على الجوال دون انتظار زر إرسال
            uploaded_files = st.file_uploader(
                att_label,
                type=ATTACH_TYPES,
                accept_multiple_files=True,
                disabled=st.session_state.citizen_locked,
                key=f"att_{st.session_state.doc_no}_{st.session_state.att_upload_nonce}",
                help="الصيغ المدعومة: PNG / JPG / JPEG / WEBP / PDF — تُصحَّح اتجاه كاميرا الجوال تلقائياً وتُصغَّر للرفع السريع.",
            )
            if uploaded_files and not st.session_state.citizen_locked:
                existing = list(st.session_state.get("attachments") or [])
                known = {attachment_fingerprint(a) for a in existing}
                added = 0
                for uf in uploaded_files:
                    item = process_uploaded_attachment(uf)
                    if not item:
                        st.warning(f"تعذّر معالجة المرفق: {getattr(uf, 'name', 'ملف')}")
                        continue
                    fp = attachment_fingerprint(item)
                    if fp in known:
                        continue
                    existing.append(item)
                    known.add(fp)
                    added += 1
                if added:
                    st.session_state.attachments = existing
                    sync_attachments_to_session()
                    st.session_state.att_upload_nonce = int(st.session_state.att_upload_nonce) + 1
                    st.toast(f"تم حفظ {added} مرفق في الجلسة", icon="📎")
                    st.rerun()

            st.checkbox(
                "إظهار المرفق المصور في التقرير المطبوع",
                key="show_attachments_in_print",
                help="عند التفعيل تُدرج الصور المرفوعة داخل ورقة A4 ونسخة الطباعة/PDF.",
            )

            persisted_atts = list(st.session_state.get("attachments") or [])
            if not persisted_atts and st.session_state.get("attachment_b64"):
                persisted_atts = parse_attachments(st.session_state.attachment_b64)
                st.session_state.attachments = persisted_atts

            if persisted_atts:
                st.markdown("##### 🖼️ معاينة المرفقات المحفوظة في الجلسة")
                for idx, att in enumerate(persisted_atts):
                    kind = (att.get("kind") or "image").lower()
                    mime = att.get("mime") or ("application/pdf" if kind == "pdf" else "image/png")
                    try:
                        raw_bytes = base64.b64decode(att.get("b64") or "")
                    except Exception:
                        raw_bytes = b""
                    c_prev, c_dl, c_del = st.columns([3, 1, 1])
                    with c_prev:
                        if kind == "pdf":
                            st.info(f"📄 مستند PDF: **{att.get('name', 'مرفق.pdf')}**")
                        elif raw_bytes:
                            st.image(raw_bytes, caption=att.get("name") or f"مرفق {idx + 1}", use_container_width=True)
                        else:
                            st.warning(f"تعذّر عرض المرفق: {att.get('name') or idx + 1}")
                    with c_dl:
                        st.download_button(
                            "⬇️ تحميل المرفق",
                            data=raw_bytes,
                            file_name=att.get("name") or f"attachment_{idx + 1}",
                            mime=mime,
                            key=f"dl_att_{st.session_state.doc_no}_{idx}_{attachment_fingerprint(att)[:8]}",
                            use_container_width=True,
                        )
                    with c_del:
                        if st.button(
                            "🗑️ حذف المرفق",
                            key=f"del_att_{st.session_state.doc_no}_{idx}_{attachment_fingerprint(att)[:8]}",
                            disabled=st.session_state.citizen_locked,
                            use_container_width=True,
                        ):
                            new_list = [a for i, a in enumerate(st.session_state.attachments) if i != idx]
                            st.session_state.attachments = new_list
                            sync_attachments_to_session()
                            st.rerun()
            elif form_def["require_image"]:
                st.caption("⚠️ هذا النموذج يتطلب إرفاق صورة قبل اعتماد الوثيقة.")

            live_legal_text = normalize_official_legal_text(form_def["legal_fn"](current_values))
            st.markdown(
                (
                    '<div class="legal-dark-box" dir="rtl" style="direction:rtl !important;text-align:justify !important;'
                    "text-justify:inter-word !important;text-align-last:right !important;line-height:1.9 !important;"
                    'width:100% !important;max-width:100% !important;box-sizing:border-box !important;'
                    'padding:14px 16px !important;overflow-wrap:anywhere !important;word-break:normal !important;'
                    'white-space:normal !important;">'
                    '<div class="legal-title" dir="rtl">⚖️ معاينة النص الرسمي المعتمد في الوثيقة:</div>'
                    '<div class="legal-body" dir="rtl" style="direction:rtl !important;unicode-bidi:embed !important;'
                    "text-align:justify !important;text-justify:inter-word !important;text-align-last:right !important;"
                    'line-height:1.9 !important;overflow-wrap:anywhere !important;white-space:normal !important;">'
                    f"\u200f{live_legal_text}</div></div>"
                ),
                unsafe_allow_html=True,
            )

            is_med_form = form_def["category"] == "إحالة طبية"
            is_letter_form = bool(form_def.get("is_official_letter"))
            s1_col, s2_col = st.columns(2)
            with s1_col:
                st.markdown("<div class='auth-panel'>", unsafe_allow_html=True)
                if is_letter_form:
                    recipient_title = form_def.get("recipient_role_title") or "المختص المستلم بحجز مرور أبو عريش"
                    role_options = [recipient_title]
                    st.markdown("#### 1️⃣ توقيع حي بالإصبع — المختص المستلم بحجز مرور أبو عريش")
                    st.caption("خانة التوقيع الحي مخصصة للمختص المستلم في حجز مرور محافظة أبو عريش.")
                    recv_name_key, recv_role_key = _receiver_widget_keys(fid)
                    if recv_name_key not in st.session_state:
                        legacy = st.session_state.get(f"receiver_name_{st.session_state.doc_no}")
                        st.session_state[recv_name_key] = legacy or st.session_state.receiver_name
                    if recv_role_key not in st.session_state or st.session_state[recv_role_key] not in role_options:
                        st.session_state[recv_role_key] = recipient_title
                    st.text_input(
                        "اسم المختص المستلم بحجز مرور أبو عريش",
                        key=recv_name_key,
                        disabled=st.session_state.citizen_locked,
                        placeholder="اسم المستلم في ساحة الحجز — أو يُترك فارغاً عند الحاجة",
                    )
                    st.selectbox(
                        "الصفة / جهة الاستلام",
                        options=role_options,
                        key=recv_role_key,
                        disabled=st.session_state.citizen_locked,
                    )
                    auth_opts = [
                        "توقيع حي على الشاشة بالإصبع (للمختص المستلم بحجز مرور أبو عريش)",
                        "بصمة منفذ الشحن (USB Type-C) للمختص المستلم",
                    ]
                elif is_med_form:
                    st.markdown("#### 1️⃣ توثيق خانة الاستلام (المستشفى / الثلاجة / المختبر)")
                    st.caption("افصل بيانات المناوب المستلم عن اسم المصاب/الحالة الظاهر في حقول النموذج أعلاه.")
                    recv_name_key, recv_role_key = _receiver_widget_keys(fid)
                    # ترحيل القيم من المفاتيح القديمة المرتبطة بـ doc_no المتغيّر
                    for legacy_key in (
                        f"receiver_name_{st.session_state.doc_no}",
                        f"receiver_name_{st.session_state.get('auto_doc_no')}",
                    ):
                        if recv_name_key not in st.session_state and legacy_key in st.session_state:
                            st.session_state[recv_name_key] = st.session_state.get(legacy_key) or ""
                    if recv_name_key not in st.session_state:
                        st.session_state[recv_name_key] = st.session_state.receiver_name
                    if recv_role_key not in st.session_state:
                        role_default = st.session_state.receiver_role if st.session_state.receiver_role in RECEIVER_ROLE_OPTIONS else RECEIVER_ROLE_OPTIONS[0]
                        st.session_state[recv_role_key] = role_default
                    st.text_input(
                        "اسم المناوب المستلم",
                        key=recv_name_key,
                        disabled=st.session_state.citizen_locked,
                        placeholder="مثال: فهد بن علي الحكمي — أو يُترك فارغاً عند الحاجة",
                    )
                    st.selectbox(
                        "الصفة / القسم",
                        options=RECEIVER_ROLE_OPTIONS,
                        key=recv_role_key,
                        disabled=st.session_state.citizen_locked,
                    )
                    auth_opts = [
                        "توقيع حي على الشاشة بالإصبع (للمختص المناوب المستلم)",
                        "تخصيص خانة ختم وتوقيع رسمي لجهة الاستلام بالورقة",
                        "بصمة منفذ الشحن (USB Type-C) للمرافق / المستلم",
                    ]
                else:
                    st.markdown("#### 1️⃣ بصمة / توقيع الطرف المعني (يقفل التعديل)")
                    auth_opts = [
                        "توقيع حي بالإصبع على الشاشة",
                        "بصمة منفذ الشحن (USB Type-C)",
                    ]
                    if form_def["allow_absence"]:
                        auth_opts.append("غياب الطرف / امتناع مثبت بالمحضر")

                chosen_auth = st.radio("وسيلة التوثيق المعتمدة:", auth_opts, disabled=st.session_state.citizen_locked)

                if not st.session_state.citizen_locked:
                    if is_letter_form:
                        btn_lbl = "✅ اعتماد الخطاب وقفل الحقول النصية"
                    elif is_med_form:
                        btn_lbl = "✅ اعتماد صيغة الإحالة وقفل الحقول النصية"
                    else:
                        btn_lbl = "🧬 اعتماد التوثيق وقفل الحقول النصية"
                    if st.button(btn_lbl, type="primary", use_container_width=True):
                        sync_attachments_to_session()
                        if form_def.get("require_image") and not (st.session_state.get("attachments") or []):
                            st.error("هذا النموذج يتطلب إرفاق صورة قبل اعتماد التوثيق.")
                        else:
                            if is_med_form or is_letter_form:
                                rk_name, rk_role = _receiver_widget_keys(fid)
                                st.session_state.receiver_name = (
                                    st.session_state.get(rk_name)
                                    or st.session_state.get(f"receiver_name_{st.session_state.doc_no}")
                                    or ""
                                ).strip()
                                fallback_role = form_def.get("recipient_role_title") if is_letter_form else RECEIVER_ROLE_OPTIONS[0]
                                st.session_state.receiver_role = (
                                    st.session_state.get(rk_role)
                                    or st.session_state.get(f"receiver_role_{st.session_state.doc_no}")
                                    or fallback_role
                                )
                            else:
                                st.session_state.receiver_name = ""
                                st.session_state.receiver_role = ""
                            if "بصمة منفذ الشحن" in chosen_auth:
                                party_signers = _waiver_signers(fid, current_values)
                                party_stamps = {}
                                if party_signers:
                                    for signer in party_signers:
                                        pad = signer["pad"]
                                        sid = _signer_id_for_pad(fid, pad, current_values)
                                        seed = f"{st.session_state.doc_no}_{sid}_{pad}_CITIZEN"
                                        party_stamps[pad] = generate_fingerprint_png_b64(seed, ink_rgb=(13, 71, 161))
                                    st.session_state.party_stamps = party_stamps
                                    st.session_state.citizen_stamp_b64 = party_stamps.get(party_signers[0]["pad"], "")
                                else:
                                    signer_id = (
                                        current_values.get("agent_id")
                                        or current_values.get("party_id")
                                        or current_values.get("p1_id")
                                        or current_values.get("observer_name")
                                        or ""
                                    )
                                    seed = f"{st.session_state.doc_no}_{signer_id}_CITIZEN"
                                    st.session_state.citizen_stamp_b64 = generate_fingerprint_png_b64(seed, ink_rgb=(13, 71, 161))
                                    st.session_state.party_stamps = {}
                                st.session_state.citizen_auth_mode = "بصمة منفذ الشحن (Type-C)"
                            elif "توقيع حي" in chosen_auth:
                                st.session_state.citizen_stamp_b64 = ""
                                st.session_state.party_stamps = {}
                                st.session_state.citizen_auth_mode = "توقيع حي على الشاشة"
                            elif "ختم وتوقيع" in chosen_auth:
                                st.session_state.citizen_stamp_b64 = ""
                                st.session_state.party_stamps = {}
                                st.session_state.citizen_auth_mode = "ختم وتوقيع جهة الاستلام الرسمية"
                            else:
                                st.session_state.citizen_stamp_b64 = ""
                                st.session_state.party_stamps = {}
                                st.session_state.citizen_auth_mode = "غياب الطرف / امتناع مثبت بالمحضر"
                            st.session_state.citizen_locked = True
                            safe_rerun()
                else:
                    st.success(f"تم القفل والتوثيق: {st.session_state.citizen_auth_mode}")
                    if is_med_form or is_letter_form:
                        shown_recv = st.session_state.receiver_name or "—"
                        recv_caption = "المختص المستلم بحجز أبو عريش" if is_letter_form else "المناوب المستلم"
                        st.caption(f"{recv_caption}: {shown_recv} | {st.session_state.receiver_role or '—'}")
                    if st.session_state.citizen_stamp_b64:
                        st.image(base64.b64decode(st.session_state.citizen_stamp_b64), caption="ختم البصمة الصوري المعتمد", width=105)
                st.markdown("</div>", unsafe_allow_html=True)

            with s2_col:
                st.markdown("<div class='auth-panel'>", unsafe_allow_html=True)
                is_toxicology_form = fid == "med_toxicology" or "تحليل سموم" in str(form_def.get("title") or "")
                if is_toxicology_form:
                    st.markdown("#### 2️⃣ مصادقة إدارة مرور منطقة جازان وتوثيق مستلم الخفر المناوب")
                    st.caption(f"التوثيق النصي لمستلم الخفر المناوب: {unit_display}")
                else:
                    st.markdown("#### 2️⃣ توثيق مستلم الخفر المناوب ومصادقة وحدة الحوادث")
                    st.caption(f"الإعدادات الافتراضية: {unit_display}  •  {duty_display}")

                _auth_sk = _stable_form_session_key()
                officer_name_key = f"officer_full_input_{_auth_sk}"
                if officer_name_key not in st.session_state:
                    st.session_state[officer_name_key] = st.session_state.officer_full_override or unit_display

                st.text_input(
                    "رتبة واسم مستلم الخفر المناوب",
                    key=officer_name_key,
                    disabled=st.session_state.officer_approved,
                    placeholder="مثال: الملازم فهد بن ...",
                )

                chosen_officer_auth = st.session_state.officer_auth_mode or "توقيع حي على الشاشة بالإصبع (لمستلم الخفر المناوب)"
                use_saved_officer_sig = False
                if not is_toxicology_form:
                    manual_sig_key = f"manual_officer_sig_{_auth_sk}"
                    if saved_officer_sig:
                        st.success("✅ تم إدراج توقيع مستلم الخفر المناوب المحفوظ من الإعدادات تلقائياً")
                        st.checkbox(
                            "✏️ التوقيع يدوياً لهذا النموذج فقط",
                            key=manual_sig_key,
                            help="فعّل هذا الخيار لرسم/بصمة مؤقتة دون المساس بالتوقيع المحفوظ في الإعدادات.",
                            disabled=st.session_state.officer_approved,
                        )
                        use_saved_officer_sig = not bool(st.session_state.get(manual_sig_key))
                        if use_saved_officer_sig and not st.session_state.officer_approved:
                            st.session_state.officer_stamp_b64 = saved_officer_sig
                            st.session_state.officer_auth_mode = "توقيع محفوظ من الإعدادات (تلقائي)"
                            chosen_officer_auth = st.session_state.officer_auth_mode
                        elif st.session_state.get(manual_sig_key) and st.session_state.officer_auth_mode == "توقيع محفوظ من الإعدادات (تلقائي)":
                            st.session_state.officer_stamp_b64 = ""
                            st.session_state.officer_auth_mode = "توقيع حي على الشاشة بالإصبع (لمستلم الخفر المناوب)"
                    if not use_saved_officer_sig:
                        officer_auth_opts = [
                            "توقيع حي على الشاشة بالإصبع (لمستلم الخفر المناوب)",
                            "بصمة رقمية (منفذ الشحن Type-C) لمستلم الخفر المناوب",
                        ]
                        officer_default_idx = 0
                        if "بصمة" in (st.session_state.officer_auth_mode or ""):
                            officer_default_idx = 1
                        chosen_officer_auth = st.radio(
                            "وسيلة توثيق مستلم الخفر المناوب:",
                            officer_auth_opts,
                            index=officer_default_idx,
                            key=f"officer_auth_radio_{_auth_sk}",
                            disabled=st.session_state.officer_approved or not st.session_state.citizen_locked,
                        )

                _form_sk = _stable_form_session_key()
                manager_auto_now, manager_cfg_now = manager_auto_signature_active()
                if manager_auto_now:
                    chosen_duty_auth = MANAGER_AUTH_MODE
                    st.session_state.duty_auth_mode = MANAGER_AUTH_MODE
                    st.session_state.duty_stamp_b64 = str(manager_cfg_now.get("manager_sig_b64") or "")
                    st.success(
                        f"✅ توقيع مدير وحدة الحوادث يُدرج تلقائياً في خانة الاعتماد: "
                        f"{manager_cfg_now.get('display_name') or DEFAULT_MANAGER_TITLE}"
                    )
                    st.caption("التعديل أو المسح متاح فقط لحامل الرمز السري من تبويب الإعدادات.")
                elif is_toxicology_form:
                    duty_auth_opts = [
                        "ختم المصادقة النظامي لإدارة مرور منطقة جازان",
                        "توقيع حي على الشاشة لمصادقة إدارة مرور منطقة جازان",
                    ]
                    if "توقيع حي" in (st.session_state.duty_auth_mode or "") and "جازان" in (st.session_state.duty_auth_mode or ""):
                        duty_default_idx = 1
                    elif "توقيع حي" in (st.session_state.duty_auth_mode or "") and "وحدة الحوادث" in (st.session_state.duty_auth_mode or ""):
                        # ترحيل خيار قديم محفوظ في الجلسة إلى الخيار المكافئ الجديد
                        duty_default_idx = 1
                    else:
                        duty_default_idx = 0
                    chosen_duty_auth = st.radio(
                        "وسيلة مصادقة إدارة مرور منطقة جازان:",
                        duty_auth_opts,
                        index=duty_default_idx,
                        key=f"duty_auth_radio_tox_{_form_sk}",
                        disabled=st.session_state.officer_approved or not st.session_state.citizen_locked,
                    )
                else:
                    duty_auth_opts = [
                        "ختم المصادقة النظامي لوحدة الحوادث",
                        "توقيع حي على الشاشة لمصادقة وحدة الحوادث",
                    ]
                    if is_letter_form or "توقيع حي" in (st.session_state.duty_auth_mode or ""):
                        duty_default_idx = 1
                    else:
                        duty_default_idx = 0
                    chosen_duty_auth = st.radio(
                        "وسيلة مصادقة وحدة الحوادث:",
                        duty_auth_opts,
                        index=duty_default_idx,
                        key=f"duty_auth_radio_{_form_sk}",
                        disabled=st.session_state.officer_approved or not st.session_state.citizen_locked,
                    )

                if not st.session_state.officer_approved:
                    if st.button("🛡️ اعتماد الوثيقة وإصدار رمز التحقق QR", type="primary", use_container_width=True, disabled=not st.session_state.citizen_locked):
                        officer_label = (st.session_state.get(officer_name_key) or "").strip() or unit_display
                        st.session_state.officer_full_override = officer_label
                        st.session_state.duty_auth_mode = chosen_duty_auth
                        if manager_auto_now:
                            st.session_state.duty_stamp_b64 = str(manager_cfg_now.get("manager_sig_b64") or "")
                        else:
                            st.session_state.duty_stamp_b64 = ""
                        if is_toxicology_form:
                            # تحليل السموم فقط: لا يُشترط توقيع/بصمة مستلم الخفر المناوب ولا يُدرج التوقيع المحفوظ
                            st.session_state.officer_auth_mode = "توثيق نصي لمستلم الخفر المناوب (بدون توقيع)"
                            st.session_state.officer_stamp_b64 = ""
                        elif use_saved_officer_sig and saved_officer_sig:
                            st.session_state.officer_auth_mode = "توقيع محفوظ من الإعدادات (تلقائي)"
                            st.session_state.officer_stamp_b64 = saved_officer_sig
                        else:
                            st.session_state.officer_auth_mode = chosen_officer_auth
                            if "بصمة" in chosen_officer_auth:
                                seed_off = f"{st.session_state.doc_no}_{officer_label}_OFFICER"
                                st.session_state.officer_stamp_b64 = generate_fingerprint_png_b64(seed_off, ink_rgb=(15, 61, 46))
                            else:
                                st.session_state.officer_stamp_b64 = ""
                        st.session_state.officer_approved = True
                        safe_rerun()
                else:
                    if is_toxicology_form:
                        st.success(
                            f"تم الاعتماد: مصادقة إدارة مرور منطقة جازان ({st.session_state.duty_auth_mode}) • "
                            f"توثيق مستلم الخفر المناوب نصياً بدون توقيع"
                        )
                    else:
                        st.success(
                            f"تم التوثيق: مستلم الخفر المناوب ({st.session_state.officer_auth_mode}) • "
                            f"وحدة الحوادث ({st.session_state.duty_auth_mode})"
                        )
                    if st.session_state.officer_stamp_b64 and not is_toxicology_form:
                        st.image(base64.b64decode(st.session_state.officer_stamp_b64), caption="ختم التوثيق المعتمد", width=105)
                st.markdown("</div>", unsafe_allow_html=True)

            if st.session_state.officer_approved:
                if fid == "decl_handover" and _is_agent_role(current_values.get("receiver_role")):
                    party_name_final = current_values.get("agent_name") or "غير محدد"
                    party_id_final = current_values.get("agent_id") or "-"
                    plate_final = current_values.get("plate_no") or "-"
                elif fid == "decl_settlement":
                    party_name_final = current_values.get("p1_name") or "غير محدد"
                    party_id_final = current_values.get("p1_id") or "-"
                    plate_final = current_values.get("p1_vehicle") or "-"
                else:
                    party_name_final = current_values.get("party_name") or current_values.get("driver_name") or "غير محدد"
                    party_id_final = current_values.get("party_id") or current_values.get("driver_id_nat") or "-"
                    plate_final = current_values.get("plate_no") or current_values.get("vehicle_plate_type") or "-"
                raw_seal = f"{st.session_state.doc_no}|{party_id_final}|{st.session_state.doc_time}"
                verify_hash = "KHF-" + hashlib.sha256(raw_seal.encode("utf-8")).hexdigest()[:16].upper()
                officer_full_final = (st.session_state.officer_full_override or "").strip() or unit_display

                sync_attachments_to_session()
                _consume_live_sig_bridge()
                live_pads = dict(st.session_state.get("live_sig_pads") or {})
                party_stamps = dict(st.session_state.get("party_stamps") or {})
                # مزامنة نهائية لضمان عدم فقدان توقيع المختص المستلم / اللوحات
                if live_pads.get("citizen"):
                    st.session_state.citizen_stamp_b64 = live_pads["citizen"]
                if live_pads.get("officer"):
                    st.session_state.officer_stamp_b64 = live_pads["officer"]
                if live_pads.get("duty"):
                    st.session_state.duty_stamp_b64 = live_pads["duty"]
                fields_for_save = dict(current_values)
                if party_stamps:
                    fields_for_save["__party_stamps"] = party_stamps
                if live_pads:
                    fields_for_save["__live_sig_pads"] = live_pads
                    for pad_key, pad_b64 in live_pads.items():
                        if pad_b64:
                            fields_for_save[f"__sig_{pad_key}"] = pad_b64
                citizen_b64 = _resolve_stamp_b64(
                    st.session_state.citizen_stamp_b64,
                    live_pads.get("citizen"),
                    next(iter(party_stamps.values()), "") if party_stamps else "",
                )
                officer_b64 = _resolve_stamp_b64(st.session_state.officer_stamp_b64, live_pads.get("officer"))
                duty_b64 = _resolve_stamp_b64(st.session_state.duty_stamp_b64, live_pads.get("duty"))
                mgr_active, mgr_cfg = manager_auto_signature_active()
                if mgr_active:
                    duty_b64 = str(mgr_cfg.get("manager_sig_b64") or "")
                    st.session_state.duty_stamp_b64 = duty_b64
                    st.session_state.duty_auth_mode = MANAGER_AUTH_MODE
                if citizen_b64:
                    st.session_state.citizen_stamp_b64 = citizen_b64
                ready_record = {
                    "doc_no": st.session_state.doc_no,
                    "auto_doc_no": st.session_state.get("auto_doc_no") or st.session_state.doc_no,
                    "form_id": fid,
                    "form_title": form_def.get("official_title") or _form_display_title(form_def, current_values, fid),
                    "category": form_def["category"],
                    "party_name": party_name_final,
                    "party_id": party_id_final,
                    "plate_no": plate_final,
                    "gps_coords": shift["default_gps"],
                    "created_at": st.session_state.doc_time,
                    "fields": fields_for_save,
                    "legal_text": live_legal_text,
                    "citizen_stamp_b64": citizen_b64,
                    "citizen_auth_mode": st.session_state.citizen_auth_mode,
                    "officer_stamp_b64": officer_b64,
                    "attachment_b64": st.session_state.attachment_b64,
                    "show_attachments_in_print": bool(st.session_state.get("show_attachments_in_print", True)),
                    "officer_full": officer_full_final,
                    "duty_full": (mgr_cfg.get("display_name") if mgr_active else duty_display),
                    "dept_name": shift["dept_name"],
                    "verify_hash": verify_hash,
                    "officer_auth_mode": st.session_state.officer_auth_mode,
                    "duty_auth_mode": MANAGER_AUTH_MODE if mgr_active else st.session_state.duty_auth_mode,
                    "duty_stamp_b64": duty_b64,
                    "receiver_name": st.session_state.receiver_name if (is_med_form or is_letter_form) else "",
                    "receiver_role": st.session_state.receiver_role if (is_med_form or is_letter_form) else "",
                    "party_stamps": party_stamps,
                    "live_sig_pads": live_pads,
                }

                a4_html = build_official_a4_html(ready_record, form_def, logo_b64_global, interactive_sig=True)
                st.write("")

                # حفظ تلقائي بمجرد اكتمال البيانات وقبل عرض زر الطباعة
                _, hash_now = ensure_device_identity()
                ref_number = str(ready_record.get("doc_no") or "").strip()
                if auto_save_to_archive(ready_record, hash_now):
                    st.success(f"تم حفظ الوثيقة تلقائياً في الأرشيف المحلي ({ref_number}).")
                elif ref_number:
                    st.caption(f"📁 السجل محفوظ في الأرشيف المحلي: {ref_number}")

                st.markdown("#### 📄 المعاينة الرسمية مقاس A4 (جاهزة للطباعة أو الحفظ كـ PDF)")
                st.caption(
                    "التواقيع تُرسم وتُحفظ محلياً داخل المعاينة. "
                    "بعد التوقيع اضغط زر الطباعة الوحيد أعلى ورقة A4 (متوافق مع Safari والآيفون)."
                )
                preview_h = 1480 if (
                    ("توقيع حي" in ready_record.get("citizen_auth_mode", ""))
                    or ("توقيع حي" in ready_record.get("officer_auth_mode", ""))
                    or ("توقيع حي" in ready_record.get("duty_auth_mode", ""))
                ) else 1160
                if ready_record.get("show_attachments_in_print") and parse_attachments(ready_record.get("attachment_b64")):
                    preview_h += 220
                components.html(a4_html, height=preview_h, scrolling=True)


# =====================================================================
# القسم الثاني: الأرشيف المحلي
# =====================================================================
elif st.session_state.nav_tab == "الأرشيف المحلي":
    st.markdown("""
    <div class="sec-heading-green">
        <span style="font-size:20px; font-weight:800; color:#ffffff;">🗂️ الأرشيف المحلي للوثائق الميدانية المقفلة</span>
    </div>
    """, unsafe_allow_html=True)

    search_q = st.text_input("🔍 ابحث برقم الهوية، رقم اللوحة، اسم الطرف، أو الرقم المرجعي:")
    show_all_dept = st.toggle(
        "عرض جميع سجلات القسم المحفوظة على السيرفر",
        value=True,
        help="مفيد على الآيفون عند اختفاء كوكي الجهاز: يعرض كل وثائق القسم دون الاعتماد على device_hash فقط.",
    )
    records = search_records_db(search_q, DEVICE_HASH, all_devices=bool(show_all_dept))

    if not records:
        st.info("لا توجد سجلات محفوظة" + (" على السيرفر." if show_all_dept else " على هذا الجهاز."))
    else:
        for r in records:
            with st.expander(f"📌 {r['form_title']}  —  {r['party_name']}  |  اللوحة: {r['plate_no']}  |  ({r['doc_no']})"):
                c_info, c_edit, c_dl, c_del = st.columns([2.4, 1.2, 1, 1])
                with c_info:
                    st.write(f"**رقم الهوية:** `{r['party_id']}`  |  **الوقت:** `{r['created_at']}`  |  **التوثيق:** {r['citizen_auth_mode']}")
                    st.write(f"**ختم التحقق الرقمي:** `{r['verify_hash']}`")
                f_def = TRAFFIC_FORMS.get(r["form_id"])
                arch_fields = r.get("fields")
                if not isinstance(arch_fields, dict):
                    try:
                        arch_fields = json.loads(r.get("fields_json") or "{}")
                    except Exception:
                        arch_fields = {}
                if isinstance(arch_fields, dict):
                    r = {**r, "fields": arch_fields, "party_stamps": arch_fields.get("__party_stamps") or {}, "live_sig_pads": arch_fields.get("__live_sig_pads") or {}}
                arch_html = build_official_a4_html(r, f_def, logo_b64_global, interactive_sig=False)
                with c_edit:
                    if st.button("✏️ استدعاء وتعديل كسجل جديد", key=f"edit_{r['id']}", use_container_width=True):
                        values = {k: v for k, v in (arch_fields or {}).items() if not str(k).startswith("__")}
                        st.session_state.pending_form_prefill = {
                            "form_id": r["form_id"],
                            "values": values,
                        }
                        open_form_from_catalog(r["form_id"])
                with c_dl:
                    st.download_button(
                        "⬇️ تنزيل A4",
                        data=arch_html.encode("utf-8"),
                        file_name=f"{r['doc_no']}.html",
                        mime="text/html",
                        key=f"dl_{r['id']}",
                        use_container_width=True,
                    )
                with c_del:
                    if st.button("🗑️ حذف السجل", key=f"del_{r['id']}", use_container_width=True):
                        delete_record_db(r["id"], DEVICE_HASH, force=bool(show_all_dept))
                        safe_rerun()

                if st.checkbox("عرض ومعاينة ورقة الـ A4 الرسمية للطباعة", key=f"chk_prev_{r['id']}"):
                    components.html(arch_html, height=1150, scrolling=True)


# =====================================================================
# القسم الثالث: الإعدادات والبصمة (مناوبة الخفر + OTG مدمجان)
# =====================================================================
elif st.session_state.nav_tab == "الإعدادات والبصمة":
    st.markdown("""
    <div class="sec-heading-green" style="margin-top:8px;">
        <span style="font-size:16px; font-weight:800; color:#ffffff;">⚙️ الإعدادات والبصمة</span>
    </div>
    """, unsafe_allow_html=True)

    sett_tab, mgr_tab, otg_tab = st.tabs([
        "👮 مناوبة الخفر",
        "✍️ توقيع مدير الحوادث",
        "🧬 بصمة الشحن OTG",
    ])

    with sett_tab:
        st.caption("إعدادات المناوبة والموقع تُحفظ على هذا الجوال فقط، ولا يراها من يفتح الرابط من جهاز آخر.")
        with st.expander("🖥️ مسار بديل للحاسوب (بدون شريحة GPS)", expanded=not gps_is_live):
            st.caption("الصق رابط خرائط Google من واتساب أو إحداثيات مثل 17.0375, 43.0764 لاعتمادها فوراً.")
            paste_gps = st.text_input(
                "رابط الخرائط أو الإحداثيات",
                value="",
                key="gps_paste_input",
                placeholder="https://maps.google.com/?q=17.0375,43.0764",
            )
            if st.button("✅ اعتماد الموقع من الرابط/الإحداثيات", type="primary", use_container_width=True, key="gps_paste_apply"):
                pasted = parse_gps_paste(paste_gps)
                if not pasted:
                    st.error("تعذر استخراج الإحداثيات من النص الملصوق.")
                else:
                    _, hash_now = ensure_device_identity()
                    if not _cookie_uid_ready:
                        st.caption("⏳ تتم مزامنة تعريف الجهاز مع المتصفح — اعتمدنا المعرّف الاحتياطي فوراً.")
                    formatted = format_live_gps(*pasted)
                    update_default_gps(hash_now, formatted)
                    st.session_state["gps_live_ok"] = True
                    st.session_state["gps_live_value"] = formatted
                    st.session_state["gps_toast"] = formatted
                    st.success(f"تم اعتماد الموقع الفعلي: {formatted}")
                    safe_rerun()
        with st.form("shift_update_form"):
            s_dept = st.text_input("القسم", value=shift["dept_name"], disabled=True)
            r1, r2 = st.columns([1, 2])
            with r1:
                s_orank = st.text_input("خانة التوثيق الأولى", value=shift["officer_rank"])
            with r2:
                s_oname = st.text_input("اسم مستلم الخفر المناوب (اختياري)", value=shift["officer_name"])

            r3, r4 = st.columns([1, 2])
            with r3:
                s_drank = st.text_input("خانة المصادقة الثانية", value=shift["duty_rank"])
            with r4:
                s_dname = st.text_input("اسم المناوب (اختياري)", value=shift["duty_name"])

            s_gps = st.text_input(
                "إحداثيات الموقع (GPS)",
                value=shift["default_gps"],
                key=f"shift_gps_{shift['default_gps']}",
            )
            maps_for_field = google_maps_url(s_gps or shift["default_gps"])
            if maps_for_field:
                st.markdown(
                    f"[🗺️ فتح الإحداثي في خرائط Google]({maps_for_field})",
                )

            save_col, clear_col = st.columns(2)
            with save_col:
                save_shift = st.form_submit_button("💾 حفظ الإعدادات", type="primary", use_container_width=True)
            with clear_col:
                clear_shift = st.form_submit_button("🗑️ مسح بياناتي من هذا الجهاز", use_container_width=True)
            if clear_shift:
                clear_device_shift(DEVICE_HASH)
                st.session_state[DUTY_SIG_KEY] = ""
                st.session_state["wipe_device_shift"] = True
                st.success("تم مسح اسم المناوبة وبيانات هذا الجهاز (بما فيها توقيع مستلم الخفر المناوب) من المتصفح.")
                safe_rerun()
            if save_shift:
                _, hash_now = ensure_device_identity()
                if not _cookie_uid_ready:
                    st.caption("⏳ تتم مزامنة تعريف الجهاز مع المتصفح — الحفظ بالمعرّف الاحتياطي متاح الآن.")
                save_device_shift(hash_now, {
                    "dept_name": "قسم مرور العارضة",
                    "officer_rank": s_orank,
                    "officer_name": s_oname,
                    "duty_rank": s_drank,
                    "duty_name": s_dname,
                    "default_gps": s_gps,
                    DUTY_SIG_KEY: st.session_state.get(DUTY_SIG_KEY) or shift.get(DUTY_SIG_KEY) or "",
                })
                st.success("تم حفظ الإعدادات على هذا الجهاز فقط.")
                safe_rerun()

        # لوحة التوقيع خارج st.form لالتقاط Base64 لحظياً دون تعارض مع نموذج الحفظ
        st.markdown("##### ✍️ التوقيع المعتمد لمستلم الخفر المناوب (يُدرج تلقائياً في جميع النماذج)")
        st.caption("يُحفظ التوقيع على هذا الجهاز فقط (SQLite + localStorage) ولا يُوضع في الكوكيز حتى لا يتجاوز حد 4KB.")
        _allow_ls_restore = not bool(
            str(st.session_state.get(DUTY_SIG_KEY) or shift.get(DUTY_SIG_KEY) or "").strip()
        )
        render_officer_sig_bridge_listener(allow_ls_restore=_allow_ls_restore)
        components.html(render_officer_sig_pad_html(), height=290, scrolling=False)
        if st.session_state.pop("_clear_duty_sig_bridge", False):
            st.session_state["duty_sig_bridge"] = ""
        bridge_val = st.text_area(
            "جسر التوقيع",
            key="duty_sig_bridge",
            height=68,
            placeholder="DUTY_SIG_BRIDGE — يُملأ تلقائياً عند اعتماد التوقيع من اللوحة",
            label_visibility="collapsed",
        )
        if bridge_val and str(bridge_val).strip() and str(bridge_val).strip() != str(st.session_state.get(DUTY_SIG_KEY) or ""):
            compressed = compress_signature_b64(bridge_val)
            if compressed:
                st.session_state[DUTY_SIG_KEY] = compressed
                st.session_state["_clear_duty_sig_bridge"] = True
                if DEVICE_HASH:
                    cur = get_device_shift(DEVICE_HASH)
                    cur[DUTY_SIG_KEY] = compressed
                    save_device_shift(DEVICE_HASH, cur)
                st.toast("تم اعتماد توقيع مستلم الخفر المناوب من اللوحة", icon="✅")
                safe_rerun()

        sig_upload = st.file_uploader(
            "أو ارفع صورة توقيع شفافة (PNG/JPG) كخيار مساند",
            type=["png", "jpg", "jpeg", "webp"],
            key="duty_sig_upload",
            help="يُفضّل خلفية شفافة أو بيضاء مع حبر أسود واضح.",
        )
        up_col, del_col = st.columns(2)
        with up_col:
            if st.button("💾 حفظ التوقيع المرفوع / الحالي في الجهاز", type="primary", use_container_width=True):
                payload = ""
                if sig_upload is not None:
                    processed = process_uploaded_attachment(sig_upload)
                    payload = compress_signature_b64((processed or {}).get("b64") or "")
                elif st.session_state.get(DUTY_SIG_KEY):
                    payload = compress_signature_b64(st.session_state.get(DUTY_SIG_KEY) or "")
                if not payload:
                    st.warning("ارسم التوقيع في اللوحة أو ارفع صورة أولاً.")
                else:
                    _, hash_now = ensure_device_identity()
                    if not _cookie_uid_ready:
                        st.caption("⏳ تتم مزامنة تعريف الجهاز مع المتصفح — الحفظ بالمعرّف الاحتياطي متاح الآن.")
                    st.session_state[DUTY_SIG_KEY] = payload
                    st.session_state["_clear_duty_sig_bridge"] = True
                    cur = get_device_shift(hash_now)
                    cur[DUTY_SIG_KEY] = payload
                    save_device_shift(hash_now, cur)
                    st.success("تم حفظ توقيع مستلم الخفر المناوب على هذا الجهاز وتفعيله تلقائياً.")
                    safe_rerun()
        with del_col:
            if st.button("🗑️ حذف / إعادة رسم توقيع مستلم الخفر المناوب", use_container_width=True):
                st.session_state[DUTY_SIG_KEY] = ""
                st.session_state["_clear_duty_sig_bridge"] = True
                if DEVICE_HASH:
                    cur = get_device_shift(DEVICE_HASH)
                    cur[DUTY_SIG_KEY] = ""
                    save_device_shift(DEVICE_HASH, cur)
                st.success("تم حذف التوقيع المحفوظ. يمكنك إعادة الرسم الآن.")
                safe_rerun()

        preview_sig = str(st.session_state.get(DUTY_SIG_KEY) or shift.get(DUTY_SIG_KEY) or "").strip()
        if preview_sig:
            st.markdown(
                "<div style='background:#0f3d2e;border:1px solid #34d399;border-radius:10px;padding:10px 12px;"
                "color:#ecfdf5;font-weight:800;margin:8px 0;'>✅ التوقيع محفوظ ومفعّل تلقائياً في جميع النماذج</div>",
                unsafe_allow_html=True,
            )
            try:
                st.image(base64.b64decode(preview_sig), caption="معاينة توقيع مستلم الخفر المناوب المعتمد", width=280)
            except Exception:
                st.caption("تعذّر عرض معاينة التوقيع المحفوظ.")
        else:
            st.info("لا يوجد توقيع محفوظ حالياً — ارسم على اللوحة أو ارفع صورة ثم احفظ.")

    with mgr_tab:
        st.markdown("### ✍️ اعتماد التوقيع الحي لمدير وحدة الحوادث")
        st.caption(
            "محمي برمز سري. اعتمد التوقيع عبر تنزيل PNG من اللوحة ثم رفعه بالزر أدناه — "
            "يُحفظ في SQLite وملف ثابت على السيرفر ويظهر لجميع أفراد الخفر تلقائياً."
        )
        if "manager_pin_ok" not in st.session_state:
            st.session_state.manager_pin_ok = False
        if not st.session_state.manager_pin_ok:
            pin_in = st.text_input(
                "الرمز السري لمدير وحدة الحوادث",
                type="password",
                key="manager_pin_input",
                placeholder="أدخل الرمز السري",
            )
            if st.button("🔓 دخول قسم المدير", type="primary", use_container_width=True, key="manager_pin_unlock"):
                if str(pin_in or "").strip() == _manager_pin():
                    st.session_state.manager_pin_ok = True
                    st.success("تم فتح قسم اعتماد توقيع المدير.")
                    safe_rerun()
                else:
                    st.error("الرمز السري غير صحيح.")
        else:
            mgr_now = get_manager_signature_settings()
            lock_c, _ = st.columns([1, 2])
            with lock_c:
                if st.button("🔒 إغلاق قسم المدير", use_container_width=True, key="manager_pin_lock"):
                    st.session_state.manager_pin_ok = False
                    safe_rerun()

            mgr_name = st.text_input(
                "الاسم والرتبة",
                value=str(mgr_now.get("manager_name") or ""),
                key="manager_name_input",
                placeholder="مثال: الرائد / ...",
            )
            mgr_title = st.text_input(
                "المسمى الوظيفي",
                value=str(mgr_now.get("manager_title") or DEFAULT_MANAGER_TITLE),
                key="manager_title_input",
            )
            mgr_auto = st.toggle(
                "تفعيل ظهور التوقيع التلقائي على الخطابات الرسمية",
                value=bool(mgr_now.get("auto_insert", True)),
                key="manager_auto_insert_toggle",
                help="أوقف هذا الخيار مؤقتاً أثناء الإجازات أو عند الحاجة لإخفاء التوقيع المركزي.",
            )

            if st.button(
                "💾 حفظ الاسم/المسمى وخيار الظهور",
                use_container_width=True,
                key="manager_meta_save_only",
            ):
                save_manager_signature_settings(
                    mgr_name,
                    mgr_title or DEFAULT_MANAGER_TITLE,
                    str(mgr_now.get("manager_sig_b64") or ""),
                    auto_insert=bool(mgr_auto),
                )
                st.success("تم تحديث بيانات المدير وخيار الظهور التلقائي.")
                safe_rerun()

            st.markdown("##### 1️⃣ ارسم ثم نزّل ملف التوقيع الشفاف")
            components.html(render_manager_sig_pad_html(), height=360, scrolling=False)

            st.markdown("##### 2️⃣ ارفع الملف لاعتماده فوراً لجميع الأفراد")
            mgr_upload = st.file_uploader(
                "📤 أو ارفع/ثبّت صورة التوقيع المحفوظة هنا لاعتمادها فوراً لجميع الأفراد",
                type=["png", "jpg", "jpeg", "webp"],
                key="manager_sig_direct_upload",
                help="ارفع manager_signature.png الذي نزل من اللوحة، أو أي صورة توقيع واضحة.",
            )
            if mgr_upload is not None:
                try:
                    raw = mgr_upload.getvalue()
                    upload_token = hashlib.sha256(
                        f"{mgr_upload.name}|{len(raw)}|".encode("utf-8") + raw[:2048]
                    ).hexdigest()
                    if st.session_state.get("_mgr_upload_token") != upload_token:
                        saved = ingest_manager_signature_bytes(
                            raw,
                            mgr_name,
                            mgr_title or DEFAULT_MANAGER_TITLE,
                            auto_insert=bool(mgr_auto),
                        )
                        st.session_state["_mgr_upload_token"] = upload_token
                        st.success(
                            f"✅ تم اعتماد توقيع المدير على السيرفر: {saved.get('display_name') or DEFAULT_MANAGER_TITLE}"
                        )
                        safe_rerun()
                except Exception as exc:
                    st.error(f"تعذّر اعتماد ملف التوقيع: {exc}")

            saved_sig = str(mgr_now.get("manager_sig_b64") or "").strip()
            if saved_sig:
                st.markdown(
                    "<div style='background:#0f3d2e;border:1px solid #34d399;border-radius:10px;"
                    "padding:12px 14px;color:#ecfdf5;font-weight:800;margin:10px 0;line-height:1.55;'>"
                    "✅ التوقيع الحي محفوظ على السيرفر ويظهر الآن تلقائياً لجميع أفراد الخفر في الخطابات الجديدة"
                    "</div>",
                    unsafe_allow_html=True,
                )
                try:
                    st.image(
                        base64.b64decode(saved_sig),
                        caption=f"معاينة التوقيع المعتمد — {mgr_now.get('display_name') or DEFAULT_MANAGER_TITLE}",
                        width=280,
                    )
                except Exception:
                    st.caption("تعذّر عرض معاينة التوقيع المحفوظ.")
                if mgr_now.get("updated_at"):
                    st.caption(f"آخر تحديث: {mgr_now.get('updated_at')}")
            else:
                st.warning("لا يوجد توقيع مدير معتمد حالياً — نزّل من اللوحة ثم ارفع الملف أعلاه.")

            if not bool(mgr_now.get("auto_insert", True)) and saved_sig:
                st.warning("التوقيع محفوظ لكن الظهور التلقائي متوقف مؤقتاً.")

            if st.button(
                "🗑️ مسح/تغيير التوقيع المعتمد",
                use_container_width=True,
                key="manager_sig_clear_all",
            ):
                save_manager_signature_settings(
                    mgr_name,
                    mgr_title or DEFAULT_MANAGER_TITLE,
                    "",
                    auto_insert=bool(mgr_auto),
                )
                st.success("تم مسح التوقيع المعتمد. يمكن إعادة الرسم والرفع الآن.")
                safe_rerun()

            with st.expander("🔐 نص جاهز للصقه في Streamlit Secrets (نسخة دائمة للأبد)", expanded=False):
                if saved_sig:
                    st.code(manager_secrets_snippet(mgr_now), language="toml")
                    st.caption(
                        "الصق المحتوى في Secrets على Streamlit Cloud مرة واحدة؛ "
                        "سيُستخدم كاحتياط دائم عبر MANAGER_SIGNATURE_B64 حتى بعد إعادة التشغيل."
                    )
                else:
                    st.info("اعتمد توقيعاً أولاً لعرض نص الـ Secrets.")

            st.markdown("#### 📥 تنزيل / 📤 استعادة النسخة الاحتياطية JSON")
            dl_c, up_c = st.columns(2)
            with dl_c:
                st.download_button(
                    "📥 تنزيل نسخة احتياطية JSON",
                    data=export_manager_signature_backup_bytes(),
                    file_name="manager_sig_backup.json",
                    mime="application/json",
                    use_container_width=True,
                    key="manager_sig_backup_dl",
                )
            with up_c:
                backup_file = st.file_uploader(
                    "📤 استعادة من JSON",
                    type=["json"],
                    key="manager_sig_backup_upload",
                )
                if backup_file is not None and st.button(
                    "📤 استعادة التوقيع من JSON",
                    use_container_width=True,
                    key="manager_sig_backup_restore",
                ):
                    try:
                        import_manager_signature_backup(backup_file.getvalue())
                        st.success("تمت استعادة توقيع المدير من النسخة الاحتياطية.")
                        safe_rerun()
                    except Exception as exc:
                        st.error(f"تعذّرت الاستعادة: {exc}")

    with otg_tab:
        st.caption("وضع المحاكاة الصوري معزول حتى توصيل القارئ الفعلي عبر Type-C.")
        selected_hw = st.selectbox(
            "بروتوكول القارئ المعتمد:",
            [
                "وضع المحاكاة متصل (معزول العتاد)",
                "SecuGen Hamster Pro 20 (Type-C OTG)",
                "Mantra MFS110 (RD Local Service 11100)",
                "ZKTeco Live20R (USB Host)",
            ],
            index=(
                [
                    "وضع المحاكاة متصل (معزول العتاد)",
                    "SecuGen Hamster Pro 20 (Type-C OTG)",
                    "Mantra MFS110 (RD Local Service 11100)",
                    "ZKTeco Live20R (USB Host)",
                ].index(st.session_state.scanner_model)
                if st.session_state.scanner_model in [
                    "وضع المحاكاة متصل (معزول العتاد)",
                    "SecuGen Hamster Pro 20 (Type-C OTG)",
                    "Mantra MFS110 (RD Local Service 11100)",
                    "ZKTeco Live20R (USB Host)",
                ]
                else 0
            ),
        )
        c_usb1, c_usb2 = st.columns(2)
        with c_usb1:
            if st.button("🔄 تحديث ربط منفذ الشحن", type="primary", use_container_width=True):
                st.session_state.scanner_model = selected_hw
                st.success(f"تم ضبط البروتوكول النشط على: {selected_hw}")
                safe_rerun()
        with c_usb2:
            if st.button("🧬 اختبار بصمة تجريبية", use_container_width=True):
                test_b64 = generate_fingerprint_png_b64(f"TEST_{datetime.now().isoformat()}")
                st.image(base64.b64decode(test_b64), caption="ختم الحبر التجريبي", width=130)
_khafar_flush_fallback_save()
