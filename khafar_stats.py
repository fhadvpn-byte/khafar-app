# -*- coding: utf-8 -*-
"""منظومة الإحصائيات ومؤشرات الأداء الميداني — مستقلة عن محرك طباعة الوثائق."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

KSA_TZ = timezone(timedelta(hours=3))
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
# قاعدة مستقلة تماماً عن khafar_system.db لتفادي التعارض/القفل
_STATS_PRIMARY = os.path.join(_APP_DIR, "khafar_stats_independent.db")
_STATS_FALLBACK = os.path.join(
    os.environ.get("TMPDIR") or os.environ.get("TEMP") or "/tmp",
    "khafar_stats_independent.db",
)
_STATS_DB = _STATS_PRIMARY
_ADMIN_PIN = "2030"

_CAT_LABELS = {
    "إقرار": "الإقرارات الميدانية",
    "محضر": "المحاضر النظامية",
    "إحالة طبية": "الطبية والجنائية",
    "تكميل": "كشوف التكميل",
}
_CAT_ORDER = ["إقرار", "محضر", "إحالة طبية", "تكميل"]


def configure(db_path: str | None = None) -> None:
    """الإحصائيات تبقى على ملف مستقل — يُتجاهل مسار قاعدة التطبيق الرئيسية عمداً."""
    global _STATS_DB
    # لا نربط الإحصائيات بـ khafar_system.db حتى لا تتزاحم الكتابة
    if db_path and "khafar_stats" in str(db_path).replace("\\", "/"):
        _STATS_DB = str(db_path)
    else:
        _STATS_DB = _STATS_PRIMARY


def _clear_stats_sidecars(path: str) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        side = f"{path}{suffix}"
        try:
            if os.path.exists(side):
                os.remove(side)
        except Exception:
            pass


def _stats_connect(path: str | None = None) -> sqlite3.Connection:
    db = str(path or _STATS_DB)
    parent = os.path.dirname(db) or "."
    try:
        os.makedirs(parent, exist_ok=True)
    except Exception:
        pass
    conn = sqlite3.connect(db, timeout=30.0, check_same_thread=False)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    return conn


def _conn() -> sqlite3.Connection:
    init_stats_db()
    return _stats_connect(_STATS_DB)


def init_stats_db(db_path: str | None = None) -> None:
    """تهيئة جداول الإحصائيات مع درع استعادة — لا توقف التطبيق أبداً."""
    global _STATS_DB
    try:
        if db_path and "khafar_stats" in str(db_path).replace("\\", "/"):
            configure(db_path)
        targets = [_STATS_DB, _STATS_PRIMARY, _STATS_FALLBACK]
        last_err = None
        for target in targets:
            conn = None
            try:
                conn = _stats_connect(target)
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS khafar_visits (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        visited_at TEXT NOT NULL,
                        device_type TEXT NOT NULL,
                        user_agent TEXT,
                        session_token TEXT
                    );
                    CREATE TABLE IF NOT EXISTS khafar_doc_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        doc_no TEXT NOT NULL,
                        form_id TEXT,
                        form_title TEXT,
                        category TEXT,
                        officer_name TEXT,
                        created_at TEXT NOT NULL,
                        has_signature INTEGER DEFAULT 0,
                        has_stamp INTEGER DEFAULT 0,
                        has_gps INTEGER DEFAULT 0,
                        has_attachment INTEGER DEFAULT 0,
                        is_complete INTEGER DEFAULT 0,
                        UNIQUE(doc_no)
                    );
                    CREATE TABLE IF NOT EXISTS khafar_stats_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    );
                    """
                )
                conn.commit()
                _STATS_DB = target
                return
            except Exception as exc:
                last_err = exc
                _clear_stats_sidecars(target)
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
        if last_err:
            _STATS_DB = _STATS_FALLBACK
    except Exception:
        try:
            _STATS_DB = _STATS_FALLBACK
        except Exception:
            pass


def _now_ksa() -> datetime:
    return datetime.now(KSA_TZ)


def _fmt_dt(dt: datetime | None = None) -> str:
    d = dt or _now_ksa()
    return d.strftime("%Y/%m/%d - %H:%M:%S")


