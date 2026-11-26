# -*- coding: utf-8 -*-
"""الخزنة السحابية الدائمة — مزامنة الأرشيف/الإحصائيات/التواقيع عبر GitHub الخاص."""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    import streamlit as st
except Exception:  # pragma: no cover
    st = None  # type: ignore

KSA_TZ = timezone(timedelta(hours=3))
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_VAULT_FILE = "khafar_vault_state.json"
_VISIT_BACKUP_MIN_SECONDS = 300
_backup_lock = threading.Lock()
_last_visit_backup_ts = 0.0
_last_backup_status = {"ok": None, "at": "", "msg": ""}


def get_unified_db_path() -> str:
    """مسار القاعدة الموحدة: /tmp على لينكس/السحابة، ومسار ثابت محلي على ويندوز."""
    if os.name == "nt":
        return os.path.join(_APP_DIR, "khafar_unified.db")
    return "/tmp/khafar_unified.db"


def _legacy_db_candidates() -> list[str]:
    return [
        os.path.join(_APP_DIR, "khafar_system.db"),
        os.path.join(_APP_DIR, "khafar_stats_independent.db"),
        os.path.join(tempfile.gettempdir(), "khafar_system_writable.db"),
        os.path.join(tempfile.gettempdir(), "khafar_stats_independent.db"),
        os.path.join(tempfile.gettempdir(), "khafar_unified.db"),
    ]


def _now_label() -> str:
    return datetime.now(KSA_TZ).strftime("%Y/%m/%d - %H:%M:%S")


def get_vault_config() -> dict:
    """قراءة إعدادات الخزنة من Secrets أو البيئة دون إيقاف التطبيق."""
    token = ""
    repo = ""
    try:
        if st is not None:
            try:
                secrets = st.secrets
                token = str(secrets.get("GITHUB_VAULT_TOKEN", "") or "").strip()
                repo = str(secrets.get("GITHUB_VAULT_REPO", "") or "").strip()
            except Exception:
                token, repo = "", ""
    except Exception:
        token, repo = "", ""
    if not token:
        token = str(os.environ.get("GITHUB_VAULT_TOKEN", "") or "").strip()
    if not repo:
        repo = str(os.environ.get("GITHUB_VAULT_REPO", "") or "").strip()
    # تنظيف صيغ مثل OWNER/REPO.git
    repo = repo.replace("https://github.com/", "").replace(".git", "").strip("/")
    return {
        "token": token,
        "repo": repo,
        "configured": bool(token and repo and "/" in repo),
    }


def is_vault_configured() -> bool:
    return bool(get_vault_config().get("configured"))


def db_connect(db_path: str | None = None) -> sqlite3.Connection:
    path = str(db_path or get_unified_db_path())
    parent = os.path.dirname(path) or "."
    try:
        os.makedirs(parent, exist_ok=True)
    except Exception:
        pass
    conn = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return bool(row)


def _ensure_core_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS shift_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            dept_name TEXT,
            officer_rank TEXT,
            officer_name TEXT,
            duty_rank TEXT,
            duty_name TEXT,
            default_gps TEXT
        );
        CREATE TABLE IF NOT EXISTS device_shifts (
            device_hash TEXT PRIMARY KEY,
            dept_name TEXT,
            officer_rank TEXT,
            officer_name TEXT,
            duty_rank TEXT,
            duty_name TEXT,
            default_gps TEXT,
            duty_sig_b64 TEXT
        );
        CREATE TABLE IF NOT EXISTS manager_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            manager_name TEXT,
            manager_title TEXT,
            manager_sig_b64 TEXT,
            auto_insert INTEGER DEFAULT 1,
            updated_at TEXT
        );
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
            duty_stamp_b64 TEXT,
            receiver_name TEXT,
            receiver_role TEXT,
            device_hash TEXT,
            signatures_json TEXT,
            archived_html TEXT
        );
        CREATE TABLE IF NOT EXISTS khafar_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visited_at TEXT NOT NULL,
            device_type TEXT NOT NULL,
            user_agent TEXT,
            session_token TEXT
        );
        CREATE TABLE IF NOT EXISTS khafar_doc_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_no TEXT NOT NULL UNIQUE,
            form_id TEXT,
            form_title TEXT,
            category TEXT,
            officer_name TEXT,
            created_at TEXT NOT NULL,
            has_signature INTEGER DEFAULT 0,
            has_stamp INTEGER DEFAULT 0,
            has_gps INTEGER DEFAULT 0,
            has_attachment INTEGER DEFAULT 0,
            is_complete INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS khafar_stats_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    conn.commit()


