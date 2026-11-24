import copy, inspect, json, re
import streamlit as st
from streamlit.delta_generator import DeltaGenerator as DG

_KHAFAR_MED_AGE_VER = "v4"

_AR_DIGITS = "".join(chr(0x0660 + i) for i in range(10))
_FA_DIGITS = "".join(chr(0x06F0 + i) for i in range(10))
_TR = str.maketrans(_AR_DIGITS + _FA_DIGITS, "0123456789" * 2)

_STATE = {
    "med_ids": set(),
    "cat_injected": 0,
    "in_med_ui": False,
    "active_title": "",
    "age_rendered": False,
    "last_age_val": "",
}

W_AGE = "\u0627\u0644\u0639\u0645\u0631"
W_AGE_PFX = "\u0639\u0645\u0631 "
W_AGE_INJURED = "\u0639\u0645\u0631 \u0627\u0644\u0645\u0635\u0627\u0628"
W_AGE_DECEASED = "\u0639\u0645\u0631 \u0627\u0644\u0645\u062a\u0648\u0641\u0649"
W_AGE_TOX = "\u0639\u0645\u0631 \u0627\u0644\u0645\u062d\u0627\u0644 \u0644\u0644\u062a\u062d\u0644\u064a\u0644"

MED_KEYWORDS = (
    "\u0633\u0645\u0648\u0645",
    "\u062a\u062d\u0644\u064a\u0644 \u0633\u0645\u0648\u0645",
    "\u062a\u062d\u0644\u064a\u0644 \u0627\u0644\u0633\u0645\u0648\u0645",
    "\u0645\u0631\u0627\u0642\u0628\u0629 \u0627\u0644\u0633\u0645\u0648\u0645",
    "\u0645\u0635\u0627\u0628",
    "\u0625\u0635\u0627\u0628\u0629",
    "\u0627\u0635\u0627\u0628\u0629",
    "\u0639\u0644\u0627\u062c",
    "\u062a\u0642\u0631\u064a\u0631 \u0637\u0628\u064a",
    "\u0643\u0634\u0641 \u0637\u0628\u064a",
    "\u062c\u062b\u0645\u0627\u0646",
    "\u0645\u062a\u0648\u0641\u0649",
    "\u0627\u0644\u0645\u062a\u0648\u0641\u0649",
    "\u0648\u0641\u0627\u0629",
    "\u062b\u0644\u0627\u062c\u0629",
    "\u0627\u0644\u0637\u0628 \u0627\u0644\u0634\u0631\u0639\u064a",
    "\u0627\u0644\u0643\u064a\u0645\u064a\u0627\u0621 \u0627\u0644\u0634\u0631\u0639\u064a\u0629",
    "\u0627\u0644\u0637\u0628\u064a\u0629 \u0648\u0627\u0644\u062c\u0646\u0627\u0626\u064a\u0629",
    "\u0637\u0628\u064a\u0629 \u0648\u062c\u0646\u0627\u0626\u064a\u0629",
)

EXCLUDED_KEYWORDS = (
    "\u0643\u0641\u0627\u0644\u0629",
    "\u062a\u0646\u0627\u0632\u0644",
    "\u062a\u0633\u0644\u064a\u0645 \u0645\u0631\u0643\u0628\u0629",
    "\u0627\u0633\u062a\u0644\u0627\u0645 \u0645\u0631\u0643\u0628\u0629",
    "\u062d\u062c\u0632 \u0645\u0631\u0643\u0628\u0629",
)

def reset_run_state():
    _STATE["in_med_ui"] = False
    _STATE["active_title"] = ""
    _STATE["age_rendered"] = False
    _STATE["last_age_val"] = ""

def format_arabic_age(raw_val) -> str:
    v = str(raw_val or "").translate(_TR).strip()
    if not v or v in ("None", "-", "\u2014", "........"):
        return ""
    if re.fullmatch(r"\d{1,3}", v):
        n = int(v)
        if n == 1:
            return "\u0633\u0646\u0629 \u0648\u0627\u062d\u062f\u0629"
        if n == 2:
            return "\u0633\u0646\u062a\u0627\u0646"
        if 3 <= n <= 10:
            return f"{n} \u0633\u0646\u0648\u0627\u062a"
        return f"{n} \u0633\u0646\u0629"
    return v

