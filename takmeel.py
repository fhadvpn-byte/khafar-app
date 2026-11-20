"""قسم التكميل الإحصائي — قاعدة تراكمية + 4 نماذج رسمية لقسم مرور العارضة."""
from __future__ import annotations

import csv
import html
import io
import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

TAKMEEL_DB = Path(__file__).resolve().parent / "takmeel_records.db"
BACKUP_DIR = Path(__file__).resolve().parent
KSA_TZ = timezone(timedelta(hours=3))

AR_DAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
AR_MONTHS = [
    "", "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
]
AGE_BUCKETS = ["أقل من 18", "من 19 إلى 30", "من 31 إلى 40", "من 41 إلى 50", "من 51 وأكثر"]
AGE_KEYS = ["u18", "a19_30", "a31_40", "a41_50", "a51"]
AGE_LABELS = {
    "u18": "18- أقل من 18",
    "a19_30": "18+ من 19-30",
    "a31_40": "30+ من 31-40",
    "a41_50": "40+ من 41-50",
    "a51": "50+ من 51 فأكثر",
}
CAUSE_KEYS = [
    ("sudden_swerve", "انحراف مفاجئ"),
    ("illegal_turn", "دوران غير نظامي"),
    ("illegal_overtake", "تجاوز غير نظامي"),
    ("signal", "عدم التقيد بالإشارة"),
    ("speed", "السرعة الزائدة"),
    ("drugs", "السائق تحت تأثير المخدر"),
    ("other", "أخرى"),
]
HOSPITAL_STATUS = [
    "تحت المتابعة أقل من 24 ساعة",
    "مضى على تنويمه أكثر من 24 ساعة",
    "خرج قبل 24 ساعة",
]

TAKMEEL_FORMS = {
    "tak_daily_incidents": {
        "title": "تكميل الوقوعات اليومية",
        "icon": "📋",
        "subtitle": "وقوعات اليوم مع المصابين والمتوفين والربط الشهري",
        "category": "تكميل",
        "allow_absence": False,
        "require_image": False,
        "fields": [],
        "legal_fn": lambda m: "",
    },
    "tak_accidents_daily": {
        "title": "إحصاء الحوادث المرورية (يومي)",
        "icon": "🚗",
        "subtitle": "سجل صفوف الحوادث اليومية الرسمية",
        "category": "تكميل",
        "allow_absence": False,
        "require_image": False,
        "fields": [],
        "legal_fn": lambda m: "",
    },
    "tak_violations_daily": {
        "title": "إحصاء المخالفات المقترنة بالحوادث (يومي)",
        "icon": "📑",
        "subtitle": "المخالفات المرتبطة بأرقام الحوادث",
        "category": "تكميل",
        "allow_absence": False,
        "require_image": False,
        "fields": [],
        "legal_fn": lambda m: "",
    },
    "tak_injured_monthly": {
        "title": "تكميل المصابين المنومين (+24 ساعة) — شهري تراكمي",
        "icon": "🏥",
        "subtitle": "متابعة مصابي الشهر المرحّلين من الوقوعات اليومية",
        "category": "تكميل",
        "allow_absence": False,
        "require_image": False,
        "fields": [],
        "legal_fn": lambda m: "",
    },
}


# ---------- تواريخ ----------
def _today_ksa() -> date:
    return datetime.now(KSA_TZ).date()


def _now_ksa() -> datetime:
    return datetime.now(KSA_TZ)


def _kuwaiti_hijri(g: date) -> tuple[int, int, int]:
    """تحويل تقريبي إلى هجري (خوارزمية كويتية شائعة)."""
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


def date_bundle(d: date | None = None) -> dict:
    d = d or _today_ksa()
    hy, hm, hd = _kuwaiti_hijri(d)
    return {
        "g_iso": d.isoformat(),
        "g_display": d.strftime("%Y/%m/%d"),
        "h_display": f"{hy}/{hm:02d}/{hd:02d}",
        "weekday_ar": AR_DAYS[d.weekday()],
        "month_ar": AR_MONTHS[d.month],
        "year": d.year,
        "month": d.month,
        "month_key": f"{d.year}-{d.month:02d}",
    }


def _i(v, default=0) -> int:
    try:
        return int(str(v).strip() or default)
    except Exception:
        return default


def _sum_map(d: dict, keys: list[str]) -> int:
    return sum(_i(d.get(k)) for k in keys)