def merge_legacy_databases_into(unified_path: str) -> None:
    """دمج أي قواعد قديمة محلية في الملف الموحد إن كان فارغاً أو ناقصاً."""
    conn = None
    try:
        conn = db_connect(unified_path)
        _ensure_core_tables(conn)
        rec_n = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        visit_n = conn.execute("SELECT COUNT(*) FROM khafar_visits").fetchone()[0]
        need_records = int(rec_n or 0) == 0
        need_visits = int(visit_n or 0) == 0
        if not need_records and not need_visits:
            # قد نحتاج device_shifts فقط
            ds_n = conn.execute("SELECT COUNT(*) FROM device_shifts").fetchone()[0]
            if int(ds_n or 0) > 0:
                return
        for legacy in _legacy_db_candidates():
            if not legacy or not os.path.exists(legacy):
                continue
            if os.path.abspath(legacy) == os.path.abspath(unified_path):
                continue
            try:
                conn.execute("ATTACH DATABASE ? AS legacy", (legacy,))
                if need_records and _table_exists(conn, "legacy.records"):
                    cols = [r[1] for r in conn.execute("PRAGMA legacy.table_info(records)").fetchall()]
                    if cols:
                        col_csv = ", ".join(cols)
                        conn.execute(
                            f"INSERT OR IGNORE INTO records ({col_csv}) SELECT {col_csv} FROM legacy.records"
                        )
                if _table_exists(conn, "legacy.device_shifts"):
                    cols = [r[1] for r in conn.execute("PRAGMA legacy.table_info(device_shifts)").fetchall()]
                    if cols:
                        col_csv = ", ".join(cols)
                        conn.execute(
                            f"INSERT OR IGNORE INTO device_shifts ({col_csv}) SELECT {col_csv} FROM legacy.device_shifts"
                        )
                if _table_exists(conn, "legacy.shift_settings"):
                    cols = [r[1] for r in conn.execute("PRAGMA legacy.table_info(shift_settings)").fetchall()]
                    if cols and conn.execute("SELECT COUNT(*) FROM shift_settings").fetchone()[0] == 0:
                        col_csv = ", ".join(cols)
                        conn.execute(
                            f"INSERT OR IGNORE INTO shift_settings ({col_csv}) SELECT {col_csv} FROM legacy.shift_settings"
                        )
                if _table_exists(conn, "legacy.manager_settings"):
                    cols = [r[1] for r in conn.execute("PRAGMA legacy.table_info(manager_settings)").fetchall()]
                    if cols and conn.execute("SELECT COUNT(*) FROM manager_settings").fetchone()[0] == 0:
                        col_csv = ", ".join(cols)
                        conn.execute(
                            f"INSERT OR IGNORE INTO manager_settings ({col_csv}) SELECT {col_csv} FROM legacy.manager_settings"
                        )
                if need_visits and _table_exists(conn, "legacy.khafar_visits"):
                    cols = [r[1] for r in conn.execute("PRAGMA legacy.table_info(khafar_visits)").fetchall()]
                    if cols:
                        col_csv = ", ".join(cols)
                        conn.execute(
                            f"INSERT OR IGNORE INTO khafar_visits ({col_csv}) SELECT {col_csv} FROM legacy.khafar_visits"
                        )
                if _table_exists(conn, "legacy.khafar_doc_events"):
                    cols = [r[1] for r in conn.execute("PRAGMA legacy.table_info(khafar_doc_events)").fetchall()]
                    if cols:
                        col_csv = ", ".join(cols)
                        conn.execute(
                            f"INSERT OR IGNORE INTO khafar_doc_events ({col_csv}) SELECT {col_csv} FROM legacy.khafar_doc_events"
                        )
                if _table_exists(conn, "legacy.khafar_stats_meta"):
                    cols = [r[1] for r in conn.execute("PRAGMA legacy.table_info(khafar_stats_meta)").fetchall()]
                    if cols:
                        col_csv = ", ".join(cols)
                        conn.execute(
                            f"INSERT OR IGNORE INTO khafar_stats_meta ({col_csv}) SELECT {col_csv} FROM legacy.khafar_stats_meta"
                        )
                conn.commit()
                conn.execute("DETACH DATABASE legacy")
            except Exception:
                try:
                    conn.execute("DETACH DATABASE legacy")
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _dump_table(conn: sqlite3.Connection, table: str) -> list[dict]:
    if not _table_exists(conn, table):
        return []
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    return [dict(r) for r in rows]


