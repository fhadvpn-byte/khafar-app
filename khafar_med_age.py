import copy, inspect, re
import streamlit as st
from streamlit.delta_generator import DeltaGenerator as DG

_KHAFAR_MED_AGE_VER = "v1"

_STATE = {
    "med_ids": set(),
    "cat_injected": 0,
    "in_med_ui": False,
    "active_title": "",
    "age_rendered": False,
    "last_age_val": "",
}

_TR = str.maketrans("", "0123456789")

MED_KEYWORDS = (
    "سموم", "مصاب", "إصابة", "اصابة", "علاج", "تقرير طبي", "كشف طبي",
    "جثمان", "متوفى", "المتوفى", "وفاة", "ثلاجة", "الطب الشرعي", "الكيمياء الشرعية",
    "طبية وجنائية", "الطبية والجنائية",
)
EXCLUDED_KEYWORDS = (
    "كفالة", "تنازل", "تسليم مركبة", "استلام مركبة", "حجز مركبة",
)

def reset_run_state():
    _STATE["in_med_ui"] = False
    _STATE["active_title"] = ""
    _STATE["age_rendered"] = False
    _STATE["last_age_val"] = ""

def format_arabic_age(raw_val) -> str:
    v = str(raw_val or "").translate(_TR).strip()
    if not v or v in ("None", "-", "", "........"):
        return ""
    if re.fullmatch(r"\d{1,3}", v):
        n = int(v)
        if n == 1:
            return "سنة واحدة"
        if n == 2:
            return "سنتان"
        if 3 <= n <= 10:
            return f"{n} سنوات"
        return f"{n} سنة"
    return v

def age_meta_for_text(txt: str):
    t = str(txt or "")
    if any(w in t for w in ("جثمان", "متوف", "وفاة", "ثلاجة")):
        return ("عمر المتوفى", "مثال: 35 سنة (أو تقديري)")
    if any(w in t for w in ("مصاب", "إصابة", "اصابة", "علاج", "تقرير طبي", "كشف طبي")):
        return ("عمر المصاب", "مثال: 28 سنة")
    if any(w in t for w in ("سموم", "مخدر", "مسكر", "تحليل")):
        return ("عمر المحال للتحليل", "مثال: 29 سنة")
    return ("العمر", "مثال: 30 سنة")

def _dict_text_blob(d: dict) -> str:
    parts = []
    for v in d.values():
        if isinstance(v, str) and len(v) < 160:
            parts.append(v)
    return " | ".join(parts)

def _is_med_seed_dict(d) -> bool:
    if not isinstance(d, dict) or len(d) < 2:
        return False
    blob = _dict_text_blob(d)
    if any(ex in blob for ex in EXCLUDED_KEYWORDS):
        return False
    return any(
        kw in blob
        for kw in ("تحليل سموم", "تحليل السموم", "مراقبة السموم", "جثمان", "ثلاجة الموتى", "إحالة مصاب", "علاج مصاب", "تقرير طبي", "كشف طبي")
    )

def _is_age_field(fd) -> bool:
    if isinstance(fd, dict):
        for k in ("key", "id", "name", "field", "k"):
            kv = str(fd.get(k, "")).lower()
            if kv == "age" or kv.endswith("_age") or "person_age" in kv:
                return True
        for lk in ("label", "title", "caption", "lbl"):
            lv = str(fd.get(lk, ""))
            if "العمر" in lv or lv.startswith("عمر ") or " عمر " in lv:
                return True
    elif isinstance(fd, (tuple, list)) and len(fd) >= 2:
        k0, l1 = str(fd[0]).lower(), str(fd[1])
        if k0 == "age" or k0.endswith("_age") or "person_age" in k0:
            return True
        if "العمر" in l1 or l1.startswith("عمر ") or " عمر " in l1:
            return True
    return False