def _detect_device_type() -> str:
    ua = ""
    try:
        headers = getattr(getattr(st, "context", None), "headers", None)
        if headers:
            ua = str(headers.get("User-Agent") or headers.get("user-agent") or "")
    except Exception:
        ua = ""
    low = ua.lower()
    if any(x in low for x in ("android", "iphone", "ipad", "ipod", "mobile", "webos", "blackberry")):
        return "جوال ميداني (Android/iOS)"
    return "حاسب مكتبي (PC)"


def log_session_visit() -> None:
    """تسجيل دخول المتصفح مرة واحدة لكل جلسة Streamlit فعلية."""
    try:
        if st.session_state.get("_khafar_visit_counted"):
            return
        init_stats_db()
        device = _detect_device_type()
        ua = ""
        try:
            headers = getattr(getattr(st, "context", None), "headers", None)
            if headers:
                ua = str(headers.get("User-Agent") or "")[:400]
        except Exception:
            ua = ""
        token = str(st.session_state.get("_khafar_visit_token") or "")
        if not token:
            token = f"v-{_now_ksa().strftime('%Y%m%d%H%M%S')}-{os.getpid()}"
            st.session_state["_khafar_visit_token"] = token
        c = _conn()
        c.execute(
            "INSERT INTO khafar_visits (visited_at, device_type, user_agent, session_token) VALUES (?, ?, ?, ?)",
            (_fmt_dt(), device, ua, token),
        )
        c.commit()
        c.close()
        st.session_state["_khafar_visit_counted"] = True
    except Exception:
        try:
            st.session_state["_khafar_visit_counted"] = True
        except Exception:
            pass


def _truthy_b64(val: Any) -> bool:
    s = str(val or "").strip()
    return len(s) > 24


def _record_completeness(rec: dict) -> dict:
    fields = rec.get("fields") if isinstance(rec.get("fields"), dict) else {}
    sigs = {}
    raw_sigs = rec.get("signatures_json")
    if isinstance(raw_sigs, str) and raw_sigs.strip():
        try:
            parsed = json.loads(raw_sigs)
            if isinstance(parsed, dict):
                sigs = parsed
        except Exception:
            sigs = {}
    elif isinstance(raw_sigs, dict):
        sigs = raw_sigs
    live = rec.get("live_sig_pads") if isinstance(rec.get("live_sig_pads"), dict) else {}
    party = rec.get("party_stamps") if isinstance(rec.get("party_stamps"), dict) else {}
    if isinstance(fields.get("__live_sig_pads"), dict):
        live = {**fields.get("__live_sig_pads"), **live}
    if isinstance(fields.get("__party_stamps"), dict):
        party = {**fields.get("__party_stamps"), **party}

    has_signature = any(
        _truthy_b64(v)
        for v in (
            rec.get("citizen_stamp_b64"),
            rec.get("officer_stamp_b64"),
            rec.get("duty_stamp_b64"),
            *list(sigs.values()),
            *list(live.values()),
            *list(party.values()),
        )
    )
    auth = " ".join(
        str(x or "")
        for x in (
            rec.get("citizen_auth_mode"),
            rec.get("officer_auth_mode"),
            rec.get("duty_auth_mode"),
        )
    )
    has_stamp = has_signature or ("بصمة" in auth) or ("ختم" in auth) or ("توقيع" in auth)
    gps = str(rec.get("gps_coords") or fields.get("gps") or "").strip()
    has_gps = bool(gps) and ("بانتظار" not in gps) and gps not in ("—", "-", "N/A")
    att = rec.get("attachment_b64") or fields.get("attachment_b64") or ""
    has_attachment = False
    if isinstance(att, str) and att.strip():
        if att.strip().startswith("["):
            try:
                items = json.loads(att)
                has_attachment = isinstance(items, list) and len(items) > 0
            except Exception:
                has_attachment = len(att.strip()) > 40
        else:
            has_attachment = len(att.strip()) > 40
    is_complete = int(has_signature and has_stamp and has_gps and has_attachment)
    return {
        "has_signature": int(bool(has_signature)),
        "has_stamp": int(bool(has_stamp)),
        "has_gps": int(bool(has_gps)),
        "has_attachment": int(bool(has_attachment)),
        "is_complete": is_complete,
    }