def export_vault_state(db_path: str | None = None) -> dict:
    path = str(db_path or get_unified_db_path())
    conn = None
    try:
        conn = db_connect(path)
        _ensure_core_tables(conn)
        return {
            "version": 1,
            "exported_at": _now_label(),
            "archive": _dump_table(conn, "records"),
            "shift_settings": _dump_table(conn, "shift_settings"),
            "device_shifts": _dump_table(conn, "device_shifts"),
            "manager_settings": _dump_table(conn, "manager_settings"),
            "khafar_visits": _dump_table(conn, "khafar_visits"),
            "khafar_doc_events": _dump_table(conn, "khafar_doc_events"),
            "khafar_stats_meta": _dump_table(conn, "khafar_stats_meta"),
        }
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _upsert_rows(conn: sqlite3.Connection, table: str, rows: list[dict], pk: str | None = None) -> None:
    if not rows:
        return
    _ensure_core_tables(conn)
    existing_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for row in rows:
        if not isinstance(row, dict):
            continue
        data = {k: v for k, v in row.items() if k in existing_cols}
        if not data:
            continue
        cols = list(data.keys())
        placeholders = ", ".join(["?"] * len(cols))
        col_csv = ", ".join(cols)
        if pk and pk in data:
            # REPLACE يحافظ على المفتاح الأساسي
            conn.execute(
                f"INSERT OR REPLACE INTO {table} ({col_csv}) VALUES ({placeholders})",
                [data[c] for c in cols],
            )
        else:
            conn.execute(
                f"INSERT OR IGNORE INTO {table} ({col_csv}) VALUES ({placeholders})",
                [data[c] for c in cols],
            )


def import_vault_state(payload: dict, db_path: str | None = None) -> bool:
    if not isinstance(payload, dict):
        return False
    path = str(db_path or get_unified_db_path())
    conn = None
    try:
        conn = db_connect(path)
        _ensure_core_tables(conn)
        _upsert_rows(conn, "records", payload.get("archive") or [], pk="id")
        _upsert_rows(conn, "shift_settings", payload.get("shift_settings") or [], pk="id")
        _upsert_rows(conn, "device_shifts", payload.get("device_shifts") or [], pk="device_hash")
        _upsert_rows(conn, "manager_settings", payload.get("manager_settings") or [], pk="id")
        _upsert_rows(conn, "khafar_visits", payload.get("khafar_visits") or [], pk="id")
        _upsert_rows(conn, "khafar_doc_events", payload.get("khafar_doc_events") or [], pk="doc_no")
        _upsert_rows(conn, "khafar_stats_meta", payload.get("khafar_stats_meta") or [], pk="key")
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _github_api(method: str, url: str, token: str, body: dict | None = None) -> tuple[int, Any]:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "khafar-cloud-vault",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
            return int(resp.status), payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        try:
            payload = json.loads(raw) if raw else {"message": str(exc)}
        except Exception:
            payload = {"message": raw or str(exc)}
        return int(exc.code), payload
    except Exception as exc:
        return 0, {"message": str(exc)}