def _inject_age_into_form_dict(fm: dict):
    blob = _dict_text_blob(fm)
    if any(ex in blob for ex in EXCLUDED_KEYWORDS):
        return False

    fid = next((str(fm[k]) for k in ("id", "key", "code", "form_id", "slug") if isinstance(fm.get(k), str) and fm.get(k)), "med")
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

    # اختيار أنسب موضع للإدراج: مباشرة بعد حقل الهوية/الجنسية أو حقل الاسم
    insert_after = 0
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
            is_select = (len(fd) >= 4 and isinstance(fd[3], (list, tuple))) or (len(fd) >= 3 and str(fd[2]).lower() in ("select", "selectbox"))

        if not is_select and proto_text_fd is None:
            proto_text_fd = fd

        if any(w in lbl for w in ("هوية", "إقامة", "اقامة", "السجل", "الجنسية")):
            insert_after = idx + 1
            if not is_select:
                proto_text_fd = fd
            break
        if any(w in lbl for w in ("اسم المصاب", "اسم المتوفى", "اسم المحال", "اسم المدعو", "اسم الشخص", "الاسم")):
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
                elif j == len(b) - 1 or "مثال" in b[j]:
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
                        if _inject_age_into_form_dict(item):
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
                        if _inject_age_into_form_dict(v):
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

# تتبع حقل العمر أو حقنه تلقائياً إذا كان النموذج مبنياً بدوال st.text_input المباشرة
if not hasattr(DG, "_kh_med_raw_ti"):
    DG._kh_med_raw_ti = DG.text_input
if not hasattr(st, "_kh_med_raw_ti"):
    st._kh_med_raw_ti = st.text_input

def _is_currently_in_med_section() -> bool:
    if _STATE["in_med_ui"]:
        return True
    try:
        for k, v in st.session_state.items():
            if isinstance(v, str):
                if "الطبية والجنائية" in v or "طبية وجنائية" in v:
                    return True
                if any(tk in str(k).lower() for tk in ("tab", "cat", "sec", "mode", "nav", "form", "doc")):
                    if v in _STATE["med_ids"] or any(w in v for w in ("تحليل سموم", "تحليل السموم", "جثمان", "إحالة مصاب", "علاج مصاب", "تقرير طبي")):
                        return True
    except Exception:
        pass
    return False

def _handle_text_input(call_fn, target_obj, label, *a, **kw):
    ret = call_fn(label, *a, **kw)
    lbl = str(label or "")
    key_str = str(kw.get("key", "") or "")

    if "العمر" in lbl or lbl.startswith("عمر ") or " عمر " in lbl or key_str.endswith("_person_age") or key_str.endswith("_age"):
        _STATE["age_rendered"] = True
        _STATE["last_age_val"] = ret
        return ret

    # مسار احتياطي فقط إذا لم تكن النماذج الطبية مبنية بقوائم fields
    if _STATE["cat_injected"] == 0 and not _STATE["age_rendered"] and _is_currently_in_med_section():
        if any(w in lbl for w in ("هوية المصاب", "هوية المتوفى", "هوية المحال", "رقم الهوية", "الهوية والجنسية", "رقم الهوية / الإقامة")):
            age_lbl, age_ph = age_meta_for_text(_STATE["active_title"] or lbl)
            _STATE["age_rendered"] = True
            age_val = target_obj.text_input(age_lbl, value="", placeholder=age_ph, key=f"_kh_imp_med_age_{key_str or abs(hash(lbl)) % 99999}")
            _STATE["last_age_val"] = age_val
    return ret

DG.text_input = lambda self, label, *a, **kw: _handle_text_input(lambda l, *x, **y: DG._kh_med_raw_ti(self, l, *x, **y), self, label, *a, **kw)
st.text_input = lambda label, *a, **kw: _handle_text_input(st._kh_med_raw_ti, st, label, *a, **kw)