def age_meta_for_text(txt: str):
    t = str(txt or "")
    if any(w in t for w in ("\u062c\u062b\u0645\u0627\u0646", "\u0645\u062a\u0648\u0641", "\u0648\u0641\u0627\u0629", "\u062b\u0644\u0627\u062c\u0629")):
        return (W_AGE_DECEASED, "\u0645\u062b\u0627\u0644: 35 \u0633\u0646\u0629")
    if any(w in t for w in ("\u0645\u0635\u0627\u0628", "\u0625\u0635\u0627\u0628\u0629", "\u0627\u0635\u0627\u0628\u0629", "\u0639\u0644\u0627\u062c", "\u062a\u0642\u0631\u064a\u0631 \u0637\u0628\u064a", "\u0643\u0634\u0641 \u0637\u0628\u064a")):
        return (W_AGE_INJURED, "\u0645\u062b\u0627\u0644: 28 \u0633\u0646\u0629")
    if any(w in t for w in ("\u0633\u0645\u0648\u0645", "\u0645\u062e\u062f\u0631", "\u0645\u0633\u0643\u0631", "\u062a\u062d\u0644\u064a\u0644")):
        return (W_AGE_TOX, "\u0645\u062b\u0627\u0644: 29 \u0633\u0646\u0629")
    return (W_AGE, "\u0645\u062b\u0627\u0644: 30 \u0633\u0646\u0629")

def _dict_text_blob(d: dict) -> str:
    return " | ".join(v for v in d.values() if isinstance(v, str) and len(v) < 160)

def _is_med_seed_dict(d) -> bool:
    if not isinstance(d, dict) or len(d) < 2:
        return False
    blob = _dict_text_blob(d)
    if any(ex in blob for ex in EXCLUDED_KEYWORDS):
        return False
    return any(
        kw in blob
        for kw in (
            "\u062a\u062d\u0644\u064a\u0644 \u0633\u0645\u0648\u0645",
            "\u062a\u062d\u0644\u064a\u0644 \u0627\u0644\u0633\u0645\u0648\u0645",
            "\u0645\u0631\u0627\u0642\u0628\u0629 \u0627\u0644\u0633\u0645\u0648\u0645",
            "\u062c\u062b\u0645\u0627\u0646",
            "\u062b\u0644\u0627\u062c\u0629",
            "\u0625\u062d\u0627\u0644\u0629 \u0645\u0635\u0627\u0628",
            "\u0639\u0644\u0627\u062c \u0645\u0635\u0627\u0628",
            "\u062a\u0642\u0631\u064a\u0631 \u0637\u0628\u064a",
            "\u0643\u0634\u0641 \u0637\u0628\u064a",
        )
    )

def _is_age_field(fd) -> bool:
    if isinstance(fd, dict):
        for k in ("key", "id", "name", "field", "k"):
            kv = str(fd.get(k, "")).lower()
            if kv == "age" or kv.endswith("_age") or "person_age" in kv:
                return True
        for lk in ("label", "title", "caption", "lbl"):
            lv = str(fd.get(lk, ""))
            if W_AGE in lv or lv.startswith(W_AGE_PFX) or (" " + W_AGE_PFX) in lv:
                return True
    elif isinstance(fd, (tuple, list)) and len(fd) >= 2:
        k0, l1 = str(fd[0]).lower(), str(fd[1])
        if k0 == "age" or k0.endswith("_age") or "person_age" in k0:
            return True
        if W_AGE in l1 or l1.startswith(W_AGE_PFX) or (" " + W_AGE_PFX) in l1:
            return True
    return False

