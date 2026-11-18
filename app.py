import streamlit as st
import streamlit.components.v1 as components
import sqlite3
import json
import base64
import io
import random
import hashlib
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

KSA_TZ = timezone(timedelta(hours=3))

st.set_page_config(
    page_title="ميدان الخفر | الإقرارات والمحاضر",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


# =====================================================================
# 1. الهوية البصرية الخضراء الداكنة والذهبية (Dark Emerald & Gold UI)
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
    --border-emerald: #1f5c46;
    --border-subtle: #263339;
    --text-light: #f1f5f9;
    --text-muted: #94a3b8;
}

html, body, [class*="css"] {
    font-family: 'Cairo', sans-serif !important;
    direction: rtl;
    text-align: right;
    color: var(--text-light);
}

/* إخفاء شريط Streamlit العلوي والقائمة الجانبية الافتراضية */
header[data-testid="stHeader"] { background: transparent !important; }
[data-testid="collapsedControl"] { display: none !important; }
section[data-testid="stSidebar"] { display: none !important; }
.block-container {
    padding-top: 1.2rem !important;
    padding-bottom: 3rem !important;
    max-width: 1120px !important;
}

.stApp {
    background-color: var(--bg-main) !important;
    color: var(--text-light) !important;
}

/* الترويسة الخضراء العلوية */
.khafar-top-header {
    background: linear-gradient(135deg, #0d4432 0%, #08291e 100%);
    border: 1px solid #1e6b50;
    border-radius: 18px 18px 0 0;
    padding: 18px 22px 14px 22px;
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.35);
}
.header-brand-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
}
.shield-badge {
    width: 46px;
    height: 46px;
    border-radius: 12px;
    background: rgba(212, 168, 83, 0.12);
    border: 1.5px solid var(--gold-main);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 22px;
}
.indep-pill {
    background: rgba(212, 168, 83, 0.16);
    border: 1px solid rgba(212, 168, 83, 0.55);
    color: var(--gold-soft);
    font-size: 12px;
    font-weight: 700;
    padding: 2px 12px;
    border-radius: 20px;
    margin-right: 8px;
}
.status-pills-row {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 14px;
}
.pill-offline {
    background: rgba(6, 34, 24, 0.85);
    border: 1px solid #1d6f52;
    color: #a7f3d0;
    padding: 5px 14px;
    border-radius: 20px;
    font-size: 12.5px;
    font-weight: 700;
}
.pill-usb {
    background: rgba(36, 33, 22, 0.85);
    border: 1px solid rgba(212, 168, 83, 0.5);
    color: var(--gold-soft);
    padding: 5px 14px;
    border-radius: 20px;
    font-size: 12.5px;
    font-weight: 700;
}

