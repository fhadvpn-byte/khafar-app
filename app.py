import streamlit as st
import streamlit.components.v1 as components
import sqlite3
import json
import base64
import io
import html
import random
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageOps
from abu_arish_impound import ABU_ARISH_IMPOUND_TEMPLATE

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
    """قراءة شعار المرور تلقائياً من مجلد المشروع"""
    base_dir = Path(__file__).resolve().parent
    for fname in ("traffic_logo.png", "traffic_logo.PNG", "traffic_logo.jpg", "traffic_logo.jpeg"):
        fpath = base_dir / fname
        if fpath.exists():
            return base64.b64encode(fpath.read_bytes()).decode("utf-8")
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
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&family=JetBrains+Mono:wght@600&display=swap');

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

/* إخفاء شريط Streamlit العلوي وأيقونات Share/GitHub لمنع التداخل مع العربية */
header[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
.stDeployButton,
#MainMenu,
footer,
footer[data-testid="stFooter"],
.stAppDeployButton {
    display: none !important;
    visibility: hidden !important;
    height: 0 !important;
    min-height: 0 !important;
    opacity: 0 !important;
    pointer-events: none !important;
}
[data-testid="collapsedControl"] { display: none !important; }
section[data-testid="stSidebar"] { display: none !important; }
.block-container {
    padding-top: 0.35rem !important;
    padding-bottom: 1.4rem !important;
    padding-left: 0.7rem !important;
    padding-right: 0.7rem !important;
    max-width: 1140px !important;
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
    grid-template-columns: repeat(3, 1fr) !important;
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
@media (max-width: 640px) {
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
    padding: 16px 20px;
    margin: 14px 0;
    color: #e2e8f0;
    font-size: 14.5px;
    line-height: 1.95;
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
label[data-testid="stWidgetLabel"] p {
    font-size: 13.5px !important;
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
.legal-dark-box { direction: rtl !important; text-align: justify !important; text-align-last: right !important; unicode-bidi: embed !important; color: #e2e8f0 !important; }
.legal-dark-box .legal-title { direction: rtl !important; text-align: right !important; color: #d4a853 !important; font-weight: 800 !important; margin-bottom: 8px !important; }
.legal-dark-box .legal-body { direction: rtl !important; unicode-bidi: embed !important; text-align: justify !important; text-align-last: right !important; text-justify: inter-word !important; line-height: 2.0 !important; color: #e2e8f0 !important; }
</style>
""", unsafe_allow_html=True)


# =====================================================================
# 2. تعريف النماذج الـ 12 والصيغ النظامية المحكمة
# =====================================================================
def _val(values: dict, key: str) -> str:
    v = str(values.get(key, "")).strip()
    return ("\u200f" + v + "\u200f") if v else "...................."


def _is_agent_role(value: str) -> bool:
    text = str(value or "")
    return ("وكيل" in text) or ("وكالة" in text)


def _handover_capacity(values: dict) -> str:
    role = str(values.get("receiver_role") or "").strip()
    if _is_agent_role(role):
        return (
            f"بصفتي وكيلاً شرعياً عن مالك المركبة ({_val(values, 'principal_name')} - هوية رقم: {_val(values, 'principal_id')}) "
            f"بموجب الوكالة السارية رقم ({_val(values, 'wakala_no')}) وتاريخ ({_val(values, 'wakala_date')})"
        )
    return f"بصفتي ({_val(values, 'receiver_role')})"


def _include_field_on_a4(field: dict, fields_map: dict) -> bool:
    if field.get("a4_hidden"):
        return False
    rule = field.get("visible_if") or {}
    if not rule:
        return True
    source = str(fields_map.get(rule.get("key"), "") or "")
    tokens = rule.get("contains_any") or []
    if not any(token in source for token in tokens):
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
    # ==================== أولاً: قائمة الإقرارات الميدانية (4) ====================
    "decl_handover": {
        "title": "إقرار تسليم مركبة في الموقع",
        "icon": "🚗",
        "subtitle": "توثيق تسليم المركبة لمالكها أو المفوض بالموقع وإخلاء مسؤولية الفرقة من السحب",
        "category": "إقرار",
        "allow_absence": False,
        "require_image": False,
        "fields": [
            {"key": "incident_no", "label": "رقم الحادث المرجعي", "type": "text", "sample": "460982341"},
            {"key": "party_name", "label": "اسم المستلم الرباعي", "type": "text", "sample": "عبدالرحمن بن محمد بن علي السبيعي"},
            {"key": "party_id", "label": "رقم الهوية / الإقامة", "type": "text", "sample": "1087654321"},
            {"key": "party_phone", "label": "رقم الجوال", "type": "text", "sample": "0551234567"},
            {"key": "receiver_role", "label": "صفة المستلم", "type": "select", "options": [
                "مالك المركبة بموجب رخصة السير",
                "مفوض رسمي بقيادة المركبة",
                "وكيل شرعي بموجب وكالة سارية"
            ], "sample": "مالك المركبة بموجب رخصة السير"},
            {"key": "principal_name", "label": "اسم الموكّل (مالك المركبة الأصلي)", "type": "text", "sample": "محمد بن علي بن سعد السبيعي", "prefill_sample": True,
             "visible_if": {"key": "receiver_role", "contains_any": ["وكيل", "وكالة"]},
             "a4_label": "الموكّل والوكالة الشرعية", "a4_compose": ["principal_id", "wakala_no", "wakala_date"]},
            {"key": "principal_id", "label": "رقم هوية / إقامة الموكّل", "type": "text", "sample": "1023456789", "prefill_sample": True,
             "visible_if": {"key": "receiver_role", "contains_any": ["وكيل", "وكالة"]},
             "a4_hidden": True},
            {"key": "wakala_no", "label": "رقم الوكالة الشرعية / الإلكترونية", "type": "text", "sample": "461829405", "prefill_sample": True,
             "visible_if": {"key": "receiver_role", "contains_any": ["وكيل", "وكالة"]},
             "a4_hidden": True},
            {"key": "wakala_date", "label": "تاريخ إصدار الوكالة", "type": "text", "sample": "1448/04/15 هـ", "prefill_sample": True,
             "visible_if": {"key": "receiver_role", "contains_any": ["وكيل", "وكالة"]},
             "a4_hidden": True},
            {"key": "vehicle_desc", "label": "نوع المركبة وموديلها ولونها", "type": "text", "sample": "تويوتا كامري 2024 - أبيض"},
            {"key": "plate_no", "label": "رقم اللوحة", "type": "text", "sample": "ح ط ر 4512"},
            {"key": "vehicle_state", "label": "حالة المركبة عند التسليم بالموقع", "type": "select", "options": [
                "أضرار سطحية لا تمنع السير الآمن",
                "صالحة للسير دون عوائق ميكانيكية ظاهرة",
                "غير صالحة للسير وتُنقل بسطحة خاصة بمعرفة المستلم"
            ], "sample": "أضرار سطحية لا تمنع السير الآمن"},
        ],
        "legal_fn": lambda m: (
            f"أقر أنا الموقع والمبصم أدناه ({_val(m, 'party_name')})، حامل الهوية رقم ({_val(m, 'party_id')})، "
            f"{_handover_capacity(m)}، بأنني استلمت المركبة ({_val(m, 'vehicle_desc')}) التي تحمل اللوحة رقم ({_val(m, 'plate_no')}) "
            f"في موقع الحادث رقم ({_val(m, 'incident_no')}) مباشرةً بحالتها الراهنة ({_val(m, 'vehicle_state')}) وبكامل مقتنياتها الشخصية دون نقص، "
            f"وبموجبه أخلي مسؤولية قسم مرور العارضة والفرقة المباشرة من سحب المركبة أو حجزها، وأتعهد بعدم قيادتها في حال وجود أي خلل يؤثر على السلامة العامة."
        ),
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
                "عدم التقيد بإشارات وتنظيمات المرور"
            ], "sample": "الانحراف المفاجئ دون التأكد من خلو المسار"},
        ],
        "legal_fn": lambda m: (
            f"أقر أنا ({_val(m, 'party_name')})، حامل الهوية رقم ({_val(m, 'party_id')})، قائد المركبة ({_val(m, 'plate_no')})، "
            f"وأنا بكامل أهليتي المعتبرة شرعاً ونظاماً، باطلاعي وموافقتي واقتناعي التام بنسبة الخطأ المقررة عليّ وقدرها ({_val(m, 'fault_ratio')}) "
            f"في الحادث المروري رقم ({_val(m, 'incident_no')}) الواقع مع الطرف الآخر ({_val(m, 'other_party')}) نتيجة ({_val(m, 'fault_cause')})، "
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
                "لا توجد كاميرات مراقبة ظاهرة في محيط الموقع"
            ], "sample": "توجد كاميرات محلات تجارية مقابلة لموقع الاصطدام مباشرة"},
        ],
        "legal_fn": lambda m: (
            f"أقر أنا المبلّغ ({_val(m, 'party_name')})، حامل الهوية رقم ({_val(m, 'party_id')})، بصحة كافة البيانات والأوصاف المدونة أعلاه "
            f"بشأن تعرض مركبتي ({_val(m, 'plate_no')}) لحادث صدم وهروب في البلاغ رقم ({_val(m, 'incident_no')}) من قِبل المركبة الموصوفة بـ ({_val(m, 'flee_desc')}) "
            f"والتي غادرت الموقع باتجاه ({_val(m, 'flee_dir')})، وحالة الكاميرات بالمحيط: ({_val(m, 'cctv_info')}). "
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
                "طرف أول (قائد مركبة)", "طرف ثاني (قائد مركبة)", "طرف ثالث", "شاهد عيان حاضر بالموقع"
            ], "sample": "طرف أول (قائد مركبة)"},
            {"key": "party_name", "label": "الاسم الرباعي للمدلي بالأقوال", "type": "text", "sample": "ياسر بن إبراهيم بن حمد الشهري"},
            {"key": "party_id", "label": "رقم الهوية / الإقامة", "type": "text", "sample": "1078899001"},
            {"key": "party_phone", "label": "رقم الجوال", "type": "text", "sample": "0567788990"},
            {"key": "plate_no", "label": "المركبة ورقم اللوحة", "type": "text", "sample": "كيا K5 رصاصي - ع م ن 2039"},
            {"key": "lane_speed", "label": "المسار والاتجاه والسرعة التقديرية قبل الحادث", "type": "text", "sample": "المسار الأيمن متجهاً شرقاً بسرعة تقارب 70 كم/س"},
            {"key": "statement_text", "label": "نص الإفادة الميدانية الفورية", "type": "textarea", "sample": "أثناء سيري النظامي في مساري فوجئت بدخول المركبة الأخرى من الفتحة الجانبية دون توقف أو إعطاء أفضلية، وحاولت التهدئة وتلافيها إلا أن ضيق المسافة أدى لوقوع الاصطدام."},
        ],
        "legal_fn": lambda m: (
            f"أقر أنا ({_val(m, 'party_name')})، حامل الهوية رقم ({_val(m, 'party_id')})، بصفتي ({_val(m, 'speaker_role')}) للمركبة ({_val(m, 'plate_no')}) "
            f"في الحادث رقم ({_val(m, 'incident_no')})، بأنني كنت أسير في ({_val(m, 'lane_speed')})، وتتلخص إفادتي الفورية بالموقع في الآتي: "
            f"\"{_val(m, 'statement_text')}\". وقد أدليت بهذه الأقوال طواعية وبكامل أهليتي فور مباشرة الحادث ودون إكراه لاعتمادها ضمن محاضر الاستدلال المروري."
        ),
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
                "تفتيش احترازي لوجود شبهة مرورية أو أمنية بالموقع"
            ], "sample": "نقل قائد المركبة للمستشفى بالهلال الأحمر إثر حادث مروري"},
            {"key": "plate_no", "label": "بيانات المركبة ورقم اللوحة", "type": "text", "sample": "جيب لكزس أبيض - ر س ل 5500"},
            {"key": "party_name", "label": "اسم القائد / المالك (أو الشاهد الحاضر)", "type": "text", "sample": "نايف بن عبدالله القحطاني"},
            {"key": "party_id", "label": "رقم الهوية / الإقامة", "type": "text", "sample": "1054433221"},
            {"key": "body_state", "label": "حالة الهيكل الخارجي والزجاج", "type": "text", "sample": "تلفيات بالمقدمة وتهشم الزجاج الأمامي وسلامة المقصورة الخلفية"},
            {"key": "inventory_list", "label": "جرد المقتنيات الشخصية والأمانات المرصودة", "type": "textarea", "sample": "محفظة شخصية بداخلها الهوية الوطنية ومبلغ (450) ريال + جوال آيفون أسود + الإطار الاحتياطي وعدة المركبة."},
            {"key": "items_action", "label": "التصرف النظامي بالمقتنيات", "type": "select", "options": [
                "حُفظت المقتنيات الثمينة بصندوق أمانات القسم بموجب سند رسمي",
                "سُلمت المقتنيات الشخصية كاملة للمالك أو ذويه في الموقع",
                "لا توجد مقتنيات ثمينة وبقيت التجهيزات العادية داخل المركبة المقفلة"
            ], "sample": "حُفظت المقتنيات الثمينة بصندوق أمانات القسم بموجب سند رسمي"},
        ],
        "legal_fn": lambda m: (
            f"إنه في الزمان والمكان المثبتين آلياً بترويسة هذا المحضر، واستناداً للمسوغ النظامي ({_val(m, 'legal_reason')}) في المعاملة رقم ({_val(m, 'incident_no')})، "
            f"جرى بمعرفتنا تفتيش المركبة ({_val(m, 'plate_no')}) العائدة لـ ({_val(m, 'party_name')} - هوية: {_val(m, 'party_id')})، وحالتها الخارجية: ({_val(m, 'body_state')})، "
            f"وأسفر الجرد الفعلي لمحتوياتها عن وجود: ({_val(m, 'inventory_list')})، وقد جرى اتخاذ الإجراء التالي حيالها: ({_val(m, 'items_action')}). "
            f"حُرر هذا المحضر الرسمي إثباتاً للحالة وصوناً للأمانات ومنعاً لأي ادعاء لاحق."
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
                "مركبة مطلوبة بتعميم قبض أو حجز مروري ساري المفعول"
            ], "sample": "طمس أو إخفاء معالم لوحات المركبة بقصد التمويه"},
            {"key": "plate_no", "label": "نوع المركبة ورقم اللوحة / الهيكل", "type": "text", "sample": "شيفروليه كابرس أسود - ك هـ ي 9012"},
            {"key": "party_name", "label": "اسم قائد المركبة عند الضبط", "type": "text", "sample": "تركي بن منصور الدوسري"},
            {"key": "party_id", "label": "رقم الهوية / الإقامة", "type": "text", "sample": "1109876543"},
            {"key": "tow_truck", "label": "بيانات سطحة السحب واسم السائق", "type": "text", "sample": "سطحة الحجز المعتمدة رقم (14) - السائق: رفيق أحمد"},
            {"key": "impound_loc", "label": "ساحة الحجز المودعة بها المركبة", "type": "text", "sample": "ساحة حجز المرور بالعارضة"},
            {"key": "pre_tow_state", "label": "حالة الهيكل الخارجي قبل الرفع على السطحة", "type": "text", "sample": "خدوش سابقة بالصدام الخلفي والزجاج سليم والأبواب مقفلة"},
        ],
        "legal_fn": lambda m: (
            f"بناءً على الصلاحيات النظامية المخولة لرجال المرور بموجب نظام المرور ولائحته التنفيذية، جرى في الزمان والمكان الموضحين بترويسة المحضر رقم ({_val(m, 'incident_no')}) "
            f"ضبط المركبة ({_val(m, 'plate_no')}) بقيادة ({_val(m, 'party_name')} - هوية: {_val(m, 'party_id')}) لارتكاب مخالفة ({_val(m, 'seize_reason')}). "
            f"وبمعاينة المركبة قبل الرفع تبين ({_val(m, 'pre_tow_state')})، وسُلمت ميدانياً إلى ({_val(m, 'tow_truck')}) لإيداعها في ({_val(m, 'impound_loc')}) لاستكمال المقتضى النظامي."
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
                "تكرار تقني مزدوج لذات المخالفة في وقت واحد بجهاز الرصد"
            ], "sample": "خطأ مطبعي غير مقصود في أحرف أو أرقام اللوحة أثناء الرصد الميداني"},
            {"key": "officer_note", "label": "إفادة راصد المخالفة التفصيلية", "type": "textarea", "sample": "أثناء مباشرة تنظيم الحركة المرورية جرى إدخال حرف (ج) بدلاً من (ح) بالخطأ للوحة المركبة المخالفة الفعلية، والمركبة المسجل عليها الإشعار لم تكن بالموقع."},
        ],
        "legal_fn": lambda m: (
            f"نرفع هذا المحضر الرسمي بشأن المخالفة المرورية رقم ({_val(m, 'incident_no')}) المقيدة بتاريخ ({_val(m, 'viol_datetime')}) على اللوحة ({_val(m, 'plate_no')})، "
            f"حيث تبين بعد المراجعة والتدقيق وقوع خطأ في الرصد ناتج عن ({_val(m, 'error_reason')})، والبيانات المرجعية هي ({_val(m, 'party_name')} - {_val(m, 'party_id')}). "
            f"وإيضاح الراصد الميداني كالآتي: ({_val(m, 'officer_note')}). وعليه حُرر هذا المحضر مرفقاً به صورة المخالفة ومعتمداً للعرض على الهيئة المرورية لإلغاء المخالفة نظاماً."
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
                "واقعة ميدانية مرورية عارضة تستوجب التوثيق الرسمي"
            ], "sample": "تلف ممتلكات عامة (عمود إنارة / لوحة إرشادية / سياج) جراء حادث"},
            {"key": "party_name", "label": "اسم الطرف ذي العلاقة (إن وجد)", "type": "text", "sample": "فيصل بن راشد الغامدي"},
            {"key": "party_id", "label": "رقم الهوية / الإقامة", "type": "text", "sample": "1081122334"},
            {"key": "plate_no", "label": "بيانات المركبة / العين المتضررة بالموقع", "type": "text", "sample": "جمس سييرا (ط ك ل 6610) - عمود إنارة رقم 48"},
            {"key": "facts_detail", "label": "تفاصيل الوقائع المشاهدة عياناً بالموقع", "type": "textarea", "sample": "عند مباشرة الموقع تبين ارتطام المركبة المذكورة بعمود الإنارة رقم (48) بالجزيرة الوسطية مما أدى لميلان العمود وانكشاف الكيبل الأرضي دون إصابات بشرية."},
            {"key": "taken_measure", "label": "الإجراء الفوري المتخذ في الموقع", "type": "textarea", "sample": "تأمين الموقع بالدورية التحذيرية وإشعار طوارئ البلدية والكهرباء لمباشرة العمود واستكمال إجراءات الحادث."},
        ],
        "legal_fn": lambda m: (
            f"إنه في الزمان والمكان المثبتين آلياً بترويسة المحضر رقم ({_val(m, 'incident_no')})، وأثناء قيامنا بمهام العمل الميداني باشرنا واقعة ({_val(m, 'incident_kind')}) "
            f"المرتبطة بـ ({_val(m, 'party_name')} - هوية: {_val(m, 'party_id')}) والمركبة / الموقع ({_val(m, 'plate_no')}). "
            f"وقد ثبت لنا بالمعاينة المباشرة الآتي: ({_val(m, 'facts_detail')})، وجرى اتخاذ الإجراء الفوري التالي: ({_val(m, 'taken_measure')}). "
            f"وعليه حُرر هذا المحضر الرسمي إثباتاً للواقعة على الطبيعة ورفعه لضابط الخفر لاستكمال اللازم نظاماً."
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
            ], "sample": "عدة مصابين في حادث مروري (مرفق بيانهم)"},
            {"key": "party_name", "label": "اسم المصاب الأول الرباعي", "type": "text", "sample": "موسى بن يحيى بن أحمد خبراني"},
            {"key": "party_id", "label": "رقم الهوية / الإقامة والجنسية", "type": "text", "sample": "1098877665 - سعودي"},
            {"key": "plate_no", "label": "بيانات المركبة وصفته بالحادث", "type": "text", "sample": "تويوتا هايلوكس (ب ر د 3318) - قائد المركبة"},
            {"key": "transport_way", "label": "وسيلة الوصول للمستشفى والحالة الأولية", "type": "select", "options": [
                "نُقل بواسطة فرقة الهلال الأحمر السعودي من موقع الحادث",
                "راجع الطوارئ عن طريق ذويه / نقل خاص إثر الحادث",
                "حضر برفقة الدورية المرورية المباشرة للموقع"
            ], "sample": "نُقل بواسطة فرقة الهلال الأحمر السعودي من موقع الحادث"},
            {"key": "security_hold", "label": "التوجيه الأمني بعد تلقي العلاج", "type": "select", "options": [
                "يُطلق سراحه بعد تلقي العلاج اللازم ما لم يكن مطلوباً لجهة أخرى",
                "يُتحفظ عليه أمنياً ويُشعر قسم مرور العارضة قبل خروجه لاستكمال التحقيق",
                "يبقى تحت الملاحظة الطبية مع تزويدنا بالتقرير الطبي العاجل"
            ], "sample": "يُطلق سراحه بعد تلقي العلاج اللازم ما لم يكن مطلوباً لجهة أخرى"},
            {"key": "other_injured", "label": "بيان المصابين الإضافيين (الاسم، الهوية، الصفة، الإصابة الظاهرة - أو يكتب لا يوجد)", "type": "textarea", "sample": "2- ريان بن موسى خبراني | هوية: 1123344556 | مرافق | إصابة متوسطة بالكتف الأيمن.\n3- عادل محمد علي | إقامة: 2456677889 | قائد الطرف الثاني | رضوض وكدمات متفرقة."},
        ],
        "legal_fn": lambda m: (
            f"سعادة مدير ({_val(m, 'hospital_name')}) المحترم، السلام عليكم ورحمة الله وبركاته.. "
            f"إشارةً إلى الحادث المروري رقم ({_val(m, 'incident_no')})، نبعث لسعادتكم ({_val(m, 'cases_mode')})، وبيانات المصاب الرئيسي: "
            f"({_val(m, 'party_name')} - هوية: {_val(m, 'party_id')} - {_val(m, 'plate_no')})، وبيان المصابين الإضافيين: ({_val(m, 'other_injured')})، "
            f"والواصلين إليكم ({_val(m, 'transport_way')}). نأمل الأمر بإجراء الكشف الطبي اللازم وإسعافهم ومعالجتهم وتنويم من تستدعي حالته الصحية ذلك، "
            f"وموافاتنا بتقرير طبي مفصل ومعتمد لكل حالة يوضح نوع الإصابات ومدة الشفاء المقررة، مع اعتماد التوجيه الأمني التالي حيال الخروج: ({_val(m, 'security_hold')})."
        ),
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
                "نُقل بواسطة إسعاف الهلال الأحمر وتأكدت الوفاة طبياً عند الوصول"
            ], "sample": "وفاة في موقع الحادث ونُقل الجثمان عبر النقل المجهز (الشرشورة) بعد المعاينة"},
            {"key": "forensic_order", "label": "التوجيه النظامي حيال التحفظ والكشف الطبي", "type": "select", "options": [
                "إيداع الجثمان بالثلاجة والتحفظ عليه وعدم تسليمه إلا بخطاب فسح رسمي من قسم مرور العارضة",
                "إجراء الكشف الطبي الظاهري وتزويدنا بتقرير الوفاة الرسمي وأسبابها المباشرة",
                "إبقاء الجثمان رهن الفحص الطبي الشرعي بناءً على توجيه النيابة العامة"
            ], "sample": "إيداع الجثمان بالثلاجة والتحفظ عليه وعدم تسليمه إلا بخطاب فسح رسمي من قسم مرور العارضة"},
            {"key": "other_deceased", "label": "بيانات الجثامين الإضافية عند تعدد الوفيات (الاسم، الهوية، الصفة - أو يكتب لا يوجد)", "type": "textarea", "sample": "لا يوجد (جثمان واحد فقط)."},
        ],
        "legal_fn": lambda m: (
            f"سعادة مدير ({_val(m, 'hospital_name')}) المحترم، السلام عليكم ورحمة الله وبركاته.. "
            f"على إثر الحادث المروري الجسيم رقم ({_val(m, 'incident_no')})، جرى بعث ({_val(m, 'deceased_count')}) للإيداع بثلاجة الموتى طرفكم، "
            f"وبيانات الجثمان: ({_val(m, 'party_name')} - هوية: {_val(m, 'party_id')} - {_val(m, 'plate_no')})، البيان الإضافي للوفيات: ({_val(m, 'other_deceased')})، "
            f"حيث كانت واقعة الوفاة والنقل: ({_val(m, 'transport_death')}). نأمل من سعادتكم الأمر باستلام وإيداع الجثمان/الجثامين في الثلاجة رسمياً، "
            f"وإجراء الكشف الطبي اللازم وموافاتنا بتقرير الوفاة المعتمد، مع التقيد التام بالتوجيه النظامي التالي: ({_val(m, 'forensic_order')})."
        ),
    },

    "med_toxicology": {
        "title": "نموذج إحالة وطلب تحليل سموم",
        "icon": "🧪",
        "subtitle": "طلب سحب عينات حيوية وفحص مخبري للسموم والمسكرات والمؤثرات العقلية وتوثيق سلسلة الحيازة",
        "category": "إحالة طبية",
        "allow_absence": True,
        "require_image": False,
        "fields": [
            {"key": "incident_no", "label": "رقم الحادث / المحضر المرجعي", "type": "text", "sample": "460986890"},
            {"key": "lab_dest", "label": "الجهة المحال إليها (المستشفى / مركز مراقبة السموم)", "type": "text", "sample": "قسم الطوارئ والمختبر / مركز مراقبة السموم والكيمياء الشرعية"},
            {"key": "party_name", "label": "اسم الشخص المحال للفحص رباعياً", "type": "text", "sample": "ماجد بن سالم بن عوض القحطاني"},
            {"key": "party_id", "label": "رقم الهوية / الإقامة والجنسية", "type": "text", "sample": "1089911223 - سعودي"},
            {"key": "plate_no", "label": "بيانات المركبة وصفته بالواقعة", "type": "text", "sample": "هيونداي إلنترا (ط س ع 6120) - قائد المركبة الطرف الأول"},
            {"key": "suspicion_signs", "label": "المسوغ النظامي والقرائن الميدانية لطلب التحليل", "type": "select", "options": [
                "الاشتباه بالقيادة تحت تأثير مسكر أو مخدر أو مؤثر عقلي لقرائن المعاينة الميدانية",
                "حادث مروري جسيم نتج عنه وفيات أو إصابات بالغة يستوجب الفحص النظامي الشامل",
                "ظهور علامات غير طبيعية واضطراب في التوازن والنطق أو العثور على مواد يشتبه بها",
                "سحب عينة حيوية احترازية لحالة منومة أو متوفاة لتحديد المسببات السمية"
            ], "sample": "الاشتباه بالقيادة تحت تأثير مسكر أو مخدر أو مؤثر عقلي لقرائن المعاينة الميدانية"},
            {"key": "sample_type", "label": "نوع العينات والفحص المخبري المطلوب", "type": "select", "options": [
                "سحب عينتي دم وبول للكشف الكمي والنوعي عن الكحول والمخدرات والمؤثرات العقلية",
                "سحب عينة دم وريدية عاجلة لقياس نسبة الكحول والسموم (حالة طوارئ / منوم)",
                "فحص سموم جنائي شامل للعينات الحيوية مع تحريزها بأختام رسمية"
            ], "sample": "سحب عينتي دم وبول للكشف الكمي والنوعي عن الكحول والمخدرات والمؤثرات العقلية"},
            {"key": "escort_info", "label": "بيانات المرافق الأمني وإجراء التسليم والتحريز", "type": "textarea", "sample": "مبعوث برفقة الدورية المرورية المستلمة — يُسحب الفحص تحت الإشراف المباشر مع توثيق سلسلة الحيازة وإعادة المذكور برفقة المرافق الأمني فور الانتهاء."},
        ],
        "legal_fn": lambda m: (
            f"سعادة مدير ({_val(m, 'lab_dest')}) المحترم، السلام عليكم ورحمة الله وبركاته.. "
            f"استناداً إلى أحكام نظام المرور ولائحته التنفيذية وإجراءات الاستدلال في الحادث/المحضر رقم ({_val(m, 'incident_no')})، "
            f"نبعث لسعادتكم المدعو ({_val(m, 'party_name')})، حامل الهوية رقم ({_val(m, 'party_id')})، وعلاقته بالواقعة ({_val(m, 'plate_no')})، "
            f"وذلك بناءً على المسوغ النظامي: ({_val(m, 'suspicion_signs')}). نأمل توجيه المختصين بإجراء ({_val(m, 'sample_type')}) وفق الأصول الفنية المعتمدة "
            f"وتوثيق وقت أخذ العينة وسلسلة الحيازة النظامية، وموافاتنا بالتقرير المخبري القطعي السري في مظروف رسمي مختوم، مع مراعاة الترتيب الأمني: ({_val(m, 'escort_info')})."
        ),
    },
}

# المحضر الخامس داخل قائمة المحاضر الرسمية — البيانات من ABU_ARISH_IMPOUND_TEMPLATE
TRAFFIC_FORMS[ABU_ARISH_IMPOUND_TEMPLATE["id"]] = _minutes_form_from_template(ABU_ARISH_IMPOUND_TEMPLATE)


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
            VALUES (1, 'قسم مرور العارضة', 'ضابط الخفر', '', 'وحدة الحوادث', '', '17.0924° N, 43.0956° E')
        """)

    c.execute('UPDATE shift_settings SET officer_rank=?, duty_rank=? WHERE id=1 AND officer_rank=? AND duty_rank=?', ('ضابط الخفر','وحدة الحوادث','وحدة الحوادث','ضابط الخفر'))

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


def get_shift_settings() -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM shift_settings WHERE id = 1").fetchone()
    conn.close()
    return dict(row)


def update_shift_settings(dept, o_rank, o_name, d_rank, d_name, gps):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        UPDATE shift_settings
        SET dept_name=?, officer_rank=?, officer_name=?, duty_rank=?, duty_name=?, default_gps=?
        WHERE id = 1
    """, (dept, o_rank, o_name, d_rank, d_name, gps))
    conn.commit()
    conn.close()


def save_record_to_db(rec: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO records (
            doc_no, form_id, form_title, category, party_name, party_id, plate_no,
            gps_coords, created_at, fields_json, legal_text, citizen_stamp_b64,
            citizen_auth_mode, officer_stamp_b64, attachment_b64, officer_full,
            duty_full, dept_name, verify_hash, officer_auth_mode, duty_auth_mode,
            duty_stamp_b64, receiver_name, receiver_role
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    ))
    conn.commit()
    conn.close()


def search_records_db(q: str = "") -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    q = q.strip()
    if not q:
        rows = conn.execute("SELECT * FROM records ORDER BY id DESC").fetchall()
    else:
        like = f"%{q}%"
        rows = conn.execute("""
            SELECT * FROM records
            WHERE party_id LIKE ? OR plate_no LIKE ? OR party_name LIKE ? OR doc_no LIKE ? OR form_title LIKE ?
            ORDER BY id DESC
        """, (like, like, like, like, like)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_record_db(rec_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM records WHERE id = ?", (rec_id,))
    conn.commit()
    conn.close()


# =====================================================================
# 5. قالب الطباعة الرسمي مقاس A4 بالترويسة الخماسية المعتمدة وشعار المرور
# =====================================================================
def _sig_slot_img(b64: str, slot_id: str) -> str:
    if b64:
        return (
            f"<img id='{slot_id}' class='sig-slot-img' "
            f"src='data:image/png;base64,{b64}' "
            f"style='height:62px; max-width:96%; object-fit:contain;' />"
        )
    return (
        f"<img id='{slot_id}' class='sig-slot-img' src='' alt='' "
        f"style='height:62px; max-width:96%; object-fit:contain; display:none;' />"
    )


def _live_pad_card(pad_id: str, title: str, subtitle: str) -> str:
    return f"""
    <div class="live-pad-card" data-pad="{pad_id}">
        <div class="live-pad-title">{title}</div>
        <div class="live-pad-sub">{subtitle}</div>
        <canvas id="pad_{pad_id}" class="live-pad-canvas" width="900" height="220"
            style="touch-action:none; cursor:crosshair;"></canvas>
        <div class="live-pad-actions no-print">
            <button type="button" class="clear-sig-btn" onclick="clearLivePad('{pad_id}')">مسح التوقيع</button>
        </div>
    </div>
    """


_WIDE_FIELD_KEYS = {
    "exterior_damages",
    "interior_inventory",
    "tow_truck_info",
    "legal_article",
    "release_condition",
    "impound_reason_cat",
}


def _field_is_wide(field: dict, value: str) -> bool:
    if field.get("type") == "textarea":
        return True
    if field.get("key") in _WIDE_FIELD_KEYS:
        return True
    label = str(field.get("label") or "")
    if len(label) > 42 or len(value) > 48:
        return True
    return False


def _data_table_rows(form_def: dict | None, fields_map: dict, dense: bool) -> str:
    def pair_cells(label: str, value: str, wide: bool) -> str:
        safe_label = html.escape(label)
        safe_value = html.escape(value)
        if wide:
            return f"<td class='lbl'>{safe_label}</td><td class='val span3' colspan='3'>{safe_value}</td>"
        return f"<td class='lbl half'>{safe_label}</td><td class='val half'>{safe_value}</td>"

    if not form_def:
        rows = []
        for key, value in fields_map.items():
            shown = str(value or "-")
            rows.append(f"<tr>{pair_cells(str(key), shown, True)}</tr>")
        return "".join(rows)

    rows = []
    pending = None
    for field in form_def["fields"]:
        if not _include_field_on_a4(field, fields_map):
            continue
        shown = str(fields_map.get(field["key"], "-") or "-")
        label = str(field.get("a4_label") or field["label"])
        sibling_key = field.get("a4_with")
        if sibling_key:
            sibling = str(fields_map.get(sibling_key, "") or "").strip()
            if sibling:
                shown = f"{shown} — {sibling}"
        compose_keys = field.get("a4_compose") or []
        if compose_keys:
            principal_id = str(fields_map.get("principal_id", "") or "").strip()
            wakala_no = str(fields_map.get("wakala_no", "") or "").strip()
            wakala_date = str(fields_map.get("wakala_date", "") or "").strip()
            shown = f"{shown} — هوية: {principal_id or '-'} | وكالة رقم {wakala_no or '-'} بتاريخ {wakala_date or '-'}"
        field = {**field, "label": label}
        wide = dense and _field_is_wide(field, shown)
        if not dense or wide:
            if pending:
                rows.append(f"<tr>{pair_cells(pending[0], pending[1], True)}</tr>")
                pending = None
            if dense and wide:
                rows.append(f"<tr>{pair_cells(field['label'], shown, True)}</tr>")
            else:
                safe_label = html.escape(str(field["label"]))
                safe_value = html.escape(shown)
                rows.append(f"<tr><td class='lbl'>{safe_label}</td><td class='val'>{safe_value}</td></tr>")
            continue
        if pending is None:
            pending = (field["label"], shown)
        else:
            rows.append(
                "<tr>"
                + pair_cells(pending[0], pending[1], False)
                + pair_cells(field["label"], shown, False)
                + "</tr>"
            )
            pending = None
    if pending:
        rows.append(f"<tr>{pair_cells(pending[0], pending[1], True)}</tr>")
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
    dense = field_count > 10
    rows_html = _data_table_rows(form_def, fields_map, dense)
    data_tbl_cls = "data-tbl cols-4" if dense else "data-tbl"

    qr_payload = f"DOC:{rec['doc_no']}|ID:{rec['party_id']}|PLATE:{rec['plate_no']}|SEAL:{rec['verify_hash']}"
    qr_b64 = generate_qr_png_b64(qr_payload)

    center_logo_html = (
        f"<img src='data:image/png;base64,{logo_b64}' style='height:82px; width:auto; object-fit:contain;' alt='شعار المرور' />"
        if logo_b64
        else "<div style='font-size:13px; font-weight:800; color:#0f3d2e;'>الإدارة العامة للمرور</div>"
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

    needs_citizen_pad = interactive_sig and ("توقيع حي" in citizen_mode) and not rec.get("citizen_stamp_b64")
    needs_officer_pad = interactive_sig and ("توقيع حي" in officer_mode) and not rec.get("officer_stamp_b64")
    needs_duty_pad = interactive_sig and ("توقيع حي" in duty_mode) and not rec.get("duty_stamp_b64")

    # إرشاد التوقيع يبقى في لوحة الرسم فوق الورقة، لا داخل خلايا المحضر
    guide_hint = ""

    # --- Citizen / receiver cell ---
    if rec.get("citizen_stamp_b64"):
        citizen_box_inner = _sig_slot_img(rec["citizen_stamp_b64"], "slot_citizen")
    elif needs_citizen_pad:
        citizen_box_inner = (
            "<div class='sig-guide'>"
            + _sig_slot_img("", "slot_citizen")
            + guide_hint
            + "</div>"
        )
    elif is_medical and "ختم وتوقيع" in citizen_mode:
        citizen_box_inner = """
        <div class='sig-guide sig-guide-print-clean' style='border:1px dashed #64748b; border-radius:6px; padding:8px 6px; margin:3px 4px; font-size:10px; color:#334155; line-height:1.6;'>
            التوقيع والختم الرسمي لجهة الاستلام
        </div>
        """
    elif "غياب" in citizen_mode or "امتناع" in citizen_mode:
        citizen_box_inner = "<div style='padding:16px 0; font-weight:700; color:#7f1d1d; font-size:11px;'>غياب الطرف / امتناع مثبت بالمحضر</div>"
    else:
        citizen_box_inner = _sig_slot_img(rec.get("citizen_stamp_b64", ""), "slot_citizen")

    # --- Officer cell ---
    if rec.get("officer_stamp_b64"):
        officer_box_inner = _sig_slot_img(rec["officer_stamp_b64"], "slot_officer")
    elif needs_officer_pad:
        officer_box_inner = (
            "<div class='sig-guide'>"
            + _sig_slot_img("", "slot_officer")
            + guide_hint
            + "</div>"
        )
    else:
        officer_box_inner = _sig_slot_img("", "slot_officer")

    # --- Duty cell ---
    if rec.get("duty_stamp_b64"):
        duty_box_inner = _sig_slot_img(rec["duty_stamp_b64"], "slot_duty")
    elif needs_duty_pad:
        duty_box_inner = (
            "<div class='sig-guide'>"
            + _sig_slot_img("", "slot_duty")
            + guide_hint
            + "</div>"
        )
    elif "ختم" in duty_mode or not duty_mode:
        duty_box_inner = """
            <div style="display:inline-block; border:1.5px solid #0f3d2e; color:#0f3d2e; padding:3px 10px; border-radius:5px; font-size:10.5px; font-weight:800;">
                مُصادق ومُعتمد نظاماً
            </div>
        """
    else:
        duty_box_inner = _sig_slot_img("", "slot_duty")

    # جدول التوقيعات ثابت بـ 3 أعمدة متساوية: جهة الاستلام | ضابط الخفر | وحدة الحوادث
    col_width = "33.3%"

    # Live signature dock ABOVE A4 (المناوب/المواطن + ضابط الخفر فقط، مع وحدة الحوادث عند الحاجة)
    dock_cards = []
    if needs_citizen_pad:
        dock_cards.append(_live_pad_card("citizen", citizen_pad_title, citizen_pad_sub))
    if needs_officer_pad:
        dock_cards.append(_live_pad_card("officer", "لوحة توقيع: ضابط الخفر المناوب", rec.get("officer_full", "")))
    if needs_duty_pad:
        dock_cards.append(_live_pad_card("duty", "لوحة توقيع: مصادقة وحدة الحوادث", rec.get("duty_full", "")))

    live_dock_html = ""
    if dock_cards:
        live_dock_html = (
            '<div class="live-sig-dock no-print">'
            '<div class="live-sig-dock-head">✍️ لوحات التوقيع الحي بالإصبع (ارسم هنا — يُنسخ فوراً إلى خانات A4)</div>'
            '<div class="live-sig-dock-grid">'
            + "".join(dock_cards)
            + "</div></div>"
        )

    attachment_block = ""
    show_atts = rec.get("show_attachments_in_print", True)
    att_items = parse_attachments(rec.get("attachment_b64"))
    if show_atts and att_items:
        cards = []
        for att in att_items:
            safe_name = html.escape(str(att.get("name") or "مرفق"))
            kind = (att.get("kind") or "image").lower()
            if kind == "pdf":
                cards.append(
                    f'<div class="att-card att-pdf-card">'
                    f'<div class="att-pdf-icon">📄</div>'
                    f'<div class="att-pdf-name">{safe_name}</div>'
                    f'<div class="att-pdf-note">مرفق PDF محفوظ مع المعاملة</div>'
                    f"</div>"
                )
            else:
                mime = html.escape(str(att.get("mime") or "image/png"))
                b64 = att.get("b64") or ""
                cards.append(
                    f'<div class="att-card">'
                    f'<img src="data:{mime};base64,{b64}" alt="{safe_name}" />'
                    f'<div class="att-caption">{safe_name}</div>'
                    f"</div>"
                )
        attachment_block = f"""
        <div class="attachment-section">
            <div class="attachment-title">📎 المرفقات المصورة المعتمدة في التقرير</div>
            <div class="attachment-grid">{"".join(cards)}</div>
        </div>
        """

    if is_letter:
        legal_box_title = "صيغة الخطاب الرسمي الموجه لحجز مرور محافظة أبو عريش:"
    elif is_medical:
        legal_box_title = "نص الخطاب والتوجيه الرسمي المعتمد:"
    else:
        legal_box_title = f"الصيغة النظامية المعتمدة ({rec['category']}):"
    banner_title = (form_def or {}).get("official_title") or rec["form_title"]
    sheet_cls = "a4-sheet dense-fit" if dense else "a4-sheet"

    return f"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<title>{rec['doc_no']} - {banner_title}</title>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
    * {{ box-sizing: border-box; font-family: 'Cairo', sans-serif; }}
    /* ورقة A4 معزولة داخل iframe: نص داكن فوق خلفية بيضاء بغض النظر عن ثيم الجهاز */
    html, body {{ color-scheme: light; }}
    body {{ margin: 0; padding: 14px; background: #0d1316; direction: rtl; color: #e2e8f0; }}
    .toolbar {{
        max-width: 210mm; margin: 0 auto 12px auto; display: flex; gap: 10px;
        justify-content: center; background: #0f3d2e; border: 1px solid #d4a853; padding: 10px; border-radius: 10px;
    }}
    .print-btn {{
        background: linear-gradient(135deg, #d4a853 0%, #a37a2c 100%); color: #fff; border: none; padding: 8px 24px;
        font-size: 14px; font-weight: 800; border-radius: 8px; cursor: pointer;
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
        background: #f8fafc; display: block; touch-action: none;
    }}
    .live-pad-actions {{ margin-top: 6px; text-align: center; }}
    .clear-sig-btn {{
        font-size: 11px; padding: 4px 12px; cursor: pointer; border-radius: 6px;
        border: 1px solid #475569; background: #1e293b; color: #e2e8f0;
    }}
    .sig-guide {{ border: 1px dashed #94a3b8; border-radius: 6px; padding: 4px; min-height: 48px; }}
    .sig-guide-hint, .sig-mode-note {{ display: none !important; }}
    .sig-person {{ font-size: 10.5px; font-weight: 800; margin-bottom: 2px; }}
    .sig-role {{ font-size: 9.5px; font-weight: 700; color: #0f3d2e; margin-bottom: 3px; }}
    .sig-slot-img {{ background: transparent; }}
    @media screen {{
        body {{ padding: 8px !important; overflow-x: hidden; }}
        .toolbar {{ width: 100%; max-width: 794px; padding: 8px; }}
        .print-btn {{ width: 100%; max-width: 360px; font-size: 13px; padding: 8px 14px; }}
        .sheet-stage {{ width: 100%; max-width: 794px; margin: 0 auto; height: var(--stage-h, auto); overflow: hidden; position: relative; }}
        .a4-sheet {{
            width: 794px !important; min-height: 1100px; margin: 0;
            background: #ffffff !important; color: #0f172a !important; padding: 9mm 12mm; border: 2px solid #0f3d2e;
            display: flex; flex-direction: column; justify-content: space-between;
            box-shadow: 0 12px 32px rgba(0,0,0,0.45);
            transform-origin: top right; transform: scale(var(--a4-scale, 1));
        }}
        .a4-sheet, .a4-sheet p, .a4-sheet td, .a4-sheet th, .a4-sheet div, .a4-sheet span {{
            color: #0f172a;
        }}
        .a4-sheet .doc-banner {{ color: #ffffff !important; }}
    }}
    .hdr {{
        display: grid; grid-template-columns: 1.35fr 0.9fr 1.15fr;
        align-items: center; border-bottom: 2px solid #0f3d2e; padding-bottom: 8px;
    }}
    .hdr-right {{ text-align: center; line-height: 1.48; }}
    .hdr-right p {{ margin: 0; font-size: 11.5px; font-weight: 800; color: #0f172a !important; }}
    .hdr-center {{ text-align: center; display: flex; justify-content: center; align-items: center; }}
    .hdr-left {{ text-align: right; padding-right: 12px; line-height: 1.65; }}
    .hdr-left p {{ margin: 0; font-size: 10.5px; font-weight: 700; color: #0f172a !important; }}
    .doc-banner {{
        background: #0f3d2e; color: #ffffff !important; text-align: center;
        padding: 5px; border-radius: 6px; font-size: 14.5px; font-weight: 800; margin: 8px 0;
    }}
    table.data-tbl {{ width: 100%; border-collapse: collapse; margin-bottom: 8px; }}
    table.data-tbl td {{ border: 1px solid #cbd5e1; padding: 4px 8px; font-size: 11px; vertical-align: top; direction: rtl; text-align: right; color: #0f172a !important; }}
    table.data-tbl td.lbl {{ width: 32%; background: #f4f7f6; font-weight: 700; color: #0f3d2e !important; }}
    table.data-tbl td.val {{ width: 68%; color: #0f172a !important; font-weight: 600; white-space: pre-line; }}
    table.data-tbl.cols-4 td.lbl.half {{ width: 17%; }}
    table.data-tbl.cols-4 td.val.half {{ width: 33%; }}
    table.data-tbl.cols-4 td.lbl {{ width: 17%; }}
    table.data-tbl.cols-4 td.val.span3 {{ width: auto; }}
    .a4-sheet.dense-fit {{ min-height: 1040px; padding: 6mm 8mm; }}
    .a4-sheet.dense-fit .hdr {{ padding-bottom: 4px; }}
    .a4-sheet.dense-fit .hdr-right p {{ font-size: 10.5px; line-height: 1.32; }}
    .a4-sheet.dense-fit .hdr-left p {{ font-size: 10px; line-height: 1.4; }}
    .a4-sheet.dense-fit .doc-banner {{ font-size: 13px; margin: 4px 0; padding: 3px 6px; }}
    .a4-sheet.dense-fit table.data-tbl {{ margin-bottom: 5px; }}
    .a4-sheet.dense-fit table.data-tbl td {{ padding: 3px 6px; font-size: 10px; }}
    .a4-sheet.dense-fit .legal-box {{ padding: 6px 8px; font-size: 10.5px; line-height: 1.55; }}
    .a4-sheet.dense-fit table.sig-tbl td {{ height: 70px; padding: 3px; }}
    .a4-sheet.dense-fit .sig-slot-img {{ height: 46px !important; }}
    .a4-sheet.dense-fit .footer-qr {{ margin-top: 4px; padding: 3px 8px; }}
    .legal-box {{
        background: #f8fafc; border: 1px solid #0f3d2e; border-right: 5px solid #0f3d2e;
        border-radius: 6px; padding: 9px 12px; font-size: 11.5px; line-height: 1.72; text-align: justify; color: #0f172a !important;
    }}
    table.sig-tbl {{ width: 100%; border-collapse: collapse; margin-top: 8px; text-align: center; page-break-inside: avoid; break-inside: avoid; }}
    table.sig-tbl th {{ background: #f1f5f3; border: 1px solid #94a3b8; padding: 4px; font-size: 10.5px; color: #0f3d2e !important; }}
    table.sig-tbl td {{ border: 1px solid #94a3b8; padding: 5px; width: {col_width}; vertical-align: middle; height: 86px; color: #0f172a !important; }}
    .sig-footer {{ page-break-inside: avoid; break-inside: avoid; }}
    .footer-qr {{
        margin-top: 7px; background: #f4f7f6; border: 1px solid #cbd5e1; border-radius: 6px;
        padding: 5px 10px; display: flex; justify-content: space-between; align-items: center;
        page-break-inside: avoid; break-inside: avoid;
    }}
    .attachment-section {{
        margin-top: 8px; border: 1px dashed #64748b; border-radius: 8px; padding: 8px 10px;
        background: #f8fafc; page-break-inside: avoid;
    }}
    .attachment-title {{
        font-size: 11px; font-weight: 800; color: #0f3d2e; margin-bottom: 8px; text-align: right;
    }}
    .attachment-grid {{
        display: flex; flex-wrap: wrap; gap: 10px; justify-content: flex-start; align-items: flex-start;
    }}
    .att-card {{
        width: calc(50% - 5px); max-width: 320px; text-align: center;
    }}
    .att-card img {{
        max-width: 100%; max-height: 180px; width: auto; height: auto;
        object-fit: contain; border: 1px solid #cbd5e1; border-radius: 6px; background: #fff;
    }}
    .att-caption {{
        font-size: 9.5px; color: #475569; margin-top: 4px; font-weight: 600; word-break: break-word;
    }}
    .att-pdf-card {{
        border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px 8px; background: #fff;
        min-height: 90px; display: flex; flex-direction: column; justify-content: center;
    }}
    .att-pdf-icon {{ font-size: 22px; line-height: 1; }}
    .att-pdf-name {{ font-size: 10.5px; font-weight: 700; color: #0f172a; margin-top: 4px; word-break: break-word; }}
    .att-pdf-note {{ font-size: 9px; color: #64748b; margin-top: 2px; }}
    @media print {{
        @page {{ size: A4 portrait; margin: 7mm; }}
        html, body {{ background: #fff !important; padding: 0 !important; margin: 0 !important; overflow: visible !important; }}
        .toolbar, .no-print, .live-sig-dock, .clear-sig-btn, .sig-guide-hint, .sig-mode-note,
        .live-pad-actions, .live-sig-dock-head {{ display: none !important; }}
        .sig-guide, .sig-guide-print-clean {{
            border: none !important; padding: 0 !important; margin: 0 !important; background: transparent !important;
        }}
        .live-pad-canvas {{ display: none !important; border: none !important; }}
        .sheet-stage {{ width: 100% !important; max-width: none !important; height: auto !important; overflow: visible !important; margin: 0 !important; }}
        table.data-tbl td {{ padding: 3.5px 7px; }}
        table.sig-tbl td {{ height: 72px; padding: 3px 4px; }}
        .sig-footer, table.sig-tbl, .footer-qr {{ page-break-inside: avoid !important; break-inside: avoid !important; }}
        .a4-sheet {{
            width: 100% !important; min-height: 270mm !important; margin: 0 !important;
            background: #ffffff; color: #0f172a; padding: 5mm 6mm; border: 2px solid #0f3d2e;
            display: flex; flex-direction: column; justify-content: space-between;
            box-shadow: none !important; transform: none !important; page-break-inside: avoid;
        }}
        .a4-sheet.dense-fit {{
            min-height: 0 !important; height: auto !important; padding: 3mm 4mm;
            page-break-after: avoid; page-break-inside: avoid;
        }}
        .a4-sheet.dense-fit table.data-tbl td {{ padding: 3.5px 7px; font-size: 9.5px; }}
        .a4-sheet.dense-fit .legal-box {{ font-size: 10px; line-height: 1.48; padding: 5px 7px; }}
        .a4-sheet.dense-fit table.sig-tbl td {{ height: 58px; }}
        .a4-sheet.dense-fit .sig-slot-img {{ height: 40px !important; }}
    }}
</style>
</head>
<body>
    <div class="toolbar no-print">
        <button class="print-btn" onclick="window.print()">🖨️ طباعة الوثيقة الرسمية / حفظ كملف A4 PDF</button>
    </div>

    {live_dock_html}

    <div class="sheet-stage" id="sheetStage"><div class="{sheet_cls}" id="a4Sheet">
        <div>
            <div class="hdr">
                <div class="hdr-right">
                    <p>المملكة العربية السعودية</p>
                    <p>وزارة الداخلية</p>
                    <p>الأمن العام - الإدارة العامة للمرور</p>
                    <p>إدارة مرور منطقة جازان</p>
                    <p style="color:#0f3d2e;">قسم مرور العارضة</p>
                </div>
                <div class="hdr-center">
                    {center_logo_html}
                </div>
                <div class="hdr-left">
                    <p>الرقم المرجعي: {rec['doc_no']}</p>
                    <p>التاريخ والوقت: {rec['created_at']}</p>
                    <p>إحداثيات الموقع: {rec['gps_coords']}</p>
                </div>
            </div>

            <div class="doc-banner">{banner_title}</div>
            <table class="{data_tbl_cls}">{rows_html}</table>

            <div class="legal-box" dir="rtl" style="direction:rtl; text-align:justify; text-align-last:right;">
                <div dir="rtl" style="font-weight:800; color:#0f3d2e; margin-bottom:4px; direction:rtl; text-align:right;">{legal_box_title}</div>
                <div dir="rtl" style="direction:rtl; unicode-bidi:embed; text-align:justify; text-align-last:right; text-justify:inter-word; line-height:1.8;">&#8207;{rec['legal_text']}</div>
            </div>
            {attachment_block}
        </div>

        <div class="sig-footer">
            <table class="sig-tbl">
                <thead>
                    <tr>
                        <th>{html.escape(col1_header)}</th>
                        <th>ضابط الخفر</th>
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
                            <div class="sig-person">{html.escape(str(rec['duty_full']))}</div>
                            {duty_box_inner}
                        </td>
                    </tr>
                </tbody>
            </table>

            <div class="footer-qr">
                <div>
                    <div style="font-size:9.5px; font-weight:800; color:#0f3d2e;">
                        وثيقة رسمية مقفلة إلكترونياً ضد الكشط أو التعديل اليدوي — قسم مرور العارضة.
                    </div>
                    <div style="font-size:9px; color:#475569;">ختم التحقق الرقمي (SHA-256 Seal): {rec['verify_hash']}</div>
                </div>
                <img src="data:image/png;base64,{qr_b64}" style="width:48px; height:48px;" />
            </div>
        </div>
    </div>
</div>
<script>
    const PEN_COLOR = '#0d47a1';
    const LIVE_PADS = {json.dumps([
        pid for pid, flag in (
            ("citizen", needs_citizen_pad),
            ("officer", needs_officer_pad),
            ("duty", needs_duty_pad),
        ) if flag
    ], ensure_ascii=False)};

    function syncPadToSlot(padId) {{
        const canvas = document.getElementById('pad_' + padId);
        const slot = document.getElementById('slot_' + padId);
        if (!canvas || !slot) return;
        const blank = document.createElement('canvas');
        blank.width = canvas.width; blank.height = canvas.height;
        const empty = canvas.toDataURL() === blank.toDataURL();
        if (empty) {{
            slot.removeAttribute('src');
            slot.style.display = 'none';
            return;
        }}
        // transparent PNG sync into A4 slot
        slot.src = canvas.toDataURL('image/png');
        slot.style.display = 'inline-block';
    }}

    function wireLivePad(padId) {{
        const canvas = document.getElementById('pad_' + padId);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        ctx.strokeStyle = PEN_COLOR;
        ctx.lineWidth = 2.8;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        let drawing = false;
        const getPt = (e) => {{
            const r = canvas.getBoundingClientRect();
            const t = (e.touches && e.touches.length) ? e.touches[0] : ((e.changedTouches && e.changedTouches.length) ? e.changedTouches[0] : e);
            return {{
                x: (t.clientX - r.left) * (canvas.width / (r.width || 1)),
                y: (t.clientY - r.top) * (canvas.height / (r.height || 1))
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
            syncPadToSlot(padId);
        }};
        const moveDraw = (e) => {{
            if (!drawing) return;
            if (e.cancelable) e.preventDefault();
            e.stopPropagation();
            const p = getPt(e);
            ctx.lineTo(p.x, p.y);
            ctx.stroke();
            syncPadToSlot(padId);
        }};
        const endDraw = () => {{ drawing = false; syncPadToSlot(padId); }};
        canvas.addEventListener('mousedown', startDraw);
        canvas.addEventListener('mousemove', moveDraw);
        window.addEventListener('mouseup', endDraw);
        canvas.addEventListener('touchstart', startDraw, {{ passive: false }});
        canvas.addEventListener('touchmove', moveDraw, {{ passive: false }});
        window.addEventListener('touchend', endDraw, {{ passive: false }});
        window.addEventListener('touchcancel', endDraw, {{ passive: false }});
    }}

    function clearLivePad(padId) {{
        const canvas = document.getElementById('pad_' + padId);
        if (!canvas) return;
        canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
        syncPadToSlot(padId);
    }}

    LIVE_PADS.forEach(wireLivePad);

    function fitA4Sheet() {{
        const stage = document.getElementById("sheetStage");
        const sheet = document.getElementById("a4Sheet");
        if (!stage || !sheet) return;
        const baseW = 794;
        const availW = stage.clientWidth || baseW;
        const scale = availW < baseW ? (availW / baseW) : 1;
        stage.style.setProperty("--a4-scale", scale.toFixed(4));
        const scaledH = Math.ceil(sheet.offsetHeight * scale);
        stage.style.setProperty("--stage-h", scale < 1 ? (scaledH + 6) + "px" : "auto");
        try {{
            if (window.frameElement) {{
                const dock = document.querySelector('.live-sig-dock');
                const dockH = dock ? dock.offsetHeight + 18 : 0;
                const totalH = (scale < 1 ? scaledH : sheet.offsetHeight) + 85 + dockH;
                window.frameElement.style.height = totalH + "px";
            }}
        }} catch (e) {{}}
    }}
    window.addEventListener("load", fitA4Sheet);
    window.addEventListener("resize", fitA4Sheet);
    if (document.fonts && document.fonts.ready) {{ document.fonts.ready.then(fitA4Sheet); }}
    setTimeout(fitA4Sheet, 150);
    setTimeout(fitA4Sheet, 600);
</script>
</body>
</html>
"""


# =====================================================================
# 6. إدارة حالة الجلسة والتنقل
# =====================================================================
init_db()
shift = get_shift_settings()
logo_b64_global = get_traffic_logo_b64()
now_ksa = datetime.now(KSA_TZ)

unit_display = format_entity(shift["officer_rank"], shift["officer_name"])
duty_display = format_entity(shift["duty_rank"], shift["duty_name"])

VALID_NAV_TABS = ["النماذج الميدانية", "الأرشيف المحلي", "الإعدادات والبصمة"]
NAV_ALIASES = {
    "مناوبة الخفر": "الإعدادات والبصمة",
    "بصمة الشحن OTG": "الإعدادات والبصمة",
}
CATEGORY_TAB_MAP = {
    "✍️ الإقرارات الميدانية (4)": "إقرار",
    "🚓 المحاضر النظامية (5)": "محضر",
    "🚑 الطبية والجنائية (3)": "إحالة طبية",
}

if "nav_tab" not in st.session_state:
    st.session_state.nav_tab = "النماذج الميدانية"
# ترحيل التبويبات القديمة إلى الشريط الأفقي المدمج
if st.session_state.nav_tab in NAV_ALIASES:
    st.session_state.nav_tab = NAV_ALIASES[st.session_state.nav_tab]
if st.session_state.nav_tab not in VALID_NAV_TABS:
    st.session_state.nav_tab = "النماذج الميدانية"
if "opened_form_id" not in st.session_state:
    st.session_state.opened_form_id = None
# إزالة فلتر «جميع النماذج» القديم إن وُجد في الجلسة
if "catalog_filter" in st.session_state:
    del st.session_state["catalog_filter"]
if "doc_no" not in st.session_state:
    st.session_state.doc_no = f"KH-{now_ksa.strftime('%y%m%d-%H%M%S')}"
if "doc_time" not in st.session_state:
    st.session_state.doc_time = now_ksa.strftime("%Y/%m/%d - %H:%M")
if "citizen_locked" not in st.session_state:
    st.session_state.citizen_locked = False
if "citizen_stamp_b64" not in st.session_state:
    st.session_state.citizen_stamp_b64 = ""
if "citizen_auth_mode" not in st.session_state:
    st.session_state.citizen_auth_mode = ""
if "officer_approved" not in st.session_state:
    st.session_state.officer_approved = False
if "officer_stamp_b64" not in st.session_state:
    st.session_state.officer_stamp_b64 = ""
if "officer_auth_mode" not in st.session_state:
    st.session_state.officer_auth_mode = "توقيع حي على الشاشة بالإصبع (لضابط الخفر)"
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
    st.session_state.doc_no = f"KH-{t_now.strftime('%y%m%d-%H%M%S')}"
    st.session_state.doc_time = t_now.strftime("%Y/%m/%d - %H:%M")
    st.session_state.citizen_locked = False
    st.session_state.citizen_stamp_b64 = ""
    st.session_state.citizen_auth_mode = ""
    st.session_state.officer_approved = False
    st.session_state.officer_stamp_b64 = ""
    st.session_state.officer_auth_mode = "توقيع حي على الشاشة بالإصبع (لضابط الخفر)"
    st.session_state.duty_auth_mode = "ختم المصادقة النظامي لوحدة الحوادث"
    st.session_state.duty_stamp_b64 = ""
    st.session_state.receiver_name = ""
    st.session_state.receiver_role = RECEIVER_ROLE_OPTIONS[0]
    st.session_state.officer_full_override = ""
    st.session_state.attachments = []
    st.session_state.attachment_b64 = ""
    st.session_state.show_attachments_in_print = True
    st.session_state.att_upload_nonce = int(st.session_state.get("att_upload_nonce") or 0) + 1


all_archived = search_records_db("")
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
<div class="compact-status-bar">
    <span class="status-chip">🟢 محلي جاهز</span>
    <span class="status-chip gold">🧬 {html.escape(scanner_short)}</span>
    <span class="status-chip gps">GPS {html.escape(str(shift['default_gps']))}</span>
    <span class="status-chip time">{now_ksa.strftime('%Y/%m/%d %H:%M')}</span>
</div>
""", unsafe_allow_html=True)

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
# القسم الأول: النماذج الميدانية (12 نموذجاً)
# =====================================================================
if st.session_state.nav_tab == "النماذج الميدانية":

    if st.session_state.opened_form_id is None:
        tab_decl, tab_min, tab_med = st.tabs(list(CATEGORY_TAB_MAP.keys()))
        with tab_decl:
            render_compact_form_buttons("إقرار", primary=False)
        with tab_min:
            render_compact_form_buttons("محضر", primary=False)
        with tab_med:
            render_compact_form_buttons("إحالة طبية", primary=False)

    else:
        fid = st.session_state.opened_form_id
        form_def = TRAFFIC_FORMS[fid]
        cat_badge_cls = {"إقرار": "green", "محضر": "gold", "إحالة طبية": "med"}.get(form_def["category"], "green")

        top_bar1, top_bar2, top_bar3 = st.columns([1.3, 1.3, 1.4])
        with top_bar1:
            if st.button("↩️ العودة للنماذج", use_container_width=True):
                st.session_state.opened_form_id = None
                safe_rerun()
        with top_bar2:
            if st.button("⚡ تعبئة بيانات تجريبية فورية", type="primary", use_container_width=True, disabled=st.session_state.citizen_locked):
                for fld in form_def["fields"]:
                    st.session_state[f"inp_{fid}_{fld['key']}"] = fld["sample"]
                safe_rerun()
        with top_bar3:
            if st.button("🆕 تفريغ وبدء سجل جديد", use_container_width=True):
                for fld in form_def["fields"]:
                    wkey = f"inp_{fid}_{fld['key']}"
                    if wkey in st.session_state:
                        del st.session_state[wkey]
                reset_doc_state()
                safe_rerun()

        st.markdown(f"""
        <div class="hero-shift-card" style="padding:16px 20px; margin-top:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;">
                <div>
                    <span class="badge-{cat_badge_cls}">قسم مرور العارضة</span>
                    <h3 style="margin:6px 0 2px 0; color:#ffffff; font-size:20px;">{form_def['icon']} {form_def['title']}</h3>
                    <div style="font-size:13px; color:#f3cc7a; font-weight:700;">{form_def.get('official_title', '')}</div>
                </div>
                <div style="font-size:12.5px; color:#d4a853; font-weight:700;">
                    الرقم المرجعي: {st.session_state.doc_no}  |  {st.session_state.doc_time}
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

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
                    st.session_state.officer_approved = False
                    st.session_state.officer_stamp_b64 = ""
                    st.session_state.officer_auth_mode = "توقيع حي على الشاشة بالإصبع (لضابط الخفر)"
                    st.session_state.duty_auth_mode = "ختم المصادقة النظامي لوحدة الحوادث"
                    st.session_state.duty_stamp_b64 = ""
                    safe_rerun()

        def render_field(fld):
            wkey = f"inp_{fid}_{fld['key']}"
            locked = st.session_state.citizen_locked
            if fld.get("prefill_sample") and wkey not in st.session_state:
                st.session_state[wkey] = fld.get("sample", "")
            if fld["type"] == "select":
                opts = fld["options"]
                default_idx = opts.index(st.session_state[wkey]) if (wkey in st.session_state and st.session_state[wkey] in opts) else 0
                return st.selectbox(fld["label"], options=opts, index=default_idx, key=wkey, disabled=locked)
            if fld["type"] == "textarea":
                return st.text_area(fld["label"], key=wkey, height=88, disabled=locked)
            return st.text_input(fld["label"], key=wkey, disabled=locked)

        def render_field_grid(fields):
            if not fields:
                return
            columns = st.columns(2)
            for idx, fld in enumerate(fields):
                target = st.container() if fld["type"] == "textarea" else columns[idx % 2]
                with target:
                    current_values[fld["key"]] = render_field(fld)

        current_values = {}
        if fid == "decl_handover":
            by_key = {fld["key"]: fld for fld in form_def["fields"]}
            leading = [fld for fld in form_def["fields"] if fld["key"] in {"incident_no", "party_name", "party_id", "party_phone"}]
            trailing = [fld for fld in form_def["fields"] if fld["key"] in {"vehicle_desc", "plate_no", "vehicle_state"}]
            render_field_grid(leading)
            role_field = by_key["receiver_role"]
            current_values["receiver_role"] = render_field(role_field)
            if _is_agent_role(current_values.get("receiver_role")):
                for pair in (("principal_name", "principal_id"), ("wakala_no", "wakala_date")):
                    pair_cols = st.columns(2)
                    for col, key in zip(pair_cols, pair):
                        with col:
                            current_values[key] = render_field(by_key[key])
            render_field_grid(trailing)
        else:
            render_field_grid([fld for fld in form_def["fields"] if not fld.get("visible_if")])

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

        live_legal_text = " ".join(form_def["legal_fn"](current_values).splitlines())
        st.markdown(
            f'<div class="legal-dark-box" dir="rtl" style="direction:rtl !important;text-align:justify !important;text-align-last:right !important;"><div class="legal-title" dir="rtl" style="direction:rtl !important;text-align:right !important;color:#d4a853;font-weight:800;margin-bottom:8px;">⚖️ معاينة النص الرسمي المعتمد في الوثيقة:</div><div class="legal-body" dir="rtl" style="direction:rtl !important;unicode-bidi:embed !important;text-align:justify !important;text-align-last:right !important;line-height:2.0;">\u200f{live_legal_text}</div></div>',
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
                recv_name_key = f"receiver_name_{st.session_state.doc_no}"
                recv_role_key = f"receiver_role_{st.session_state.doc_no}"
                if recv_name_key not in st.session_state:
                    st.session_state[recv_name_key] = st.session_state.receiver_name
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
                recv_name_key = f"receiver_name_{st.session_state.doc_no}"
                recv_role_key = f"receiver_role_{st.session_state.doc_no}"
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
                            st.session_state.receiver_name = (st.session_state.get(f"receiver_name_{st.session_state.doc_no}") or "").strip()
                            fallback_role = form_def.get("recipient_role_title") if is_letter_form else RECEIVER_ROLE_OPTIONS[0]
                            st.session_state.receiver_role = st.session_state.get(f"receiver_role_{st.session_state.doc_no}") or fallback_role
                        else:
                            st.session_state.receiver_name = ""
                            st.session_state.receiver_role = ""
                        if "بصمة منفذ الشحن" in chosen_auth:
                            seed = f"{st.session_state.doc_no}_{current_values.get('party_id', '')}_CITIZEN"
                            st.session_state.citizen_stamp_b64 = generate_fingerprint_png_b64(seed, ink_rgb=(13, 71, 161))
                            st.session_state.citizen_auth_mode = "بصمة منفذ الشحن (Type-C)"
                        elif "توقيع حي" in chosen_auth:
                            st.session_state.citizen_stamp_b64 = ""
                            st.session_state.citizen_auth_mode = "توقيع حي على الشاشة"
                        elif "ختم وتوقيع" in chosen_auth:
                            st.session_state.citizen_stamp_b64 = ""
                            st.session_state.citizen_auth_mode = "ختم وتوقيع جهة الاستلام الرسمية"
                        else:
                            st.session_state.citizen_stamp_b64 = ""
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
            st.markdown("#### 2️⃣ توثيق ضابط الخفر ومصادقة وحدة الحوادث")
            st.caption(f"الإعدادات الافتراضية: {unit_display}  •  {duty_display}")

            officer_name_key = f"officer_full_input_{st.session_state.doc_no}"
            if officer_name_key not in st.session_state:
                st.session_state[officer_name_key] = st.session_state.officer_full_override or unit_display

            st.text_input(
                "رتبة واسم ضابط الخفر المناوب",
                key=officer_name_key,
                disabled=st.session_state.officer_approved,
                placeholder="مثال: الملازم فهد بن ...",
            )

            officer_auth_opts = [
                "توقيع حي على الشاشة بالإصبع (لضابط الخفر)",
                "بصمة رقمية (منفذ الشحن Type-C) لضابط الخفر",
            ]
            officer_default_idx = 0
            if "بصمة" in (st.session_state.officer_auth_mode or ""):
                officer_default_idx = 1
            chosen_officer_auth = st.radio(
                "وسيلة توثيق ضابط الخفر:",
                officer_auth_opts,
                index=officer_default_idx,
                key=f"officer_auth_radio_{st.session_state.doc_no}",
                disabled=st.session_state.officer_approved or not st.session_state.citizen_locked,
            )

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
                key=f"duty_auth_radio_{st.session_state.doc_no}",
                disabled=st.session_state.officer_approved or not st.session_state.citizen_locked,
            )

            if not st.session_state.officer_approved:
                if st.button("🛡️ اعتماد الوثيقة وإصدار رمز التحقق QR", type="primary", use_container_width=True, disabled=not st.session_state.citizen_locked):
                    officer_label = (st.session_state.get(officer_name_key) or "").strip() or unit_display
                    st.session_state.officer_full_override = officer_label
                    st.session_state.officer_auth_mode = chosen_officer_auth
                    st.session_state.duty_auth_mode = chosen_duty_auth
                    if "بصمة" in chosen_officer_auth:
                        seed_off = f"{st.session_state.doc_no}_{officer_label}_OFFICER"
                        st.session_state.officer_stamp_b64 = generate_fingerprint_png_b64(seed_off, ink_rgb=(15, 61, 46))
                    else:
                        st.session_state.officer_stamp_b64 = ""
                    st.session_state.duty_stamp_b64 = ""
                    st.session_state.officer_approved = True
                    safe_rerun()
            else:
                st.success(
                    f"تم التوثيق: ضابط الخفر ({st.session_state.officer_auth_mode}) • "
                    f"وحدة الحوادث ({st.session_state.duty_auth_mode})"
                )
                if st.session_state.officer_stamp_b64:
                    st.image(base64.b64decode(st.session_state.officer_stamp_b64), caption="ختم التوثيق المعتمد", width=105)
            st.markdown("</div>", unsafe_allow_html=True)

        if st.session_state.officer_approved:
            party_name_final = current_values.get("party_name") or current_values.get("driver_name") or "غير محدد"
            party_id_final = current_values.get("party_id") or current_values.get("driver_id_nat") or "-"
            plate_final = current_values.get("plate_no") or current_values.get("vehicle_plate_type") or "-"
            raw_seal = f"{st.session_state.doc_no}|{party_id_final}|{st.session_state.doc_time}"
            verify_hash = "KHF-" + hashlib.sha256(raw_seal.encode("utf-8")).hexdigest()[:16].upper()
            officer_full_final = (st.session_state.officer_full_override or "").strip() or unit_display

            sync_attachments_to_session()
            ready_record = {
                "doc_no": st.session_state.doc_no,
                "form_id": fid,
                "form_title": form_def.get("official_title") or form_def["title"],
                "category": form_def["category"],
                "party_name": party_name_final,
                "party_id": party_id_final,
                "plate_no": plate_final,
                "gps_coords": shift["default_gps"],
                "created_at": st.session_state.doc_time,
                "fields": current_values,
                "legal_text": live_legal_text,
                "citizen_stamp_b64": st.session_state.citizen_stamp_b64,
                "citizen_auth_mode": st.session_state.citizen_auth_mode,
                "officer_stamp_b64": st.session_state.officer_stamp_b64,
                "attachment_b64": st.session_state.attachment_b64,
                "show_attachments_in_print": bool(st.session_state.get("show_attachments_in_print", True)),
                "officer_full": officer_full_final,
                "duty_full": duty_display,
                "dept_name": shift["dept_name"],
                "verify_hash": verify_hash,
                "officer_auth_mode": st.session_state.officer_auth_mode,
                "duty_auth_mode": st.session_state.duty_auth_mode,
                "duty_stamp_b64": st.session_state.duty_stamp_b64,
                "receiver_name": st.session_state.receiver_name if (is_med_form or is_letter_form) else "",
                "receiver_role": st.session_state.receiver_role if (is_med_form or is_letter_form) else "",
            }

            a4_html = build_official_a4_html(ready_record, form_def, logo_b64_global, interactive_sig=True)
            st.write("")
            act1, act2 = st.columns(2)
            with act1:
                if st.button("💾 حفظ الوثيقة نهائياً في الأرشيف المحلي", type="primary", use_container_width=True):
                    save_record_to_db(ready_record)
                    st.success(f"تم حفظ الوثيقة ({ready_record['doc_no']}) في الأرشيف المحلي بنجاح.")
            with act2:
                st.download_button(
                    "⬇️ تنزيل الوثيقة الرسمية للطباعة والمشاركة",
                    data=a4_html.encode("utf-8"),
                    file_name=f"{ready_record['doc_no']}.html",
                    mime="text/html",
                    use_container_width=True,
                )

            st.markdown("#### 📄 المعاينة الرسمية مقاس A4 (جاهزة للطباعة أو الحفظ كـ PDF)")
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
    records = search_records_db(search_q)

    if not records:
        st.info("لا توجد سجلات محفوظة حالياً في قاعدة البيانات المحلية.")
    else:
        for r in records:
            with st.expander(f"📌 {r['form_title']}  —  {r['party_name']}  |  اللوحة: {r['plate_no']}  |  ({r['doc_no']})"):
                c_info, c_dl, c_del = st.columns([3, 1, 1])
                with c_info:
                    st.write(f"**رقم الهوية:** `{r['party_id']}`  |  **الوقت:** `{r['created_at']}`  |  **التوثيق:** {r['citizen_auth_mode']}")
                    st.write(f"**ختم التحقق الرقمي:** `{r['verify_hash']}`")
                f_def = TRAFFIC_FORMS.get(r["form_id"])
                arch_html = build_official_a4_html(r, f_def, logo_b64_global, interactive_sig=False)
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
                        delete_record_db(r["id"])
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

    sett_tab, otg_tab = st.tabs(["👮 مناوبة الخفر", "🧬 بصمة الشحن OTG"])

    with sett_tab:
        with st.form("shift_update_form"):
            s_dept = st.text_input("القسم", value=shift["dept_name"], disabled=True)
            r1, r2 = st.columns([1, 2])
            with r1:
                s_orank = st.text_input("خانة التوثيق الأولى", value=shift["officer_rank"])
            with r2:
                s_oname = st.text_input("اسم ضابط الخفر (اختياري)", value=shift["officer_name"])

            r3, r4 = st.columns([1, 2])
            with r3:
                s_drank = st.text_input("خانة المصادقة الثانية", value=shift["duty_rank"])
            with r4:
                s_dname = st.text_input("اسم المناوب (اختياري)", value=shift["duty_name"])

            s_gps = st.text_input("إحداثيات الموقع (GPS)", value=shift["default_gps"])

            if st.form_submit_button("💾 حفظ الإعدادات", type="primary", use_container_width=True):
                update_shift_settings("قسم مرور العارضة", s_orank, s_oname, s_drank, s_dname, s_gps)
                st.success("تم حفظ الإعدادات بنجاح.")
                safe_rerun()

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