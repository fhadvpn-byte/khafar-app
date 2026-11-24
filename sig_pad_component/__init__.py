# -*- coding: utf-8 -*-
"""مكوّن Streamlit ثنائي الاتجاه للوحة التوقيع الحي — بدون مكتبات خارجية."""
from pathlib import Path
import streamlit.components.v1 as components

_COMPONENT_DIR = Path(__file__).resolve().parent
_sig_pad = components.declare_component("khafar_sig_pad", path=str(_COMPONENT_DIR))


def sig_pad(
    *,
    key: str,
    title: str,
    subtitle: str = "",
    saved: str = "",
    ls_key: str = "khafar_duty_sig",
    pad_id: str = "officer",
    accent: str = "#0044cc",
    default=None,
):
    """لوحة توقيع ثنائية الاتجاه تُرجع dict {action, data_url, pad_id, ts} عند الحفظ/المسح."""
    return _sig_pad(
        title=title,
        subtitle=subtitle or "",
        saved=saved or "",
        ls_key=ls_key,
        pad_id=pad_id,
        accent=accent,
        key=key,
        default=default,
    )