def _age_sample_for_label(age_lbl: str) -> str:
    if age_lbl == W_AGE_INJURED:
        return "28"
    if age_lbl == W_AGE_DECEASED:
        return "38"
    if age_lbl == W_AGE_TOX:
        return "29"
    return "30"


def _inject_age_into_form_dict(fm: dict, form_id: str = "") -> bool:
    blob = _dict_text_blob(fm)
    if any(ex in blob for ex in EXCLUDED_KEYWORDS):
        return False

    fid = (form_id or "").strip() or next((str(fm[k]) for k in ("id", "key", "code", "form_id", "slug") if isinstance(fm.get(k), str) and fm.get(k)), "med")
    _STATE["med_ids"].add(fid)

    flk = None
    for k, v in fm.items():
        if isinstance(v, list) and len(v) >= 2 and isinstance(v[0], (dict, tuple, list)):
            if (isinstance(v[0], dict) and any(fk in v[0] for fk in ("label", "title", "key", "id", "name"))) or (
                isinstance(v[0], (tuple, list)) and len(v[0]) >= 2
            ):
                if flk is None or k in ("fields", "inputs", "schema", "form_fields"):
                    flk = k
    if not flk:
        return False

    flist = fm[flk]
    if any(_is_age_field(fd) for fd in flist):
        return True

    age_lbl, age_ph = age_meta_for_text(blob)
    age_key = f"{fid}_person_age"

    insert_after = 1
    proto_text_fd = None

    for idx, fd in enumerate(flist):
        lbl = ""
        is_select = False
        if isinstance(fd, dict):
            lbl = str(next((fd.get(lk, "") for lk in ("label", "title", "caption", "lbl") if lk in fd), ""))
            is_select = any(ok in fd and isinstance(fd[ok], (list, tuple)) for ok in ("options", "choices", "items", "opts")) or (
                str(fd.get("type", fd.get("kind", ""))).lower() in ("select", "selectbox")
            )
        elif isinstance(fd, (tuple, list)) and len(fd) >= 2:
            lbl = str(fd[1])
            is_select = (len(fd) >= 4 and isinstance(fd[3], (list, tuple))) or (
                len(fd) >= 3 and str(fd[2]).lower() in ("select", "selectbox")
            )

        if not is_select and proto_text_fd is None:
            proto_text_fd = fd

        if any(w in lbl for w in ("\u0647\u0648\u064a\u0629", "\u0625\u0642\u0627\u0645\u0629", "\u0627\u0642\u0627\u0645\u0629", "\u0627\u0644\u0633\u062c\u0644", "\u0627\u0644\u062c\u0646\u0633\u064a\u0629")):
            insert_after = idx + 1
            if not is_select:
                proto_text_fd = fd
            break
        if any(w in lbl for w in ("\u0627\u0633\u0645 ", "\u0627\u0644\u0627\u0633\u0645", "\u0627\u0644\u0645\u062f\u0639\u0648", "\u0627\u0644\u0645\u0635\u0627\u0628", "\u0627\u0644\u0645\u062a\u0648\u0641\u0649")):
            insert_after = idx + 1
            if not is_select:
                proto_text_fd = fd

    if proto_text_fd is None:
        proto_text_fd = flist[0]

    if isinstance(proto_text_fd, dict):
        new_fd = copy.deepcopy(proto_text_fd)
        for rm_k in ("options", "choices", "items", "opts"):
            new_fd.pop(rm_k, None)
        for wk in ("full", "full_width", "wide"):
            if wk in new_fd:
                new_fd[wk] = False
        for sk in ("span", "colspan"):
            if sk in new_fd and isinstance(new_fd[sk], int):
                new_fd[sk] = 1
        kk = next((k for k in ("key", "id", "name", "field", "k") if k in new_fd), "key")
        lk = next((k for k in ("label", "title", "caption", "lbl") if k in new_fd), "label")
        new_fd[kk] = age_key
        new_fd[lk] = age_lbl
        for tk in ("type", "kind", "widget", "input_type"):
            if tk in new_fd and str(new_fd[tk]).lower() in ("select", "selectbox", "textarea"):
                new_fd[tk] = "text"
        age_sample = _age_sample_for_label(age_lbl)
        new_fd["sample"] = age_sample
        for dk in ("default", "value", "val", "initial"):
            if dk in new_fd:
                new_fd[dk] = ""
        pk = next((k for k in ("placeholder", "hint", "help", "ph") if k in new_fd), None)
        if pk:
            new_fd[pk] = age_ph
    else:
        tp = type(proto_text_fd)
        b = list(proto_text_fd)
        b[0] = age_key
        b[1] = age_lbl
        for j in range(2, len(b)):
            if isinstance(b[j], bool):
                b[j] = False
            elif isinstance(b[j], int):
                b[j] = 1
            elif isinstance(b[j], (list, tuple)):
                b[j] = ""
            elif isinstance(b[j], str):
                if b[j].lower() in ("select", "selectbox", "textarea", "text", "number", "date"):
                    b[j] = "text"
                elif j == len(b) - 1 or "\u0645\u062b\u0627\u0644" in b[j]:
                    b[j] = age_ph
                else:
                    b[j] = ""
        new_fd = tp(b)

    flist.insert(min(insert_after, len(flist)), new_fd)
    return True