def log_document_certified(rec: dict | None) -> bool:
    """تسجيل اعتماد وثيقة مع منع التكرار لنفس الرقم المرجعي."""
    if not isinstance(rec, dict):
        return False
    doc_no = str(rec.get("doc_no") or "").strip()
    if not doc_no:
        return False
    try:
        init_stats_db()
        flags = _record_completeness(rec)
        created = str(rec.get("created_at") or _fmt_dt()).strip() or _fmt_dt()
        officer = str(
            rec.get("officer_full")
            or rec.get("officer_name")
            or ""
        ).strip() or "—"
        c = _conn()
        c.execute(
            """
            INSERT INTO khafar_doc_events (
                doc_no, form_id, form_title, category, officer_name, created_at,
                has_signature, has_stamp, has_gps, has_attachment, is_complete
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(doc_no) DO UPDATE SET
                form_id=excluded.form_id,
                form_title=excluded.form_title,
                category=excluded.category,
                officer_name=excluded.officer_name,
                created_at=excluded.created_at,
                has_signature=excluded.has_signature,
                has_stamp=excluded.has_stamp,
                has_gps=excluded.has_gps,
                has_attachment=excluded.has_attachment,
                is_complete=excluded.is_complete
            """,
            (
                doc_no,
                str(rec.get("form_id") or ""),
                str(rec.get("form_title") or ""),
                str(rec.get("category") or ""),
                officer,
                created,
                flags["has_signature"],
                flags["has_stamp"],
                flags["has_gps"],
                flags["has_attachment"],
                flags["is_complete"],
            ),
        )
        c.commit()
        c.close()
        return True
    except Exception:
        return False


def _parse_created(text: str) -> datetime | None:
    s = str(text or "").strip()
    if not s:
        return None
    s = s.replace("T", " ").replace("،", "-")
    for fmt in (
        "%Y/%m/%d - %H:%M:%S",
        "%Y/%m/%d - %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ):
        try:
            dt = datetime.strptime(s[:19] if len(s) >= 16 else s, fmt)
            return dt.replace(tzinfo=KSA_TZ)
        except Exception:
            continue
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2}).*?(\d{1,2}):(\d{2})", s)
    if m:
        try:
            return datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)),
                int(m.group(4)), int(m.group(5)), tzinfo=KSA_TZ,
            )
        except Exception:
            return None
    return None


def _period_bounds(period: str) -> tuple[datetime | None, datetime | None]:
    now = _now_ksa()
    if period == "اليوم":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if period == "آخر 7 أيام":
        start = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if period == "هذا الشهر":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now
    return None, None


def _in_period(dt: datetime | None, start: datetime | None, end: datetime | None) -> bool:
    if start is None:
        return True
    if dt is None:
        return False
    if end is None:
        return dt >= start
    return start <= dt <= end


def _load_visits() -> list[dict]:
    try:
        c = _conn()
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT id, visited_at, device_type, user_agent, session_token FROM khafar_visits ORDER BY id DESC"
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _load_doc_events() -> list[dict]:
    try:
        c = _conn()
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """
            SELECT doc_no, form_id, form_title, category, officer_name, created_at,
                   has_signature, has_stamp, has_gps, has_attachment, is_complete
            FROM khafar_doc_events ORDER BY id DESC
            """
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _archive_as_events(archive_records: list | None) -> list[dict]:
    out = []
    for rec in archive_records or []:
        if not isinstance(rec, dict):
            continue
        doc_no = str(rec.get("doc_no") or "").strip()
        if not doc_no:
            continue
        flags = _record_completeness(rec)
        out.append(
            {
                "doc_no": doc_no,
                "form_id": str(rec.get("form_id") or ""),
                "form_title": str(rec.get("form_title") or ""),
                "category": str(rec.get("category") or ""),
                "officer_name": str(rec.get("officer_full") or rec.get("officer_name") or "—"),
                "created_at": str(rec.get("created_at") or ""),
                **flags,
                "_from_archive": True,
            }
        )
    return out


def _merge_docs(archive_records: list | None) -> list[dict]:
    """دمج أحداث الإحصائيات مع سجلات الأرشيف الحالية (الأرشيف يغلب عند التعارض)."""
    by_doc: dict[str, dict] = {}
    for ev in _load_doc_events():
        doc = str(ev.get("doc_no") or "").strip()
        if doc:
            by_doc[doc] = dict(ev)
    for ev in _archive_as_events(archive_records):
        doc = str(ev.get("doc_no") or "").strip()
        if doc:
            by_doc[doc] = dict(ev)
    docs = list(by_doc.values())
    docs.sort(key=lambda d: str(d.get("created_at") or ""), reverse=True)
    return docs