/* شريط الإحداثيات والوقت الآلي */
.gps-time-bar {
    background: #0b1015;
    border-left: 1px solid #1e293b;
    border-right: 1px solid #1e293b;
    border-bottom: 2px solid #9a7432;
    border-radius: 0 0 14px 14px;
    padding: 9px 18px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 18px;
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

/* بطاقة المنصة والمناوبة الرئيسية */
.hero-shift-card {
    background: linear-gradient(135deg, #0f3d2c 0%, #112421 65%, #151d21 100%);
    border: 1px solid #21634b;
    border-radius: 16px;
    padding: 22px 24px;
    margin-bottom: 18px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
}
.hero-eyebrow {
    color: var(--gold-main);
    font-size: 13px;
    font-weight: 700;
    margin-bottom: 4px;
}
.hero-title {
    color: #ffffff;
    font-size: 23px;
    font-weight: 900;
    margin: 0 0 8px 0;
}
.hero-desc {
    color: #cbd5e1;
    font-size: 13.5px;
    line-height: 1.75;
    margin-bottom: 16px;
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

/* عناوين الأقسام (الإقرارات والمحاضر) */
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

/* بطاقات النماذج */
.form-item-card {
    background: linear-gradient(180deg, #162024 0%, #12191c 100%);
    border: 1px solid #24353b;
    border-radius: 14px;
    padding: 16px 18px 10px 18px;
    margin-bottom: 6px;
    transition: all 0.2s ease;
}
.form-item-card:hover {
    border-color: #2b8a68;
}

/* معاينة النص النظامي والقفل */
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

/* تخصيص الحقول والقوائم المنسدلة والأزرار باللون الأخضر والذهبي */
div[data-baseweb="input"] > div,
div[data-baseweb="textarea"] > div,
div[data-baseweb="select"] > div {
    background-color: #152024 !important;
    border: 1px solid #2b4246 !important;
    border-radius: 10px !important;
    color: #f8fafc !important;
}
div[data-baseweb="input"] input,
div[data-baseweb="textarea"] textarea {
    color: #f8fafc !important;
    -webkit-text-fill-color: #f8fafc !important;
    font-family: 'Cairo', sans-serif !important;
}
label[data-testid="stWidgetLabel"] p {
    color: #cbd5e1 !important;
    font-weight: 700 !important;
    font-size: 13.5px !important;
}

/* الأزرار: إلغاء اللون الأحمر نهائياً واستبداله بالأخضر الملكي والذهبي */
div.stButton > button {
    background: #172628 !important;
    color: #e2e8f0 !important;
    border: 1px solid #2c4a47 !important;
    border-radius: 10px !important;
    font-weight: 700 !important;
    padding: 0.5rem 1rem !important;
    transition: 0.2s all !important;
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

/* تنسيق أزرار الراديو الأفقية كألسنة تنقل خضراء */
div[role="radiogroup"] {
    background: #131a1e;
    padding: 6px;
    border-radius: 12px;
    border: 1px solid #25353b;
    gap: 8px;
}
</style>
""", unsafe_allow_html=True)


# =====================================================================
# 2. تعريف النماذج الثمانية والصيغ النظامية المحكمة
# =====================================================================
def _val(values: dict, key: str) -> str:
    v = str(values.get(key, "")).strip()
    return v if v else "...................."


TRAFFIC_FORMS = {
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
            f"بصفتي ({_val(m, 'receiver_role')})، بأنني استلمت المركبة ({_val(m, 'vehicle_desc')}) التي تحمل اللوحة رقم ({_val(m, 'plate_no')}) "
            f"في موقع الحادث رقم ({_val(m, 'incident_no')}) مباشرةً بحالتها الراهنة ({_val(m, 'vehicle_state')}) وبكامل مقتنياتها الشخصية دون نقص، "
            f"وبموجبه أخلي مسؤولية الفرقة الميدانية المباشرة وقسم المرور من سحب المركبة أو حجزها، وأتعهد بعدم قيادتها في حال وجود أي خلل يؤثر على السلامة العامة."
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
            {"key": "impound_loc", "label": "ساحة الحجز المودعة بها المركبة", "type": "text", "sample": "ساحة حجز المرور الرئيسية بالمحافظة"},
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
            {"key": "officer_note", "label": "إفادة رجل المرور راصد المخالفة التفصيلية", "type": "textarea", "sample": "أثناء مباشرة تنظيم الحركة المرورية جرى إدخال حرف (ج) بدلاً من (ح) بالخطأ للوحة المركبة المخالفة الفعلية، والمركبة المسجل عليها الإشعار لم تكن بالموقع."},
        ],
        "legal_fn": lambda m: (
            f"نرفع هذا المحضر الرسمي بشأن المخالفة المرورية رقم ({_val(m, 'incident_no')}) المقيدة بتاريخ ({_val(m, 'viol_datetime')}) على اللوحة ({_val(m, 'plate_no')})، "
            f"حيث تبين بعد المراجعة والتدقيق وقوع خطأ في الرصد ناتج عن ({_val(m, 'error_reason')})، والبيانات المرجعية هي ({_val(m, 'party_name')} - {_val(m, 'party_id')}). "
            f"وإيضاح الراصد الميداني كالآتي: ({_val(m, 'officer_note')}). وعليه حُرر هذا المحضر مرفقاً به صورة المخالفة ومعتمداً ببصمة الفرد المعد ومصادقة ضابط الخفر للعرض على الهيئة المرورية لإلغاء المخالفة نظاماً."
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
}


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
# 4. قاعدة البيانات المحلية SQLite مع تهيئة سجلات تجريبية
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
            VALUES (1, 'شعبة المرور - وحدة الحوادث والخفر • دورية خفر (ميدان - 14)', 'رقيب أول', 'فهد بن عبدالله القحطاني', 'رئيس رقباء', 'سالم بن محمد الدوسري', '17.0924° N, 43.0956° E')
        """)

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
            verify_hash TEXT
        )
    """)

    # إضافة 3 نماذج تجريبية جاهزة عند التشغيل الأول فقط لمعاينة الأرشيف مباشرة
    if c.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0:
        now_str = datetime.now(KSA_TZ).strftime("%Y/%m/%d - %H:%M")
        for idx, fid in enumerate(["decl_handover", "decl_fault", "min_inspection"], start=1):
            fdef = TRAFFIC_FORMS[fid]
            sample_map = {f["key"]: f["sample"] for f in fdef["fields"]}
            d_no = f"KH-261118-00{idx}"
            c_b64 = generate_fingerprint_png_b64(f"SEED_C_{idx}")
            o_b64 = generate_fingerprint_png_b64(f"SEED_O_{idx}", ink_rgb=(15, 61, 46))
            v_hash = "KHF-" + hashlib.sha256(d_no.encode()).hexdigest()[:14].upper()
            c.execute("""
                INSERT INTO records (
                    doc_no, form_id, form_title, category, party_name, party_id, plate_no,
                    gps_coords, created_at, fields_json, legal_text, citizen_stamp_b64,
                    citizen_auth_mode, officer_stamp_b64, attachment_b64, officer_full,
                    duty_full, dept_name, verify_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                d_no, fid, fdef["title"], fdef["category"],
                sample_map.get("party_name", "-"), sample_map.get("party_id", "-"),
                sample_map.get("plate_no", "-"), "17.0924° N, 43.0956° E", now_str,
                json.dumps(sample_map, ensure_ascii=False), fdef["legal_fn"](sample_map),
                c_b64, "بصمة منفذ الشحن (Type-C)", o_b64, "",
                "رقيب أول / فهد بن عبدالله القحطاني", "رئيس رقباء / سالم بن محمد الدوسري",
                "شعبة المرور - وحدة الحوادث والخفر", v_hash
            ))

    conn.commit()
    conn.close()


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
            duty_full, dept_name, verify_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        rec["doc_no"], rec["form_id"], rec["form_title"], rec["category"],
        rec["party_name"], rec["party_id"], rec["plate_no"], rec["gps_coords"],
        rec["created_at"], json.dumps(rec["fields"], ensure_ascii=False),
        rec["legal_text"], rec["citizen_stamp_b64"], rec["citizen_auth_mode"],
        rec["officer_stamp_b64"], rec["attachment_b64"], rec["officer_full"],
        rec["duty_full"], rec["dept_name"], rec["verify_hash"]
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
# 5. قالب الطباعة الرسمي مقاس A4 (ورقة بيضاء رسمية بهوية المرور الخضراء)
# =====================================================================
def build_official_a4_html(rec: dict, form_def: dict | None, interactive_sig: bool = False) -> str:
    fields_map = rec["fields"] if isinstance(rec.get("fields"), dict) else json.loads(rec["fields_json"])
    rows_html = ""
    if form_def:
        for f in form_def["fields"]:
            val = fields_map.get(f["key"], "-") or "-"
            rows_html += f"<tr><td class='lbl'>{f['label']}</td><td class='val'>{val}</td></tr>"
    else:
        for k, v in fields_map.items():
            rows_html += f"<tr><td class='lbl'>{k}</td><td class='val'>{v}</td></tr>"

    qr_payload = f"DOC:{rec['doc_no']}|ID:{rec['party_id']}|PLATE:{rec['plate_no']}|SEAL:{rec['verify_hash']}"
    qr_b64 = generate_qr_png_b64(qr_payload)

    if rec.get("citizen_stamp_b64"):
        citizen_box_inner = f"<img src='data:image/png;base64,{rec['citizen_stamp_b64']}' style='height:68px; object-fit:contain;' />"
    elif interactive_sig and "توقيع حي" in rec.get("citizen_auth_mode", ""):
        citizen_box_inner = """
        <div>
            <canvas id="liveSigCanvas" width="180" height="68" style="border:1px dashed #0d47a1; border-radius:6px; background:#f8fafc; touch-action:none; cursor:crosshair;"></canvas>
            <div class="no-print" style="margin-top:2px;">
                <button onclick="clearSig()" style="font-size:10px; padding:1px 6px; cursor:pointer;">مسح التوقيع</button>
            </div>
        </div>
        """
    else:
        citizen_box_inner = "<div style='padding:18px 0; font-weight:700; color:#7f1d1d; font-size:11px;'>غياب الطرف / امتناع مثبت بالمحضر</div>"

    officer_img = (
        f"<img src='data:image/png;base64,{rec['officer_stamp_b64']}' style='height:68px; object-fit:contain;' />"
        if rec.get("officer_stamp_b64") else ""
    )

    attachment_block = ""
    if rec.get("attachment_b64"):
        attachment_block = f"""
        <div style="margin-top:8px; border:1px dashed #64748b; border-radius:6px; padding:6px 10px; display:flex; align-items:center; justify-content:space-between;">
            <span style="font-size:10.5px; font-weight:700; color:#0f3d2e;">📎 مرفق موثق بالمعاملة:</span>
            <img src="data:image/png;base64,{rec['attachment_b64']}" style="height:48px; border-radius:4px; border:1px solid #cbd5e1;" />
        </div>
        """

    return f"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<title>{rec['doc_no']} - {rec['form_title']}</title>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
    * {{ box-sizing: border-box; font-family: 'Cairo', sans-serif; }}
    body {{ margin: 0; padding: 14px; background: #0d1316; direction: rtl; }}
    .toolbar {{
        max-width: 210mm; margin: 0 auto 12px auto; display: flex; gap: 10px;
        justify-content: center; background: #0f3d2e; border: 1px solid #d4a853; padding: 10px; border-radius: 10px;
    }}
    .print-btn {{
        background: linear-gradient(135deg, #d4a853 0%, #a37a2c 100%); color: #fff; border: none; padding: 8px 24px;
        font-size: 14px; font-weight: 800; border-radius: 8px; cursor: pointer;
    }}
    .a4-sheet {{
        width: 210mm; min-height: 285mm; max-height: 292mm; margin: 0 auto;
        background: #ffffff; color: #0f172a; padding: 11mm 13mm; border: 2px solid #0f3d2e;
        display: flex; flex-direction: column; justify-content: space-between;
        box-shadow: 0 12px 32px rgba(0,0,0,0.45);
    }}
    .hdr {{ display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #0f3d2e; padding-bottom: 8px; }}
    .hdr-right p, .hdr-left p {{ margin: 1px 0; font-size: 11.5px; font-weight: 700; color: #0f172a; }}
    .hdr-center {{
        background: #f1f5f3; border: 1.5px solid #0f3d2e; border-radius: 8px;
        padding: 6px 16px; text-align: center;
    }}
    .doc-banner {{
        background: #0f3d2e; color: #ffffff; text-align: center;
        padding: 6px; border-radius: 6px; font-size: 15px; font-weight: 800; margin: 10px 0;
    }}
    table.data-tbl {{ width: 100%; border-collapse: collapse; margin-bottom: 10px; }}
    table.data-tbl td {{ border: 1px solid #cbd5e1; padding: 5px 9px; font-size: 11.5px; }}
    table.data-tbl td.lbl {{ width: 32%; background: #f4f7f6; font-weight: 700; color: #0f3d2e; }}
    table.data-tbl td.val {{ width: 68%; color: #0f172a; font-weight: 600; }}
    .legal-box {{
        background: #f8fafc; border: 1px solid #0f3d2e; border-right: 5px solid #0f3d2e;
        border-radius: 6px; padding: 10px 12px; font-size: 12px; line-height: 1.8; text-align: justify; color: #0f172a;
    }}
    table.sig-tbl {{ width: 100%; border-collapse: collapse; margin-top: 10px; text-align: center; }}
    table.sig-tbl th {{ background: #f1f5f3; border: 1px solid #94a3b8; padding: 5px; font-size: 11px; color: #0f3d2e; }}
    table.sig-tbl td {{ border: 1px solid #94a3b8; padding: 6px; width: 33.3%; vertical-align: middle; height: 108px; color: #0f172a; }}
    .footer-qr {{
        margin-top: 8px; background: #f4f7f6; border: 1px solid #cbd5e1; border-radius: 6px;
        padding: 6px 10px; display: flex; justify-content: space-between; align-items: center;
    }}
    @media print {{
        @page {{ size: A4 portrait; margin: 6mm; }}
        body {{ background: #fff; padding: 0; }}
        .toolbar, .no-print {{ display: none !important; }}
        .a4-sheet {{ width: 100%; min-height: 278mm; box-shadow: none; margin: 0; }}
    }}
</style>
</head>
<body>
    <div class="toolbar no-print">
        <button class="print-btn" onclick="window.print()">🖨️ طباعة الوثيقة الرسمية / حفظ كملف A4 PDF</button>
    </div>

    <div class="a4-sheet">
        <div>
            <div class="hdr">
                <div class="hdr-right">
                    <p>المملكة العربية السعودية</p>
                    <p>وزارة الداخلية - الأمن العام</p>
                    <p>الإدارة العامة للمرور</p>
                    <p style="color:#0f3d2e;">{rec['dept_name']}</p>
                </div>
                <div class="hdr-center">
                    <div style="font-size:13px; font-weight:800; color:#0f3d2e;">ميدان الخفر - الإصدار الميداني</div>
                    <div style="font-size:10.5px; color:#475569;">وثيقة {rec['category']} رسمية مقفلة إلكترونياً</div>
                </div>
                <div class="hdr-left">
                    <p>الرقم المرجعي: {rec['doc_no']}</p>
                    <p>التاريخ والوقت: {rec['created_at']}</p>
                    <p style="font-size:10.5px;">إحداثيات GPS: {rec['gps_coords']}</p>
                </div>
            </div>

            <div class="doc-banner">{rec['form_title']}</div>
            <table class="data-tbl">{rows_html}</table>

            <div class="legal-box">
                <div style="font-weight:800; color:#0f3d2e; margin-bottom:4px;">الصيغة النظامية المعتمدة ({rec['category']}):</div>
                {rec['legal_text']}
            </div>
            {attachment_block}
        </div>

        <div>
            <table class="sig-tbl">
                <thead>
                    <tr>
                        <th>بصمة / توقيع الطرف المعني</th>
                        <th>بصمة وتوثيق الفرد المعد</th>
                        <th>مصادقة ضابط الخفر المستلم</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>
                            <div style="font-size:10.5px; font-weight:700; margin-bottom:3px;">{rec['party_name']}</div>
                            {citizen_box_inner}
                            <div style="font-size:9.5px; color:#475569; margin-top:2px;">{rec['citizen_auth_mode']}</div>
                        </td>
                        <td>
                            <div style="font-size:10.5px; font-weight:700; margin-bottom:3px;">{rec['officer_full']}</div>
                            {officer_img}
                            <div style="font-size:9.5px; color:#475569; margin-top:2px;">بصمة الفرد المباشر المعتمدة</div>
                        </td>
                        <td>
                            <div style="font-size:11px; font-weight:800; margin-bottom:10px;">{rec['duty_full']}</div>
                            <div style="display:inline-block; border:1.5px solid #0f3d2e; color:#0f3d2e; padding:4px 12px; border-radius:5px; font-size:11px; font-weight:800;">
                                مُصادق ومُعتمد نظاماً
                            </div>
                            <div style="font-size:9.5px; color:#475569; margin-top:10px;">إشراف مناوبة الخفر</div>
                        </td>
                    </tr>
                </tbody>
            </table>

            <div class="footer-qr">
                <div>
                    <div style="font-size:10px; font-weight:800; color:#0f3d2e;">
                        وثيقة ميدانية محررة ومقفلة إلكترونياً فور توثيق الطرف المعني - يُلغى العمل بها عند أي كشط أو تعديل يدوي.
                    </div>
                    <div style="font-size:9.5px; color:#475569;">ختم التحقق الرقمي (SHA-256 Seal): {rec['verify_hash']}</div>
                </div>
                <img src="data:image/png;base64,{qr_b64}" style="width:54px; height:54px;" />
            </div>
        </div>
    </div>

<script>
    const canvas = document.getElementById('liveSigCanvas');
    if (canvas) {{
        const ctx = canvas.getContext('2d');
        ctx.strokeStyle = '#0d47a1';
        ctx.lineWidth = 2.2;
        ctx.lineCap = 'round';
        let drawing = false;
        const pos = (e) => {{
            const r = canvas.getBoundingClientRect();
            const clientX = e.touches ? e.touches[0].clientX : e.clientX;
            const clientY = e.touches ? e.touches[0].clientY : e.clientY;
            return {{ x: clientX - r.left, y: clientY - r.top }};
        }};
        canvas.addEventListener('pointerdown', (e) => {{ drawing = true; const p = pos(e); ctx.beginPath(); ctx.moveTo(p.x, p.y); }});
        canvas.addEventListener('pointermove', (e) => {{ if (!drawing) return; const p = pos(e); ctx.lineTo(p.x, p.y); ctx.stroke(); }});
        window.addEventListener('pointerup', () => {{ drawing = false; }});
    }}
    function clearSig() {{
        if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
    }}
</script>
</body>
</html>
"""


# =====================================================================
# 6. إدارة حالة الجلسة والتنقل بين الشاشات الأربعة
# =====================================================================
init_db()
shift = get_shift_settings()
now_ksa = datetime.now(KSA_TZ)

if "nav_tab" not in st.session_state:
    st.session_state.nav_tab = "النماذج الميدانية"
if "opened_form_id" not in st.session_state:
    st.session_state.opened_form_id = None
if "catalog_filter" not in st.session_state:
    st.session_state.catalog_filter = "جميع النماذج (8)"
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
if "attachment_b64" not in st.session_state:
    st.session_state.attachment_b64 = ""
if "scanner_model" not in st.session_state:
    st.session_state.scanner_model = "وضع المحاكاة متصل (معزول العتاد)"


def reset_doc_state():
    t_now = datetime.now(KSA_TZ)
    st.session_state.doc_no = f"KH-{t_now.strftime('%y%m%d-%H%M%S')}"
    st.session_state.doc_time = t_now.strftime("%Y/%m/%d - %H:%M")
    st.session_state.citizen_locked = False
    st.session_state.citizen_stamp_b64 = ""
    st.session_state.citizen_auth_mode = ""
    st.session_state.officer_approved = False
    st.session_state.officer_stamp_b64 = ""
    st.session_state.attachment_b64 = ""


all_archived = search_records_db("")
archive_count = len(all_archived)

# =====================================================================
# 7. الترويسة الخضراء الملكية وشريط الإحداثيات المثبت
# =====================================================================
st.markdown(f"""
<div class="khafar-top-header">
    <div class="header-brand-row">
        <div style="display:flex; align-items:center; gap:14px;">
            <div class="shield-badge">🛡️</div>
            <div>
                <div style="display:flex; align-items:center; flex-wrap:wrap; gap:6px;">
                    <span style="font-size:22px; font-weight:900; color:#ffffff;">ميدان الخفر</span>
                    <span class="indep-pill">إصدار ميداني مستقل</span>
                </div>
                <div style="font-size:13px; color:#a7f3d0; opacity:0.9;">
                    نظام الإقرارات والمحاضر الذكي • الإدارة العامة للمرور
                </div>
            </div>
        </div>
        <div class="status-pills-row" style="margin-top:0;">
            <span class="pill-offline">🟢 وضع العمل المحلي دون شبكة - جاهز</span>
            <span class="pill-usb">🧬 قارئ البصمة Type-C: {st.session_state.scanner_model}</span>
        </div>
    </div>
</div>

<div class="gps-time-bar">
    <div>
        <span style="color:#d4a853; font-weight:800; font-size:13px;">🔒 إحداثيات الموقع المثبتة (GPS): </span>
        <span class="gps-mono-box">{shift['default_gps']}</span>
    </div>
    <div>
        <span style="color:#94a3b8; font-size:12.5px;">التاريخ والوقت: </span>
        <span class="time-auto-box">{now_ksa.strftime('%Y/%m/%d  |  %I:%M %p')} (مثبت آلياً)</span>
    </div>
</div>
""", unsafe_allow_html=True)

# شريط التنقل الرئيسي بالأقسام الأربعة
nav_cols = st.columns(4)
nav_items = [
    ("النماذج الميدانية", "📋 النماذج الميدانية"),
    ("الأرشيف المحلي", f"🗂️ الأرشيف المحلي ({archive_count})"),
    ("مناوبة الخفر", "👮 مناوبة الخفر"),
    ("بصمة الشحن OTG", "🧬 بصمة الشحن OTG"),
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

st.write("")

# =====================================================================
# القسم الأول: النماذج الميدانية (عرض البطاقات + شاشة تحرير النموذج)
# =====================================================================
if st.session_state.nav_tab == "النماذج الميدانية":

    # أ) عرض الكتالوج الرئيسي عند عدم فتح نموذج فرعي
    if st.session_state.opened_form_id is None:
        st.markdown(f"""
        <div class="hero-shift-card">
            <div class="hero-eyebrow">{shift['dept_name']}</div>
            <h2 class="hero-title">منصة تحرير وتوثيق الإقرارات والمحاضر الميدانية</h2>
            <div class="hero-desc">
                اختر النموذج المطلوب لتعبئة الحقول يدوياً أو بالتعبئة الذكية السريعة، ثم توثيق بصمة الطرف المعني عبر منفذ الشحن (USB Type-C) لقفل الحقول نهائياً وتصدير ملف PDF رسمي مقاس A4.
            </div>
            <div class="shift-summary-inner">
                <div>
                    <div style="font-size:12.5px; color:#94a3b8;">الفرد المُعد: <strong style="color:#ffffff;">{shift['officer_rank']} / {shift['officer_name']}</strong></div>
                    <div style="font-size:12.5px; color:#94a3b8; margin-top:3px;">ضابط الخفر: <strong style="color:#d4a853;">{shift['duty_rank']} / {shift['duty_name']}</strong></div>
                </div>
                <div style="font-size:12px; color:#34d399; font-weight:700;">
                    جميع النماذج مدعومة بقفل الحقول التراتبي وطباعة A4 الرسمية ✓
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        f_col1, f_col2, f_col3 = st.columns(3)
        for col_obj, flt_label in zip([f_col1, f_col2, f_col3], ["جميع النماذج (8)", "قائمة الإقرارات (4)", "قائمة المحاضر (4)"]):
            with col_obj:
                if st.button(
                    flt_label,
                    key=f"flt_{flt_label}",
                    type="primary" if st.session_state.catalog_filter == flt_label else "secondary",
                    use_container_width=True,
                ):
                    st.session_state.catalog_filter = flt_label
                    safe_rerun()

        # عرض أولاً: قائمة الإقرارات الميدانية
        if st.session_state.catalog_filter in ["جميع النماذج (8)", "قائمة الإقرارات (4)"]:
            st.markdown("""
            <div class="sec-heading-green">
                <span style="font-size:19px; font-weight:800; color:#ffffff;">أولاً: قائمة الإقرارات الميدانية</span>
                <span class="badge-green">4 نماذج معتمدة</span>
            </div>
            """, unsafe_allow_html=True)

            decl_keys = [k for k, v in TRAFFIC_FORMS.items() if v["category"] == "إقرار"]
            d_cols = st.columns(2)
            for i, fid in enumerate(decl_keys):
                f_item = TRAFFIC_FORMS[fid]
                with d_cols[i % 2]:
                    st.markdown(f"""
                    <div class="form-item-card">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                            <span style="font-size:16.5px; font-weight:800; color:#ffffff;">{f_item['icon']} {f_item['title']}</span>
                            <span class="badge-green">إقرار ميداني</span>
                        </div>
                        <div style="font-size:12.5px; color:#94a3b8; line-height:1.6; margin-bottom:8px;">{f_item['subtitle']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button(f"فتح وتحرير {f_item['title']} ←", key=f"open_{fid}", type="primary", use_container_width=True):
                        st.session_state.opened_form_id = fid
                        reset_doc_state()
                        safe_rerun()

        # عرض ثانياً: قائمة المحاضر الرسمية
        if st.session_state.catalog_filter in ["جميع النماذج (8)", "قائمة المحاضر (4)"]:
            st.markdown("""
            <div class="sec-heading-gold">
                <span style="font-size:19px; font-weight:800; color:#ffffff;">ثانياً: قائمة المحاضر الرسمية</span>
                <span class="badge-gold">4 محاضر نظامية</span>
            </div>
            """, unsafe_allow_html=True)

            min_keys = [k for k, v in TRAFFIC_FORMS.items() if v["category"] == "محضر"]
            m_cols = st.columns(2)
            for i, fid in enumerate(min_keys):
                f_item = TRAFFIC_FORMS[fid]
                with m_cols[i % 2]:
                    st.markdown(f"""
                    <div class="form-item-card">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                            <span style="font-size:16.5px; font-weight:800; color:#ffffff;">{f_item['icon']} {f_item['title']}</span>
                            <span class="badge-gold">محضر رسمي</span>
                        </div>
                        <div style="font-size:12.5px; color:#94a3b8; line-height:1.6; margin-bottom:8px;">{f_item['subtitle']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button(f"فتح وتحرير {f_item['title']} ←", key=f"open_{fid}", use_container_width=True):
                        st.session_state.opened_form_id = fid
                        reset_doc_state()
                        safe_rerun()

    # ب) شاشة تحرير وتبصيم النموذج المختار
    else:
        fid = st.session_state.opened_form_id
        form_def = TRAFFIC_FORMS[fid]

        top_bar1, top_bar2, top_bar3 = st.columns([1.3, 1.3, 1.4])
        with top_bar1:
            if st.button("↩️ العودة لقائمة النماذج الثمانية", use_container_width=True):
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
                    <span class="badge-{'green' if form_def['category']=='إقرار' else 'gold'}">{form_def['category']} معتمد</span>
                    <h3 style="margin:6px 0 2px 0; color:#ffffff; font-size:20px;">{form_def['icon']} {form_def['title']}</h3>
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
                    🔒 تم قفل جميع الحقول النصية نهائياً بعد توثيق الطرف المعني لمنع أي تعديل لاحق على الوثيقة.
                </div>
                """, unsafe_allow_html=True)
            with lk2:
                if st.button("🔓 فك القفل (يمسح البصمة)", use_container_width=True):
                    st.session_state.citizen_locked = False
                    st.session_state.citizen_stamp_b64 = ""
                    st.session_state.officer_approved = False
                    st.session_state.officer_stamp_b64 = ""
                    safe_rerun()

        current_values = {}
        f_cols = st.columns(2)
        for idx, fld in enumerate(form_def["fields"]):
            wkey = f"inp_{fid}_{fld['key']}"
            target_col = f_cols[idx % 2] if fld["type"] != "textarea" else st.container()
            with target_col:
                if fld["type"] == "select":
                    opts = fld["options"]
                    default_idx = opts.index(st.session_state[wkey]) if (wkey in st.session_state and st.session_state[wkey] in opts) else 0
                    val = st.selectbox(fld["label"], options=opts, index=default_idx, key=wkey, disabled=st.session_state.citizen_locked)
                elif fld["type"] == "textarea":
                    val = st.text_area(fld["label"], key=wkey, height=88, disabled=st.session_state.citizen_locked)
                else:
                    val = st.text_input(fld["label"], key=wkey, disabled=st.session_state.citizen_locked)
                current_values[fld["key"]] = val

        att_label = (
            "📸 إرفاق صورة إشعار المخالفة (مطلوب لحوكمة الإلغاء بالهيئة المرورية)"
            if form_def["require_image"]
            else "📎 إرفاق صورة الهوية / الاستمارة أو صورة ميدانية داعمة (اختياري)"
        )
        uploaded_img = st.file_uploader(att_label, type=["png", "jpg", "jpeg"], disabled=st.session_state.citizen_locked, key=f"att_{st.session_state.doc_no}")
        if uploaded_img is not None and not st.session_state.citizen_locked:
            img_pil = Image.open(uploaded_img)
            img_pil.thumbnail((420, 420))
            b_io = io.BytesIO()
            img_pil.save(b_io, format="PNG")
            st.session_state.attachment_b64 = base64.b64encode(b_io.getvalue()).decode("utf-8")

        live_legal_text = form_def["legal_fn"](current_values)
        st.markdown(f"""
        <div class="legal-dark-box">
            <div style="color:#d4a853; font-weight:800; margin-bottom:6px;">⚖️ معاينة الصيغة النظامية المعتمدة في ملف الـ PDF:</div>
            {live_legal_text}
        </div>
        """, unsafe_allow_html=True)

        # خطوتا التبصيم والاعتماد التراتبي
        s1_col, s2_col = st.columns(2)
        with s1_col:
            st.markdown("<div class='auth-panel'>", unsafe_allow_html=True)
            st.markdown("#### 1️⃣ بصمة / توقيع الطرف المعني (يقفل التعديل)")
            auth_opts = ["بصمة منفذ الشحن (USB Type-C)", "توقيع حي بالإصبع على الشاشة (بديل الطوارئ)"]
            if form_def["allow_absence"]:
                auth_opts.append("غياب الطرف / امتناع مثبت بالمحضر")

            chosen_auth = st.radio("وسيلة التوثيق الميداني:", auth_opts, disabled=st.session_state.citizen_locked)

            if not st.session_state.citizen_locked:
                if st.button("🧬 التقاط البصمة وقفل الحقول النصية", type="primary", use_container_width=True):
                    if "بصمة منفذ الشحن" in chosen_auth:
                        seed = f"{st.session_state.doc_no}_{current_values.get('party_id', '')}_CITIZEN"
                        st.session_state.citizen_stamp_b64 = generate_fingerprint_png_b64(seed, ink_rgb=(13, 71, 161))
                        st.session_state.citizen_auth_mode = "بصمة منفذ الشحن (Type-C)"
                    elif "توقيع حي" in chosen_auth:
                        st.session_state.citizen_stamp_b64 = ""
                        st.session_state.citizen_auth_mode = "توقيع حي على الشاشة"
                    else:
                        st.session_state.citizen_stamp_b64 = ""
                        st.session_state.citizen_auth_mode = "غياب الطرف / امتناع مثبت بالمحضر"
                    st.session_state.citizen_locked = True
                    safe_rerun()
            else:
                st.success(f"تم التوثيق بنجاح: {st.session_state.citizen_auth_mode}")
                if st.session_state.citizen_stamp_b64:
                    st.image(base64.b64decode(st.session_state.citizen_stamp_b64), caption="ختم البصمة الصوري (تم مسح الأثر الحيوي)", width=105)
            st.markdown("</div>", unsafe_allow_html=True)

        with s2_col:
            st.markdown("<div class='auth-panel'>", unsafe_allow_html=True)
            st.markdown("#### 2️⃣ بصمة الفرد المعد ومصادقة ضابط الخفر")
            st.caption(f"الفرد المعد: {shift['officer_rank']} / {shift['officer_name']}  •  ضابط الخفر: {shift['duty_rank']} / {shift['duty_name']}")

            if not st.session_state.officer_approved:
                if st.button("🛡️ تبصيم الفرد المعد وإصدار رمز التحقق QR", type="primary", use_container_width=True, disabled=not st.session_state.citizen_locked):
                    seed_off = f"{st.session_state.doc_no}_{shift['officer_name']}_OFFICER"
                    st.session_state.officer_stamp_b64 = generate_fingerprint_png_b64(seed_off, ink_rgb=(15, 61, 46))
                    st.session_state.officer_approved = True
                    safe_rerun()
            else:
                st.success("تم اعتماد بصمة الفرد المعد ومصادقة ضابط الخفر.")
                st.image(base64.b64decode(st.session_state.officer_stamp_b64), caption="بصمة الفرد المعد المعتمدة", width=105)
            st.markdown("</div>", unsafe_allow_html=True)

        if st.session_state.officer_approved:
            raw_seal = f"{st.session_state.doc_no}|{current_values.get('party_id', '')}|{st.session_state.doc_time}"
            verify_hash = "KHF-" + hashlib.sha256(raw_seal.encode("utf-8")).hexdigest()[:16].upper()

            ready_record = {
                "doc_no": st.session_state.doc_no,
                "form_id": fid,
                "form_title": form_def["title"],
                "category": form_def["category"],
                "party_name": current_values.get("party_name") or "غير محدد",
                "party_id": current_values.get("party_id") or "-",
                "plate_no": current_values.get("plate_no") or "-",
                "gps_coords": shift["default_gps"],
                "created_at": st.session_state.doc_time,
                "fields": current_values,
                "legal_text": live_legal_text,
                "citizen_stamp_b64": st.session_state.citizen_stamp_b64,
                "citizen_auth_mode": st.session_state.citizen_auth_mode,
                "officer_stamp_b64": st.session_state.officer_stamp_b64,
                "attachment_b64": st.session_state.attachment_b64,
                "officer_full": f"{shift['officer_rank']} / {shift['officer_name']}",
                "duty_full": f"{shift['duty_rank']} / {shift['duty_name']}",
                "dept_name": shift["dept_name"],
                "verify_hash": verify_hash,
            }

            a4_html = build_official_a4_html(ready_record, form_def, interactive_sig=True)
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
            components.html(a4_html, height=1160, scrolling=True)


# =====================================================================
# القسم الثاني: الأرشيف المحلي واسترجاع الوثائق
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
        st.info("لا توجد سجلات مطابقة في قاعدة البيانات المحلية.")
    else:
        for r in records:
            with st.expander(f"📌 {r['form_title']}  —  {r['party_name']}  |  اللوحة: {r['plate_no']}  |  ({r['doc_no']})"):
                c_info, c_dl, c_del = st.columns([3, 1, 1])
                with c_info:
                    st.write(f"**رقم الهوية:** `{r['party_id']}`  |  **الوقت:** `{r['created_at']}`  |  **التوثيق:** {r['citizen_auth_mode']}")
                    st.write(f"**ختم التحقق الرقمي:** `{r['verify_hash']}`")
                f_def = TRAFFIC_FORMS.get(r["form_id"])
                arch_html = build_official_a4_html(r, f_def, interactive_sig=False)
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
# القسم الثالث: إعدادات مناوبة الخفر
# =====================================================================
elif st.session_state.nav_tab == "مناوبة الخفر":
    st.markdown("""
    <div class="hero-shift-card">
        <div class="hero-eyebrow">ضبط بيانات الاستلام الميداني</div>
        <h3 style="margin:4px 0 8px 0; color:#ffffff;">👮 إعدادات استلام مناوبة الخفر والفرقة المباشرة</h3>
        <div style="font-size:13px; color:#cbd5e1;">
            تُثبت البيانات هنا مرة واحدة بداية الاستلام لتُدرج تلقائياً في ترويسة وذيل جميع الإقرارات والمحاضر الثمانية دون الحاجة لإعادة كتابتها.
        </div>
    </div>
    """, unsafe_allow_html=True)

    with st.form("shift_update_form"):
        s_dept = st.text_input("اسم الشعبة / القسم والدورية الميدانية", value=shift["dept_name"])
        r1, r2 = st.columns([1, 2])
        with r1:
            s_orank = st.text_input("رتبة الفرد المعد", value=shift["officer_rank"])
        with r2:
            s_oname = st.text_input("اسم الفرد المعد الثلاثي", value=shift["officer_name"])

        r3, r4 = st.columns([1, 2])
        with r3:
            s_drank = st.text_input("رتبة ضابط الخفر", value=shift["duty_rank"])
        with r4:
            s_dname = st.text_input("اسم ضابط الخفر المستلم", value=shift["duty_name"])

        s_gps = st.text_input("إحداثيات الموقع الميداني (GPS)", value=shift["default_gps"])

        if st.form_submit_button("💾 حفظ واعتماد بيانات المناوبة", type="primary", use_container_width=True):
            update_shift_settings(s_dept, s_orank, s_oname, s_drank, s_dname, s_gps)
            st.success("تم تحديث بيانات المناوبة وتعميمها على كافة النماذج بنجاح.")
            safe_rerun()


# =====================================================================
# القسم الرابع: فحص ومحاكاة بصمة منفذ الشحن (USB Type-C OTG)
# =====================================================================
elif st.session_state.nav_tab == "بصمة الشحن OTG":
    st.markdown("""
    <div class="hero-shift-card">
        <div class="hero-eyebrow">طبقة عزل العتاد الحيوي (Hardware Abstraction Layer)</div>
        <h3 style="margin:4px 0 8px 0; color:#ffffff;">🧬 إدارة وفحص قارئ البصمة عبر منفذ الشحن (USB Type-C)</h3>
        <div style="font-size:13px; color:#cbd5e1;">
            يعمل النظام حالياً بوضع المحاكاة الصوري المعزول لحين توصيل القارئ الفعلي، مع تحويل البصمة إلى ختم حبر إلكتروني وحذف الأثر الحيوي من الذاكرة المؤقتة فوراً.
        </div>
    </div>
    """, unsafe_allow_html=True)

    c_usb1, c_usb2 = st.columns(2)
    with c_usb1:
        selected_hw = st.selectbox(
            "بروتوكول القارئ المعتمد:",
            [
                "وضع المحاكاة متصل (معزول العتاد)",
                "SecuGen Hamster Pro 20 (Type-C OTG)",
                "Mantra MFS110 (RD Local Service 11100)",
                "ZKTeco Live20R (USB Host)",
            ],
        )
        if st.button("🔄 تحديث ربط منفذ الشحن", type="primary", use_container_width=True):
            st.session_state.scanner_model = selected_hw
            st.success(f"تم ضبط البروتوكول النشط على: {selected_hw}")
            safe_rerun()

    with c_usb2:
        if st.button("🧬 اختبار التقاط بصمة تجريبية الآن", use_container_width=True):
            test_b64 = generate_fingerprint_png_b64(f"TEST_{datetime.now().isoformat()}")
            st.image(base64.b64decode(test_b64), caption="اختبار ختم الحبر الأزرق الشفاف — جاهز للدمج في A4 PDF", width=130)