def _scan_med_catalog(obj, seen=None, depth=0) -> int:
    if depth > 5 or obj is None or isinstance(obj, (str, bytes, int, float, bool)):
        return 0
    if seen is None:
        seen = set()
    if id(obj) in seen:
        return 0
    seen.add(id(obj))
    count = 0

    if isinstance(obj, list):
        seed = next((x for x in obj if _is_med_seed_dict(x)), None)
        if seed is not None:
            ck = next((k for k in ("category", "cat", "section", "group", "tab", "sec") if k in seed and seed.get(k)), None)
            for item in obj:
                if isinstance(item, dict):
                    if (ck and item.get(ck) == seed.get(ck)) or (not ck and (_is_med_seed_dict(item) or any(w in _dict_text_blob(item) for w in MED_KEYWORDS))):
                        item_id = next((str(item[ik]) for ik in ("id", "key", "code", "form_id", "slug") if isinstance(item.get(ik), str) and item.get(ik)), "")
                        if _inject_age_into_form_dict(item, form_id=item_id):
                            count += 1
            return count
        for x in obj:
            if isinstance(x, (dict, list, tuple)):
                count += _scan_med_catalog(x, seen, depth + 1)

    elif isinstance(obj, dict):
        seed_it = next(((k, v) for k, v in obj.items() if not str(k).startswith("_KHAFAR") and _is_med_seed_dict(v)), None)
        if seed_it is not None:
            seed = seed_it[1]
            ck = next((k for k in ("category", "cat", "section", "group", "tab", "sec") if k in seed and seed.get(k)), None)
            for k, v in obj.items():
                if isinstance(v, dict):
                    if (ck and v.get(ck) == seed.get(ck)) or (not ck and (_is_med_seed_dict(v) or any(w in _dict_text_blob(v) for w in MED_KEYWORDS))):
                        _STATE["med_ids"].add(str(k))
                        if _inject_age_into_form_dict(v, form_id=str(k)):
                            count += 1
            return count
        for k, v in list(obj.items()):
            if str(k).startswith("_KHAFAR") or inspect.ismodule(v) or inspect.isfunction(v) or inspect.isclass(v):
                continue
            if isinstance(v, tuple) and any(_is_med_seed_dict(x) for x in v):
                tmp = list(v)
                c = _scan_med_catalog(tmp, seen, depth + 1)
                if c:
                    obj[k] = tuple(tmp)
                    count += c
            elif isinstance(v, (dict, list)):
                count += _scan_med_catalog(v, seen, depth + 1)
    return count

def register_catalog(*namespaces):
    total = 0
    for ns in namespaces:
        if isinstance(ns, dict):
            total += _scan_med_catalog(ns)
    if total > 0:
        _STATE["cat_injected"] = max(_STATE["cat_injected"], total)
    return total