def _shift_bucket(dt: datetime | None) -> str:
    if dt is None:
        return "غير محدد"
    h = dt.hour
    if 6 <= h < 14:
        return "الفترة الصباحية (06:00 - 14:00)"
    if 14 <= h < 22:
        return "الفترة المسائية (14:00 - 22:00)"
    return "الفترة الليلية (22:00 - 06:00)"


def _pct(n: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * n / total, 1)


def _export_csv(visits: list[dict], docs: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["=== زيارات التطبيق ==="])
    w.writerow(["الوقت", "نوع الجهاز", "رمز الجلسة"])
    for v in visits:
        w.writerow([v.get("visited_at"), v.get("device_type"), v.get("session_token")])
    w.writerow([])
    w.writerow(["=== الوثائق المعتمدة ==="])
    w.writerow(
        [
            "الرقم المرجعي",
            "النموذج",
            "القسم",
            "مستلم الخفر",
            "الوقت",
            "توقيع",
            "بصمة/ختم",
            "GPS",
            "مرفق",
            "مكتمل",
        ]
    )
    for d in docs:
        w.writerow(
            [
                d.get("doc_no"),
                d.get("form_title"),
                _CAT_LABELS.get(str(d.get("category") or ""), d.get("category")),
                d.get("officer_name"),
                d.get("created_at"),
                d.get("has_signature"),
                d.get("has_stamp"),
                d.get("has_gps"),
                d.get("has_attachment"),
                d.get("is_complete"),
            ]
        )
    return buf.getvalue().encode("utf-8-sig")