# ---------- قاعدة البيانات ----------
def init_takmeel_db() -> None:
    conn = sqlite3.connect(TAKMEEL_DB)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS daily_summary (
            g_date TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS accidents_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            g_date TEXT NOT NULL,
            row_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS violations_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            g_date TEXT NOT NULL,
            row_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS injured_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month_key TEXT NOT NULL,
            incident_no TEXT,
            name TEXT,
            accident_date TEXT,
            place TEXT,
            place_type TEXT,
            registry_no TEXT,
            gender TEXT,
            nationality TEXT,
            age_group TEXT,
            coverage TEXT,
            hospital_status TEXT,
            source_day TEXT,
            active INTEGER DEFAULT 1,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS monthly_meta (
            month_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def _now() -> str:
    return _now_ksa().strftime("%Y-%m-%d %H:%M:%S")


def save_daily_summary(g_date: str, payload: dict) -> None:
    conn = sqlite3.connect(TAKMEEL_DB)
    conn.execute(
        "INSERT INTO daily_summary(g_date, payload_json, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(g_date) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at",
        (g_date, json.dumps(payload, ensure_ascii=False), _now()),
    )
    conn.commit()
    conn.close()


def load_daily_summary(g_date: str) -> dict:
    conn = sqlite3.connect(TAKMEEL_DB)
    row = conn.execute("SELECT payload_json FROM daily_summary WHERE g_date=?", (g_date,)).fetchone()
    conn.close()
    return json.loads(row[0]) if row else {}


def list_accidents(g_date: str) -> list[dict]:
    conn = sqlite3.connect(TAKMEEL_DB)
    rows = conn.execute(
        "SELECT id, row_json FROM accidents_daily WHERE g_date=? ORDER BY id", (g_date,)
    ).fetchall()
    conn.close()
    out = []
    for rid, payload in rows:
        item = json.loads(payload)
        item["_id"] = rid
        out.append(item)
    return out


def add_accident(g_date: str, row: dict) -> None:
    conn = sqlite3.connect(TAKMEEL_DB)
    conn.execute(
        "INSERT INTO accidents_daily(g_date, row_json, created_at) VALUES(?,?,?)",
        (g_date, json.dumps(row, ensure_ascii=False), _now()),
    )
    conn.commit()
    conn.close()


def delete_accident(row_id: int) -> None:
    conn = sqlite3.connect(TAKMEEL_DB)
    conn.execute("DELETE FROM accidents_daily WHERE id=?", (row_id,))
    conn.commit()
    conn.close()


def list_violations(g_date: str) -> list[dict]:
    conn = sqlite3.connect(TAKMEEL_DB)
    rows = conn.execute(
        "SELECT id, row_json FROM violations_daily WHERE g_date=? ORDER BY id", (g_date,)
    ).fetchall()
    conn.close()
    out = []
    for rid, payload in rows:
        item = json.loads(payload)
        item["_id"] = rid
        out.append(item)
    return out


def add_violation(g_date: str, row: dict) -> None:
    conn = sqlite3.connect(TAKMEEL_DB)
    conn.execute(
        "INSERT INTO violations_daily(g_date, row_json, created_at) VALUES(?,?,?)",
        (g_date, json.dumps(row, ensure_ascii=False), _now()),
    )
    conn.commit()
    conn.close()


def delete_violation(row_id: int) -> None:
    conn = sqlite3.connect(TAKMEEL_DB)
    conn.execute("DELETE FROM violations_daily WHERE id=?", (row_id,))
    conn.commit()
    conn.close()


def upsert_injured_from_daily(month_key: str, source_day: str, injured_list: list[dict]) -> None:
    conn = sqlite3.connect(TAKMEEL_DB)
    keep_keys: set[tuple[str, str]] = set()
    for item in injured_list:
        if not item.get("name"):
            continue
        status = item.get("hospital_status") or HOSPITAL_STATUS[0]
        if item.get("hospitalize_24"):
            status = HOSPITAL_STATUS[1]
        inc_no = str(item.get("incident_no", "") or "")
        name = str(item.get("name", "") or "")
        keep_keys.add((inc_no, name))
        existing = conn.execute(
            "SELECT id FROM injured_cases WHERE month_key=? AND incident_no=? AND name=? AND source_day=?",
            (month_key, inc_no, name, source_day),
        ).fetchone()
        payload = (
            month_key,
            inc_no,
            name,
            item.get("accident_date", source_day),
            item.get("place", ""),
            item.get("place_type", "داخل المدينة"),
            item.get("registry_no", ""),
            item.get("gender", "ذكر"),
            item.get("nationality", "سعودي"),
            item.get("age_group", AGE_BUCKETS[1]),
            item.get("coverage", ""),
            status,
            source_day,
            1,
            _now(),
        )
        if existing:
            conn.execute(
                """UPDATE injured_cases SET incident_no=?, name=?, accident_date=?, place=?, place_type=?,
                registry_no=?, gender=?, nationality=?, age_group=?, coverage=?, hospital_status=?,
                source_day=?, active=1, updated_at=? WHERE id=?""",
                (
                    payload[1], payload[2], payload[3], payload[4], payload[5], payload[6],
                    payload[7], payload[8], payload[9], payload[10], payload[11], payload[12],
                    payload[14], existing[0],
                ),
            )
        else:
            conn.execute(
                """INSERT INTO injured_cases(
                    month_key, incident_no, name, accident_date, place, place_type, registry_no,
                    gender, nationality, age_group, coverage, hospital_status, source_day, active, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                payload,
            )
    stale = conn.execute(
        "SELECT id, incident_no, name FROM injured_cases WHERE month_key=? AND source_day=? AND active=1",
        (month_key, source_day),
    ).fetchall()
    for row_id, inc_no, name in stale:
        if (str(inc_no or ""), str(name or "")) not in keep_keys:
            conn.execute(
                "UPDATE injured_cases SET active=0, updated_at=? WHERE id=?",
                (_now(), row_id),
            )
    conn.commit()
    conn.close()


def list_injured(month_key: str, only_active: bool = True) -> list[dict]:
    conn = sqlite3.connect(TAKMEEL_DB)
    conn.row_factory = sqlite3.Row
    q = "SELECT * FROM injured_cases WHERE month_key=?"
    args: list = [month_key]
    if only_active:
        q += " AND active=1"
    q += " ORDER BY id"
    out = [dict(r) for r in conn.execute(q, args).fetchall()]
    conn.close()
    return out


def update_injured_status(case_id: int, status: str) -> None:
    conn = sqlite3.connect(TAKMEEL_DB)
    conn.execute(
        "UPDATE injured_cases SET hospital_status=?, updated_at=? WHERE id=?",
        (status, _now(), case_id),
    )
    conn.commit()
    conn.close()


def add_injured_manual(month_key: str, item: dict) -> None:
    conn = sqlite3.connect(TAKMEEL_DB)
    conn.execute(
        """INSERT INTO injured_cases(
            month_key, incident_no, name, accident_date, place, place_type, registry_no,
            gender, nationality, age_group, coverage, hospital_status, source_day, active, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            month_key,
            item.get("incident_no", ""),
            item.get("name", ""),
            item.get("accident_date", ""),
            item.get("place", ""),
            item.get("place_type", "داخل المدينة"),
            item.get("registry_no", ""),
            item.get("gender", "ذكر"),
            item.get("nationality", "سعودي"),
            item.get("age_group", AGE_BUCKETS[1]),
            item.get("coverage", ""),
            item.get("hospital_status", HOSPITAL_STATUS[1]),
            item.get("source_day", ""),
            1,
            _now(),
        ),
    )
    conn.commit()
    conn.close()


def save_monthly_meta(month_key: str, payload: dict) -> None:
    conn = sqlite3.connect(TAKMEEL_DB)
    conn.execute(
        "INSERT INTO monthly_meta(month_key, payload_json, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(month_key) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at",
        (month_key, json.dumps(payload, ensure_ascii=False), _now()),
    )
    conn.commit()
    conn.close()


def load_monthly_meta(month_key: str) -> dict:
    conn = sqlite3.connect(TAKMEEL_DB)
    row = conn.execute("SELECT payload_json FROM monthly_meta WHERE month_key=?", (month_key,)).fetchone()
    conn.close()
    return json.loads(row[0]) if row else {}


def clear_month_data(month_key: str) -> None:
    prefix = f"{month_key}%"
    conn = sqlite3.connect(TAKMEEL_DB)
    conn.execute("UPDATE injured_cases SET active=0, updated_at=? WHERE month_key=?", (_now(), month_key))
    conn.execute("DELETE FROM monthly_meta WHERE month_key=?", (month_key,))
    conn.execute("DELETE FROM daily_summary WHERE g_date LIKE ?", (prefix,))
    conn.execute("DELETE FROM accidents_daily WHERE g_date LIKE ?", (prefix,))
    conn.execute("DELETE FROM violations_daily WHERE g_date LIKE ?", (prefix,))
    conn.commit()
    conn.close()


def export_month_backup(month_key: str) -> dict:
    year, month = month_key.split("-")
    prefix = f"{year}-{month}"
    conn = sqlite3.connect(TAKMEEL_DB)
    days = conn.execute(
        "SELECT g_date, payload_json FROM daily_summary WHERE g_date LIKE ?", (f"{prefix}%",)
    ).fetchall()
    accidents = conn.execute(
        "SELECT g_date, row_json FROM accidents_daily WHERE g_date LIKE ?", (f"{prefix}%",)
    ).fetchall()
    viols = conn.execute(
        "SELECT g_date, row_json FROM violations_daily WHERE g_date LIKE ?", (f"{prefix}%",)
    ).fetchall()
    conn.close()
    return {
        "month_key": month_key,
        "exported_at": _now(),
        "daily_summary": {d: json.loads(p) for d, p in days},
        "accidents": [{"g_date": d, **json.loads(p)} for d, p in accidents],
        "violations": [{"g_date": d, **json.loads(p)} for d, p in viols],
        "injured_cases": list_injured(month_key, only_active=False),
        "monthly_meta": load_monthly_meta(month_key),
    }


def import_month_backup(data: dict) -> None:
    month_key = data.get("month_key") or ""
    if not month_key:
        raise ValueError("النسخة الاحتياطية بلا مفتاح شهر")
    prefix = f"{month_key}%"
    conn = sqlite3.connect(TAKMEEL_DB)
    conn.execute("DELETE FROM accidents_daily WHERE g_date LIKE ?", (prefix,))
    conn.execute("DELETE FROM violations_daily WHERE g_date LIKE ?", (prefix,))
    conn.execute("DELETE FROM injured_cases WHERE month_key=?", (month_key,))
    conn.execute("DELETE FROM daily_summary WHERE g_date LIKE ?", (prefix,))
    conn.execute("DELETE FROM monthly_meta WHERE month_key=?", (month_key,))
    conn.commit()
    conn.close()
    for g_date, payload in (data.get("daily_summary") or {}).items():
        save_daily_summary(g_date, payload)
    for row in data.get("accidents") or []:
        row = dict(row)
        g_date = row.pop("g_date", None)
        row.pop("_id", None)
        row.pop("id", None)
        if g_date:
            add_accident(g_date, row)
    for row in data.get("violations") or []:
        row = dict(row)
        g_date = row.pop("g_date", None)
        row.pop("_id", None)
        row.pop("id", None)
        if g_date:
            add_violation(g_date, row)
    for item in data.get("injured_cases") or []:
        item = dict(item)
        item.pop("id", None)
        add_injured_manual(month_key, item)
    if data.get("monthly_meta"):
        save_monthly_meta(month_key, data["monthly_meta"])


def compute_monthly_stats(cases: list[dict]) -> dict:
    approved = [c for c in cases if c.get("hospital_status") == HOSPITAL_STATUS[1]]
    incidents = set()
    place_inc = {"داخل المدينة": set(), "خارج المدينة": set()}
    place_p = {"داخل المدينة": 0, "خارج المدينة": 0}
    gender = {"ذكر": 0, "أنثى": 0}
    nation = {"سعودي": 0, "غير سعودي": 0}
    ages = {k: 0 for k in AGE_BUCKETS}
    for c in approved:
        inc = str(c.get("incident_no") or "").strip() or f"id-{c.get('id')}"
        pt = c.get("place_type") or "داخل المدينة"
        if pt not in place_inc:
            pt = "داخل المدينة"
        place_inc[pt].add(inc)
        incidents.add(inc)
        place_p[pt] = place_p.get(pt, 0) + 1
        g = c.get("gender") or "ذكر"
        gender[g] = gender.get(g, 0) + 1
        n = c.get("nationality") or "سعودي"
        nation[n] = nation.get(n, 0) + 1
        ag = c.get("age_group") or AGE_BUCKETS[1]
        if ag in ages:
            ages[ag] += 1
    return {
        "accidents_in": len(place_inc["داخل المدينة"]),
        "accidents_out": len(place_inc["خارج المدينة"]),
        "accidents_total": len(incidents),
        "injured_in": place_p["داخل المدينة"],
        "injured_out": place_p["خارج المدينة"],
        "injured_total": len(approved),
        "male": gender.get("ذكر", 0),
        "female": gender.get("أنثى", 0),
        "saudi": nation.get("سعودي", 0),
        "nonsaudi": nation.get("غير سعودي", 0),
        "ages": ages,
        "approved_count": len(approved),
    }


# ---------- طباعة A4 ----------
_FONT_STACK = '"Cairo","Tajawal","Segoe UI",Tahoma,Arial,sans-serif'
_FONT_IMPORT = "@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@600;700;800;900&family=Tajawal:wght@700;800;900&display=swap');"


def _zoom_controls_html() -> str:
    return """
<div class="zoom-bar no-print" id="zoomBar">
  <button type="button" class="z-btn" data-z="-">➖ تصغير</button>
  <button type="button" class="z-btn" data-z="+">➕ تكبير</button>
  <span class="z-pct" id="zoomPct">100%</span>
  <button type="button" class="z-btn" data-z="1">100%</button>
  <button type="button" class="z-btn" data-z="1.3">130%</button>
  <button type="button" class="z-btn" data-z="1.6">160%</button>
  <button type="button" class="z-btn" data-z="fit">↔️ ملاءمة الشاشة</button>
</div>
"""


def _zoom_script() -> str:
    return """
<script>
(function(){
  var KEY='khafar_preview_zoom';
  var sheet=document.getElementById('a4Sheet');
  var scroller=document.getElementById('previewScroll');
  var pctEl=document.getElementById('zoomPct');
  if(!sheet||!scroller) return;
  var zoom=1;
  try{ var saved=parseFloat(localStorage.getItem(KEY)||''); if(saved>=0.55&&saved<=2.2) zoom=saved; }catch(e){}
  function clamp(v){ return Math.max(0.55, Math.min(2.2, Math.round(v*100)/100)); }
  function apply(){
    sheet.style.zoom=String(zoom);
    sheet.style.transform='';
    sheet.style.transformOrigin='top right';
    scroller.style.overflow='auto';
    scroller.style.height='auto';
    if(pctEl) pctEl.textContent=Math.round(zoom*100)+'%';
    try{ localStorage.setItem(KEY, String(zoom)); }catch(e){}
  }
  function fit(){
    var avail=scroller.clientWidth||scroller.parentElement.clientWidth||794;
    var base=sheet.offsetWidth||794;
    if(sheet.style.zoom){ try{ sheet.style.zoom='1'; }catch(e){} }
    zoom=clamp(avail/Math.max(base,1));
    apply();
  }
  function clearForPrint(){
    sheet.style.zoom='1';
    sheet.style.transform='none';
    sheet.style.transformOrigin='';
    scroller.style.height='auto';
    scroller.style.overflow='visible';
    sheet.style.maxHeight='none';
    sheet.style.overflow='visible';
  }
  function forceOpenEmptyCells(container){
    if(!container) return;
    container.querySelectorAll('table').forEach(function(tbl){
      var h = tbl.querySelectorAll('tr').length > 25 ? 21 : 32;
      tbl.querySelectorAll('td').forEach(function(td){
        if (td.colSpan < 10 && !td.querySelector('img') && td.textContent.replace(/\u00a0/g, '').trim() === '') {
          td.innerHTML = '<div style="display:block!important;height:' + h + 'px!important;min-height:' + h + 'px!important;line-height:' + h + 'px!important;">&nbsp;</div>';
        }
      });
    });
  }
  document.querySelectorAll('#zoomBar [data-z]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var v=btn.getAttribute('data-z');
      if(v==='+') zoom=clamp(zoom+0.15);
      else if(v==='-') zoom=clamp(zoom-0.15);
      else if(v==='fit'){ fit(); return; }
      else zoom=clamp(parseFloat(v)||1);
      apply();
    });
  });
  window.addEventListener('beforeprint', function(){
    clearForPrint();
    forceOpenEmptyCells(sheet);
  });
  window.addEventListener('afterprint', apply);
  var printBtn=document.querySelector('.print-btn');
  if(printBtn){
    printBtn.addEventListener('click', function(ev){
      ev.preventDefault();
      clearForPrint();
      forceOpenEmptyCells(sheet);
      try { window.focus(); } catch(e) {}
      window.print();
    });
  }
  apply();
  setTimeout(apply, 200);
})();
</script>
"""


def _logo_img(logo_b64: str, h: int = 48) -> str:
    if logo_b64:
        return (
            f"<img class='logo-img' src='data:image/png;base64,{logo_b64}' "
            f"alt='شعار المرور' style='height:{h}px;width:auto;max-width:100%;"
            f"object-fit:contain;-webkit-print-color-adjust:exact;print-color-adjust:exact;' />"
        )
    return "<div style='font-size:12px;font-weight:800;color:#000000;'>الإدارة العامة للمرور</div>"


def _force_open_empty_cells(html_str: str, box_h: int = 21) -> str:
    box = (
        f'<div style="display:block!important;height:{box_h}px!important;'
        f'min-height:{box_h}px!important;line-height:{box_h}px!important;">&nbsp;</div>'
    )
    return re.sub(
        r'(<td(?![^>]*colspan\s*=\s*["\']?10)[^>]*>)\s*(?:&nbsp;|\u00a0)?\s*(</td>)',
        rf"\1{box}\2",
        html_str,
        flags=re.IGNORECASE,
    )


def _print_shell(title: str, body: str, logo_b64: str) -> str:
    body = _force_open_empty_cells(body, box_h=32)
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="UTF-8">
<meta name="format-detection" content="telephone=no">
<title>{html.escape(title)}</title>
<style>
{_FONT_IMPORT}
*{{box-sizing:border-box;font-family:{_FONT_STACK}!important}}
html,body{{direction:rtl;margin:0;padding:10px;background:#0d1316;color:#e2e8f0}}
.toolbar{{max-width:210mm;margin:0 auto 8px;text-align:center}}
.print-btn{{background:linear-gradient(135deg,#d4a853,#a37a2c);color:#fff;border:none;padding:8px 20px;border-radius:8px;font-weight:800;cursor:pointer;font-size:14px}}
.zoom-bar{{max-width:210mm;margin:0 auto 10px;display:flex;flex-wrap:wrap;gap:6px;justify-content:center;align-items:center}}
.z-btn{{background:#112924;color:#fff;border:1px solid #d4a853;border-radius:8px;padding:6px 10px;font-weight:800;cursor:pointer;font-size:12.5px}}
.z-pct{{background:#fff;color:#000;border-radius:8px;padding:6px 10px;font-weight:900;min-width:58px;text-align:center}}
.preview-scroll{{max-width:100%;overflow:auto;margin:0 auto}}
.a4{{width:794px;margin:0 auto;background:#fff;color:#000000!important;border:2px solid #000000;padding:6mm 7mm;direction:rtl}}
.a4,.a4 *{{color:#000000!important;opacity:1!important}}
.a4 .txt-red,.a4 .note-red{{color:#c00000!important}}
table{{width:100%;border-collapse:collapse;margin:4px 0;table-layout:fixed}}
th,td{{border:1.4px solid #000000!important;padding:4px 6px!important;text-align:center;vertical-align:middle;font-size:13px!important;line-height:1.3!important;font-weight:700!important}}
th{{background:#d9ead3;font-weight:800!important;height:34px!important;min-height:34px!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
td{{height:32px!important;min-height:32px!important}}
.lbl{{background:#f4f7f6;font-weight:800!important;text-align:right;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.hdr{{display:grid;grid-template-columns:1fr 2.2fr 1fr;align-items:center;gap:6px;margin-bottom:6px;border-bottom:2px solid #000;padding-bottom:4px}}
.hdr-title{{text-align:center;font-size:16px;font-weight:800!important;line-height:1.4}}
.logo-img{{-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}}
.note-red{{color:#c00000!important;font-size:12.5px;font-weight:800;margin-top:6px}}
.foot{{display:flex;justify-content:space-between;margin-top:8px;font-size:13.5px;font-weight:800}}
.a4-monthly .hdr-title{{font-size:15px}}
.a4-monthly th{{height:34px!important;min-height:34px!important;font-size:13px!important}}
.a4-monthly td{{height:32px!important;min-height:32px!important;padding:4px 6px!important;font-size:13px!important;font-weight:700!important}}
@media print{{
  @page{{size:A4 portrait;margin:4mm!important}}
  html,body{{background:#fff;padding:0;margin:0}}
  .toolbar,.no-print,.zoom-bar{{display:none!important}}
  .preview-scroll{{overflow:visible!important;height:auto!important;max-height:none!important}}
  .a4{{width:100%!important;max-width:200mm!important;height:auto!important;min-height:0!important;max-height:none!important;overflow:visible!important;margin:0 auto!important;border:none!important;padding:3mm 4mm!important;box-shadow:none!important;transform:none!important;zoom:1!important;page-break-inside:avoid!important;page-break-after:avoid!important;break-inside:avoid!important;-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}}
  .a4-monthly{{padding:2.5mm 3.5mm!important}}
  th{{height:34px!important;min-height:34px!important;font-size:13px!important;font-weight:800!important;background:#d9ead3!important;padding:4px 6px!important;border:1.4px solid #000000!important}}
  td{{height:32px!important;min-height:32px!important;font-size:13px!important;font-weight:700!important;padding:4px 6px!important;line-height:1.3!important;border:1.4px solid #000000!important}}
  .lbl{{background:#f4f7f6!important}}
  .bg-green{{background:#d9ead3!important}}
  .bg-blue{{background:#dce6f1!important}}
  .bg-peach{{background:#fbe4d5!important}}
  .txt-red,.note-red{{color:#c00000!important}}
  .hdr-title{{font-size:13px!important}}
  .logo-img{{display:inline-block!important;visibility:visible!important}}
}}
</style></head><body>
<div class="toolbar no-print"><button class="print-btn" type="button">🖨️ طباعة / حفظ PDF (1/1)</button></div>
{_zoom_controls_html()}
<div class="preview-scroll" id="previewScroll"><div class="a4" id="a4Sheet">{body}</div></div>
{_zoom_script()}
</body></html>"""


def _waqoat_cell(v) -> str:
    return html.escape(str(v if v is not None and str(v) != "" else "0"))


def _cell_text(v) -> str:
    """محتوى خلية؛ القيم الفارغة تُترك لـ _force_open_empty_cells لحقن صندوق الارتفاع."""
    if v is None:
        return ""
    s = str(v).strip() if isinstance(v, str) else str(v)
    if s == "":
        return ""
    return html.escape(s)


def _person_row_blank(item: dict | None) -> bool:
    item = item or {}
    return not any(
        str(item.get(k) or "").strip()
        for k in ("name", "incident_no", "registry_no", "place")
    )


def _waqoat_person_rows(items: list[dict], min_rows: int = 5) -> str:
    rows = []
    count = max(min_rows, len(items or []))
    for index in range(count):
        item = (items or [])[index] if index < len(items or []) else {}
        blank = _person_row_blank(item)
        male_txt = "" if blank else _cell_text(item.get("male") if item.get("male") not in (None, "") else "")
        female_txt = "" if blank else _cell_text(item.get("female") if item.get("female") not in (None, "") else "")
        rows.append(
            '<tr class="person-row">'
            f"<td colspan='2'>{_cell_text(item.get('name'))}</td>"
            f"<td colspan='2'>{_cell_text(item.get('incident_no'))}</td>"
            f"<td colspan='2'>{_cell_text(item.get('place'))}</td>"
            f"<td>{_cell_text(item.get('registry_no'))}</td>"
            f"<td>{_cell_text(item.get('coverage'))}</td>"
            f"<td>{male_txt}</td>"
            f"<td>{female_txt}</td>"
            "</tr>"
        )
    return "".join(rows)


def _waqoat_age_vals(ages: dict) -> tuple[list[int], int]:
    vals = [_i((ages or {}).get(k)) for k in AGE_KEYS]
    return vals, sum(vals)


def build_daily_incidents_a4(payload: dict, logo_b64: str) -> str:
    d = payload.get("dates") or date_bundle()
    day_name = d.get("weekday_ar") or "...."
    g_date = d.get("g_display") or "YYYY/MM/DD"
    h_date = d.get("h_display") or "YYYY/MM/DD"
    title = (
        f"الوقوعات اليومية لقسم مرور محافظة العارضة ليوم ({day_name}) "
        f"الموافق {g_date} م - {h_date} هـ"
    )
    p = payload
    c = p.get("causes") or {}
    age_drv, age_drv_sum = _waqoat_age_vals(p.get("age_drv") or {})
    age_inj, age_inj_sum = _waqoat_age_vals(p.get("age_inj") or {})
    age_dead, age_dead_sum = _waqoat_age_vals(p.get("age_dead") or {})

    acc_in, acc_out = _i(p.get("acc_in")), _i(p.get("acc_out"))
    inj_in, inj_out = _i(p.get("inj_in")), _i(p.get("inj_out"))
    dead_in, dead_out = _i(p.get("dead_in")), _i(p.get("dead_out"))
    viol_m, viol_f = _i(p.get("viol_m")), _i(p.get("viol_f"))
    detain_sa, detain_ns = _i(p.get("detain_sa")), _i(p.get("detain_ns"))

    sev_dmg_in, sev_dmg_out = _i(p.get("sev_dmg_in")), _i(p.get("sev_dmg_out"))
    sev_inj_in, sev_inj_out = _i(p.get("sev_inj_in")), _i(p.get("sev_inj_out"))
    sev_dead_in, sev_dead_out = _i(p.get("sev_dead_in")), _i(p.get("sev_dead_out"))

    drv_m, drv_f = _i(p.get("drv_m")), _i(p.get("drv_f"))
    p_inj_m, p_inj_f = _i(p.get("p_inj_m")), _i(p.get("p_inj_f"))
    p_dead_m, p_dead_f = _i(p.get("p_dead_m")), _i(p.get("p_dead_f"))
    drv_sa, drv_ns = _i(p.get("drv_sa")), _i(p.get("drv_ns"))
    p_inj_sa, p_inj_ns = _i(p.get("p_inj_sa")), _i(p.get("p_inj_ns"))
    p_dead_sa, p_dead_ns = _i(p.get("p_dead_sa")), _i(p.get("p_dead_ns"))

    cause_cells = "".join(
        f"<td>{_waqoat_cell(c.get(key, 0))}</td>" for key, _label in CAUSE_KEYS
    )
    prepared = html.escape(str(p.get("prepared_by") or ".........."))
    phone = html.escape(str(p.get("phone") or "................."))
    logo_r = _logo_img(logo_b64, 40)
    logo_l = _logo_img(logo_b64, 40)

    body = f"""
<table class="waqoat-grid">
  <colgroup>
    <col style="width:11.5%">
    <col style="width:11.5%">
    <col style="width:8.5%">
    <col style="width:8.5%">
    <col style="width:8.5%">
    <col style="width:8.5%">
    <col style="width:15.0%">
    <col style="width:9.0%">
    <col style="width:9.5%">
    <col style="width:9.5%">
  </colgroup>
  <tr>
    <td colspan="10" style="height:48px;padding:4px 14px;background:#fff;">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;direction:rtl;">
        <div style="flex:0 0 auto;">{logo_r}</div>
        <div style="flex:1 1 auto;text-align:center;font-weight:800;font-size:14.5px;line-height:1.3;color:#000000;">
          {html.escape(title)}
        </div>
        <div style="flex:0 0 auto;">{logo_l}</div>
      </div>
    </td>
  </tr>
  <tr class="bg-green">
    <th colspan="2">عدد الحوادث المرورية</th>
    <th colspan="2">عدد الأشخاص المصابين</th>
    <th colspan="2">عدد الأشخاص المتوفين</th>
    <th colspan="2">عدد المخالفات</th>
    <th colspan="2">عدد المواقيف</th>
  </tr>
  <tr class="bg-blue">
    <th>داخل المدينه</th><th>خارج المدينه</th>
    <th>داخل المدينه</th><th>خارج المدينه</th>
    <th>داخل المدينه</th><th>خارج المدينه</th>
    <th>ذكور</th><th>اناث</th>
    <th>سعودي</th><th>غير سعودي</th>
  </tr>
  <tr>
    <td>{_waqoat_cell(acc_in)}</td><td>{_waqoat_cell(acc_out)}</td>
    <td>{_waqoat_cell(inj_in)}</td><td>{_waqoat_cell(inj_out)}</td>
    <td>{_waqoat_cell(dead_in)}</td><td>{_waqoat_cell(dead_out)}</td>
    <td>{_waqoat_cell(viol_m)}</td><td>{_waqoat_cell(viol_f)}</td>
    <td>{_waqoat_cell(detain_sa)}</td><td>{_waqoat_cell(detain_ns)}</td>
  </tr>
  <tr>
    <td colspan="2">{_waqoat_cell(acc_in + acc_out)}</td>
    <td colspan="2">{_waqoat_cell(inj_in + inj_out)}</td>
    <td colspan="2">{_waqoat_cell(dead_in + dead_out)}</td>
    <td colspan="2">{_waqoat_cell(viol_m + viol_f)}</td>
    <td colspan="2">{_waqoat_cell(detain_sa + detain_ns)}</td>
  </tr>
  <tr class="bg-green"><th colspan="10">اجمالي الحوادث حسب الجسامه</th></tr>
  <tr class="bg-green">
    <th colspan="3">عدد حوادث التلفيات</th>
    <th colspan="3">عدد حوادث الإصابات</th>
    <th colspan="4">عدد حوادث الوفيات</th>
  </tr>
  <tr class="bg-blue">
    <th>داخل المدينة</th><th>خارج المدينه</th><th>المجموع</th>
    <th>داخل المدينة</th><th>خارج المدينه</th><th>المجموع</th>
    <th>داخل المدينة</th><th>خارج المدينه</th><th colspan="2">المجموع</th>
  </tr>
  <tr>
    <td>{_waqoat_cell(sev_dmg_in)}</td><td>{_waqoat_cell(sev_dmg_out)}</td><td>{_waqoat_cell(sev_dmg_in + sev_dmg_out)}</td>
    <td>{_waqoat_cell(sev_inj_in)}</td><td>{_waqoat_cell(sev_inj_out)}</td><td>{_waqoat_cell(sev_inj_in + sev_inj_out)}</td>
    <td>{_waqoat_cell(sev_dead_in)}</td><td>{_waqoat_cell(sev_dead_out)}</td><td colspan="2">{_waqoat_cell(sev_dead_in + sev_dead_out)}</td>
  </tr>
  <tr><td colspan="10" class="sep-row"></td></tr>
  <tr class="bg-green"><th colspan="10">اجمالي عدد السائقين المشتركين في الحوادث المرورية والاشخاص المصابين والمتوفين ( حسب الجسامه)</th></tr>
  <tr class="bg-green">
    <th colspan="3">عدد السائقين المشتركين في الحوادث</th>
    <th colspan="3">عدد الأشخاص المصابين</th>
    <th colspan="4">عدد الأشخاص المتوفين</th>
  </tr>
  <tr class="bg-blue">
    <th>ذكور</th><th>اناث</th><th>المجموع</th>
    <th>ذكور</th><th>اناث</th><th>المجموع</th>
    <th>ذكور</th><th>اناث</th><th colspan="2">المجموع</th>
  </tr>
  <tr>
    <td>{_waqoat_cell(drv_m)}</td><td>{_waqoat_cell(drv_f)}</td><td>{_waqoat_cell(drv_m + drv_f)}</td>
    <td>{_waqoat_cell(p_inj_m)}</td><td>{_waqoat_cell(p_inj_f)}</td><td>{_waqoat_cell(p_inj_m + p_inj_f)}</td>
    <td>{_waqoat_cell(p_dead_m)}</td><td>{_waqoat_cell(p_dead_f)}</td><td colspan="2">{_waqoat_cell(p_dead_m + p_dead_f)}</td>
  </tr>
  <tr><td colspan="10" class="sep-row"></td></tr>
  <tr class="bg-green"><th colspan="10">اجمالي عدد السائقين المشتركين في الحوادث المرورية والاشخاص المصابين والمتوفين ( حسب الجنسية)</th></tr>
  <tr class="bg-green">
    <th colspan="3">عدد السائقين المشتركين في الحوادث</th>
    <th colspan="3">عدد الأشخاص المصابين</th>
    <th colspan="4">عدد الأشخاص المتوفين</th>
  </tr>
  <tr class="bg-blue">
    <th>سعودي</th><th>غير سعودي</th><th>المجموع</th>
    <th>سعودي</th><th>غير سعودي</th><th>المجموع</th>
    <th>سعودي</th><th>غير سعودي</th><th colspan="2">المجموع</th>
  </tr>
  <tr>
    <td>{_waqoat_cell(drv_sa)}</td><td>{_waqoat_cell(drv_ns)}</td><td>{_waqoat_cell(drv_sa + drv_ns)}</td>
    <td>{_waqoat_cell(p_inj_sa)}</td><td>{_waqoat_cell(p_inj_ns)}</td><td>{_waqoat_cell(p_inj_sa + p_inj_ns)}</td>
    <td>{_waqoat_cell(p_dead_sa)}</td><td>{_waqoat_cell(p_dead_ns)}</td><td colspan="2">{_waqoat_cell(p_dead_sa + p_dead_ns)}</td>
  </tr>
  <tr><td colspan="10" class="sep-row"></td></tr>
  <tr class="bg-green"><th colspan="10">الفئة العمرية للسائقين ( تلفيات - اصابات - وفيات )</th></tr>
  <tr class="bg-green">
    <th colspan="3">الفئة العمرية</th>
    <th>18-</th><th>18+</th><th>30+</th><th>40+</th><th>50+</th><th colspan="2">المجموع</th>
  </tr>
  <tr>
    <td colspan="3" style="font-weight:700;">عدد السائقين المشتركين في الحوادث</td>
    <td>{_waqoat_cell(age_drv[0])}</td><td>{_waqoat_cell(age_drv[1])}</td><td>{_waqoat_cell(age_drv[2])}</td>
    <td>{_waqoat_cell(age_drv[3])}</td><td>{_waqoat_cell(age_drv[4])}</td><td colspan="2">{_waqoat_cell(age_drv_sum)}</td>
  </tr>
  <tr>
    <td colspan="3" style="font-weight:700;">عدد الاشخاص المصابين</td>
    <td>{_waqoat_cell(age_inj[0])}</td><td>{_waqoat_cell(age_inj[1])}</td><td>{_waqoat_cell(age_inj[2])}</td>
    <td>{_waqoat_cell(age_inj[3])}</td><td>{_waqoat_cell(age_inj[4])}</td><td colspan="2">{_waqoat_cell(age_inj_sum)}</td>
  </tr>
  <tr>
    <td colspan="3" style="font-weight:700;">عدد الأشخاص المتوفين</td>
    <td>{_waqoat_cell(age_dead[0])}</td><td>{_waqoat_cell(age_dead[1])}</td><td>{_waqoat_cell(age_dead[2])}</td>
    <td>{_waqoat_cell(age_dead[3])}</td><td>{_waqoat_cell(age_dead[4])}</td><td colspan="2">{_waqoat_cell(age_dead_sum)}</td>
  </tr>
  <tr>
    <th colspan="3" class="bg-white">أسباب الحوادث المرورية</th>
    <th class="bg-peach">انحراف مفاجىء</th>
    <th class="bg-peach">دوران غير نظامي</th>
    <th class="bg-peach">تجاوز غير نظامي</th>
    <th class="bg-peach">عدم التقيد بالإشارة</th>
    <th class="bg-peach">السرعة الزائدة</th>
    <th class="bg-peach">السائق تحت تاثير المخدر</th>
    <th class="bg-peach">أخرى</th>
  </tr>
  <tr>
    <td colspan="3"></td>
    {cause_cells}
  </tr>
  <tr class="bg-blue"><th colspan="10">أسماء الأشخاص المصابين</th></tr>
  <tr>
    <th colspan="2" rowspan="2" class="bg-blue">الاسم</th>
    <th colspan="2" rowspan="2" class="bg-blue">رقم الحادث</th>
    <th colspan="2" rowspan="2" class="bg-blue">مكان الحادث</th>
    <th rowspan="2" class="bg-blue">رقم السجل</th>
    <th rowspan="2" class="bg-blue txt-red">جهة التغطية</th>
    <th colspan="2" class="bg-blue">عدد المصابين</th>
  </tr>
  <tr>
    <th class="bg-white">ذكور</th><th class="bg-white">اناث</th>
  </tr>
  {_waqoat_person_rows(p.get("injured") or [], 5)}
  <tr class="bg-blue"><th colspan="10">أسماء الأشخاص المتوفي</th></tr>
  <tr>
    <th colspan="2" rowspan="2" class="bg-blue">الاسم</th>
    <th colspan="2" rowspan="2" class="bg-blue">رقم الحادث</th>
    <th colspan="2" rowspan="2" class="bg-blue">مكان الحادث</th>
    <th rowspan="2" class="bg-blue">رقم السجل</th>
    <th rowspan="2" class="bg-blue txt-red">جهة التغطية</th>
    <th colspan="2" class="bg-blue">عدد المتوفين</th>
  </tr>
  <tr>
    <th class="bg-white">ذكور</th><th class="bg-white">اناث</th>
  </tr>
  {_waqoat_person_rows(p.get("dead") or [], 5)}
</table>
<div class="waqoat-note txt-red">ملاحظة / جهة التغطية ( المرور - امن الطرق - الشرطة - الدوريات او جهات أخرى )</div>
<div class="waqoat-foot">
  <span>معد البيان/ {prepared}</span>
  <span>رقم الجوال ( {phone} )</span>
</div>
"""
    html_doc = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="UTF-8">
<meta name="format-detection" content="telephone=no">
<title>{html.escape(title)}</title>
<style>
{_FONT_IMPORT}
*{{box-sizing:border-box;font-family:{_FONT_STACK}!important}}
html,body{{direction:rtl;margin:0;padding:10px;background:#0d1316;color:#e2e8f0}}
.toolbar{{max-width:210mm;margin:0 auto 8px;text-align:center}}
.print-btn{{background:linear-gradient(135deg,#d4a853,#a37a2c);color:#fff;border:none;padding:8px 20px;border-radius:8px;font-weight:800;cursor:pointer;font-size:14px}}
.zoom-bar{{max-width:210mm;margin:0 auto 10px;display:flex;flex-wrap:wrap;gap:6px;justify-content:center;align-items:center}}
.z-btn{{background:#112924;color:#fff;border:1px solid #d4a853;border-radius:8px;padding:6px 10px;font-weight:800;cursor:pointer;font-size:12.5px}}
.z-pct{{background:#fff;color:#000;border-radius:8px;padding:6px 10px;font-weight:900;min-width:58px;text-align:center}}
.preview-scroll{{max-width:100%;overflow:auto;margin:0 auto}}
.a4{{width:794px;margin:0 auto;background:#fff;color:#000000!important;border:1px solid #000;padding:3mm 4mm;direction:rtl}}
.a4,.a4 *{{color:#000000!important;opacity:1!important}}
.a4 .txt-red{{color:#c00000!important}}
table.waqoat-grid{{
  width:100%;border-collapse:collapse;table-layout:fixed;direction:rtl;
  border:1.4px solid #000000!important;font-family:{_FONT_STACK}!important;
}}
table.waqoat-grid th,table.waqoat-grid td{{
  border:1.4px solid #000000!important;padding:2px 3px!important;text-align:center;vertical-align:middle;
  font-size:12px!important;line-height:1.3!important;color:#000000!important;font-weight:700!important;
}}
table.waqoat-grid th,.waqoat-grid .bg-green,.waqoat-grid .bg-blue,.waqoat-grid .bg-peach{{font-weight:800!important;font-size:13.5px}}
table.waqoat-grid tr.person-row td{{
  padding:2px 4px!important;line-height:1.3!important;
}}
.bg-green{{background-color:#d9ead3!important;font-weight:800!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.bg-blue{{background-color:#dce6f1!important;font-weight:800!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.bg-peach{{background-color:#fbe4d5!important;font-weight:800!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.bg-white{{background-color:#ffffff!important;font-weight:800!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.txt-red{{color:#c00000!important;font-weight:800}}
td.sep-row,.sep-row{{
  height:6px!important;min-height:6px!important;max-height:6px!important;
  line-height:6px!important;padding:0!important;font-size:0!important;
  background:#ffffff!important;border-left:1.4px solid #000;border-right:1.4px solid #000;
  overflow:hidden!important;
}}
.logo-img{{-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}}
.waqoat-note{{text-align:center;margin-top:4px;font-size:12.5px;font-weight:800}}
.waqoat-foot{{display:flex;justify-content:space-between;margin-top:4px;font-size:13px;font-weight:800;direction:rtl}}
@media print{{
  @page{{size:A4 portrait;margin:4mm!important}}
  html,body{{background:#fff!important;padding:0!important;margin:0!important}}
  .toolbar,.no-print,.zoom-bar{{display:none!important}}
  .preview-scroll{{overflow:visible!important;height:auto!important;max-height:none!important}}
  .a4{{width:100%!important;max-width:198mm!important;height:auto!important;min-height:0!important;max-height:none!important;overflow:visible!important;margin:0 auto!important;border:none!important;padding:0!important;box-shadow:none!important;transform:none!important;zoom:1!important;page-break-inside:avoid!important;page-break-after:avoid!important;break-inside:avoid!important;-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}}
  table.waqoat-grid{{page-break-inside:avoid!important;border:1.4px solid #000000!important}}
  table.waqoat-grid th,table.waqoat-grid td{{
    font-size:11.5px!important;padding:2px 3px!important;line-height:1.3!important;
    border:1.4px solid #000000!important;
  }}
  table.waqoat-grid th{{font-size:12.5px!important;background:#d9ead3!important}}
  table.waqoat-grid tr.bg-blue th,table.waqoat-grid th.bg-blue{{background:#dce6f1!important}}
  table.waqoat-grid tr.bg-peach th,table.waqoat-grid th.bg-peach{{background:#fbe4d5!important}}
  table.waqoat-grid tr.bg-white th,table.waqoat-grid th.bg-white{{background:#ffffff!important}}
  table.waqoat-grid th.txt-red{{color:#c00000!important}}
  table.waqoat-grid tr.person-row td{{
    padding:2px 4px!important;line-height:1.3!important;font-size:11.5px!important;
  }}
  td.sep-row,.sep-row{{
    height:6px!important;min-height:6px!important;max-height:6px!important;
    line-height:6px!important;padding:0!important;font-size:0!important;
  }}
  .bg-green{{background:#d9ead3!important}}
  .bg-blue{{background:#dce6f1!important}}
  .bg-peach{{background:#fbe4d5!important}}
  .txt-red,.waqoat-note{{color:#c00000!important}}
  .logo-img{{display:inline-block!important;visibility:visible!important}}
}}
</style></head><body>
<div class="toolbar no-print"><button class="print-btn" type="button">🖨️ طباعة / حفظ PDF (1/1)</button></div>
{_zoom_controls_html()}
<div class="preview-scroll" id="previewScroll"><div class="a4" id="a4Sheet">{body}</div></div>
{_zoom_script()}
</body></html>"""
    return _force_open_empty_cells(html_doc, box_h=21)


def build_accidents_a4(rows: list[dict], dates: dict, prepared_by: str, phone: str, logo_b64: str) -> str:
    title = (
        f"إحصاء الحوادث المرورية لقسم مرور محافظة العارضة ليوم {dates.get('weekday_ar')} "
        f"الموافق {dates.get('g_display')} م - {dates.get('h_display')} هـ"
    )
    lines = []
    for i in range(max(12, len(rows or []))):
        r = rows[i] if i < len(rows or []) else {}
        lines.append(
            "<tr>"
            + "".join(
                f"<td>{_cell_text(r.get(k))}</td>"
                for k in (
                    "incident_no", "road_name", "road_no", "severity", "accident_type",
                    "cause", "gender", "nationality", "coverage",
                )
            )
            + "</tr>"
        )
    body = f"""
    <div class="hdr">
      <div style="text-align:center">{_logo_img(logo_b64)}</div>
      <div class="hdr-title">{html.escape(title)}</div>
      <div style="text-align:center">{_logo_img(logo_b64)}</div>
    </div>
    <table>
      <tr><th>رقم الحادث</th><th>اسم الطريق</th><th>رقم الطريق</th><th>جسامة الحادث</th>
          <th>نوع الحادث</th><th>سبب الحادث</th><th>جنس السائق</th><th>جنسية السائق</th><th>جهة التغطية</th></tr>
      {''.join(lines)}
    </table>
    <div class="foot"><span>معد البيان / {html.escape(prepared_by or '..........')}</span>
    <span>رقم الجوال ({html.escape(phone or '..........')})</span></div>
    """
    return _print_shell(title, body, logo_b64)


def build_violations_a4(rows: list[dict], dates: dict, prepared_by: str, phone: str, logo_b64: str) -> str:
    title = (
        f"المخالفات المرورية المقترنة بالحوادث لقسم مرور العارضة / ليوم {dates.get('weekday_ar')} "
        f"الموافق {dates.get('h_display')} هـ"
    )
    lines = []
    for i in range(max(16, len(rows or []))):
        r = rows[i] if i < len(rows or []) else {}
        lines.append(
            "<tr>"
            f"<td>{_cell_text(i + 1 if r else '')}</td>"
            f"<td>{_cell_text(r.get('incident_no'))}</td>"
            f"<td>{_cell_text(r.get('violation_no'))}</td>"
            f"<td>{_cell_text(r.get('violation_type'))}</td>"
            f"<td>{_cell_text(r.get('accident_type'))}</td>"
            "</tr>"
        )
    body = f"""
    <div class="hdr">
      <div style="text-align:center">{_logo_img(logo_b64)}</div>
      <div class="hdr-title">{html.escape(title)}</div>
      <div style="text-align:center">{_logo_img(logo_b64)}</div>
    </div>
    <table>
      <tr><th>عدد</th><th>رقم الحادث</th><th>رقم المخالفة</th><th>نوع المخالفة</th><th>نوع الحادث</th></tr>
      {''.join(lines)}
    </table>
    <div class="foot"><span>معد البيان / {html.escape(prepared_by or '..........')}</span>
    <span>رقم الجوال ({html.escape(phone or '..........')})</span></div>
    """
    return _print_shell(title, body, logo_b64)


def build_monthly_injured_a4(stats: dict, month_ar: str, year: int, prepared_by: str, phone: str, logo_b64: str) -> str:
    title = (
        f"إجمالي عدد الحوادث الإصابات والأشخاص المصابين الذين مضى على تنويمهم في المستشفى أكثر من (24) ساعة "
        f"بسبب الحادث خلال شهر {month_ar} عام {year} م (حسب المكان والجنس والجنسية والعمر) قسم مرور العارضة"
    )
    ages = stats.get("ages") or {}
    body = f"""
    <div class="a4-monthly">
    <div class="hdr">
      <div style="text-align:center">{_logo_img(logo_b64, 42)}</div>
      <div class="hdr-title">{html.escape(title)}</div>
      <div style="text-align:center">{_logo_img(logo_b64, 42)}</div>
    </div>
    <table>
      <tr>
        <th colspan="4">عدد الحوادث الإصابات (حسب المكان)</th>
        <th colspan="9">عدد الأشخاص المصابين</th>
      </tr>
      <tr>
        <td class="lbl">داخل المدينة</td><td>{stats.get('accidents_in',0)}</td>
        <td class="lbl">خارج المدينة</td><td>{stats.get('accidents_out',0)}</td>
        <td class="lbl">المجموع</td><td>{stats.get('accidents_total',0)}</td>
        <td class="lbl">حسب المكان داخل</td><td>{stats.get('injured_in',0)}</td>
        <td class="lbl">خارج</td><td>{stats.get('injured_out',0)}</td>
        <td class="lbl">المجموع</td><td colspan="2">{stats.get('injured_total',0)}</td>
      </tr>
      <tr>
        <td class="lbl" colspan="2">حسب الجنس</td>
        <td class="lbl">ذكر</td><td>{stats.get('male',0)}</td>
        <td class="lbl">أنثى</td><td>{stats.get('female',0)}</td>
        <td class="lbl">المجموع</td><td>{_i(stats.get('male'))+_i(stats.get('female'))}</td>
        <td class="lbl">سعودي</td><td>{stats.get('saudi',0)}</td>
        <td class="lbl">غير سعودي</td><td>{stats.get('nonsaudi',0)}</td>
        <td>{_i(stats.get('saudi'))+_i(stats.get('nonsaudi'))}</td>
      </tr>
    </table>
    <table>
      <tr><th colspan="6">عدد الأشخاص المصابين حسب العمر التي مضى عليهم أكثر من (24) ساعة منومين بسبب الإصابة</th></tr>
      <tr><th>أقل من 18</th><th>من 19 إلى 30</th><th>من 31 إلى 40</th><th>من 41 إلى 50</th><th>من 51 وأكثر</th><th>المجموع</th></tr>
      <tr>
        <td>{ages.get(AGE_BUCKETS[0],0)}</td><td>{ages.get(AGE_BUCKETS[1],0)}</td>
        <td>{ages.get(AGE_BUCKETS[2],0)}</td><td>{ages.get(AGE_BUCKETS[3],0)}</td>
        <td>{ages.get(AGE_BUCKETS[4],0)}</td>
        <td>{sum(_i(ages.get(k)) for k in AGE_BUCKETS)}</td>
      </tr>
    </table>
    <table class="footer-meta">
      <tr><td class="lbl">اسم معد البيان</td><td>{_cell_text(prepared_by)}</td>
          <td class="lbl">رقم الجوال</td><td>{_cell_text(phone)}</td></tr>
    </table>
    </div>
    """
    return _print_shell(title, body, logo_b64)


# ---------- واجهة Streamlit ----------
def _num(label: str, key: str, default: int = 0) -> int:
    return int(st.number_input(label, min_value=0, step=1, value=int(default), key=key))


def _inject_local_backup_js(month_key: str, payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    st.html(
        f"""
<script>
(function(){{
  try {{
    var key = "takmeel_backup_{html.escape(month_key)}";
    localStorage.setItem(key, {json.dumps(raw)});
  }} catch (e) {{}}
}})();
</script>
""",
        unsafe_allow_javascript=True,
    )


def render_backup_controls(month_key: str) -> None:
    st.markdown("#### 💾 النسخ الاحتياطي والتصفير")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("📥 تصدير نسخة JSON للشهر", use_container_width=True, key=f"exp_json_{month_key}"):
            data = export_month_backup(month_key)
            _inject_local_backup_js(month_key, data)
            st.download_button(
                "⬇️ تنزيل JSON",
                data=json.dumps(data, ensure_ascii=False, indent=2),
                file_name=f"takmeel_backup_{month_key}.json",
                mime="application/json",
                use_container_width=True,
                key=f"dl_json_{month_key}",
            )
            # CSV مبسّط للمصابين
            buf = io.StringIO()
            writer = csv.DictWriter(
                buf,
                fieldnames=[
                    "name", "incident_no", "accident_date", "place", "place_type",
                    "registry_no", "gender", "nationality", "age_group", "coverage", "hospital_status",
                ],
                extrasaction="ignore",
            )
            writer.writeheader()
            for row in data.get("injured_cases") or []:
                writer.writerow(row)
            st.download_button(
                "⬇️ تنزيل Excel/CSV للمصابين",
                data=buf.getvalue().encode("utf-8-sig"),
                file_name=f"takmeel_injured_{month_key}.csv",
                mime="text/csv",
                use_container_width=True,
                key=f"dl_csv_{month_key}",
            )
    with c2:
        up = st.file_uploader("📤 استعادة نسخة احتياطية JSON", type=["json"], key=f"up_{month_key}")
        if up and st.button("تطبيق الاستعادة", use_container_width=True, key=f"apply_up_{month_key}"):
            try:
                import_month_backup(json.loads(up.getvalue().decode("utf-8")))
                st.success("تمت استعادة النسخة الاحتياطية.")
                st.rerun()
            except Exception as exc:
                st.error(f"تعذرت الاستعادة: {exc}")
    with c3:
        st.caption("تصفير بيانات الشهر محمي بتأكيد مزدوج ورمز رئيس وحدة الحوادث.")
        code = st.text_input("رمز رئيس وحدة الحوادث", type="password", key=f"clr_code_{month_key}")
        conf1 = st.checkbox("أؤكد أن الإرسال الشهري تم", key=f"clr_c1_{month_key}")
        conf2 = st.checkbox("أؤكد حذف بيانات هذا الشهر نهائياً", key=f"clr_c2_{month_key}")
        if st.button("🗑️ تصفير بيانات الشهر بعد الإرسال", type="secondary", use_container_width=True, key=f"clr_btn_{month_key}"):
            if code.strip().translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")) != "1404" or not conf1 or not conf2:
                st.error("رمز غير صحيح أو التأكيد غير مكتمل.")
            else:
                clear_month_data(month_key)
                st.success("تم تصفير بيانات الشهر.")
                st.rerun()


def _auto_fill_from_day(g_date: str, payload: dict) -> dict:
    accidents = list_accidents(g_date)
    viols = list_violations(g_date)
    out = dict(payload)
    out["drv_m"] = 0
    out["drv_f"] = 0
    out["drv_sa"] = 0
    out["drv_ns"] = 0
    out["sev_dmg_in"] = 0
    out["sev_dmg_out"] = 0
    out["sev_inj_in"] = 0
    out["sev_inj_out"] = 0
    out["sev_dead_in"] = 0
    out["sev_dead_out"] = 0
    causes = {key: 0 for key, _label in CAUSE_KEYS}
    out["acc_in"] = sum(1 for r in accidents if r.get("place_type") != "خارج المدينة")
    out["acc_out"] = sum(1 for r in accidents if r.get("place_type") == "خارج المدينة")
    if not out["acc_in"] and not out["acc_out"] and accidents:
        out["acc_in"] = len(accidents)
    for r in accidents:
        is_out = str(r.get("place_type") or "") == "خارج المدينة"
        g = str(r.get("severity") or r.get("accident_type") or "")
        if "وفاة" in g or "وفيات" in g:
            if is_out:
                out["sev_dead_out"] += 1
            else:
                out["sev_dead_in"] += 1
        elif "إصاب" in g:
            if is_out:
                out["sev_inj_out"] += 1
            else:
                out["sev_inj_in"] += 1
        elif "تلفيات" in g or "تلف" in g:
            if is_out:
                out["sev_dmg_out"] += 1
            else:
                out["sev_dmg_in"] += 1
        if r.get("gender") == "أنثى":
            out["drv_f"] += 1
        else:
            out["drv_m"] += 1
        if r.get("nationality") == "غير سعودي":
            out["drv_ns"] += 1
        else:
            out["drv_sa"] += 1
        cause = str(r.get("cause") or "").strip()
        matched = False
        for key, label in CAUSE_KEYS:
            if cause == label or label in cause or key in cause:
                causes[key] += 1
                matched = True
                break
        if cause and not matched:
            causes["other"] += 1
    out["causes"] = causes
    out["viol_m"] = len(viols)
    return out


def render_daily_incidents(logo_b64: str, shift: dict) -> None:
    st.subheader("📋 تكميل الوقوعات اليومية")
    day = st.date_input("تاريخ البيان", value=_today_ksa(), key="tak_day_inc")
    dates = date_bundle(day)
    g_date = dates["g_iso"]
    saved = load_daily_summary(g_date)
    flash = st.session_state.pop("_tak_daily_seed", None)
    if isinstance(flash, dict):
        saved = {**saved, **flash}
        for key, value in flash.items():
            if isinstance(value, (int, float)):
                st.session_state[f"{key}_{g_date}"] = int(value)
            elif isinstance(value, dict):
                for sub_key, sub_val in value.items():
                    if not isinstance(sub_val, (int, float)):
                        continue
                    if key.startswith("age_"):
                        st.session_state[f"{key}_{sub_key}_{g_date}"] = int(sub_val)
                    elif key == "causes":
                        st.session_state[f"cause_{sub_key}_{g_date}"] = int(sub_val)
    if st.button("🔄 احتساب الأرقام تلقائياً من إحصاء الحوادث والمخالفات المسجلة لهذا اليوم", use_container_width=True):
        st.session_state["_tak_daily_seed"] = _auto_fill_from_day(g_date, saved)
        st.rerun()

    st.caption(f"{dates['weekday_ar']} | {dates['g_display']} م | {dates['h_display']} هـ")

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        acc_in = _num("حوادث داخل", f"acc_in_{g_date}", saved.get("acc_in", 0))
        acc_out = _num("حوادث خارج", f"acc_out_{g_date}", saved.get("acc_out", 0))
    with c2:
        inj_in = _num("مصابون داخل", f"inj_in_{g_date}", saved.get("inj_in", 0))
        inj_out = _num("مصابون خارج", f"inj_out_{g_date}", saved.get("inj_out", 0))
    with c3:
        dead_in = _num("متوفون داخل", f"dead_in_{g_date}", saved.get("dead_in", 0))
        dead_out = _num("متوفون خارج", f"dead_out_{g_date}", saved.get("dead_out", 0))
    with c4:
        viol_m = _num("مخالفات ذكور", f"viol_m_{g_date}", saved.get("viol_m", 0))
        viol_f = _num("مخالفات إناث", f"viol_f_{g_date}", saved.get("viol_f", 0))
    with c5:
        detain_sa = _num("مواقيف سعودي", f"detain_sa_{g_date}", saved.get("detain_sa", 0))
        detain_ns = _num("مواقيف غير سعودي", f"detain_ns_{g_date}", saved.get("detain_ns", 0))

    st.markdown("**إجمالي الحوادث حسب الجسامة**")
    g1, g2, g3 = st.columns(3)
    with g1:
        sev_dmg_in = _num("تلفيات داخل", f"sev_dmg_in_{g_date}", saved.get("sev_dmg_in", 0))
        sev_dmg_out = _num("تلفيات خارج", f"sev_dmg_out_{g_date}", saved.get("sev_dmg_out", 0))
        st.info(f"مجموع التلفيات: {sev_dmg_in + sev_dmg_out}")
    with g2:
        sev_inj_in = _num("إصابات داخل", f"sev_inj_in_{g_date}", saved.get("sev_inj_in", 0))
        sev_inj_out = _num("إصابات خارج", f"sev_inj_out_{g_date}", saved.get("sev_inj_out", 0))
        st.info(f"مجموع الإصابات: {sev_inj_in + sev_inj_out}")
    with g3:
        sev_dead_in = _num("وفيات داخل", f"sev_dead_in_{g_date}", saved.get("sev_dead_in", 0))
        sev_dead_out = _num("وفيات خارج", f"sev_dead_out_{g_date}", saved.get("sev_dead_out", 0))
        st.info(f"مجموع الوفيات: {sev_dead_in + sev_dead_out}")

    st.markdown("**السائقون / المصابون / المتوفون (جنس وجنسية)**")
    s1, s2, s3 = st.columns(3)
    with s1:
        drv_m = _num("سائقون ذكور", f"drv_m_{g_date}", saved.get("drv_m", 0))
        drv_f = _num("سائقون إناث", f"drv_f_{g_date}", saved.get("drv_f", 0))
        drv_sa = _num("سائقون سعودي", f"drv_sa_{g_date}", saved.get("drv_sa", 0))
        drv_ns = _num("سائقون غير سعودي", f"drv_ns_{g_date}", saved.get("drv_ns", 0))
    with s2:
        p_inj_m = _num("مصابون ذكور", f"p_inj_m_{g_date}", saved.get("p_inj_m", 0))
        p_inj_f = _num("مصابون إناث", f"p_inj_f_{g_date}", saved.get("p_inj_f", 0))
        p_inj_sa = _num("مصابون سعودي", f"p_inj_sa_{g_date}", saved.get("p_inj_sa", 0))
        p_inj_ns = _num("مصابون غير سعودي", f"p_inj_ns_{g_date}", saved.get("p_inj_ns", 0))
    with s3:
        p_dead_m = _num("متوفون ذكور", f"p_dead_m_{g_date}", saved.get("p_dead_m", 0))
        p_dead_f = _num("متوفون إناث", f"p_dead_f_{g_date}", saved.get("p_dead_f", 0))
        p_dead_sa = _num("متوفون سعودي", f"p_dead_sa_{g_date}", saved.get("p_dead_sa", 0))
        p_dead_ns = _num("متوفون غير سعودي", f"p_dead_ns_{g_date}", saved.get("p_dead_ns", 0))

    def age_block(prefix: str, label: str, seed: dict) -> dict:
        st.markdown(f"**الفئة العمرية — {label}**")
        cols = st.columns(5)
        out = {}
        for i, key in enumerate(AGE_KEYS):
            with cols[i]:
                out[key] = _num(AGE_LABELS.get(key, key), f"{prefix}_{key}_{g_date}", seed.get(key, 0))
        st.caption(f"المجموع: {sum(out.values())}")
        return out

    age_drv = age_block("age_drv", "السائقون", saved.get("age_drv") or {})
    age_inj = age_block("age_inj", "المصابون", saved.get("age_inj") or {})
    age_dead = age_block("age_dead", "المتوفون", saved.get("age_dead") or {})

    st.markdown("**أسباب الحوادث**")
    cause_cols = st.columns(4)
    causes = {}
    seed_c = saved.get("causes") or {}
    for idx, (key, label) in enumerate(CAUSE_KEYS):
        with cause_cols[idx % 4]:
            causes[key] = _num(label, f"cause_{key}_{g_date}", seed_c.get(key, 0))

    st.markdown("**أسماء المصابين**")
    inj_count = st.number_input(
        "عدد صفوف المصابين",
        min_value=0,
        max_value=20,
        value=len(saved.get("injured") or []),
        key=f"inj_rows_n_{g_date}",
    )
    injured = []
    seed_inj = saved.get("injured") or []
    for i in range(int(inj_count)):
        seed = seed_inj[i] if i < len(seed_inj) else {}
        blank_seed = _person_row_blank(seed)
        with st.expander(f"مصاب #{i+1}", expanded=i == 0):
            a, b = st.columns(2)
            with a:
                name = st.text_input("الاسم", value=seed.get("name", ""), key=f"inj_name_{g_date}_{i}")
                incident_no = st.text_input("رقم الحادث", value=seed.get("incident_no", ""), key=f"inj_inc_{g_date}_{i}")
                place = st.text_input("مكان الحادث", value=seed.get("place", ""), key=f"inj_place_{g_date}_{i}")
                registry_no = st.text_input("رقم السجل", value=seed.get("registry_no", ""), key=f"inj_reg_{g_date}_{i}")
                coverage = st.text_input("جهة التغطية", value=seed.get("coverage", ""), key=f"inj_cov_{g_date}_{i}")
            with b:
                place_type = st.selectbox("المكان", ["داخل المدينة", "خارج المدينة"], index=0 if seed.get("place_type", "داخل المدينة") != "خارج المدينة" else 1, key=f"inj_pt_{g_date}_{i}")
                gender = st.selectbox("الجنس", ["ذكر", "أنثى"], index=0 if seed.get("gender", "ذكر") != "أنثى" else 1, key=f"inj_g_{g_date}_{i}")
                nationality = st.selectbox("الجنسية", ["سعودي", "غير سعودي"], index=0 if seed.get("nationality", "سعودي") != "غير سعودي" else 1, key=f"inj_n_{g_date}_{i}")
                age_group = st.selectbox("الفئة العمرية", AGE_BUCKETS, index=AGE_BUCKETS.index(seed.get("age_group")) if seed.get("age_group") in AGE_BUCKETS else 1, key=f"inj_age_{g_date}_{i}")
                male_default = 0 if blank_seed else seed.get("male", 1 if gender == "ذكر" else 0)
                female_default = 0 if blank_seed else seed.get("female", 1 if gender == "أنثى" else 0)
                male = _num("عدد ذكور", f"inj_male_{g_date}_{i}", male_default)
                female = _num("عدد إناث", f"inj_female_{g_date}_{i}", female_default)
                hospitalize_24 = st.checkbox("✅ منوّم بالمستشفى لأكثر من 24 ساعة — يُدرج في التكميل الشهري", value=bool(seed.get("hospitalize_24")), key=f"inj_h24_{g_date}_{i}")
            injured.append({
                "name": name, "incident_no": incident_no, "place": place, "registry_no": registry_no,
                "coverage": coverage, "place_type": place_type, "gender": gender, "nationality": nationality,
                "age_group": age_group, "male": male, "female": female, "hospitalize_24": hospitalize_24,
                "accident_date": g_date,
                "hospital_status": HOSPITAL_STATUS[1] if hospitalize_24 else HOSPITAL_STATUS[0],
            })
    injured = [row for row in injured if not _person_row_blank(row)]

    st.markdown("**أسماء المتوفين**")
    dead_count = st.number_input(
        "عدد صفوف المتوفين",
        min_value=0,
        max_value=15,
        value=len(saved.get("dead") or []),
        key=f"dead_rows_n_{g_date}",
    )
    dead = []
    seed_dead = saved.get("dead") or []
    for i in range(int(dead_count)):
        seed = seed_dead[i] if i < len(seed_dead) else {}
        blank_seed = _person_row_blank(seed)
        a, b, c = st.columns(3)
        with a:
            name = st.text_input("الاسم", value=seed.get("name", ""), key=f"dead_name_{g_date}_{i}")
            incident_no = st.text_input("رقم الحادث", value=seed.get("incident_no", ""), key=f"dead_inc_{g_date}_{i}")
        with b:
            place = st.text_input("مكان الحادث", value=seed.get("place", ""), key=f"dead_place_{g_date}_{i}")
            registry_no = st.text_input("رقم السجل", value=seed.get("registry_no", ""), key=f"dead_reg_{g_date}_{i}")
        with c:
            coverage = st.text_input("جهة التغطية", value=seed.get("coverage", ""), key=f"dead_cov_{g_date}_{i}")
            male = _num("ذكور", f"dead_m_{g_date}_{i}", 0 if blank_seed else seed.get("male", 0))
            female = _num("إناث", f"dead_f_{g_date}_{i}", 0 if blank_seed else seed.get("female", 0))
        dead.append({
            "name": name, "incident_no": incident_no, "place": place, "registry_no": registry_no,
            "coverage": coverage, "male": male, "female": female,
        })
    dead = [row for row in dead if not _person_row_blank(row)]

    prepared_by = st.text_input(
        "معد البيان",
        value=saved.get("prepared_by") or shift.get("officer_name") or "",
        key=f"prep_daily_{g_date}",
    )
    phone = st.text_input("رقم الجوال", value=saved.get("phone") or "", key=f"phone_daily_{g_date}")

    payload = {
        "dates": dates,
        "acc_in": acc_in, "acc_out": acc_out, "inj_in": inj_in, "inj_out": inj_out,
        "dead_in": dead_in, "dead_out": dead_out, "viol_m": viol_m, "viol_f": viol_f,
        "detain_sa": detain_sa, "detain_ns": detain_ns,
        "sev_dmg_in": sev_dmg_in, "sev_dmg_out": sev_dmg_out,
        "sev_inj_in": sev_inj_in, "sev_inj_out": sev_inj_out,
        "sev_dead_in": sev_dead_in, "sev_dead_out": sev_dead_out,
        "drv_m": drv_m, "drv_f": drv_f, "drv_sa": drv_sa, "drv_ns": drv_ns,
        "p_inj_m": p_inj_m, "p_inj_f": p_inj_f, "p_inj_sa": p_inj_sa, "p_inj_ns": p_inj_ns,
        "p_dead_m": p_dead_m, "p_dead_f": p_dead_f, "p_dead_sa": p_dead_sa, "p_dead_ns": p_dead_ns,
        "age_drv": age_drv, "age_inj": age_inj, "age_dead": age_dead, "causes": causes,
        "injured": injured, "dead": dead, "prepared_by": prepared_by, "phone": phone,
    }

    if st.button("💾 حفظ الوقوعات اليومية وترحيل المصابين للشهر", type="primary", use_container_width=True):
        save_daily_summary(g_date, payload)
        upsert_injured_from_daily(dates["month_key"], g_date, injured)
        _inject_local_backup_js(dates["month_key"], export_month_backup(dates["month_key"]))
        st.success("تم الحفظ التراكمي وترحيل المصابين إلى التكميل الشهري.")

    st.markdown("#### معاينة وطباعة A4")
    components.html(build_daily_incidents_a4(payload, logo_b64), height=1380, scrolling=True)
    render_backup_controls(dates["month_key"])


def render_accidents_daily(logo_b64: str, shift: dict) -> None:
    st.subheader("🚗 إحصاء الحوادث المرورية (يومي)")
    day = st.date_input("تاريخ الإحصاء", value=_today_ksa(), key="tak_day_acc")
    dates = date_bundle(day)
    g_date = dates["g_iso"]
    rows = list_accidents(g_date)
    st.caption(f"{dates['weekday_ar']} | {dates['g_display']} م | {dates['h_display']} هـ — المحفوظ: {len(rows)}")

    with st.form("acc_add_form", clear_on_submit=True):
        a, b, c = st.columns(3)
        with a:
            incident_no = st.text_input("رقم الحادث")
            road_name = st.text_input("اسم الطريق")
            road_no = st.text_input("رقم الطريق")
        with b:
            severity = st.selectbox("جسامة الحادث", ["تلفيات", "إصابات", "وفيات"])
            accident_type = st.text_input("نوع الحادث")
            cause = st.selectbox("سبب الحادث", [x[1] for x in CAUSE_KEYS])
        with c:
            gender = st.selectbox("جنس السائق", ["ذكر", "أنثى"])
            nationality = st.selectbox("جنسية السائق", ["سعودي", "غير سعودي"])
            coverage = st.text_input("جهة التغطية")
            place_type = st.selectbox("المكان", ["داخل المدينة", "خارج المدينة"])
        if st.form_submit_button("➕ إضافة وحفظ فوري", use_container_width=True):
            add_accident(g_date, {
                "incident_no": incident_no, "road_name": road_name, "road_no": road_no,
                "severity": severity, "accident_type": accident_type, "cause": cause,
                "gender": gender, "nationality": nationality, "coverage": coverage, "place_type": place_type,
            })
            st.rerun()

    for r in rows:
        cols = st.columns([8, 1])
        with cols[0]:
            st.write(
                f"{r.get('incident_no')} | {r.get('road_name')} | {r.get('severity')} | {r.get('cause')} | {r.get('coverage')}"
            )
        with cols[1]:
            if st.button("🗑️", key=f"del_acc_{r['_id']}"):
                delete_accident(r["_id"])
                st.rerun()

    prepared_by = st.text_input("معد البيان", value=shift.get("officer_name") or "", key="prep_acc")
    phone = st.text_input("رقم الجوال", value="", key="phone_acc")
    components.html(build_accidents_a4(rows, dates, prepared_by, phone, logo_b64), height=1000, scrolling=True)
    render_backup_controls(dates["month_key"])


def render_violations_daily(logo_b64: str, shift: dict) -> None:
    st.subheader("📑 إحصاء المخالفات المقترنة بالحوادث (يومي)")
    day = st.date_input("تاريخ المخالفات", value=_today_ksa(), key="tak_day_viol")
    dates = date_bundle(day)
    g_date = dates["g_iso"]
    rows = list_violations(g_date)
    st.caption(f"{dates['weekday_ar']} | {dates['h_display']} هـ — المحفوظ: {len(rows)}")

    with st.form("viol_add_form", clear_on_submit=True):
        a, b = st.columns(2)
        with a:
            incident_no = st.text_input("رقم الحادث")
            violation_no = st.text_input("رقم المخالفة")
        with b:
            violation_type = st.text_input("نوع المخالفة")
            accident_type = st.selectbox("نوع الحادث", ["تلفيات", "إصابة", "وفاة"])
        if st.form_submit_button("➕ إضافة وحفظ فوري", use_container_width=True):
            add_violation(g_date, {
                "incident_no": incident_no, "violation_no": violation_no,
                "violation_type": violation_type, "accident_type": accident_type,
            })
            st.rerun()

    for r in rows:
        cols = st.columns([8, 1])
        with cols[0]:
            st.write(f"{r.get('incident_no')} | {r.get('violation_no')} | {r.get('violation_type')} | {r.get('accident_type')}")
        with cols[1]:
            if st.button("🗑️", key=f"del_viol_{r['_id']}"):
                delete_violation(r["_id"])
                st.rerun()

    prepared_by = st.text_input("معد البيان", value=shift.get("officer_name") or "", key="prep_viol")
    phone = st.text_input("رقم الجوال", value="", key="phone_viol")
    components.html(build_violations_a4(rows, dates, prepared_by, phone, logo_b64), height=1000, scrolling=True)
    render_backup_controls(dates["month_key"])


def render_injured_monthly(logo_b64: str, shift: dict) -> None:
    st.subheader("🏥 تكميل المصابين المنومين (+24 ساعة) — شهري تراكمي")
    today = _today_ksa()
    year = st.number_input("السنة", min_value=2020, max_value=2100, value=today.year, key="tak_year")
    month = st.selectbox(
        "الشهر",
        list(range(1, 13)),
        index=today.month - 1,
        format_func=lambda m: AR_MONTHS[m],
        key="tak_month",
    )
    month_key = f"{int(year)}-{int(month):02d}"
    cases = list_injured(month_key)
    st.markdown("#### سجل متابعة مصابي الشهر المرحّلين من الوقوعات اليومية")
    if not cases:
        st.info("لا توجد حالات مرحّلة لهذا الشهر بعد.")
    for c in cases:
        with st.expander(f"{c.get('name')} — حادث {c.get('incident_no')} — {c.get('hospital_status')}", expanded=False):
            st.write(
                f"المكان: {c.get('place')} ({c.get('place_type')}) | {c.get('gender')} | {c.get('nationality')} | {c.get('age_group')}"
            )
            new_status = st.selectbox(
                "تحديث الحالة",
                HOSPITAL_STATUS,
                index=HOSPITAL_STATUS.index(c.get("hospital_status")) if c.get("hospital_status") in HOSPITAL_STATUS else 0,
                key=f"st_{c['id']}",
            )
            if st.button("💾 حفظ الحالة", key=f"save_st_{c['id']}"):
                update_injured_status(c["id"], new_status)
                st.rerun()

    with st.expander("➕ إضافة حالة يدوية"):
        a, b = st.columns(2)
        with a:
            name = st.text_input("اسم المصاب", key=f"man_name_{month_key}")
            incident_no = st.text_input("رقم الحادث", key=f"man_inc_{month_key}")
            place = st.text_input("مكان الحادث التفصيلي", key=f"man_place_{month_key}")
            registry_no = st.text_input("رقم السجل", key=f"man_reg_{month_key}")
        with b:
            place_type = st.selectbox("تصنيف المكان", ["داخل المدينة", "خارج المدينة"], key=f"man_pt_{month_key}")
            gender = st.selectbox("الجنس", ["ذكر", "أنثى"], key=f"man_g_{month_key}")
            nationality = st.selectbox("الجنسية", ["سعودي", "غير سعودي"], key=f"man_n_{month_key}")
            age_group = st.selectbox("الفئة العمرية", AGE_BUCKETS, key=f"man_age_{month_key}")
            coverage = st.text_input("جهة التغطية", key=f"man_cov_{month_key}")
            hospital_status = st.selectbox("حالة التنويم", HOSPITAL_STATUS, index=1, key=f"man_hs_{month_key}")
        if st.button("حفظ الحالة اليدوية", type="primary"):
            add_injured_manual(month_key, {
                "name": name, "incident_no": incident_no, "place": place, "registry_no": registry_no,
                "place_type": place_type, "gender": gender, "nationality": nationality,
                "age_group": age_group, "coverage": coverage, "hospital_status": hospital_status,
                "accident_date": _today_ksa().isoformat(), "source_day": "manual",
            })
            st.rerun()

    stats = compute_monthly_stats(list_injured(month_key))
    meta = load_monthly_meta(month_key)
    mk = f"{month_key}_{stats.get('approved_count', 0)}"
    st.markdown("#### الإجماليات المحسوبة (+24 ساعة) — قابلة للتعديل")
    e1, e2, e3 = st.columns(3)
    with e1:
        stats["accidents_in"] = _num("حوادث داخل", f"m_acc_in_{mk}", meta.get("accidents_in", stats["accidents_in"]))
        stats["accidents_out"] = _num("حوادث خارج", f"m_acc_out_{mk}", meta.get("accidents_out", stats["accidents_out"]))
        stats["accidents_total"] = stats["accidents_in"] + stats["accidents_out"]
        st.info(f"مجموع الحوادث: {stats['accidents_total']}")
    with e2:
        stats["injured_in"] = _num("مصابون داخل", f"m_inj_in_{mk}", meta.get("injured_in", stats["injured_in"]))
        stats["injured_out"] = _num("مصابون خارج", f"m_inj_out_{mk}", meta.get("injured_out", stats["injured_out"]))
        stats["injured_total"] = stats["injured_in"] + stats["injured_out"]
        stats["male"] = _num("ذكور", f"m_male_{mk}", meta.get("male", stats["male"]))
        stats["female"] = _num("إناث", f"m_female_{mk}", meta.get("female", stats["female"]))
    with e3:
        stats["saudi"] = _num("سعودي", f"m_sa_{mk}", meta.get("saudi", stats["saudi"]))
        stats["nonsaudi"] = _num("غير سعودي", f"m_ns_{mk}", meta.get("nonsaudi", stats["nonsaudi"]))
        ages = dict(stats.get("ages") or {})
        for bucket in AGE_BUCKETS:
            ages[bucket] = _num(bucket, f"m_age_{bucket}_{mk}", meta.get("ages", {}).get(bucket, ages.get(bucket, 0)))
        stats["ages"] = ages

    prepared_by = st.text_input(
        "معد البيان",
        value=meta.get("prepared_by") or shift.get("officer_name") or "",
        key=f"prep_mon_{mk}",
    )
    phone = st.text_input("رقم الجوال", value=meta.get("phone") or "", key=f"phone_mon_{mk}")
    if st.button("💾 حفظ إجماليات الشهر", type="primary", use_container_width=True):
        save_monthly_meta(month_key, {**stats, "prepared_by": prepared_by, "phone": phone})
        _inject_local_backup_js(month_key, export_month_backup(month_key))
        st.success("تم حفظ إجماليات الشهر.")

    components.html(
        build_monthly_injured_a4(stats, AR_MONTHS[int(month)], int(year), prepared_by, phone, logo_b64),
        height=980,
        scrolling=True,
    )
    render_backup_controls(month_key)


def render_takmeel_form(fid: str, logo_b64: str, shift: dict | None = None) -> None:
    init_takmeel_db()
    shift = shift or {}
    if fid == "tak_daily_incidents":
        render_daily_incidents(logo_b64, shift)
    elif fid == "tak_accidents_daily":
        render_accidents_daily(logo_b64, shift)
    elif fid == "tak_violations_daily":
        render_violations_daily(logo_b64, shift)
    elif fid == "tak_injured_monthly":
        render_injured_monthly(logo_b64, shift)
    else:
        st.error("نموذج تكميل غير معروف.")