def wrap_catalog_fn(fn):
    raw = getattr(fn, "_kh_med_raw_cat", fn)
    def _w(*a, **kw):
        r = raw(*a, **kw)
        if isinstance(r, (list, dict)):
            c = _scan_med_catalog(r)
            if c:
                _STATE["cat_injected"] = max(_STATE["cat_injected"], c)
        return r
    _w._kh_med_raw_cat = raw
    return _w

def _is_archive_open() -> bool:
    try:
        for k, v in st.session_state.items():
            kl = str(k).lower()
            if isinstance(v, str) and any(t in kl for t in ("tab", "nav", "page", "view", "mode")):
                if "\u0623\u0631\u0634\u064a\u0641" in v or "\u0627\u0631\u0634\u064a\u0641" in v or v.strip().lower() == "archive":
                    return True
    except Exception:
        pass
    return False

if not hasattr(DG, "_kh_med_prev_sel"):
    DG._kh_med_prev_sel = DG.selectbox
if not hasattr(st, "_kh_med_prev_sel"):
    st._kh_med_prev_sel = st.selectbox

def _track_med_sel(options, ret, kw):
    try:
        opts = list(options or [])
        ff = kw.get("format_func")
        disp = [str(ff(x)) if callable(ff) else str(x) for x in opts]
        if any(any(w in s for w in ("\u0633\u0645\u0648\u0645", "\u062c\u062b\u0645\u0627\u0646", "\u0645\u0635\u0627\u0628")) for s in disp):
            _STATE["in_med_ui"] = True
            _STATE["active_title"] = str(ff(ret)) if (callable(ff) and ret is not None) else str(ret or "")
    except Exception:
        pass
    return ret

DG.selectbox = lambda self, label, options=(), index=0, *a, **kw: _track_med_sel(options, DG._kh_med_prev_sel(self, label, options, index, *a, **kw), kw)
st.selectbox = lambda label, options=(), index=0, *a, **kw: _track_med_sel(options, st._kh_med_prev_sel(label, options, index, *a, **kw), kw)

if not hasattr(DG, "_kh_med_raw_ti"):
    DG._kh_med_raw_ti = DG.text_input
if not hasattr(st, "_kh_med_raw_ti"):
    st._kh_med_raw_ti = st.text_input

def _is_currently_in_med_section() -> bool:
    if _is_archive_open():
        return False
    if _STATE["in_med_ui"]:
        return True
    try:
        for k, v in st.session_state.items():
            if isinstance(v, str):
                if "\u0627\u0644\u0637\u0628\u064a\u0629 \u0648\u0627\u0644\u062c\u0646\u0627\u0626\u064a\u0629" in v or "\u0637\u0628\u064a\u0629 \u0648\u062c\u0646\u0627\u0626\u064a\u0629" in v:
                    return True
                if any(tk in str(k).lower() for tk in ("tab", "cat", "sec", "mode", "nav", "form", "doc")):
                    if v in _STATE["med_ids"] or any(w in v for w in ("\u0633\u0645\u0648\u0645", "\u062c\u062b\u0645\u0627\u0646", "\u0625\u062d\u0627\u0644\u0629 \u0645\u0635\u0627\u0628", "\u0639\u0644\u0627\u062c \u0645\u0635\u0627\u0628", "\u062a\u0642\u0631\u064a\u0631 \u0637\u0628\u064a")):
                        return True
    except Exception:
        pass
    return False