def _inject_age_in_legal_text(txt: str, fmt_age: str) -> str:
    if not isinstance(txt, str) or not fmt_age:
        return txt
    if "العمر" in txt or "عمر " in txt or "البالغ من العمر" in txt:
        return txt
    # 1) بعد عبارة الهوية / الإقامة بين قوسين مباشرة
    n_txt, cnt = re.subn(
        r"((?:الهوية|الإقامة|هوية|إقامة|السجل المدني)[^()\n]{0,35}\([^()\n]{2,65}\))",
        rf"\1، العمر ({fmt_age})",
        txt,
        count=1,
    )
    if cnt > 0:
        return n_txt
    # 2) بعد اسم المدعو / المصاب / المتوفى بين قوسين
    n_txt, cnt = re.subn(
        r"((?:المدعو|المصاب|المتوفى|المتوفاة|جثمان المتوفى|جثمان)\s*/?\s*\([^()\n]{2,85}\))",
        rf"\1، العمر ({fmt_age})",
        txt,
        count=1,
    )
    if cnt > 0:
        return n_txt
    return txt

def _build_dom_age_script(age_lbl: str, disp_age: str, fmt_age: str) -> str:
    import json as _json
    lbl_js = _json.dumps(age_lbl, ensure_ascii=False)
    disp_js = _json.dumps(disp_age, ensure_ascii=False)
    fmt_js = _json.dumps(fmt_age, ensure_ascii=False)
    return f"""<script id="kh-med-age-dom-sync">(function(){{
  var ageLbl = {lbl_js};
  var dispAge = {disp_js};
  var fmtAge = {fmt_js};
  function syncMedAgeDom(root) {{
    var sheet = (root.getElementById ? root.getElementById('a4Sheet') : null) || root;
    if (!sheet) return;
    var tbl = sheet.querySelector('table.data-tbl');
    if (tbl) {{
      var foundAgeCell = false;
      Array.prototype.forEach.call(tbl.querySelectorAll('th, td'), function(c) {{
        var t = (c.textContent || '').trim();
        if (t === 'العمر' || t === 'عمر المصاب' || t === 'عمر المتوفى' || t === 'عمر المحال للتحليل') {{
          foundAgeCell = true;
          var valCell = c.nextElementSibling;
          if (valCell) {{
            var curV = (valCell.textContent || '').trim();
            if (!curV || curV === '-' || curV === 'None' || /^\\d{{1,3}}$/.test(curV)) {{
              valCell.textContent = dispAge;
            }}
          }}
        }}
      }});
      if (!foundAgeCell && tbl.rows && tbl.rows.length > 0) {{
        var doc = sheet.ownerDocument || document;
        var r0 = tbl.rows[0];
        var totalCols = 0;
        for (var i = 0; i < r0.cells.length; i++) totalCols += (r0.cells[i].colSpan || 1);
        if (totalCols < 2) totalCols = 2;
        var sampleLbl = r0.cells[0];
        var sampleVal = r0.cells.length > 1 ? r0.cells[1] : r0.cells[0];

        var insertRowIdx = 1;
        for (var rIdx = 0; rIdx < tbl.rows.length; rIdx++) {{
          var rTxt = tbl.rows[rIdx].textContent || '';
          if (/هوية|إقامة|الجنسية|اسم المصاب|اسم المتوفى|المدعو/.test(rTxt)) {{
            insertRowIdx = rIdx + 1;
          }}
        }}
        var newTr = doc.createElement('tr');
        var tdL = doc.createElement(sampleLbl.tagName || 'td');
        tdL.className = sampleLbl.className || '';
        tdL.style.cssText = sampleLbl.style.cssText || '';
        tdL.textContent = ageLbl;

        var tdV = doc.createElement(sampleVal.tagName || 'td');
        tdV.className = sampleVal.className || '';
        tdV.style.cssText = sampleVal.style.cssText || '';
        if (totalCols > 2) tdV.colSpan = totalCols - 1;
        tdV.textContent = dispAge;

        newTr.appendChild(tdL);
        newTr.appendChild(tdV);
        var refRow = tbl.rows[insertRowIdx] || null;
        if (refRow && refRow.parentNode) refRow.parentNode.insertBefore(newTr, refRow);
        else (tbl.tBodies[0] || tbl).appendChild(newTr);
      }}
    }}
    if (fmtAge) {{
      var lb = sheet.querySelector('.legal-box-body');
      if (lb) {{
        var lt = lb.innerHTML || '';
        if (lt.indexOf('العمر') === -1 && lt.indexOf('عمر ') === -1) {{
          var updated = lt.replace(/((?:الهوية|الإقامة|هوية|إقامة|السجل المدني)[^()\\n<]{{0,35}}\([^()\\n<]{{2,65}}\))/, '$1، العمر (' + fmtAge + ')');
          if (updated === lt) {{
            updated = lt.replace(/((?:المدعو|المصاب|المتوفى|جثمان المتوفى|جثمان)\\s*\\/?\\s*\([^()\\n<]{{2,85}}\))/, '$1، العمر (' + fmtAge + ')');
          }}
          if (updated !== lt) lb.innerHTML = updated;
        }}
      }}
    }}
  }}
  try {{ syncMedAgeDom(document); }} catch (e) {{}}
  addEventListener('load', function() {{ try {{ syncMedAgeDom(document); }} catch (e) {{}} }});
  addEventListener('beforeprint', function() {{ try {{ syncMedAgeDom(document); }} catch (e) {{}} }});
}})();</script>"""