def _fetch_vault_file(cfg: dict) -> tuple[dict | None, str | None]:
    repo = cfg["repo"]
    token = cfg["token"]
    url = f"https://api.github.com/repos/{repo}/contents/{_VAULT_FILE}"
    code, payload = _github_api("GET", url, token)
    if code == 404:
        return None, None
    if code != 200 or not isinstance(payload, dict):
        return None, None
    content_b64 = str(payload.get("content") or "").replace("\n", "")
    sha = str(payload.get("sha") or "") or None
    if not content_b64:
        return None, sha
    try:
        raw = base64.b64decode(content_b64).decode("utf-8")
        data = json.loads(raw)
        return (data if isinstance(data) else None), sha
    except Exception:
        return None, sha


def _local_is_empty(db_path: str) -> bool:
    conn = None
    try:
        if not os.path.exists(db_path):
            return True
        conn = db_connect(db_path)
        _ensure_core_tables(conn)
        rec_n = int(conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] or 0)
        visit_n = int(conn.execute("SELECT COUNT(*) FROM khafar_visits").fetchone()[0] or 0)
        ds_n = int(conn.execute("SELECT COUNT(*) FROM device_shifts").fetchone()[0] or 0)
        return (rec_n + visit_n + ds_n) == 0
    except Exception:
        return True
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def restore_vault_if_needed(db_path: str | None = None) -> dict:
    """استرجاع حالة الخزنة مرة واحدة عند إقلاع الحاوية إن كانت الجداول فارغة."""
    path = str(db_path or get_unified_db_path())
    result = {"restored": False, "reason": "", "configured": False}
    try:
        merge_legacy_databases_into(path)
        cfg = get_vault_config()
        result["configured"] = bool(cfg.get("configured"))
        if not cfg.get("configured"):
            result["reason"] = "لم تُضبط مفاتيح الخزنة بعد"
            return result
        if not _local_is_empty(path):
            result["reason"] = "البيانات المحلية موجودة — تم تخطي الاسترجاع"
            return result
        data, _sha = _fetch_vault_file(cfg)
        if not data:
            result["reason"] = "لا توجد نسخة سحابية بعد"
            return result
        ok = import_vault_state(data, path)
        result["restored"] = bool(ok)
        result["reason"] = "تم الاسترجاع السحابي" if ok else "تعذّر الاسترجاع السحابي"
        return result
    except Exception as exc:
        result["reason"] = f"خطأ أثناء الاسترجاع: {exc}"
        return result