def _handle_text_input(raw_call, raw_extra_call, label, *a, **kw):
    ret = raw_call(label, *a, **kw)
    lbl = str(label or "")
    key_str = str(kw.get("key", "") or "")

    if W_AGE in lbl or lbl.startswith(W_AGE_PFX) or (" " + W_AGE_PFX) in lbl or key_str.endswith("_person_age") or key_str.endswith("_age"):
        _STATE["age_rendered"] = True
        _STATE["last_age_val"] = ret
        return ret

    if _STATE["cat_injected"] == 0 and not _STATE["age_rendered"] and _is_currently_in_med_section():
        if any(w in lbl for w in ("\u0647\u0648\u064a\u0629", "\u0627\u0644\u0647\u0648\u064a\u0629", "\u0625\u0642\u0627\u0645\u0629", "\u0627\u0644\u062c\u0646\u0633\u064a\u0629")):
            age_lbl, age_ph = age_meta_for_text(_STATE["active_title"] or lbl)
            _STATE["age_rendered"] = True
            age_val = raw_extra_call(age_lbl, value="", placeholder=age_ph, key=f"_kh_imp_med_age_{key_str or abs(hash(lbl)) % 99999}")
            _STATE["last_age_val"] = age_val
    return ret

DG.text_input = lambda self, label, *a, **kw: _handle_text_input(
    lambda l, *x, **y: DG._kh_med_raw_ti(self, l, *x, **y),
    lambda l, *x, **y: DG._kh_med_raw_ti(self, l, *x, **y),
    label, *a, **kw,
)
st.text_input = lambda label, *a, **kw: _handle_text_input(
    st._kh_med_raw_ti,
    st._kh_med_raw_ti,
    label, *a, **kw,
)

_W_ID_ALT = "\u0627\u0644\u0647\u0648\u064a\u0629|\u0627\u0644\u0625\u0642\u0627\u0645\u0629|\u0647\u0648\u064a\u0629|\u0625\u0642\u0627\u0645\u0629|\u0627\u0644\u0633\u062c\u0644 \u0627\u0644\u0645\u062f\u0646\u064a"
_W_NM_ALT = "\u0627\u0644\u0645\u062f\u0639\u0648|\u0627\u0644\u0645\u0635\u0627\u0628|\u0627\u0644\u0645\u062a\u0648\u0641\u0649|\u062c\u062b\u0645\u0627\u0646"
_PAT_ID = re.compile(rf"((?:{_W_ID_ALT})[^()\n]{{0,35}}\([^()\n]{{2,65}}\))")
_PAT_NAME = re.compile(rf"((?:{_W_NM_ALT})\s*/?\s*\([^()\n]{{2,85}}\))")

def _inject_age_in_legal_text(txt: str, fmt_age: str) -> str:
    if not isinstance(txt, str) or not fmt_age:
        return txt
    if W_AGE in txt or W_AGE_PFX in txt:
        return txt
    n_txt, cnt = _PAT_ID.subn(lambda m: f"{m.group(1)}\u060c {W_AGE} ({fmt_age})", txt, count=1)
    if cnt > 0:
        return n_txt
    n_txt, cnt = _PAT_NAME.subn(lambda m: f"{m.group(1)}\u060c {W_AGE} ({fmt_age})", txt, count=1)
    if cnt > 0:
        return n_txt
    return txt