def _backup_json(visits: list[dict], docs: list[dict]) -> bytes:
    payload = {
        "exported_at": _fmt_dt(),
        "visits": visits,
        "doc_events": docs,
        "meta": _load_meta(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _load_meta() -> dict:
    try:
        c = _conn()
        rows = c.execute("SELECT key, value FROM khafar_stats_meta").fetchall()
        c.close()
        return {str(k): str(v) for k, v in rows}
    except Exception:
        return {}


def _set_meta(key: str, value: str) -> None:
    c = _conn()
    c.execute(
        "INSERT INTO khafar_stats_meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    c.commit()
    c.close()


def restore_stats_backup(raw: bytes | str) -> tuple[bool, str]:
    try:
        data = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
    except Exception:
        return False, "ملف JSON غير صالح."
    if not isinstance(data, dict):
        return False, "صيغة النسخة الاحتياطية غير معروفة."
    try:
        init_stats_db()
        c = _conn()
        visits = data.get("visits") or []
        docs = data.get("doc_events") or data.get("docs") or []
        if isinstance(visits, list):
            for v in visits:
                if not isinstance(v, dict):
                    continue
                c.execute(
                    """
                    INSERT INTO khafar_visits (visited_at, device_type, user_agent, session_token)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        str(v.get("visited_at") or _fmt_dt()),
                        str(v.get("device_type") or "حاسب مكتبي (PC)"),
                        str(v.get("user_agent") or ""),
                        str(v.get("session_token") or ""),
                    ),
                )
        if isinstance(docs, list):
            for d in docs:
                if not isinstance(d, dict):
                    continue
                doc_no = str(d.get("doc_no") or "").strip()
                if not doc_no:
                    continue
                c.execute(
                    """
                    INSERT INTO khafar_doc_events (
                        doc_no, form_id, form_title, category, officer_name, created_at,
                        has_signature, has_stamp, has_gps, has_attachment, is_complete
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(doc_no) DO UPDATE SET
                        form_id=excluded.form_id,
                        form_title=excluded.form_title,
                        category=excluded.category,
                        officer_name=excluded.officer_name,
                        created_at=excluded.created_at,
                        has_signature=excluded.has_signature,
                        has_stamp=excluded.has_stamp,
                        has_gps=excluded.has_gps,
                        has_attachment=excluded.has_attachment,
                        is_complete=excluded.is_complete
                    """,
                    (
                        doc_no,
                        str(d.get("form_id") or ""),
                        str(d.get("form_title") or ""),
                        str(d.get("category") or ""),
                        str(d.get("officer_name") or "—"),
                        str(d.get("created_at") or _fmt_dt()),
                        int(d.get("has_signature") or 0),
                        int(d.get("has_stamp") or 0),
                        int(d.get("has_gps") or 0),
                        int(d.get("has_attachment") or 0),
                        int(d.get("is_complete") or 0),
                    ),
                )
        meta = data.get("meta") or {}
        if isinstance(meta, dict):
            for k, v in meta.items():
                c.execute(
                    "INSERT INTO khafar_stats_meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(k), str(v)),
                )
        c.commit()
        c.close()
        return True, "تمت استعادة النسخة الاحتياطية بنجاح."
    except Exception as exc:
        return False, f"تعذرت الاستعادة: {exc}"


def reset_visits_counter(pin: str) -> tuple[bool, str]:
    if str(pin or "").strip() != _ADMIN_PIN:
        return False, "الرمز السري غير صحيح."
    try:
        c = _conn()
        c.execute("DELETE FROM khafar_visits")
        c.execute(
            "INSERT INTO khafar_stats_meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("visits_reset_at", _fmt_dt()),
        )
        c.commit()
        c.close()
        return True, "تم تصفير عداد الزيارات."
    except Exception as exc:
        return False, f"تعذر التصفير: {exc}"


def _build_stats_print_html(
    *,
    period: str,
    officer_name: str,
    kpis: dict,
    cat_rows: list[tuple],
    top_forms: list[tuple],
    officer_rows: list[dict],
    shifts: list[tuple],
) -> str:
    now = _fmt_dt()
    cat_trs = "".join(
        f"<tr><td>{html_escape(lab)}</td><td>{n}</td><td>{p}%</td></tr>"
        for lab, n, p in cat_rows
    )
    form_trs = "".join(
        f"<tr><td>{html_escape(t)}</td><td>{n}</td></tr>" for t, n in top_forms
    ) or "<tr><td colspan='2'>لا توجد بيانات</td></tr>"
    off_trs = "".join(
        "<tr>"
        f"<td>{html_escape(r['name'])}</td>"
        f"<td>{r['total']}</td><td>{r['decl']}</td><td>{r['min']}</td><td>{r['med']}</td>"
        f"<td>{html_escape(r['last'])}</td>"
        "</tr>"
        for r in officer_rows
    ) or "<tr><td colspan='6'>لا توجد بيانات</td></tr>"
    shift_trs = "".join(
        f"<tr><td>{html_escape(lab)}</td><td>{n}</td><td>{'ذروة' if peak else ''}</td></tr>"
        for lab, n, peak in shifts
    )
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8" />
<title>بيان إحصائي بأعمال مناوبة الخفر</title>
<style>
@page {{ size: A4 portrait; margin: 12mm; }}
html, body {{
  margin: 0; padding: 0; background: #ffffff; color: #000000;
  font-family: Tahoma, Arial, sans-serif; direction: rtl; text-align: right;
}}
.sheet {{ width: 100%; max-width: 190mm; margin: 0 auto; padding: 8px 4px; }}
.header {{ text-align: center; border-bottom: 2px solid #000; padding-bottom: 8px; margin-bottom: 12px; }}
.header h1 {{ font-size: 16px; margin: 2px 0; }}
.header h2 {{ font-size: 14px; margin: 2px 0; font-weight: 700; }}
.header p {{ font-size: 12px; margin: 2px 0; }}
.meta {{ font-size: 12px; margin: 8px 0 12px; }}
table {{ width: 100%; border-collapse: collapse; margin: 8px 0 14px; font-size: 11.5px; }}
th, td {{ border: 1px solid #111; padding: 5px 6px; }}
th {{ background: #f3f4f6; }}
.kpi {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px; }}
.kpi div {{ border: 1px solid #333; padding: 8px; border-radius: 4px; }}
.kpi b {{ display: block; font-size: 18px; margin-top: 4px; }}
.actions {{ text-align: center; margin: 10px 0 14px; }}
.actions button {{
  background: #0E2920; color: #fff; border: 1px solid #D4AF37;
  padding: 10px 18px; font-weight: 800; border-radius: 8px; cursor: pointer; margin: 0 4px;
}}
@media print {{ .actions {{ display: none !important; }} }}
h3 {{ font-size: 13px; margin: 14px 0 6px; border-right: 3px solid #D4AF37; padding-right: 6px; }}
</style>
</head>
<body>
<div class="sheet" id="khafarStatsPrintSheet">
  <div class="actions">
    <button type="button" onclick="window.print()">🖨️ طباعة التقرير</button>
    <button type="button" onclick="window.close()">إغلاق</button>
  </div>
  <div class="header">
    <h1>المملكة العربية السعودية</h1>
    <h2>وزارة الداخلية — الأمن العام</h2>
    <h2>مرور منطقة جازان — قسم مرور العارضة</h2>
    <p>بيان إحصائي بأعمال مناوبة الخفر والوثائق المعتمدة</p>
  </div>
  <div class="meta">
    <div>الفترة: <b>{html_escape(period)}</b></div>
    <div>مستلم الخفر الحالي: <b>{html_escape(officer_name or "—")}</b></div>
    <div>تاريخ الإصدار: <b>{html_escape(now)}</b></div>
  </div>
  <div class="kpi">
    <div>إجمالي الدخول<div><b>{kpis['visits_total']}</b></div></div>
    <div>دخول اليوم<div><b>{kpis['visits_today']}</b></div></div>
    <div>الوثائق المعتمدة<div><b>{kpis['docs_total']}</b></div></div>
    <div>اكتمال التوثيق<div><b>{kpis['quality_pct']}%</b></div></div>
  </div>
  <h3>توزيع الأقسام</h3>
  <table><thead><tr><th>القسم</th><th>العدد</th><th>النسبة</th></tr></thead><tbody>{cat_trs}</tbody></table>
  <h3>أكثر النماذج إصداراً</h3>
  <table><thead><tr><th>النموذج</th><th>العدد</th></tr></thead><tbody>{form_trs}</tbody></table>
  <h3>سجل إنجاز مستلمي الخفر</h3>
  <table>
    <thead><tr><th>مستلم الخفر</th><th>الإجمالي</th><th>إقرارات</th><th>محاضر</th><th>طبية</th><th>آخر وثيقة</th></tr></thead>
    <tbody>{off_trs}</tbody>
  </table>
  <h3>توزيع أوقات الذروة</h3>
  <table><thead><tr><th>الفترة</th><th>العدد</th><th>ملاحظة</th></tr></thead><tbody>{shift_trs}</tbody></table>
</div>
<script>
(function(){{
  try {{
    var btn = document.querySelector('.actions button');
    if (btn) {{ /* ready */ }}
  }} catch (e) {{}}
}})();
</script>
</body>
</html>"""


def html_escape(text: Any) -> str:
    s = str(text or "")
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_stats_dashboard(archive_records: list | None = None, current_officer_name: str = "") -> None:
    """لوحة قيادة الإحصائيات الميدانية."""
    init_stats_db()
    st.markdown(
        '<div class="sec-heading-green"><span style="font-size:18px;font-weight:800;color:#ffffff;">📊 الإحصائيات ومؤشرات الأداء الميداني</span></div>',
        unsafe_allow_html=True,
    )

    period = st.radio(
        "الفترة الزمنية",
        options=["الكل", "اليوم", "آخر 7 أيام", "هذا الشهر"],
        horizontal=True,
        key="khafar_stats_period",
        label_visibility="collapsed",
    )
    start, end = _period_bounds(period)

    all_visits = _load_visits()
    all_docs = _merge_docs(archive_records)

    visits = []
    for v in all_visits:
        dt = _parse_created(v.get("visited_at") or "")
        if _in_period(dt, start, end):
            visits.append(v)
    docs = []
    for d in all_docs:
        dt = _parse_created(d.get("created_at") or "")
        if _in_period(dt, start, end):
            docs.append(d)

    today_start, _ = _period_bounds("اليوم")
    month_start, _ = _period_bounds("هذا الشهر")
    visits_today = sum(
        1 for v in all_visits if _in_period(_parse_created(v.get("visited_at") or ""), today_start, None)
    )
    docs_month = sum(
        1 for d in all_docs if _in_period(_parse_created(d.get("created_at") or ""), month_start, None)
    )

    mobile_n = sum(1 for v in visits if "جوال" in str(v.get("device_type") or ""))
    pc_n = len(visits) - mobile_n
    complete_n = sum(1 for d in docs if int(d.get("is_complete") or 0) == 1)
    quality_pct = _pct(complete_n, len(docs))

    # KPI cards
    st.markdown(
        (
            '<div class="khafar-stats-kpi-grid">'
            f'<div class="khafar-stats-kpi"><div class="k-label">👁️ إجمالي الدخول للتطبيق</div><div class="k-val">{len(visits)}</div><div class="k-sub">اليوم: {visits_today}</div></div>'
            f'<div class="khafar-stats-kpi"><div class="k-label">📜 الوثائق الموثقة والمعتمدة</div><div class="k-val">{len(docs)}</div><div class="k-sub">هذا الشهر: {docs_month}</div></div>'
            f'<div class="khafar-stats-kpi"><div class="k-label">📱 الاستخدام الميداني مقابل المكتبي</div><div class="k-val">{_pct(mobile_n, len(visits))}%</div><div class="k-sub">جوال {mobile_n} · حاسب {pc_n}</div></div>'
            f'<div class="khafar-stats-kpi"><div class="k-label">🛡️ مؤشر جودة واكتمال التوثيق</div><div class="k-val">{quality_pct}%</div><div class="k-sub">مكتمل {complete_n} من {len(docs)}</div></div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    # Category distribution
    cat_counts = Counter(str(d.get("category") or "أخرى") for d in docs)
    cat_rows = []
    bars_html = ['<div class="khafar-stats-card"><div class="khafar-stats-title">توزيع الوثائق حسب الأقسام</div>']
    for cat in _CAT_ORDER:
        n = int(cat_counts.get(cat, 0))
        p = _pct(n, len(docs))
        lab = _CAT_LABELS.get(cat, cat)
        cat_rows.append((lab, n, p))
        bars_html.append(
            f'<div class="khafar-stats-bar-row"><div class="khafar-stats-bar-lab">{html_escape(lab)}'
            f'<span>{n} ({p}%)</span></div>'
            f'<div class="khafar-stats-bar-track"><div class="khafar-stats-bar-fill" style="width:{p}%;"></div></div></div>'
        )
    other_n = sum(v for k, v in cat_counts.items() if k not in _CAT_ORDER)
    if other_n:
        p = _pct(other_n, len(docs))
        cat_rows.append(("أخرى", other_n, p))
        bars_html.append(
            f'<div class="khafar-stats-bar-row"><div class="khafar-stats-bar-lab">أخرى<span>{other_n} ({p}%)</span></div>'
            f'<div class="khafar-stats-bar-track"><div class="khafar-stats-bar-fill" style="width:{p}%;"></div></div></div>'
        )
    form_counts = Counter(str(d.get("form_title") or d.get("form_id") or "—") for d in docs)
    top_forms = form_counts.most_common(5)
    bars_html.append('<div class="khafar-stats-subtitle">أكثر 5 نماذج إصداراً</div><ul class="khafar-stats-top">')
    if top_forms:
        for title, n in top_forms:
            bars_html.append(f"<li><span>{html_escape(title)}</span><b>{n}</b></li>")
    else:
        bars_html.append("<li><span>لا توجد وثائق في هذه الفترة</span><b>0</b></li>")
    bars_html.append("</ul></div>")
    st.markdown("".join(bars_html), unsafe_allow_html=True)

    # Officer leaderboard
    by_officer: dict[str, dict] = {}
    for d in docs:
        name = str(d.get("officer_name") or "—").strip() or "—"
        row = by_officer.setdefault(
            name,
            {"name": name, "total": 0, "decl": 0, "min": 0, "med": 0, "last": "", "last_dt": None},
        )
        row["total"] += 1
        cat = str(d.get("category") or "")
        if cat == "إقرار":
            row["decl"] += 1
        elif cat == "محضر":
            row["min"] += 1
        elif cat == "إحالة طبية":
            row["med"] += 1
        dt = _parse_created(d.get("created_at") or "")
        if dt and (row["last_dt"] is None or dt > row["last_dt"]):
            row["last_dt"] = dt
            row["last"] = str(d.get("created_at") or "")
    officer_rows = sorted(by_officer.values(), key=lambda r: r["total"], reverse=True)
    st.markdown(
        '<div class="khafar-stats-card"><div class="khafar-stats-title">سجل إنجاز مستلمي الخفر المناوبين</div></div>',
        unsafe_allow_html=True,
    )
    if officer_rows:
        table_data = [
            {
                "مستلم الخفر المناوب": r["name"],
                "عدد الوثائق": r["total"],
                "الإقرارات": r["decl"],
                "المحاضر": r["min"],
                "الطبية والجنائية": r["med"],
                "آخر وثيقة معتمدة": r["last"] or "—",
            }
            for r in officer_rows
        ]
        st.dataframe(table_data, use_container_width=True, hide_index=True)
    else:
        st.info("لا يوجد إنجاز مسجّل لمستلمي الخفر في هذه الفترة.")

    # Peak shifts
    shift_counter = Counter()
    for d in docs:
        shift_counter[_shift_bucket(_parse_created(d.get("created_at") or ""))] += 1
    shift_labels = [
        "الفترة الصباحية (06:00 - 14:00)",
        "الفترة المسائية (14:00 - 22:00)",
        "الفترة الليلية (22:00 - 06:00)",
    ]
    peak_lab = None
    if any(shift_counter[s] for s in shift_labels):
        peak_lab = max(shift_labels, key=lambda s: shift_counter[s])
    shift_rows = [(lab, int(shift_counter.get(lab, 0)), lab == peak_lab) for lab in shift_labels]
    peak_html = ['<div class="khafar-stats-card"><div class="khafar-stats-title">توزيع أوقات الذروة الميدانية (المناوبات)</div>']
    for lab, n, is_peak in shift_rows:
        p = _pct(n, len(docs))
        badge = '<span class="khafar-stats-peak">ذروة</span>' if is_peak and n else ""
        peak_html.append(
            f'<div class="khafar-stats-bar-row"><div class="khafar-stats-bar-lab">{html_escape(lab)} {badge}'
            f'<span>{n} ({p}%)</span></div>'
            f'<div class="khafar-stats-bar-track"><div class="khafar-stats-bar-fill alt" style="width:{p}%;"></div></div></div>'
        )
    peak_html.append("</div>")
    st.markdown("".join(peak_html), unsafe_allow_html=True)

    # Tools
    st.markdown(
        '<div class="khafar-stats-card"><div class="khafar-stats-title">التقرير الرسمي والنسخ الاحتياطي</div></div>',
        unsafe_allow_html=True,
    )
    t1, t2 = st.columns(2)
    kpis = {
        "visits_total": len(visits),
        "visits_today": visits_today,
        "docs_total": len(docs),
        "quality_pct": quality_pct,
    }
    with t1:
        if st.button("🖨️ طباعة التقرير الإحصائي الرسمي A4", use_container_width=True, key="stats_print_btn"):
            print_html = _build_stats_print_html(
                period=period,
                officer_name=current_officer_name,
                kpis=kpis,
                cat_rows=cat_rows,
                top_forms=top_forms,
                officer_rows=officer_rows,
                shifts=shift_rows,
            )
            st.session_state["_khafar_stats_print_html"] = print_html
        if st.session_state.get("_khafar_stats_print_html"):
            components.html(
                st.session_state.get("_khafar_stats_print_html") or "",
                height=820,
                scrolling=True,
            )
    with t2:
        csv_bytes = _export_csv(visits, docs)
        st.download_button(
            "📥 تصدير الإحصائيات والسجل (Excel CSV)",
            data=csv_bytes,
            file_name=f"khafar_stats_{_now_ksa().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True,
            key="stats_csv_dl",
        )

    with st.expander("🔐 النسخ الاحتياطي وإدارة العدادات - للمشرف"):
        b1, b2 = st.columns(2)
        with b1:
            st.download_button(
                "⬇️ تنزيل نسخة JSON للإحصائيات",
                data=_backup_json(all_visits, all_docs),
                file_name=f"khafar_stats_backup_{_now_ksa().strftime('%Y%m%d_%H%M')}.json",
                mime="application/json",
                use_container_width=True,
                key="stats_json_dl",
            )
        with b2:
            up = st.file_uploader("استعادة نسخة JSON", type=["json"], key="stats_json_up")
            if up is not None and st.button("♻️ استعادة النسخة", use_container_width=True, key="stats_json_restore"):
                ok, msg = restore_stats_backup(up.getvalue())
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        pin = st.text_input("رمز المشرف لتصفير عداد الزيارات", type="password", key="stats_reset_pin")
        if st.button("🧹 تصفير عداد الزيارات", use_container_width=True, key="stats_reset_visits"):
            ok, msg = reset_visits_counter(pin)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    st.caption(f"مستلم الخفر الحالي: {current_officer_name or '—'} · الفترة المعروضة: {period}")
