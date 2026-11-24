# -*- coding: utf-8 -*-
"""مكوّن رفع ملفات الجوال ثنائي الاتجاه — يفتح المعرض الأصلي عبر accept=image/* فقط."""
from __future__ import annotations

import base64
import hashlib
import io
import uuid
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass

_COMPONENT_DIR = Path(__file__).resolve().parent
_mobile_uploader = components.declare_component("khafar_mobile_uploader", path=str(_COMPONENT_DIR))


class KhafarUploadedFile(io.BytesIO):
    """واجهة متوافقة مع UploadedFile في Streamlit."""

    def __init__(self, data: bytes, name: str, mime: str = "application/octet-stream", file_id: str | None = None):
        super().__init__(data or b"")
        self.name = name or "upload.bin"
        self.type = mime or "application/octet-stream"
        self.size = len(data or b"")
        self.file_id = file_id or hashlib.sha1(f"{self.name}|{self.size}".encode("utf-8")).hexdigest()[:16]
        self.seek(0)

    def getvalue(self) -> bytes:
        pos = self.tell()
        try:
            self.seek(0)
            return super().getvalue()
        finally:
            try:
                self.seek(pos)
            except Exception:
                pass


def _b64_to_bytes(raw_b64: str) -> bytes:
    text = str(raw_b64 or "").strip()
    if not text:
        return b""
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[-1]
    try:
        return base64.b64decode(text)
    except Exception:
        return b""


def _maybe_convert_heic(data: bytes, name: str, mime: str, *, preserve_alpha: bool) -> tuple[bytes, str, str]:
    """إن كانت البايتات صورة (بما فيها HEIC) حوّلها إلى JPEG/PNG مع EXIF."""
    if not data:
        return data, name, mime
    if data[:5] == b"%PDF-" or data[:4] == b"%PDF":
        out_name = name if str(name).lower().endswith(".pdf") else f"{Path(name or 'مرفق').stem}.pdf"
        return data, out_name, "application/pdf"
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
    except Exception:
        return data, name, mime

    stem = Path(name or "صورة").stem or "صورة"
    max_edge = 1600
    if max(img.size) > max_edge:
        img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    if preserve_alpha:
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA") if "A" in (img.getbands() or ()) else img.convert("RGB")
        if img.mode != "RGBA":
            img = img.convert("RGBA") if img.mode in ("LA", "P") else img.convert("RGB")
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), f"{stem}.png", "image/png"

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in (img.info or {})):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue(), f"{stem}.jpg", "image/jpeg"


def _items_from_component(value: Any, *, preserve_alpha: bool) -> list[KhafarUploadedFile]:
    if not value:
        return []
    files_raw = value
    if isinstance(value, dict):
        files_raw = value.get("files") or []
    if not isinstance(files_raw, list):
        return []
    out: list[KhafarUploadedFile] = []
    for item in files_raw:
        if not isinstance(item, dict):
            continue
        raw = _b64_to_bytes(item.get("data_b64") or "")
        if not raw:
            continue
        name = str(item.get("name") or "مرفق.bin")
        mime = str(item.get("type") or "application/octet-stream")
        raw, name, mime = _maybe_convert_heic(raw, name, mime, preserve_alpha=preserve_alpha)
        out.append(
            KhafarUploadedFile(
                raw,
                name=name,
                mime=mime,
                file_id=str(item.get("id") or uuid.uuid4().hex[:12]),
            )
        )
    return out


def khafar_file_uploader(
    label: str,
    *,
    key: str,
    accept_multiple_files: bool = False,
    allow_pdf: bool = True,
    preserve_alpha: bool = False,
    disabled: bool = False,
    help: str | None = None,
    subtitle: str | None = None,
    default=None,
):
    """
    رافع ملفات جوال ثنائي الاتجاه.
    - accept_multiple_files=False → يعيد KhafarUploadedFile | None
    - accept_multiple_files=True → يعيد list[KhafarUploadedFile]
    """
    store_key = f"_khafar_mu_files_{key}"
    token_key = f"_khafar_mu_token_{key}"

    if help and not subtitle:
        subtitle = help
    if subtitle is None:
        subtitle = (
            "🖼️ المعرض يفتح تطبيق الصور الأصلي في أندرويد/آيفون — "
            "بدون فلتر امتدادات يعطّل content://"
        )

    result = _mobile_uploader(
        title=label or "إرفاق ملفات",
        subtitle=subtitle or "",
        multiple=bool(accept_multiple_files),
        allow_pdf=bool(allow_pdf),
        preserve_alpha=bool(preserve_alpha),
        disabled=bool(disabled),
        key=key,
        default=default if default is not None else {"action": "idle", "files": [], "ts": 0},
    )

    files = _items_from_component(result, preserve_alpha=preserve_alpha)
    if files:
        token = hashlib.sha256(
            "|".join(f"{f.file_id}:{f.size}:{f.name}" for f in files).encode("utf-8")
        ).hexdigest()
        st.session_state[store_key] = files
        st.session_state[token_key] = token
    elif store_key in st.session_state and isinstance(result, dict) and result.get("action") == "update":
        # قائمة فارغة صريحة من المكوّن = مسح
        if not (result.get("files") or []):
            st.session_state[store_key] = []
            st.session_state[token_key] = ""

    stored = st.session_state.get(store_key) or []
    if not isinstance(stored, list):
        stored = []

    if accept_multiple_files:
        return list(stored)
    if not stored:
        return None
    return stored[0]