_DOM_SYNC_JS_TPL = r"""<script id="kh-med-age-dom-sync">(function(){
  var CFG = __KH_MED_CFG_JSON__;
  function syncMedAgeDom(root) {
    var sheet = (root.getElementById ? root.getElementById('a4Sheet') : null) || root;
    if (!sheet) return;
    var tbl = sheet.querySelector('table.data-tbl');
    if (tbl) {
      var found = false;
      Array.prototype.forEach.call(tbl.querySelectorAll('th, td'), function(c) {
        var t = (c.textContent || '').trim();
        if (CFG.ageNames.indexOf(t) !== -1) {
          found = true;
          var vc = c.nextElementSibling;
          if (vc) {
            var cv = (vc.textContent || '').trim();
            if (!cv || cv === '-' || cv === 'None' || /^\d{1,3}$/.test(cv)) {
              vc.textContent = CFG.dispAge;
            }
          }
        }
      });
      if (!found && tbl.rows && tbl.rows.length > 0) {
        var doc = sheet.ownerDocument || document;
        var r0 = tbl.rows[0];
        var totalCols = 0;
        for (var i = 0; i < r0.cells.length; i++) totalCols += (r0.cells[i].colSpan || 1);
        if (totalCols < 2) totalCols = 2;
        var sL = r0.cells[0];
        var sV = r0.cells.length > 1 ? r0.cells[1] : r0.cells[0];
        var insIdx = 1;
        for (var r = 0; r < tbl.rows.length; r++) {
          var rTxt = tbl.rows[r].textContent || '';
          for (var h = 0; h < CFG.rowHints.length; h++) {
            if (rTxt.indexOf(CFG.rowHints[h]) !== -1) { insIdx = r + 1; break; }
          }
        }
        var tr = doc.createElement('tr');
        var tdL = doc.createElement(sL.tagName || 'td');
        var tdV = doc.createElement(sV.tagName || 'td');
        tdL.className = sL.className || '';
        tdL.style.cssText = sL.style.cssText || '';
        tdL.textContent = CFG.ageLbl;
        tdV.className = sV.className || '';
        tdV.style.cssText = sV.style.cssText || '';
        if (totalCols > 2) tdV.colSpan = totalCols - 1;
        tdV.textContent = CFG.dispAge;
        tr.appendChild(tdL);
        tr.appendChild(tdV);
        var ref = tbl.rows[insIdx] || null;
        if (ref && ref.parentNode) ref.parentNode.insertBefore(tr, ref);
        else (tbl.tBodies[0] || tbl).appendChild(tr);
      }
    }
    if (CFG.fmtAge) {
      var lb = sheet.querySelector('.legal-box-body');
      if (lb) {
        var lt = lb.innerHTML || '';
        if (lt.indexOf(CFG.wAge) === -1 && lt.indexOf(CFG.wAgePfx) === -1) {
          var idRe = new RegExp('((?:' + CFG.idAlt + ')[^()\\n<]{0,35}\\([^()\\n<]{2,65}\\))');
          var nmRe = new RegExp('((?:' + CFG.nmAlt + ')\\s*\\/?\\s*\\([^()\\n<]{2,85}\\))');
          var rep = '$1' + CFG.comma + ' ' + CFG.wAge + ' (' + CFG.fmtAge + ')';
          var up = lt.replace(idRe, rep);
          if (up === lt) up = lt.replace(nmRe, rep);
          if (up !== lt) lb.innerHTML = up;
        }
      }
    }
  }
  try { syncMedAgeDom(document); } catch (e) {}
  addEventListener('load', function() { try { syncMedAgeDom(document); } catch (e) {} });
  addEventListener('beforeprint', function() { try { syncMedAgeDom(document); } catch (e) {} });
})();</script>"""

def _build_dom_age_script(age_lbl: str, disp_age: str, fmt_age: str) -> str:
    cfg = {
        "ageLbl": age_lbl,
        "dispAge": disp_age,
        "fmtAge": fmt_age,
        "wAge": W_AGE,
        "wAgePfx": W_AGE_PFX,
        "comma": "\u060c",
        "idAlt": _W_ID_ALT,
        "nmAlt": _W_NM_ALT,
        "ageNames": [W_AGE, W_AGE_INJURED, W_AGE_DECEASED, W_AGE_TOX],
        "rowHints": ["\u0647\u0648\u064a\u0629", "\u0625\u0642\u0627\u0645\u0629", "\u0627\u0644\u062c\u0646\u0633\u064a\u0629", "\u0627\u0644\u0645\u062f\u0639\u0648", "\u0627\u0644\u0645\u0635\u0627\u0628", "\u0627\u0644\u0645\u062a\u0648\u0641\u0649"],
    }
    return _DOM_SYNC_JS_TPL.replace("__KH_MED_CFG_JSON__", json.dumps(cfg, ensure_ascii=True))