def _upload_vault_state(cfg: dict, state: dict, sha: str | None = None) -> tuple[bool, str]:
    repo = cfg["repo"]
    token = cfg["token"]
    url = f"https://api.github.com/repos/{repo}/contents/{_VAULT_FILE}"
    content_b64 = base64.b64encode(
        json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("ascii")
    body = {
        "message": f"vault backup {_now_label()}",
        "content": content_b64,
        "branch": "main",
    }
    if sha:
        body["sha"] = sha
    code, payload = _github_api("PUT", url, token, body)
    if code in (200, 201):
        return True, "تم الحفظ السحابي"
    if code == 409:
        # تعارض — أعد جلب sha وحاول مرة أخرى
        _data, fresh_sha = _fetch_vault_file(cfg)
        if not fresh_sha:
            return False, "تعارض في المزامنة — تعذّر جلب النسخة الحالية"
        body["sha"] = fresh_sha
        code2, payload2 = _github_api("PUT", url, token, body)
        if code2 in (200, 201):
            return True, "تم الحفظ السحابي بعد حل التعارض"
        return False, str((payload2 or {}).get("message") or f"فشل المزامنة ({code2})")
    if code == 404 and not sha:
        # الفرع قد يكون master
        body["branch"] = "master"
        code3, payload3 = _github_api("PUT", url, token, body)
        if code3 in (200, 201):
            return True, "تم الحفظ السحابي"
        return False, str((payload3 or {}).get("message") or f"فشل المزامنة ({code3})")
    return False, str((payload or {}).get("message") or f"فشل المزامنة ({code})")


def _run_backup() -> None:
    global _last_backup_status
    with _backup_lock:
        try:
            cfg = get_vault_config()
            if not cfg.get("configured"):
                _last_backup_status = {"ok": False, "at": _now_label(), "msg": "لم تُضبط مفاتيح الخزنة بعد"}
                return
            state = export_vault_state(get_unified_db_path())
            _data, sha = _fetch_vault_file(cfg)
            ok, msg = _upload_vault_state(cfg, state, sha)
            _last_backup_status = {"ok": ok, "at": _now_label(), "msg": msg}
        except Exception as exc:
            _last_backup_status = {"ok": False, "at": _now_label(), "msg": f"تعذّرت المزامنة: {exc}"}


def trigger_vault_backup(*, immediate: bool = False, from_visit: bool = False) -> None:
    """رفع حالة القاعدة إلى GitHub في خيط خلفي دون تعطيل الواجهة."""
    global _last_visit_backup_ts
    cfg = get_vault_config()
    if not cfg.get("configured"):
        return
    if from_visit and not immediate:
        now = time.time()
        if now - float(_last_visit_backup_ts or 0) < _VISIT_BACKUP_MIN_SECONDS:
            return
        _last_visit_backup_ts = now
    try:
        t = threading.Thread(target=_run_backup, name="khafar-vault-backup", daemon=True)
        t.start()
        if immediate:
            # لا ننتظر طويلاً؛ نعطي فرصة بسيطة لبدء الخيط فقط
            time.sleep(0.01)
    except Exception:
        pass


def get_last_backup_status() -> dict:
    return dict(_last_backup_status or {})


def render_vault_status_badge(*, key_prefix: str = "vault") -> None:
    """شارة حالة الحفظ السحابي + زر مزامنة فورية."""
    if st is None:
        return
    cfg = get_vault_config()
    if cfg.get("configured"):
        st.markdown(
            '<div style="background:linear-gradient(135deg,#0E2920 0%,#071A14 100%);'
            "border:1.5px solid #34d399;border-radius:12px;padding:10px 12px;margin:8px 0;"
            'color:#ecfdf5;font-weight:800;direction:rtl;text-align:right;">'
            "☁️ الحفظ السحابي الدائم مفعّل — الأرشيف والإحصائيات محمية ضد إعادة التشغيل"
            "</div>",
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns([1.2, 2.8])
        with c1:
            if st.button("🔄 مزامنة سحابية فورية الآن", use_container_width=True, key=f"{key_prefix}_sync_now"):
                _run_backup()
                st.success("تمت المزامنة السحابية.")
                try:
                    st.rerun()
                except Exception:
                    pass
        status = get_last_backup_status()
        if status.get("at"):
            mark = "✅" if status.get("ok") else "⚠️"
            with c2:
                st.caption(f"{mark} آخر مزامنة: {status.get('at')} — {status.get('msg') or ''}")
    else:
        st.markdown(
            '<div style="background:#13382B;border:1.5px solid #D4AF37;border-radius:12px;'
            "padding:10px 12px;margin:8px 0;color:#FEF3C7;font-weight:700;direction:rtl;text-align:right;\">"
            "🔐 لتفعيل الحفظ السحابي الدائم أضف في Streamlit Secrets:<br/>"
            "<code>GITHUB_VAULT_TOKEN</code> و <code>GITHUB_VAULT_REPO = \"fhadvpn-byte/khafar-data-vault\"</code>"
            "</div>",
            unsafe_allow_html=True,
        )


# واجهة cache_resource تُستدعى من app.py بعد توفر streamlit
def cached_boot_vault(db_path: str | None = None) -> dict:
    path = str(db_path or get_unified_db_path())
    merge_legacy_databases_into(path)
    return restore_vault_if_needed(path)