def bind_functions(g):
    register_catalog(g)
    bh = g.get("build_official_a4_html")
    if callable(bh) and not getattr(bh, "_kh_med_age_wrapped", False):
        orig_bh = bh

        def _med_bh_wrap(*a, **kw):
            all_args = list(a) + list(kw.values())
            str_blob = " | ".join(x for x in all_args if isinstance(x, str) and len(x) < 200)
            is_med = (
                any(isinstance(x, str) and x in _STATE["med_ids"] for x in all_args)
                or any(w in str_blob for w in MED_KEYWORDS)
            ) and not any(ex in str_blob for ex in EXCLUDED_KEYWORDS)

            if not is_med:
                return orig_bh(*a, **kw)

            age_lbl, _ = age_meta_for_text(str_blob)
            raw_age = ""

            # 1) استخراج قيمة العمر من القواميس الممررة أو من الحالة الحية
            for item in all_args:
                if isinstance(item, dict):
                    for dk, dv in item.items():
                        dkl = str(dk).lower()
                        if dkl == "age" or dkl.endswith("_person_age") or dkl.endswith("_age") or "العمر" in str(dk) or str(dk).startswith("عمر "):
                            if str(dv or "").strip():
                                raw_age = dv
                                break
            if not str(raw_age or "").strip() and _STATE["last_age_val"]:
                raw_age = _STATE["last_age_val"]
            if not str(raw_age or "").strip():
                for sk, sv in st.session_state.items():
                    if str(sk).endswith("_person_age") and str(sv or "").strip():
                        raw_age = sv
                        break

            fmt_age = format_arabic_age(raw_age)
            disp_age = fmt_age if fmt_age else "........"

            # 2) تحديث قائمة rows ونص الخطاب الرسمي مباشرة قبل بناء الـ HTML
            def _patch_arg(val):
                if isinstance(val, list) and val and isinstance(val[0], (tuple, list)) and len(val[0]) == 2 and isinstance(val[0][0], str):
                    new_rows = []
                    has_age = False
                    for r in val:
                        rl, rv = str(r[0]), r[1]
                        if "العمر" in rl or rl.startswith("عمر ") or " عمر " in rl:
                            has_age = True
                            rv_fmt = format_arabic_age(rv)
                            new_rows.append(type(r)([r[0], rv_fmt if rv_fmt else disp_age]))
                        else:
                            new_rows.append(r)
                    if not has_age:
                        ins_at = 1
                        for idx_r, r in enumerate(new_rows):
                            if any(w in str(r[0]) for w in ("هوية", "إقامة", "الجنسية", "اسم المصاب", "اسم المتوفى", "اسم المحال", "المدعو", "الاسم")):
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
        g["build_official_a4_html"] = _med_bh_wrap