def bind_functions(g):
    register_catalog(g)
    bh = g.get("build_official_a4_html")
    if callable(bh) and not getattr(bh, "_kh_med_age_wrapped", False):
        orig_bh = bh

        def _med_bh_wrap(*a, **kw):
            all_args = list(a) + list(kw.values())
            str_blob = " | ".join(x for x in all_args if isinstance(x, str) and len(x) < 200)
            is_med = (
                _STATE["in_med_ui"]
                or any(isinstance(x, str) and x in _STATE["med_ids"] for x in all_args)
                or any(w in str_blob for w in MED_KEYWORDS)
            ) and not any(ex in str_blob for ex in EXCLUDED_KEYWORDS)

            if not is_med:
                return orig_bh(*a, **kw)

            age_lbl, age_ph = age_meta_for_text(str_blob or _STATE["active_title"])
            raw_age = ""

            for item in all_args:
                if isinstance(item, dict):
                    for dk, dv in item.items():
                        dkl = str(dk).lower()
                        if dkl == "age" or dkl.endswith("_person_age") or dkl.endswith("_age") or W_AGE in str(dk) or str(dk).startswith(W_AGE_PFX):
                            if str(dv or "").strip():
                                raw_age = dv
                                break
            if not str(raw_age or "").strip() and _STATE["last_age_val"]:
                raw_age = _STATE["last_age_val"]

            if not _STATE["age_rendered"] and not _is_archive_open() and not str(raw_age or "").strip():
                _STATE["age_rendered"] = True
                raw_age = st._kh_med_raw_ti(age_lbl, value="", placeholder=age_ph, key=f"_kh_med_age_fb_{abs(hash(age_lbl)) % 9999}")
                _STATE["last_age_val"] = raw_age

            if not str(raw_age or "").strip():
                for sk, sv in st.session_state.items():
                    if str(sk).endswith("_person_age") and str(sv or "").strip():
                        raw_age = sv
                        break

            fmt_age = format_arabic_age(raw_age)
            disp_age = fmt_age if fmt_age else "........"

            def _patch_arg(val):
                if isinstance(val, list) and val and isinstance(val[0], (tuple, list)) and len(val[0]) == 2 and isinstance(val[0][0], str):
                    new_rows = []
                    has_age = False
                    for r in val:
                        rl, rv = str(r[0]), r[1]
                        if W_AGE in rl or rl.startswith(W_AGE_PFX) or (" " + W_AGE_PFX) in rl:
                            has_age = True
                            rv_fmt = format_arabic_age(rv)
                            new_rows.append(type(r)([r[0], rv_fmt if rv_fmt else disp_age]))
                        else:
                            new_rows.append(r)
                    if not has_age:
                        ins_at = 1
                        for idx_r, r in enumerate(new_rows):
                            if any(w in str(r[0]) for w in ("\u0647\u0648\u064a\u0629", "\u0625\u0642\u0627\u0645\u0629", "\u0627\u0644\u062c\u0646\u0633\u064a\u0629", "\u0627\u0644\u0645\u062f\u0639\u0648", "\u0627\u0633\u0645 ")):
                                ins_at = idx_r + 1
                        tp_r = type(new_rows[0])
                        new_rows.insert(min(ins_at, len(new_rows)), tp_r([age_lbl, disp_age]))
                    return new_rows
                if isinstance(val, str) and len(val) > 95 and fmt_age:
                    return _inject_age_in_legal_text(val, fmt_age)
                return val

            new_a = tuple(_patch_arg(x) for x in a)
            new_kw = {k: _patch_arg(v) for k, v in kw.items()}

            html = orig_bh(*new_a, **new_kw)
            if isinstance(html, str) and "kh-med-age-dom-sync" not in html:
                dom_js = _build_dom_age_script(age_lbl, disp_age, fmt_age)
                if "</body>" in html:
                    html = html.replace("</body>", dom_js + "\n</body>", 1)
                else:
                    html = html + dom_js
            return html

        _med_bh_wrap._kh_med_age_wrapped = True
        _med_bh_wrap._kh_bail_wrapped = getattr(bh, "_kh_bail_wrapped", False)
        if hasattr(bh, "_kh_bail_raw_bh"):
            _med_bh_wrap._kh_bail_raw_bh = bh._kh_bail_raw_bh
        g["build_official_a4_html"] = _med_bh_wrap